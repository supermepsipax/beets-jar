"""Turning the work area's form fields into the reply a blocked import prompt expects."""

from beets_jar.models.imports import ChoiceType, Prompt, WebChoice


def build_reply(prompt: Prompt, type: str, value: str, artist: str, query: str, mbid: str):
    """Turn form fields into what the blocked pipeline thread expects. Raises ValueError."""
    if prompt.kind == "resume":
        return value == "yes"

    if prompt.kind == "candidate" and type == "candidate":
        candidates = prompt.task.candidates or []
        try:
            index = int(value) - 1
        except ValueError:
            raise ValueError("Unknown candidate.") from None
        if not 0 <= index < len(candidates):
            raise ValueError("Unknown candidate.")
        return WebChoice(candidates[index], {})

    choice = next((c for c in prompt.choices if c.short == value), None)
    if choice is None:
        raise ValueError("Unknown action.")

    if prompt.kind == "candidate":
        if choice.short == ChoiceType.SEARCH:
            if not query:
                raise ValueError("Enter something to search for.")
            return WebChoice(choice, {"artist": artist, "query": query})
        if choice.short == ChoiceType.ID:
            if not mbid:
                raise ValueError("Enter a MusicBrainz ID.")
            return WebChoice(choice, {"mbid": mbid})

    return WebChoice(choice, {})
