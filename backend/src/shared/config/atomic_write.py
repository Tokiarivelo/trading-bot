"""Crash-safe text writes: a torn write to a config file that's read back on
every startup (or, worse, mid-request) is worse than a failed write, so every
writer in this module set goes through here instead of a bare `open("w")`.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: Path, text: str) -> None:
    """Writes `text` to `path` via a sibling temp file + `os.replace`, which
    is atomic on POSIX — a reader never observes a partially-written file,
    and a crash mid-write leaves the original untouched."""
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text)
    os.replace(tmp_path, path)
