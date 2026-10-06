"""Turning the work area's form fields into the reply a blocked import prompt expects."""

from beets_jar.models.imports import ChoiceType, Prompt, WebChoice


def build_reply(
    prompt: Prompt, choice_type: str, value: str, artist: str, query: str, mbid: str
) -> bool | WebChoice:
    """Turn form fields into what the blocked pipeline thread expects.

    choice_type is "candidate" (value is a 1-based candidate number) or "action"
    (value is a choice's short letter). Raises ValueError with a message for the user.
    """
    if prompt.kind == "resume":
        return value == "yes"
    if prompt.kind == "candidate" and choice_type == "candidate":
        return _candidate_reply(prompt, value)
    return _choice_reply(prompt, value, artist, query, mbid)


def _candidate_reply(prompt: Prompt, value: str) -> WebChoice:
    candidates = prompt.task.candidates or []
    try:
        index = int(value) - 1
    except ValueError:
        raise ValueError("Unknown candidate.") from None
    if not 0 <= index < len(candidates):
        raise ValueError("Unknown candidate.")
    return WebChoice(candidates[index], {})


def _choice_reply(prompt: Prompt, value: str, artist: str, query: str, mbid: str) -> WebChoice:
    choice = next((choice for choice in prompt.choices if choice.short == value), None)
    if choice is None:
        raise ValueError("Unknown action.")

    if prompt.kind == "candidate" and choice.short == ChoiceType.SEARCH:
        if not query:
            raise ValueError("Enter something to search for.")
        return WebChoice(choice, {"artist": artist, "query": query})
    if prompt.kind == "candidate" and choice.short == ChoiceType.ID:
        if not mbid:
            raise ValueError("Enter a MusicBrainz ID.")
        return WebChoice(choice, {"mbid": mbid})
    return WebChoice(choice, {})
