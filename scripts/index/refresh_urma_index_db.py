#!/usr/bin/env python3
"""Refresh IDE compile_commands for UB/URMA indexing.

Generate an indexing-only compile_commands database by copying an existing
compile_commands.json and appending feature macros to every compile command.

Default paths resolve the datasystem checkout from ``.../scripts`` (see ``lib/datasystem_root``). This script can be run from any working directory when using defaults.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List


def _bootstrap_scripts_dir() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "lib" / "datasystem_root.py").is_file():
            return p
        p = p.parent
    raise RuntimeError(f"Could not find scripts/lib above {__file__!r}")


_SCRIPTS_DIR = _bootstrap_scripts_dir()
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.datasystem_root import resolve_datasystem_root


def _repo_root() -> Path:
    return resolve_datasystem_root(scripts_dir=_SCRIPTS_DIR)


def _patch_command(command: str, macros: List[str]) -> str:
    extra = [m for m in macros if m not in command]
    if not extra:
        return command
    return f"{command} {' '.join(extra)}"


def _patch_arguments(arguments: List[str], macros: List[str]) -> List[str]:
    result = list(arguments)
    for macro in macros:
        if macro not in result:
            result.append(macro)
    return result


def _normalize_macros(raw_macros: List[str]) -> List[str]:
    normalized: List[str] = []
    for raw in raw_macros:
        items = shlex.split(raw)
        for item in items:
            if not item:
                continue
            normalized.append(item if item.startswith("-D") else f"-D{item}")
    return list(dict.fromkeys(normalized))


def _update_database(data: List[Dict[str, Any]], macros: List[str]) -> int:
    patched = 0
    for item in data:
        changed = False
        if isinstance(item.get("command"), str):
            new_command = _patch_command(item["command"], macros)
            changed = changed or (new_command != item["command"])
            item["command"] = new_command
        if isinstance(item.get("arguments"), list):
            new_arguments = _patch_arguments(item["arguments"], macros)
            changed = changed or (new_arguments != item["arguments"])
            item["arguments"] = new_arguments
        if changed:
            patched += 1
    return patched


def _resolve_path(path_str: str, cwd: Path, repo: Path) -> Path:
    p = Path(path_str)
    if p.is_absolute():
        return p.resolve()
    # Prefer resolving relative to cwd (standard CLI); repo is available if needed later.
    return (cwd / p).resolve()


def main() -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(
        description="Generate indexing compile_commands with extra feature macros."
    )
    parser.add_argument(
        "--source",
        default=str(root / "build" / "compile_commands.json"),
        help="Source compile_commands.json path (default: <repo>/build/compile_commands.json).",
    )
    parser.add_argument(
        "--output",
        default=str(root / ".cursor" / "compile_commands.json"),
        help="Output path for IDE indexing (default: <repo>/.cursor/compile_commands.json).",
    )
    parser.add_argument(
        "--macro",
        action="append",
        default=["USE_URMA", "URMA_OVER_UB"],
        help=(
            "Macro to append, can be used multiple times. "
            "Accepts both USE_URMA and -DUSE_URMA forms."
        ),
    )
    args = parser.parse_args()
    cwd = Path.cwd()

    src = _resolve_path(args.source, cwd, root)
    dst = _resolve_path(args.output, cwd, root)
    macros = _normalize_macros(args.macro)

    if not src.exists():
        print(f"Source file not found: {src}", file=sys.stderr)
        return 1

    with src.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        print(f"Invalid compile_commands format in {src}: root is not a list", file=sys.stderr)
        return 1

    patched = _update_database(data, macros)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Source : {src}")
    print(f"Output : {dst}")
    print(f"Entries: {len(data)}")
    print(f"Patched: {patched}")
    print(f"Macros : {' '.join(macros)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
