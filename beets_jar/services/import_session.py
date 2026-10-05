from __future__ import annotations

import threading
from collections import Counter
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
from beets.exceptions import UserError
from beets.importer import DuplicateAction, SingletonImportTask
from beets.library import Album
from beets.util import PromptChoice, displayable_path
from beets.util.units import human_bytes, human_seconds_short

from beets_jar.imports.events import (
    Prompt,
    PromptClosed,
    PromptOpened,
    SessionFinished,
    SessionStarted,
    SessionStatus,
    TaskFinished,
    TaskOutcome,
)
from beets_jar.imports.snapshot import task_key
from beets_jar.models.web_choice import ChoiceType, WebChoice
from beets_jar.services.event_bus import import_event_bus

if TYPE_CHECKING:
    from beets.importer import ImportTask
    from beets.library import AlbumOrItem, Item
    from beets.util import PathBytes

log = logging.getLogger("beets")


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
    An import session that can be triggered and ran with another asynchronous process.

    Goes through the normal import process but when user intervention is required, blocks
    its main thread while it waits for a response. Responses are passed in via stored queue objects
    based on unique identifiers.
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
        status, error = SessionStatus.COMPLETED, None
        try:
            super().run()
        except Exception as e:
            status, error = SessionStatus.FAILED, str(e)
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
                log.exception(
                    f"cli_exit listeners failed for session {self.session_id}"
                )
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
        task_id = task_key(task) if task is not None else None
        import_event_bus.emit(PromptOpened(self.session_id, task_id, prompt))
        try:
            return prompt.reply.get()
        finally:
            import_event_bus.emit(PromptClosed(self.session_id, prompt.prompt_id))

    def choose_match(self, task: ImportTask) -> AlbumMatch | importer.Action:
        """Given an initial autotagging of items, go through an interactive
        dance with the user to ask for a choice of metadata. Returns an
        AlbumMatch object, ASIS, or SKIP.
        """

        if self.seed_id and not task.candidates:
            # seed matched nothing (typo, wrong provider, provider plugin not enabled): fall back to a normal search
            task.lookup_candidates([])

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

        # Take immediate action if appropriate.
        assert task.rec is not None
        assert task.candidates is not None
        action = _summary_judgment(task.rec, self.config)
        if action == importer.Action.APPLY:
            match = task.candidates[0]
            # TODO: introduce AlbumImportTask to remove this assertion
            assert isinstance(match, AlbumMatch)
            return match
        if action is not None:
            return action
        if task.rec == Recommendation.strong and not self.config["timid"]:
            assert isinstance(task.candidates[0], AlbumMatch)
            return task.candidates[0]

        while True:
            # Ask for a choice from the user. The result of
            # `choose_candidate` may be an `importer.Action`, an
            # `AlbumMatch` object for a specific selection, or a
            # `PromptChoice`.
            choices = self._get_choices(task)
            web_choice: WebChoice = self._ask("candidate", task, choices)

            # WAIT FOR USER RESPONSE
            # We have a specific match selection.
            # or, basic choices that require no more action here.
            if isinstance(web_choice.choice, AlbumMatch) or (
                isinstance(web_choice.choice, importer.Action)
                and web_choice.choice in (importer.Action.SKIP, importer.Action.ASIS)
            ):
                # Pass selection to main control flow.
                return web_choice.choice

            # Plugin-provided choices. We invoke the associated callback
            # function.
            if (
                isinstance(web_choice.choice, PromptChoice)
                and web_choice.choice.callback
            ):
                if web_choice.choice.short == ChoiceType.SEARCH:
                    post_choice = web_choice.choice.callback(
                        self,
                        task,
                        web_choice.follow_up_info["artist"],
                        web_choice.follow_up_info["query"],
                    )
                elif web_choice.choice.short == ChoiceType.ID:
                    post_choice = web_choice.choice.callback(
                        self, task, web_choice.follow_up_info["mbid"]
                    )
                else:
                    post_choice = web_choice.choice.callback(self, task)
                if isinstance(post_choice, importer.Action):
                    return post_choice
                elif isinstance(post_choice, Proposal):
                    task.candidates = post_choice.candidates
                    task.rec = post_choice.recommendation

            # Anything else (e.g. a plugin choice without a callback): ask again

    def choose_item(self, task: SingletonImportTask) -> TrackMatch | importer.Action:
        """Ask the user for a choice about tagging a single item. Returns
        either an action constant or a TrackMatch object.
        """

        if self.seed_id and not task.candidates:
            # seed matched nothing (typo, wrong provider, provider plugin not enabled): fall back to a normal search
            task.lookup_candidates([])

        # Take immediate action if appropriate.
        # TODO: introduce beets.autotag.Candidates to remove these assertions
        assert task.rec is not None
        assert task.candidates is not None
        action = _summary_judgment(task.rec, self.config)
        if action == importer.Action.APPLY:
            match = task.candidates[0]
            # TODO: introduce AlbumImportTask to remove this assertion
            assert isinstance(match, TrackMatch)
            # show_item_change(task.source, match)
            return match
        if action is not None:
            return action
        if task.rec == Recommendation.strong and not self.config["timid"]:
            assert isinstance(task.candidates[0], TrackMatch)
            return task.candidates[0]

        while True:
            # Ask for a choice.
            choices = self._get_choices(task)
            web_choice: WebChoice = self._ask("candidate", task, choices)

            # We have a specific match selection.
            # or, basic web_choice.choices that require no more action here.
            if isinstance(web_choice.choice, TrackMatch) or (
                isinstance(web_choice.choice, importer.Action)
                and web_choice.choice in (importer.Action.SKIP, importer.Action.ASIS)
            ):
                # Pass selection to main control flow.
                return web_choice.choice

            # Plugin-provided web_choice.choices. We invoke the associated callback
            # function.
            if (
                isinstance(web_choice.choice, PromptChoice)
                and web_choice.choice.callback
            ):
                if web_choice.choice.short == ChoiceType.SEARCH:
                    post_choice = web_choice.choice.callback(
                        self,
                        task,
                        web_choice.follow_up_info["artist"],
                        web_choice.follow_up_info["query"],
                    )
                elif web_choice.choice.short == ChoiceType.ID:
                    post_choice = web_choice.choice.callback(
                        self, task, web_choice.follow_up_info["mbid"]
                    )
                else:
                    post_choice = web_choice.choice.callback(self, task)
                if isinstance(post_choice, importer.Action):
                    return post_choice
                elif isinstance(post_choice, Proposal):
                    task.candidates = post_choice.candidates
                    task.rec = post_choice.recommendation

    def _report_item_summary(
        self, prefix: Literal["Old", "New"], items: list[Item], is_album: bool
    ) -> str:
        summary_string = f"{prefix}: {summarize_items(items, not is_album)}"
        if self.config["duplicate_verbose_prompt"].get(bool):
            for dup in items:
                summary_string += f"\n  {dup}"
        return summary_string

    def get_duplicate_action(self, task, found_duplicates) -> DuplicateAction:
        action = super().get_duplicate_action(task, found_duplicates)
        if action is DuplicateAction.ASK:
            action = DuplicateAction(
                self._get_duplicate_action_from_user(task, found_duplicates)
            )

        if action is DuplicateAction.SKIP:
            import_event_bus.emit(
                TaskFinished(
                    self.session_id, task_key(task), TaskOutcome.SKIPPED, "duplicate"
                )
            )
        elif action is DuplicateAction.MERGE:
            import_event_bus.emit(
                TaskFinished(self.session_id, task_key(task), TaskOutcome.MERGED)
            )
        return action

    def _get_duplicate_action_from_user(
        self, task: importer.ImportTask, found_duplicates: list[AlbumOrItem]
    ) -> str:
        """Decide what to do when a new album or item seems similar to one
        that's already in the library.
        """
        is_album = task.is_album
        # log.warning("This {.source.type} is already in the library!", task)

        # if config["import"]["quiet"]:
        if self.config["quiet"]:
            # In quiet mode, don't prompt -- just skip.
            log.info("Skipping.")
            return "s"
        choices = []
        for action in DuplicateAction:
            if action is DuplicateAction.ASK:
                continue
            choice: PromptChoice = PromptChoice(action.value, action.text, None)
            choices.append(choice)

        # Print some detail about the existing and new items so the
        # user can make an informed decision.
        duplicate_summary = {"old": []}
        for duplicate in found_duplicates:
            duplicate_summary["old"].append(
                self._report_item_summary(
                    "Old",
                    (
                        list(duplicate.items())
                        if isinstance(duplicate, Album)
                        else [duplicate]
                    ),
                    is_album,
                )
            )

        duplicate_summary["new"] = self._report_item_summary(
            "New", task.imported_items(), is_album
        )

        web_choice: WebChoice = self._ask(
            "duplicate", task, choices, duplicate_summary=duplicate_summary
        )

        assert isinstance(web_choice.choice, PromptChoice)
        return web_choice.choice.short

    def should_resume(self, path: PathBytes) -> bool:
        return self._ask("resume", path=displayable_path(path))

    def _get_choices(self, task: ImportTask) -> list[PromptChoice]:
        """Get the list of prompt choices that should be presented to the
        user. This consists of both built-in choices and ones provided by
        plugins.

        The `before_choose_candidate` event is sent to the plugins, with
        session and task as its parameters. Plugins are responsible for
        checking the right conditions and returning a list of `PromptChoice`s,
        which is flattened and checked for conflicts.

        If two or more choices have the same short letter, a warning is
        emitted and all but one choices are discarded, giving preference
        to the default importer choices.

        Returns a list of `PromptChoice`s.
        """
        # Standard, built-in choices.
        choices = [
            PromptChoice("s", "Skip", lambda s, t: importer.Action.SKIP),
            PromptChoice("u", "Use as-is", lambda s, t: importer.Action.ASIS),
        ]
        if task.is_album:
            choices += [
                PromptChoice("t", "as Tracks", lambda s, t: importer.Action.TRACKS),
                PromptChoice("g", "Group albums", lambda s, t: importer.Action.ALBUMS),
            ]
        choices += [
            # TODO: introduce beets.autotag.Candidates to remove these ignores
            #  context: Candidates is a Sequence which will be updated in place
            #  by manual_search and manual_id, with return types as None.
            PromptChoice("e", "Enter search", web_search),  # type: ignore[arg-type]
            PromptChoice("i", "enter Id", web_id),  # type: ignore[arg-type]
            PromptChoice("b", "aBort", abort_action),
        ]

        # Send the before_choose_candidate event and flatten list.
        extra_choices = list(
            chain(*plugins.send("before_choose_candidate", session=self, task=task))
        )

        # Add a "dummy" choice for the other baked-in option, for
        # duplicate checking.
        all_choices = [
            PromptChoice("a", "Apply", lambda s, t: importer.Action.APPLY),
            *choices,
            *extra_choices,
        ]

        # Check for conflicts.
        short_letters = [c.short for c in all_choices]
        if len(short_letters) != len(set(short_letters)):
            # Duplicate short letter has been found.
            duplicates = [i for i, count in Counter(short_letters).items() if count > 1]
            for short in duplicates:
                # Keep the first of the choices, removing the rest.
                dup_choices = [c for c in all_choices if c.short == short]
                for c in dup_choices[1:]:
                    log.warning(
                        "Prompt choice '{0.long}' removed due to conflict "
                        "with '{1[0].long}' (short letter: '{0.short}')",
                        c,
                        dup_choices,
                    )
                    extra_choices.remove(c)

        return choices + extra_choices


