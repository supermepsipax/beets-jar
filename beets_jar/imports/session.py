from __future__ import annotations

import os
import threading
from itertools import chain
from queue import Queue
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

import confuse
from beets import importer, logging, plugins
from beets.autotag import (
    AlbumMatch,
    Proposal,
    Recommendation,
    TrackMatch,
    tag_album,
    tag_item,
)

from beets.importer import DuplicateAction, SingletonImportTask
from beets.library import Album
from beets.util import PromptChoice, displayable_path
from beets.util.units import human_bytes, human_seconds_short

from beets_jar.models.import_events import (
    PromptClosed,
    PromptOpened,
    SessionFinished,
    SessionStarted,
    TaskFinished,
)
from beets_jar.models.imports import (
    ChoiceType,
    Prompt,
    SessionStatus,
    TaskOutcome,
    WebChoice,
)
from beets_jar.services.event_bus import import_event_bus

if TYPE_CHECKING:
    from beets.importer import ImportTask
    from beets.library import AlbumOrItem, Item
    from beets.util import PathBytes

log = logging.getLogger("beets")


def ensure_task_id(task) -> str:
    """The registry's id for a beets ImportTask. Stored on the task itself the
    first time it's asked for (so this mutates `task`)."""
    task_id = getattr(task, "task_id", None)
    if task_id is None:
        task_id = task.task_id = uuid4().hex
    return task_id

class _LocalConfig:
    """Per-session import config. Reads fall through to the global `config["import"]`
    except keys set on this session; writes (overrides, and beets' own implied
    tweaks in `set_config`) stay local, so concurrent sessions never see them."""

    def __init__(self, view, overrides: dict | None = None):
        self._view = view
        self._local = confuse.RootView([])
        self._keys: set[str] = set()
        for key, value in (overrides or {}).items():
            self[key] = value

    def __getitem__(self, key):
        return self._local[key] if key in self._keys else self._view[key]

    def __setitem__(self, key, value):
        self._local[key] = value
        self._keys.add(key)

