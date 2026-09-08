from beets.util.color import colorize
from beets.autotag import Recommendation
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

def manual_search(session, task):
    """Get a new `Proposal` using manual search criteria.

    Input either an artist and album (for full albums) or artist and
    track name (for singletons) for manual search.
    """
    artist = input_("Artist:").strip()
    name = input_("Album:" if task.is_album else "Track:").strip()

    if task.is_album:
        _, _, prop = tag_album(task.items, artist, name)
        return prop
    return tag_item(task.item, artist, name)


def manual_id(session, task):
    """Get a new `Proposal` using a manually-entered ID.

    Input an ID, either for an album ("release") or a track ("recording").
    """
    prompt = f"Enter {'release' if task.is_album else 'recording'} ID:"
    search_id = input_(prompt).strip()

    if task.is_album:
        _, _, prop = tag_album(task.items, search_ids=search_id.split())
        return prop
    return tag_item(task.item, search_ids=search_id.split())



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