def start_web_import(
    lib, imports, paths, *, restart: bool = False, seed_id: str = ""
) -> WebImportSession:
    """Create a session, register it in the registry right away, and run it in a thread.

    Must be called from the event loop (i.e. from an endpoint), because it
    touches the registry directly.
    """
    session = WebImportSession(
        lib=lib,
        paths=paths,
        loghandler=None,
        query=None,
        restart=restart,
        seed_id=seed_id,
    )
    imports.apply(
        SessionStarted(
            session.session_id, tuple(displayable_path(p) for p in session.paths)
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
        # Enumerate all the formats by decreasing frequencies:
        for fmt, count in sorted(
            format_counts.items(),
            key=lambda fmt_and_count: (-fmt_and_count[1], fmt_and_count[0]),
        ):
            summary_parts.append(f"{fmt} {count}")

    if items:
        average_bitrate = sum([item.bitrate for item in items]) / len(items)
        total_duration = sum([item.length for item in items])
        total_filesize = sum([item.filesize for item in items])
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
        # action = config["import"]["quiet_fallback"].as_choice(
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


def web_search(session, task, artist, name):
    """Get a new `Proposal` using manual search criteria.

    Input either an artist and album (for full albums) or artist and
    track name (for singletons) for manual search.
    """

    method = tag_item if isinstance(task, SingletonImportTask) else tag_album
    return method(task.source, artist.strip(), name.strip())


def web_id(session, task, mbid):
    """Get a new `Proposal` using a manually-entered ID.

    Input an ID, either for an album ("release") or a track ("recording").
    """
    method = tag_item if isinstance(task, SingletonImportTask) else tag_album
    return method(task.source, search_ids=mbid.split())


def abort_action(session: ImportSession, task: ImportTask) -> None:
    """A prompt choice callback that aborts the importer."""
    session.abort()
