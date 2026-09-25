from __future__ import annotations
from app.models.queues import QueueStorageType
import uuid
from app.models import QueueStorage, QueueStorageItem, WebChoice, ChoiceType
from beets.exceptions import UserError

from collections import Counter
from itertools import chain
from typing import TYPE_CHECKING, Literal, Iterator
from beets import config, importer, logging, plugins, ui
from beets.autotag import (
    AlbumMatch,
    Recommendation,
    TrackMatch,
    tag_album,
    tag_item,
)
from beets.importer import DuplicateAction, SingletonImportTask
from beets.library import Album
from beets.util import PromptChoice, displayable_path
from beets.autotag import Proposal
from beets.util.color import colorize
from beets.util.units import human_bytes, human_seconds_short

if TYPE_CHECKING:
    from collections.abc import Sequence
    from beets.importer import ImportSession, ImportTask
    from beets.library import AlbumOrItem, Item
    from beets.util import PathBytes

# Global logger.
log = logging.getLogger("beets")


class WebImportSession(importer.ImportSession):
    """
    An import session that can be triggered and ran with another asynchronous process.

    Goes through the normal import process but when user intervention is required, blocks
    its main thread while it waits for a response. Responses are passed in via stored queue objects
    based on unique identifiers.
    """

    def __init__(self, *args, queues: QueueStorage, mbid: str = "", **kwargs):
        super().__init__(*args,  **kwargs)
        self.session_id = uuid.uuid4().hex
        self.queues = queues
        self._queue_ids = []

    def run(self):
        try:
            super().run()
        finally:
            for qid in self._queue_ids:
                self.queues.delete(qid)

    def choose_match(self, task: ImportTask) -> AlbumMatch | importer.Action:
        """Given an initial autotagging of items, go through an interactive
        dance with the user to ask for a choice of metadata. Returns an
        AlbumMatch object, ASIS, or SKIP.
        """
        # Show what we're tagging.
        #TODO: Figure out how to hook into import_task_before_choice event to broadcast info
        # prompt = f"{displayable_path(task.paths, "\n")} ({len(task.items)} items)"
        # print(prompt)

        # Let plugins display info or prompt the user before we go through the
        # process of selecting candidate.
        results = plugins.send(
            "import_task_before_choice", session=self, task=task
        )
        actions = [action for action in results if action]

        if len(actions) == 1:
            return actions[0]
        if len(actions) > 1:
            raise plugins.PluginConflictError(
                "Only one handler for `import_task_before_choice` may return "
                "an action."
            )

        # Take immediate action if appropriate.
        assert task.rec is not None
        assert task.candidates is not None
        action = _summary_judgment(task.rec)
        if action == importer.Action.APPLY:
            match = task.candidates[0]
            # TODO: introduce AlbumImportTask to remove this assertion
            assert isinstance(match, AlbumMatch)
            return match
        if action is not None:
            return action

        # Loop until we have a choice.

        queue_item = QueueStorageItem(task, queue_type=QueueStorageType.CANDIDATE)
        queue_id = self.queues.store(queue_item)
        self._queue_ids.append(queue_id)

        while True:
            # Ask for a choice from the user. The result of
            # `choose_candidate` may be an `importer.Action`, an
            # `AlbumMatch` object for a specific selection, or a
            # `PromptChoice`.
            choices = self._get_choices(task)
            self.queues.update(queue_id, task, choices)

            # WAIT FOR USER RESPONSE
            web_choice: WebChoice = queue_item.queue.get()

            # We have a specific match selection.
            # or, basic choices that require no more action here.
            if isinstance(web_choice.choice, AlbumMatch) or (
                isinstance(web_choice.choice, importer.Action)
                and web_choice.choice in (importer.Action.SKIP, importer.Action.ASIS)
            ):
                # Pass selection to main control flow.
                self.queues.delete(queue_id)
                return web_choice.choice

            # Plugin-provided choices. We invoke the associated callback
            # function.
            if isinstance(web_choice.choice, PromptChoice) and web_choice.choice.callback:
                if ChoiceType(web_choice.choice.short) == ChoiceType.SEARCH:
                    post_choice = web_choice.choice.callback(self, task, web_choice.follow_up_info["artist"], web_choice.follow_up_info["query"])
                elif ChoiceType(web_choice.choice.short) == ChoiceType.ID:
                    post_choice = web_choice.choice.callback(self, task, web_choice.follow_up_info["mbid"])
                else:
                    post_choice = web_choice.choice.callback(self, task)
                if isinstance(post_choice, importer.Action):
                    self.queues.delete(queue_id)
                    return post_choice
                elif isinstance(post_choice, Proposal):
                    task.candidates = post_choice.candidates
                    task.rec = post_choice.recommendation

            else:
                # We have a candidate! Finish tagging. Here, choice is an
                # AlbumMatch object.
                assert isinstance(web_choice.choice, AlbumMatch)
                self.queues.delete(queue_id)
                return web_choice.choice


    def choose_item(
        self, task: SingletonImportTask
    ) -> TrackMatch | importer.Action:
        """Ask the user for a choice about tagging a single item. Returns
        either an action constant or a TrackMatch object.
        """
        print(displayable_path(task.item.path))

        # Take immediate action if appropriate.
        # TODO: introduce beets.autotag.Candidates to remove these assertions
        assert task.rec is not None
        assert task.candidates is not None
        action = _summary_judgment(task.rec)
        if action == importer.Action.APPLY:
            match = task.candidates[0]
            # TODO: introduce AlbumImportTask to remove this assertion
            assert isinstance(match, TrackMatch)
            # show_item_change(task.source, match)
            return match
        if action is not None:
            return action

        queue_item = QueueStorageItem(task)
        queue_id = self.queues.store(queue_item)
        self._queue_ids.append(queue_id)

        while True:
            # Ask for a choice.
            choices = self._get_choices(task)
            self.queues.update(queue_id, task, choices)
            web_choice: WebChoice = queue_item.queue.get()
            # choice = choose_candidate(
            #     # TODO: introduce AlbumImportTask to remove this ignore
            #     task.candidates,  # type: ignore[arg-type]
            #     task.rec,
            #     task.source,
            #     choices=choices,
            # )

            # We have a specific match selection.
            # or, basic web_choice.choices that require no more action here.
            if isinstance(web_choice.choice, TrackMatch) or (
                isinstance(web_choice.choice, importer.Action)
                and web_choice.choice in (importer.Action.SKIP, importer.Action.ASIS)
            ):
                # Pass selection to main control flow.
                self.queues.delete(queue_id)
                return web_choice.choice

            # Plugin-provided web_choice.choices. We invoke the associated callback
            # function.
            if isinstance(web_choice.choice, PromptChoice) and web_choice.choice.callback:
                if ChoiceType(web_choice.choice.short) == ChoiceType.SEARCH:
                    post_choice = web_choice.choice.callback(self, task, web_choice.follow_up_info["artist"], web_choice.follow_up_info["query"])
                elif ChoiceType(web_choice.choice.short) == ChoiceType.ID:
                    post_choice = web_choice.choice.callback(self, task, web_choice.follow_up_info["mbid"])
                else:
                    post_choice = web_choice.choice.callback(self, task)
                if isinstance(post_choice, importer.Action):
                    return post_choice
                elif isinstance(post_choice, Proposal):
                    task.candidates = post_choice.candidates
                    task.rec = post_choice.recommnedation

    def _report_item_summary(
        self, prefix: Literal["Old", "New"], items: list[Item], is_album: bool
    ) -> str:
        summary_string = f"{prefix}: {summarize_items(items, not is_album)}"
        if self.config["duplicate_verbose_prompt"].get(bool):
            for dup in items:
                summary_string += f"\n  {dup}"
        return summary_string

    def _get_duplicate_action_from_user(
        self, task: importer.ImportTask, found_duplicates: list[AlbumOrItem]
    ) -> str:
        """Decide what to do when a new album or item seems similar to one
        that's already in the library.
        """
        is_album = task.is_album
        # log.warning("This {.source.type} is already in the library!", task)

        if config["import"]["quiet"]:
            # In quiet mode, don't prompt -- just skip.
            log.info("Skipping.")
            return "s"
        choices = []
        for action in DuplicateAction:
            choice: PromptChoice = PromptChoice(action.value, action.text, None)
            choices.append(choice)

        # Print some detail about the existing and new items so the
        # user can make an informed decision.
        duplicate_summary = {"old" : []}
        for duplicate in found_duplicates:
            duplicate_summary["old"].append(self._report_item_summary(
                "Old",
                (
                    list(duplicate.items())
                    if isinstance(duplicate, Album)
                    else [duplicate]
                ),
                is_album,
            ))

        duplicate_summary["new"] = self._report_item_summary("New", task.imported_items(), is_album)
        queue_item = QueueStorageItem(task, choices, QueueStorageType.DUPLICATE, duplicate_summary)
        queue_id = self.queues.store(queue_item)
        self._queue_ids.append(queue_id)

        web_choice: WebChoice = queue_item.queue.get()


        assert isinstance(web_choice.choice, PromptChoice)
            
        self.queues.delete(queue_id)
        return web_choice.choice.short
        # return input_options(DuplicateAction.strict_options())

    def get_duplicate_action(
        self, task: importer.ImportTask, found_duplicates: list[AlbumOrItem]
    ) -> DuplicateAction:
        action = super().get_duplicate_action(task, found_duplicates)
        if action is DuplicateAction.ASK:
            return DuplicateAction(
                self._get_duplicate_action_from_user(task, found_duplicates)
            )  # type: ignore[call-arg]

        return action

    def should_resume(self, path: PathBytes) -> bool:
        queue_item = QueueStorageItem(queue_type=QueueStorageType.RESUME, path=displayable_path(path))
        queue_id = self.queues.store(queue_item)
        self._queue_ids.append(queue_id)
        choice = queue_item.queue.get()
        self.queues.delete(queue_id)
        return choice


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
                PromptChoice(
                    "t", "as Tracks", lambda s, t: importer.Action.TRACKS
                ),
                PromptChoice(
                    "g", "Group albums", lambda s, t: importer.Action.ALBUMS
                ),
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
            chain(
                *plugins.send(
                    "before_choose_candidate", session=self, task=task
                )
            )
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
            duplicates = [
                i for i, count in Counter(short_letters).items() if count > 1
            ]
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


