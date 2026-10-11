from dataclasses import dataclass
from pathlib import Path

MB = 1024 * 1024


@dataclass(frozen=True)
class UploadSettings:
    """The jar.upload config, read once per request."""

    directory: Path
    max_bytes: int

    @property
    def max_mb(self) -> int:
        return self.max_bytes // MB
