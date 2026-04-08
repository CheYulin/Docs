"""Resolve yuanrong-datasystem repo root when scripts live under vibe-coding-files."""

from __future__ import annotations

import os
from pathlib import Path


def scripts_root_from_here(caller_file: str | Path) -> Path:
    """Return ``.../vibe-coding-files/scripts`` containing ``lib/datasystem_root.py``."""
    p = Path(caller_file).resolve().parent
    while p != p.parent:
        if (p / "lib" / "datasystem_root.py").is_file():
            return p
        p = p.parent
    raise RuntimeError(
        f"Could not find scripts/ (lib/datasystem_root.py) above {caller_file!r}"
    )


def resolve_datasystem_root(*, scripts_dir: Path) -> Path:
    """Return datasystem checkout root.

    Resolution order:
    1. Environment variable DATASYSTEM_ROOT (or YUANRONG_DATASYSTEM_ROOT).
    2. Parent of ``scripts_dir`` if it looks like a datasystem tree
       (CMakeLists.txt + src/datasystem).
    3. Sibling ``../yuanrong-datasystem`` if that directory exists.
    4. Fallback: parent of ``scripts_dir`` (historical behaviour).
    """
    for key in ("DATASYSTEM_ROOT", "YUANRONG_DATASYSTEM_ROOT"):
        raw = os.environ.get(key)
        if raw:
            return Path(raw).resolve()

    scripts_dir = scripts_dir.resolve()
    parent = scripts_dir.parent

    if (parent / "CMakeLists.txt").is_file() and (parent / "src" / "datasystem").is_dir():
        return parent

    sibling = parent.parent / "yuanrong-datasystem"
    if (sibling / "CMakeLists.txt").is_file():
        return sibling.resolve()

    return parent
