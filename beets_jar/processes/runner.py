"""Runs plugin commands, one process at a time, on a single worker thread."""

import logging
import threading
from collections import OrderedDict
from uuid import uuid4

import beets.ui
from beets_jar.services.event_bus import process_event_bus
from beets import config as beets_config
from beets.exceptions import UserError
from beets.library import Library

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
                self._current, self._cancel_current = process_id, False
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
        sub = find_subcommand(spec.plugin, spec.command)
        if sub is None:
            self.bus.emit(
                ProcessFinished(
                    process_id, ProcessStatus.FAILED, f"{spec.name} isn't available"
                )
            )
            return

        opts, _ = sub.parse_args([])  # the command's own defaults
        for dest, value in spec.overrides.items():
            setattr(opts, dest, value)
        if spec.album is not None:
            opts.album = spec.album

        # Some plugins copy their options into the global config (lyrics does
        # config.set(vars(opts)); lastgenre and ftintitle do set_args(opts)).
        # Put the config back afterwards so a one-off override doesn't stick
        # for the rest of the server's life.
        saved_sources = list(beets_config.sources)
        status, failed = ProcessStatus.COMPLETED, 0
        _prompts.blocked = True
        try:
            for query in spec.queries:
                if self._cancel_current:
                    status = ProcessStatus.CANCELLED
                    break
                ok, detail = True, None
                try:
                    sub.func(self.lib, opts, [query])
                except (Exception, SystemExit) as e:
                    ok, detail = False, str(e) or type(e).__name__
                    failed += 1
                    log.exception("%s failed on %r", spec.name, query)
                self.bus.emit(TargetFinished(process_id, ok, detail))
        finally:
            _prompts.blocked = False
            beets_config.sources[:] = saved_sources

        if (
            status is ProcessStatus.COMPLETED
            and spec.queries
            and failed == len(spec.queries)
        ):
            status = ProcessStatus.FAILED
        self.bus.emit(ProcessFinished(process_id, status))
