"""Browser uploads for the importer: settings, safe paths, archive unpacking, cleanup."""

import os
import secrets
import shutil
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import IO

from beets import config

from beets_jar.models.uploads import MB, UploadSettings

CHUNK = MB
MAX_FILES = 5000  # per request, and per archive
# Loose files (dropped without a folder) are put in this folder
LOOSE_FOLDER = PurePosixPath("Uploaded files")
FORM_SLACK = 8 * MB  # multipart envelope overhead allowed on top of max_size

AUDIO_EXTS = {
    ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav",
    ".aif", ".aiff", ".wv", ".ape", ".mpc", ".dsf", ".dff",
}  # fmt: skip
SIDECAR_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".cue", ".log",
    ".lrc", ".elrc", ".srt", ".vtt", ".txt", ".lyrics",
}  # fmt: skip
# .tar.zst needs Python 3.14's compression.zstd; on 3.12/3.13 it fails to open
ARCHIVE_SUFFIXES = (
    ".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
    ".tar.zst",
)  # fmt: skip


class UploadError(Exception):
    """A user-facing reason the upload was refused."""


def upload_settings() -> UploadSettings | None:
    """The upload config, or None when uploads are off (or no directory is set)."""
    upload_config = config["jar"]["upload"]
    if not upload_config["enabled"].get(bool) or not upload_config["directory"].get():
        return None
    return UploadSettings(
        Path(upload_config["directory"].as_filename()),
        upload_config["max_size"].get(int) * MB,
    )


# ---------------------------------------------------------------- paths


def safe_relpath(name: str) -> PurePosixPath | None:
    """A client-supplied path as a clean relative path, or None if it's junk.

    Drops empty, '.' and '..' parts (so absolute and traversal paths collapse
    into the staging dir) and macOS resource-fork litter.
    """
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts or "__MACOSX" in parts or parts[-1].startswith("._"):
        return None
    return PurePosixPath(*parts)


def is_archive(rel: PurePosixPath) -> bool:
    return rel.name.lower().endswith(ARCHIVE_SUFFIXES)


def is_wanted(rel: PurePosixPath) -> bool:
    return rel.suffix.lower() in AUDIO_EXTS | SIDECAR_EXTS


def archive_stem(rel: PurePosixPath) -> PurePosixPath:
    """'Downloads/Album.tar.gz' -> 'Downloads/Album' (the folder it unpacks into)."""
    name = rel.name
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if name.lower().endswith(suffix):
            return rel.with_name(name[: -len(suffix)] or "archive")
    return rel


def new_staging_dir(settings: UploadSettings) -> Path:
    path = settings.directory / f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    path.mkdir(parents=True)
    return path


# ---------------------------------------------------------------- writing


class Budget:
    """Bytes left to write for one upload. Raises UploadError when overdrawn."""

    def __init__(self, settings: UploadSettings):
        self.left = settings.max_bytes
        self.max_mb = settings.max_mb

    def take(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise UploadError(f"That's over the {self.max_mb} MB upload limit.")


def _write(src: IO[bytes], staging: Path, rel: PurePosixPath, budget: Budget) -> None:
    dest = (staging / rel).resolve()
    if not dest.is_relative_to(staging.resolve()):  # belt and braces after safe_relpath
        raise UploadError("Upload contained a bad file path.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        while chunk := src.read(CHUNK):
            budget.take(len(chunk))
            out.write(chunk)


def _unpack(src: IO[bytes], staging: Path, into: PurePosixPath, budget: Budget) -> int:
    """Copy the wanted regular files of a zip/tar into staging/into.

    Members are read and written one by one rather than with extractall, so
    links, devices and anything off the allowlist are never created, and every
    byte goes through the budget (declared sizes can lie).
    """
    written = 0
    src.seek(0)
    if zipfile.is_zipfile(src):
        src.seek(0)
        with zipfile.ZipFile(src) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            # Fail fast on obvious bombs; the budget still enforces the real limit.
            if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > budget.left:
                raise UploadError(f"{into.name} is too large to unpack.")
            for info in infos:
                rel = safe_relpath(info.filename)
                if rel and is_wanted(rel):
                    with zf.open(info) as member:
                        _write(member, staging, into / rel, budget)
                    written += 1
        return written

    src.seek(0)
    try:
        tf = tarfile.open(fileobj=src, mode="r:*")
    except tarfile.TarError:
        raise UploadError(f"Couldn't open {into.name}.") from None
    with tf:
        for count, member in enumerate(tf, start=1):
            if count > MAX_FILES:
                raise UploadError(f"{into.name} has too many files.")
            rel = safe_relpath(member.name)
            if not (member.isfile() and rel and is_wanted(rel)):
                continue
            data = tf.extractfile(member)  # only None for non-regular members
            if data is not None:
                _write(data, staging, into / rel, budget)
                written += 1
    return written


def store_upload(
    staging: Path, entries: list[tuple[IO[bytes], str]], settings: UploadSettings
) -> int:
    """Write (file, client path) pairs into staging, unpacking archives.

    Every file ends up inside a top-level folder (see import_paths): archives
    unpack into a folder named after them, and loose files go into LOOSE_FOLDER.
    Returns how many files landed. Raises UploadError; the caller removes staging.
    """
    budget = Budget(settings)
    written = 0
    for src, name in entries:
        rel = safe_relpath(name)
        if rel is None:
            continue
        if is_archive(rel):
            written += _unpack(src, staging, archive_stem(rel), budget)
        elif is_wanted(rel):
            if len(rel.parts) == 1:
                rel = LOOSE_FOLDER / rel
            _write(src, staging, rel, budget)
            written += 1
    return written


def import_paths(staging: Path) -> list[str]:
    """The folders to import: the upload's top-level folders, not staging itself.

    Session titles come from the import path, so this gives "/import/…/Album"
    rather than the staging folder's timestamp. Staging stays the unique parent,
    because beets keys incremental and resume state on the path.
    """
    return sorted(str(path) for path in staging.iterdir() if path.is_dir())


# ---------------------------------------------------------------- cleanup


def prune_upload(staging: Path) -> None:
    """After the import session ends: remove the staging dir if no audio is left.

    With `import.move`, everything imported is gone and only sidecars (cover,
    cue, log) remain, so the whole folder goes. With `copy`, or when albums were
    skipped, the audio is still here and restart needs it, so only empty dirs go.
    """
    if not staging.exists():
        return
    if not any(p.suffix.lower() in AUDIO_EXTS for p in staging.rglob("*")):
        shutil.rmtree(staging, ignore_errors=True)
        return
    for root, _, _ in os.walk(staging, topdown=False):
        try:
            os.rmdir(root)
        except OSError:
            pass