class WebImportSession(importer.ImportSession):
    """
    An import session that runs on its own thread and asks the browser instead of the terminal.

    Goes through the normal import process, but when the user has to decide something it
    posts a Prompt (carrying a reply Queue) to the ImportRegistry and blocks its thread until
    the work area answers.
    """

    def __init__(self, *args, seed_id: str = "", restart: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_id = uuid4().hex
        self.seed_id = seed_id.strip()
        self._aborted = False
        self._restart = restart

    def _config_overrides(self) -> dict:
        """Import config this session changes. Add future per-import options here."""
        overrides = {}
        if self.seed_id:
            overrides["search_ids"] = [self.seed_id]
        return overrides

    def set_config(self, config):
        # wrap *before* beets applies its implied changes (move => copy off, ...), so those
        # are computed from the overrides too, and written to the session, not the global
        super().set_config(_LocalConfig(config, self._config_overrides()))

    def run(self):
        # No SessionStarted here: start_web_import applies it to the registry
        # before this thread starts, so the session shows up immediately.
        status = SessionStatus.COMPLETED
        error = None
        try:
            super().run()
        except Exception as exception:
            status = SessionStatus.FAILED
            error = str(exception)
            log.exception(f"Import session {self.session_id} failed")

        finally:
            if self._aborted:
                status = SessionStatus.ABORTED
            import_event_bus.emit(SessionFinished(self.session_id, status, error))
            # `beet jar` never returns to the CLI, so plugins that defer work
            # until `cli_exit` (subsonicupdate, mpdupdate, smartplaylist, ...)
            # would otherwise never run after a web import.
            try:
                plugins.send("cli_exit", lib=self.lib)
            except Exception:
                log.exception(f"cli_exit listeners failed for session {self.session_id}")

    def abort(self) -> None:
        """Stop the whole import. Called from the Abort prompt choice."""
        self._aborted = True
        raise importer.ImportAbortError()

    def already_imported(self, toppath, paths) -> bool:
        if self._restart:
            return False
        return super().already_imported(toppath, paths)

    def _ask(self, kind, task=None, choices=None, **extra):
        prompt = Prompt(uuid4().hex, kind, Queue(), task, choices or [], **extra)
        task_id = ensure_task_id(task) if task is not None else None
        import_event_bus.emit(PromptOpened(self.session_id, task_id, prompt))
        try:
            return prompt.reply.get()
        finally:
            import_event_bus.emit(PromptClosed(self.session_id, prompt.prompt_id))

    # ---- choosing a candidate ----

    def choose_match(self, task: ImportTask) -> AlbumMatch | importer.Action:
        """Given an initial autotagging of items, go through an interactive
        dance with the user to ask for a choice of metadata. Returns an
        AlbumMatch object, ASIS, or SKIP.
        """
        self._fall_back_from_empty_seed(task)

        # Let plugins display info or prompt the user before we go through the
        # process of selecting candidate.
        results = plugins.send("import_task_before_choice", session=self, task=task)
        actions = [action for action in results if action]
        if len(actions) == 1:
            return actions[0]
        if len(actions) > 1:
            raise plugins.PluginConflictError(
                "Only one handler for `import_task_before_choice` may return an action."
            )

        return self._choose(task, AlbumMatch)

    def choose_item(self, task: SingletonImportTask) -> TrackMatch | importer.Action:
        """Ask the user for a choice about tagging a single item. Returns
        either an action constant or a TrackMatch object.
        """
        self._fall_back_from_empty_seed(task)
        return self._choose(task, TrackMatch)

    def _fall_back_from_empty_seed(self, task) -> None:
        if self.seed_id and not task.candidates:
            # seed matched nothing (typo, wrong provider, provider plugin not enabled):
            # fall back to a normal search
            task.lookup_candidates([])

    def _choose(self, task, match_type: type[AlbumMatch] | type[TrackMatch]):
        """Take the top candidate when no question is needed; otherwise ask until
        the user picks a candidate (a `match_type`) or an action ends the task."""
        decided = self._decide_without_asking(task, match_type)
        if decided is not None:
            return decided

        while True:
            # The reply's choice is a candidate match or a PromptChoice (see imports/replies.py)
            web_choice: WebChoice = self._ask("candidate", task, self._get_choices(task))
            if isinstance(web_choice.choice, match_type):
                return web_choice.choice

            if isinstance(web_choice.choice, PromptChoice) and web_choice.choice.callback:
                result = self._run_choice_callback(task, web_choice)
                if isinstance(result, importer.Action):
                    return result
                if isinstance(result, Proposal):  # a new search: ask again with its candidates
                    task.candidates = result.candidates
                    task.rec = result.recommendation
            # Anything else (e.g. a plugin choice without a callback): ask again

    def _decide_without_asking(self, task, match_type):
        """Quiet mode's verdict, or the top candidate of a strong match (unless timid).
        None means the user has to be asked."""
        # TODO: introduce beets.autotag.Candidates to remove these assertions
        assert task.rec is not None
        assert task.candidates is not None
        action = _summary_judgment(task.rec, self.config)
        if action == importer.Action.APPLY:
            match = task.candidates[0]
            assert isinstance(match, match_type)
            return match
        if action is not None:
            return action
        if task.rec == Recommendation.strong and not self.config["timid"]:
            assert isinstance(task.candidates[0], match_type)
            return task.candidates[0]
        return None

    def _run_choice_callback(self, task, web_choice: WebChoice):
        """Run a prompt choice's callback. Returns an importer.Action, a Proposal
        (new candidates from a search or ID lookup), or None."""
        choice = web_choice.choice
        info = web_choice.follow_up_info
        if choice.short == ChoiceType.SEARCH:
            return choice.callback(self, task, info["artist"], info["query"])
        if choice.short == ChoiceType.ID:
            return choice.callback(self, task, info["mbid"])
        return choice.callback(self, task)

    def _get_choices(self, task: ImportTask) -> list[PromptChoice]:
        """Get the list of prompt choices that should be presented to the
        user. This consists of both built-in choices and ones provided by
        plugins.

        The `before_choose_candidate` event is sent to the plugins, with
        session and task as its parameters. Plugins are responsible for
        checking the right conditions and returning a list of `PromptChoice`s,
        which is flattened and checked for conflicts.

        A plugin choice whose short letter is already taken (by a built-in
        choice, by "a" for Apply, or by an earlier plugin choice) is dropped
        with a warning.
        """
        # Standard, built-in choices.
        choices = [
            PromptChoice("s", "Skip", lambda session, task: importer.Action.SKIP),
            PromptChoice("u", "Use as-is", lambda session, task: importer.Action.ASIS),
        ]
        if task.is_album:
            choices += [
                PromptChoice("t", "as Tracks", lambda session, task: importer.Action.TRACKS),
                PromptChoice("g", "Group albums", lambda session, task: importer.Action.ALBUMS),
            ]
        choices += [
            # TODO: introduce beets.autotag.Candidates to remove these ignores
            #  context: Candidates is a Sequence which will be updated in place
            #  by manual_search and manual_id, with return types as None.
            PromptChoice("e", "Enter search", web_search),  # type: ignore[arg-type]
            PromptChoice("i", "enter Id", web_id),  # type: ignore[arg-type]
            PromptChoice("b", "aBort", abort_action),
        ]

        plugin_choices = chain.from_iterable(
            plugins.send("before_choose_candidate", session=self, task=task)
        )
        taken = {"a"} | {choice.short for choice in choices}  # "a" is Apply, chosen by candidate
        for plugin_choice in plugin_choices:
            if plugin_choice.short in taken:
                log.warning(
                    "Prompt choice '{0.long}' removed: short letter '{0.short}' is already taken",
                    plugin_choice,
                )
                continue
            taken.add(plugin_choice.short)
            choices.append(plugin_choice)
        return choices

    # ---- duplicates and resuming ----

    def get_duplicate_action(self, task, found_duplicates) -> DuplicateAction:
        action = super().get_duplicate_action(task, found_duplicates)
        if action is DuplicateAction.ASK:
            action = DuplicateAction(
                self._get_duplicate_action_from_user(task, found_duplicates)
            )

        if action is DuplicateAction.SKIP:
            import_event_bus.emit(
                TaskFinished(
                    self.session_id, ensure_task_id(task), TaskOutcome.SKIPPED, "duplicate"
                )
            )
        elif action is DuplicateAction.MERGE:
            import_event_bus.emit(
                TaskFinished(self.session_id, ensure_task_id(task), TaskOutcome.MERGED)
            )
        return action

    def _get_duplicate_action_from_user(
        self, task: importer.ImportTask, found_duplicates: list[AlbumOrItem]
    ) -> str:
        """Decide what to do when a new album or item seems similar to one
        that's already in the library.
        """
        if self.config["quiet"]:
            # In quiet mode, don't prompt -- just skip.
            log.info("Skipping.")
            return "s"
        choices = [
            PromptChoice(action.value, action.text, None)
            for action in DuplicateAction
            if action is not DuplicateAction.ASK
        ]

        # Some detail about the existing and new items so the user can make an
        # informed decision.
        old_summaries = []
        for duplicate in found_duplicates:
            items = list(duplicate.items()) if isinstance(duplicate, Album) else [duplicate]
            old_summaries.append(self._report_item_summary("Old", items, task.is_album))
        duplicate_summary = {
            "old": old_summaries,
            "new": self._report_item_summary("New", task.imported_items(), task.is_album),
        }

        web_choice: WebChoice = self._ask(
            "duplicate", task, choices, duplicate_summary=duplicate_summary
        )
        assert isinstance(web_choice.choice, PromptChoice)
        return web_choice.choice.short

    def _report_item_summary(
        self, prefix: Literal["Old", "New"], items: list[Item], is_album: bool
    ) -> str:
        summary_string = f"{prefix}: {summarize_items(items, not is_album)}"
        if self.config["duplicate_verbose_prompt"].get(bool):
            for item in items:
                summary_string += f"\n  {item}"
        return summary_string

    def should_resume(self, path: PathBytes) -> bool:
        return self._ask("resume", resume_path=displayable_path(path))


def validate_import_path(raw_path: str) -> str | None:
    """The path, stripped, if it exists on the server; None otherwise."""
    path = raw_path.strip()
    if not path or not os.path.exists(path):
        return None
    return path


def start_web_import(lib, import_registry, paths, *, restart: bool = False, seed_id: str = "") -> WebImportSession:
    """Create a session, register it in the registry right away, and run it in a thread.

    Must be called from the event loop (i.e. from an endpoint), because it
    touches the registry directly.
    """
    session = WebImportSession(
        lib=lib, paths=paths, loghandler=None, query=None, restart=restart, seed_id=seed_id
    )
    import_registry.apply(
        SessionStarted(
            session.session_id, tuple(displayable_path(path) for path in session.paths)
        )
    )
    threading.Thread(target=session.run, daemon=True).start()
    return session


def summarize_items(items: list[Item], singleton: bool) -> str:
    """Produces a brief summary line describing a set of items. Used for
    manually resolving duplicates during import.

    `items` is a list of `Item` objects. `singleton` indicates whether
    this is an album or single-item import (if the latter, them `items`
    should only have one element).
    """
    summary_parts = []
    if not singleton:
        summary_parts.append(f"{len(items)} items")

    format_counts: dict[str, int] = {}
    for item in items:
        format_counts[item.format] = format_counts.get(item.format, 0) + 1
    if len(format_counts) == 1:
        # A single format.
        summary_parts.append(items[0].format)
    else:
        # Enumerate all the formats by decreasing frequencies, then by name
        def by_count_then_name(format_and_count):
            file_format, count = format_and_count
            return -count, file_format

        for file_format, count in sorted(format_counts.items(), key=by_count_then_name):
            summary_parts.append(f"{file_format} {count}")

    if items:
        average_bitrate = sum(item.bitrate for item in items) / len(items)
        total_duration = sum(item.length for item in items)
        total_filesize = sum(item.filesize for item in items)
        summary_parts.append(f"{int(average_bitrate / 1000)}kbps")
        if items[0].format == "FLAC":
            sample_bits = (
                f"{round(int(items[0].samplerate) / 1000, 1)}kHz"
                f"/{items[0].bitdepth} bit"
            )
            summary_parts.append(sample_bits)
        summary_parts.append(human_seconds_short(total_duration))
        summary_parts.append(human_bytes(total_filesize))

    return ", ".join(summary_parts)


def _summary_judgment(rec: Recommendation, local_config) -> importer.Action | None:
    """Determines whether a decision should be made without even asking
    the user. This occurs in quiet mode and when an action is chosen for
    NONE recommendations. Return None if the user should be queried.
    Otherwise, returns an action. May also print to the console if a
    summary judgment is made.
    """

    action: importer.Action | None
    if local_config["quiet"]:
        if rec == Recommendation.strong:
            return importer.Action.APPLY
        action = local_config["quiet_fallback"].as_choice(
            {"skip": importer.Action.SKIP, "asis": importer.Action.ASIS}
        )
    elif local_config["timid"]:
        return None
    elif rec == Recommendation.none:
        action = local_config["none_rec_action"].as_choice(
            {
                "skip": importer.Action.SKIP,
                "asis": importer.Action.ASIS,
                "ask": None,
            }
        )
    else:
        return None

    if action == importer.Action.SKIP:
        print("Skipping.")
    elif action == importer.Action.ASIS:
        print("Importing as-is.")
    return action


# ---- prompt choice callbacks (beets calls these as callback(session, task, ...)) ----


def _tagger(task):
    """beets' lookup function for this kind of task."""
    return tag_item if isinstance(task, SingletonImportTask) else tag_album


def web_search(session, task, artist, name):
    """Get a new `Proposal` using manual search criteria.

    Input either an artist and album (for full albums) or artist and
    track name (for singletons) for manual search.
    """
    tag = _tagger(task)
    return tag(task.source, artist.strip(), name.strip())


def web_id(session, task, mbid):
    """Get a new `Proposal` using a manually-entered ID.

    Input an ID, either for an album ("release") or a track ("recording").
    """
    tag = _tagger(task)
    return tag(task.source, search_ids=mbid.split())


def abort_action(session: WebImportSession, task: ImportTask) -> None:
    """A prompt choice callback that aborts the importer."""
    session.abort()