def _summary_judgment(rec: Recommendation) -> importer.Action | None:
    """Determines whether a decision should be made without even asking
    the user. This occurs in quiet mode and when an action is chosen for
    NONE recommendations. Return None if the user should be queried.
    Otherwise, returns an action. May also print to the console if a
    summary judgment is made.
    """

    action: importer.Action | None
    if config["import"]["quiet"]:
        if rec == Recommendation.strong:
            return importer.Action.APPLY
        action = config["import"]["quiet_fallback"].as_choice(
            {"skip": importer.Action.SKIP, "asis": importer.Action.ASIS}
        )
    elif config["import"]["timid"]:
        return None
    elif rec == Recommendation.none:
        action = config["import"]["none_rec_action"].as_choice(
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

def choose_candidate(
    candidates,
    singleton,
    rec,
    cur_artist=None,
    cur_album=None,
    item=None,
    itemcount=None,
    choices=[],
):
    """Given a sorted list of candidates, ask the user for a selection
    of which candidate to use. Applies to both full albums and
    singletons  (tracks). Candidates are either AlbumMatch or TrackMatch
    objects depending on `singleton`. for albums, `cur_artist`,
    `cur_album`, and `itemcount` must be provided. For singletons,
    `item` must be provided.

    `choices` is a list of `PromptChoice`s to be used in each prompt.

    Returns one of the following:
    * the result of the choice, which may be SKIP or ASIS
    * a candidate (an AlbumMatch/TrackMatch object)
    * a chosen `PromptChoice` from `choices`
    """
    # Sanity check.
    if singleton:
        assert item is not None
    else:
        assert cur_artist is not None
        assert cur_album is not None

    # Build helper variables for the prompt choices.
    choice_opts = tuple(c.long for c in choices)
    choice_actions = {c.short: c for c in choices}

    # Zero candidates.
    if not candidates:
        if singleton:
            print("No matching recordings found.")
        else:
            print(f"No matching release found for {itemcount} tracks.")
            print(
                "For help, see: "
                "https://beets.readthedocs.org/en/latest/faq.html#nomatch"
            )
        sel = input_options(choice_opts)
        if sel in choice_actions:
            return choice_actions[sel]
        assert False

    # Is the change good enough?
    bypass_candidates = False
    if rec != Recommendation.none:
        match = candidates[0]
        bypass_candidates = True

    while True:
        # Display and choose from candidates.
        require = rec <= Recommendation.low

        if not bypass_candidates:
            # Display list of candidates.
            print(
                f"Finding tags for {'track' if singleton else 'album'} "
                f'"{item.artist if singleton else cur_artist} -'
                f' {item.title if singleton else cur_album}".'
            )

            print("  Candidates:")
            for i, match in enumerate(candidates):
                # Index, metadata, and distance.
                dist_color = match.distance.color
                line_parts = [
                    colorize(dist_color, f"{i + 1}."),
                    match.distance.string,
                    colorize(
                        dist_color if i == 0 else "text_highlight_minor",
                        f"{match.info.artist} - {match.info.name}",
                    ),
                ]
                print(f"  {' '.join(line_parts)}")

                # Penalties.
                if penalty_keys := match.distance.generic_penalty_keys:
                    if len(penalty_keys) > 3:
                        penalty_keys = [*penalty_keys[:3], "..."]
                    penalty_text = colorize(
                        "changed", f"\u2260 {', '.join(penalty_keys)}"
                    )
                    print(f"{' ' * 13}{penalty_text}")

                # Disambiguation
                if disambig := match.disambig_string:
                    print(f"{' ' * 13}{disambig}")

            # Ask the user for a choice.
            sel = input_options(choice_opts, numrange=(1, len(candidates)))
            if sel == "m":
                pass
            elif sel in choice_actions:
                return choice_actions[sel]
            else:  # Numerical selection.
                match = candidates[sel - 1]
                if sel != 1:
                    # When choosing anything but the first match,
                    # disable the default action.
                    require = True
        bypass_candidates = False

        # # Show what we're about to do.
        # if singleton:
        #     show_item_change(item, match)
        # else:
        #     show_change(cur_artist, cur_album, match)

        # Exact match => tag automatically if we're not in timid mode.
        if rec == Recommendation.strong and not config["import"]["timid"]:
            return match

        # Ask for confirmation.
        default = config["import"]["default_action"].as_choice(
            {"apply": "a", "skip": "s", "asis": "u", "none": None}
        )
        if default is None:
            require = True
        # Bell ring when user interaction is needed.
        if config["import"]["bell"]:
            print("\a", end="")
        sel = input_options(
            ("Apply", "More candidates", *choice_opts),
            require=require,
            default=default,
        )
        if sel == "a":
            return match
        if sel in choice_actions:
            return choice_actions[sel]


def web_search(session, task, artist, name):
    """Get a new `Proposal` using manual search criteria.

    Input either an artist and album (for full albums) or artist and
    track name (for singletons) for manual search.
    """

    if task.is_album:
        _, _, prop = tag_album(task.items, artist.strip(), name.strip())
        return prop
    return tag_item(task.item, artist.strip(), name.strip())

def web_id(session, task, mbid):
    """Get a new `Proposal` using a manually-entered ID.

    Input an ID, either for an album ("release") or a track ("recording").
    """
    if task.is_album:
        _, _, prop = tag_album(task.items, search_ids=mbid.split())
        return prop
    return tag_item(task.item, search_ids=mbid.split())



def abort_action(session: ImportSession, task: ImportTask) -> None:
    """A prompt choice callback that aborts the importer."""
    raise importer.ImportAbortError()

def input_(prompt=None):
    """Like `input`, but decodes the result to a Unicode string.
    Raises a UserError if stdin is not available. The prompt is sent to
    stdout rather than stderr. A printed between the prompt and the
    input cursor.
    """
    # raw_input incorrectly sends prompts to stderr, not stdout, so we
    # use print_() explicitly to display prompts.
    # https://bugs.python.org/issue1927
    if prompt:
        print(prompt, end=" ")

    try:
        resp = input()
    except EOFError:
        raise UserError("stdin stream ended while input required")

    return resp


def input_options(
    options,
    require=False,
    prompt=None,
    fallback_prompt=None,
    numrange=None,
    default=None,
    max_width=72,
):
    """Prompts a user for input. The sequence of `options` defines the
    choices the user has. A single-letter shortcut is inferred for each
    option; the user's choice is returned as that single, lower-case
    letter. The options should be provided as lower-case strings unless
    a particular shortcut is desired; in that case, only that letter
    should be capitalized.

    By default, the first option is the default. `default` can be provided to
    override this. If `require` is provided, then there is no default. The
    prompt and fallback prompt are also inferred but can be overridden.

    If numrange is provided, it is a pair of `(high, low)` (both ints)
    indicating that, in addition to `options`, the user may enter an
    integer in that inclusive range.

    `max_width` specifies the maximum number of columns in the
    automatically generated prompt string.
    """
    # Assign single letters to each option. Also capitalize the options
    # to indicate the letter.
    letters = {}
    display_letters = []
    capitalized = []
    first = True
    for option in options:
        # Is a letter already capitalized?
        for letter in option:
            if letter.isalpha() and letter.upper() == letter:
                found_letter = letter
                break
        else:
            # Infer a letter.
            for letter in option:
                if not letter.isalpha():
                    continue  # Don't use punctuation.
                if letter not in letters:
                    found_letter = letter
                    break
            else:
                raise ValueError("no unambiguous lettering found")

        letters[found_letter.lower()] = option
        index = option.index(found_letter)

        # Mark the option's shortcut letter for display.
        if not require and (
            (default is None and not numrange and first)
            or (
                isinstance(default, str)
                and found_letter.lower() == default.lower()
            )
        ):
            # The first option is the default; mark it.
            show_letter = f"[{found_letter.upper()}]"
            is_default = True
        else:
            show_letter = found_letter.upper()
            is_default = False

        # Colorize the letter shortcut.
        show_letter = colorize(
            "action_default" if is_default else "action", show_letter
        )

        # Insert the highlighted letter back into the word.
        descr_color = "action_default" if is_default else "action_description"
        capitalized.append(
            colorize(descr_color, option[:index])
            + show_letter
            + colorize(descr_color, option[index + 1 :])
        )
        display_letters.append(found_letter.upper())

        first = False

    # The default is just the first option if unspecified.
    if require:
        default = None
    elif default is None:
        if numrange:
            default = numrange[0]
        else:
            default = display_letters[0].lower()

    # Make a prompt if one is not provided.
    if not prompt:
        prompt_parts = []
        prompt_part_lengths = []
        if numrange:
            if isinstance(default, int):
                default_name = str(default)
                default_name = colorize("action_default", default_name)
                tmpl = "# selection (default {})"
                prompt_parts.append(tmpl.format(default_name))
                prompt_part_lengths.append(len(tmpl) - 2 + len(str(default)))
            else:
                prompt_parts.append("# selection")
                prompt_part_lengths.append(len(prompt_parts[-1]))
        prompt_parts += capitalized
        prompt_part_lengths += [len(s) for s in options]

        # Wrap the query text.
        # Start prompt with U+279C: Heavy Round-Tipped Rightwards Arrow
        prompt = colorize("action", "\u279c ")
        line_length = 0
        for i, (part, length) in enumerate(
            zip(prompt_parts, prompt_part_lengths)
        ):
            # Add punctuation.
            if i == len(prompt_parts) - 1:
                part += colorize("action_description", "?")
            else:
                part += colorize("action_description", ",")
            length += 1

            # Choose either the current line or the beginning of the next.
            if line_length + length + 1 > max_width:
                prompt += "\n"
                line_length = 0

            if line_length != 0:
                # Not the beginning of the line; need a space.
                part = f" {part}"
                length += 1

            prompt += part
            line_length += length

    # Make a fallback prompt too. This is displayed if the user enters
    # something that is not recognized.
    if not fallback_prompt:
        fallback_prompt = "Enter one of "
        if numrange:
            fallback_prompt += "{}-{}, ".format(*numrange)
        fallback_prompt += f"{', '.join(display_letters)}:"

    resp = input_(prompt)
    while True:
        resp = resp.strip().lower()

        # Try default option.
        if default is not None and not resp:
            resp = default

        # Try an integer input if available.
        if numrange:
            try:
                resp = int(resp)
            except ValueError:
                pass
            else:
                low, high = numrange
                if low <= resp <= high:
                    return resp
                resp = None

        # Try a normal letter input.
        if resp:
            resp = resp[0]
            if resp in letters:
                return resp

        # Prompt for new input.
        resp = input_(fallback_prompt)




