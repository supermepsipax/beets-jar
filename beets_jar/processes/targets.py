from beets.library import Library


def build_queries(lib: Library, target: str, mode: str, ids: list[int]) -> tuple[str, ...]:
    """
    target: what the command's query selects ("album" | "item" | "flag")
    mode:   what the rows are ("album" | "item")
    """
    if target == "item" and mode == "album":
        track_ids = []
        for id_ in ids:
            album = lib.get_album(id_)
            if album is not None:
                track_ids.extend(item.id for item in album.items())
        return tuple(f"id:{track_id}" for track_id in track_ids)
    if target == "album" and mode == "item":
        album_ids = {}
        for id_ in ids:
            item = lib.get_item(id_)
            if item is not None and item.album_id is not None:
                album_ids[item.album_id] = None  # dict keeps first-seen order
        return tuple(f"id:{album_id}" for album_id in album_ids)
    return tuple(f"id:{id_}" for id_ in ids)


def album_flag(target: str, mode: str) -> bool | None:
    """opts.album for commands with -a/--album; None leaves other commands alone."""
    return mode == "album" if target == "flag" else None


