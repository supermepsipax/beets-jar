"""Turning the library page's Process form into ProcessSpecs."""

from collections.abc import Mapping

from beets.library import Library

from beets_jar.models.processes import ProcessSpec
from beets_jar.services.plugins import get_panel_plugins, read_overrides


def build_specs(lib: Library, form: Mapping) -> list[ProcessSpec]:
    """One spec per switched-on plugin, in panel order.

    Form: kind, query, ids[] (from #results-form) plus plugins[],
    <plugin>.command and <plugin>.<command>.<dest> (from #plugin-form).
    Raises ValueError with a message for the user when there's nothing to run.
    """
    kind = form.get("kind")
    ids = [int(raw_id) for raw_id in form.getlist("ids") if str(raw_id).isdigit()]
    if kind not in ("album", "item") or not ids:
        raise ValueError("Select something first.")
    plugin_names = form.getlist("plugins")
    if not plugin_names:
        raise ValueError("Switch a plugin on first.")

    panel = {plugin.name: plugin for plugin in get_panel_plugins()}
    specs = []
    for name in plugin_names:
        plugin = panel.get(str(name))
        if plugin is None:
            continue
        requested = str(form.get(f"{name}.command", ""))
        command = plugin.command(requested) or plugin.commands[0]
        try:
            overrides = read_overrides(command, form, f"{name}.{command.name}")
        except ValueError:
            raise ValueError(f"Check the {name} settings.") from None
        queries = build_queries(lib, command.target, kind, ids)
        if not queries:  # e.g. an album command on singletons only
            continue
        specs.append(
            ProcessSpec(
                plugin=plugin.name,
                command=command.name,
                queries=queries,
                # opts.album for commands with -a/--album; None leaves other commands alone
                album=(kind == "album") if command.target == "flag" else None,
                overrides={**overrides, **command.fixed},  # fixed wins
                subtitle=str(form.get("query", "")),
            )
        )

    if not specs:
        raise ValueError("Nothing to do for that selection.")
    return specs


def build_queries(lib: Library, target: str, kind: str, ids: list[int]) -> tuple[str, ...]:
    """One `id:N` query per thing the command should run on.

    target: what the command's query selects ("album" | "item" | "flag")
    kind:   what the selected rows are ("album" | "item")
    """
    if target == "item" and kind == "album":
        track_ids = []
        for album_id in ids:
            album = lib.get_album(album_id)
            if album is not None:
                track_ids.extend(item.id for item in album.items())
        return tuple(f"id:{track_id}" for track_id in track_ids)
    if target == "album" and kind == "item":
        album_ids = {}
        for item_id in ids:
            item = lib.get_item(item_id)
            if item is not None and item.album_id is not None:
                album_ids[item.album_id] = None  # dict keeps first-seen order
        return tuple(f"id:{album_id}" for album_id in album_ids)
    return tuple(f"id:{row_id}" for row_id in ids)
