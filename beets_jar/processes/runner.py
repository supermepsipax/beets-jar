"""Runs plugin commands, one process at a time, on a single worker thread."""

import logging
import threading
from collections import OrderedDict
from contextlib import contextmanager
from uuid import uuid4

import beets.ui
from beets_jar.services.event_bus import process_event_bus
from beets import config as beets_config
from beets.exceptions import UserError
from beets.library import Library
from beets.ui import Subcommand

from beets_jar.models.process_events import (
    ProcessFinished,
    ProcessQueued,
    ProcessStarted,
    TargetFinished,
)
from beets_jar.models.processes import ProcessSpec, ProcessStatus
from beets_jar.services.plugins import find_subcommand

log = logging.getLogger("uvicorn.error")

# ---- prompt guard ----
# Every beets prompt (input_yn, input_options, plugins' own questions) ends in
# beets.ui.input_. On the worker thread that would block forever on the server's
# terminal, so while a process runs it raises instead and fails just that step.
# The manifest's `fixed: {"yes": true}` should make this rare; it's the safety net.
_prompts = threading.local()
_original_input = beets.ui.input_


def _guarded_input(prompt=None):
    if getattr(_prompts, "blocked", False):
        raise UserError("the command asked a question; run it from the CLI instead")
    return _original_input(prompt)


beets.ui.input_ = _guarded_input


@contextmanager
def _isolated_run():
    """Block prompts while a command runs, and put the global config back afterwards.

    Some plugins copy their options into the global config (lyrics does
    config.set(vars(opts)); lastgenre and ftintitle do set_args(opts)).
    Restoring it stops a one-off override sticking for the rest of the server's life.
    """
    saved_sources = list(beets_config.sources)
    _prompts.blocked = True
    try:
        yield
    finally:
        _prompts.blocked = False
        beets_config.sources[:] = saved_sources


def _build_opts(subcommand: Subcommand, spec: ProcessSpec):
    """The command's own option defaults, with the spec's overrides on top."""
    opts, _ = subcommand.parse_args([])
    for dest, value in spec.overrides.items():
        setattr(opts, dest, value)
    if spec.album is not None:
        opts.album = spec.album
    return opts


class ProcessRunner:
    """A FIFO of ProcessSpecs worked through by one daemon thread.

    One thread means one plugin command at a time: beets plugins aren't written
    to run concurrently, and it keeps our own writes to SQLite serial.
    """

    def __init__(self, lib: Library, bus=process_event_bus):
        self.lib = lib
        self.bus = bus
        self._pending: OrderedDict[str, ProcessSpec] = OrderedDict()
        self._cond = threading.Condition()
        self._current: str | None = None
        self._cancel_current = False
        self._stopped = False
        self._thread = threading.Thread(
            target=self._loop, name="jar-processes", daemon=True
        )

    # ---- called from request handlers ----
    def start(self):
        self._thread.start()

    def stop(self):
        with self._cond:
            self._stopped = True
            self._cond.notify()

    def enqueue(self, spec: ProcessSpec, process_id: str | None = None) -> str | None:
        """Queue a spec. Passing an existing id restarts that process in place.

        Returns the id, or None if that id is already queued or running.
        """
        process_id = process_id or uuid4().hex
        with self._cond:
            if process_id in self._pending or process_id == self._current:
                return None
            # Emitting under the lock guarantees ProcessQueued lands before ProcessStarted
            self.bus.emit(ProcessQueued(process_id, spec))
            self._pending[process_id] = spec
            self._cond.notify()
        return process_id

    def cancel(self, process_id: str) -> bool:
        """Queued: dropped immediately. Running: stops before its next step."""
        with self._cond:
            if self._pending.pop(process_id, None) is not None:
                self.bus.emit(ProcessFinished(process_id, ProcessStatus.CANCELLED))
                return True
            if process_id == self._current:
                self._cancel_current = True
                return True
        return False

    # ---- worker thread ----
    def _loop(self):
        while True:
            with self._cond:
                while not self._pending and not self._stopped:
                    self._cond.wait()
                if self._stopped:
                    return
                process_id, spec = self._pending.popitem(last=False)
                self._current = process_id
                self._cancel_current = False
            try:
                self.run(process_id, spec)
            except Exception:  # never let one process take the worker down
                log.exception("Process %s crashed", process_id)
                self.bus.emit(
                    ProcessFinished(
                        process_id, ProcessStatus.FAILED, "Crashed, see the server log"
                    )
                )
            finally:
                with self._cond:
                    self._current = None

    def run(self, process_id: str, spec: ProcessSpec):
        """Run one process on the calling thread (the worker, or a test)."""
        self.bus.emit(ProcessStarted(process_id))
        subcommand = find_subcommand(spec.plugin, spec.command)
        if subcommand is None:
            self.bus.emit(
                ProcessFinished(
                    process_id, ProcessStatus.FAILED, f"{spec.display_name} isn't available"
                )
            )
            return

        opts = _build_opts(subcommand, spec)
        status = ProcessStatus.COMPLETED
        failed = 0
        # beets resolves the relative paths stored in the db against a ContextVar,
        # and this worker thread doesn't inherit the main thread's value
        with _isolated_run(), self.lib.music_dir_context():
            for query in spec.queries:
                if self._cancel_current:
                    status = ProcessStatus.CANCELLED
                    break
                error = self._run_query(subcommand, opts, spec, query)
                if error is not None:
                    failed += 1
                self.bus.emit(TargetFinished(process_id, error is None, error))

        every_query_failed = bool(spec.queries) and failed == len(spec.queries)
        if status is ProcessStatus.COMPLETED and every_query_failed:
            status = ProcessStatus.FAILED
        self.bus.emit(ProcessFinished(process_id, status))

    def _run_query(self, subcommand: Subcommand, opts, spec: ProcessSpec, query: str) -> str | None:
        """Run the command on one query. Returns what went wrong, or None if it worked."""
        try:
            subcommand.func(self.lib, opts, [query])
        except (Exception, SystemExit) as error:
            log.exception("%s failed on %r", spec.display_name, query)
            return str(error) or type(error).__name__
        return None
