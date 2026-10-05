"""Turning beets albums and items into library result rows."""

from beets.library import Album, Item, Library

from beets_jar.models.library import Kind, ResultRow


def get_album_or_item(lib: Library, kind: Kind, album_or_item_id: int) -> Album | Item | None:
    if kind == "album":
        return lib.get_album(album_or_item_id)
    return lib.get_item(album_or_item_id)


def result_row(album_or_item: Album | Item) -> ResultRow:
    if isinstance(album_or_item, Album):
        return ResultRow(
            album_or_item.id,
            album_or_item.album or "Unknown album",
            album_or_item.albumartist or "",
            album_or_item.year or None,
        )
    item = album_or_item
    subtitle = " · ".join(value for value in (item.artist, item.album) if value)
    return ResultRow(item.id, item.title or "Unknown track", subtitle, item.year or None)
