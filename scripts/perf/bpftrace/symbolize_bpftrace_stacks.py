#!/usr/bin/env python3
"""
Post-process bpftrace stack output: replace 0x... addresses with symbol+file:line when possible.

Requires a /proc/<pid>/maps snapshot taken while the traced process (or same binaries+ASLR
layout) is running. Capture example (run in another terminal while test runs):

  pgrep -nx ds_st_kv_cache | xargs -I{} cat /proc/{}/maps > /tmp/ds_maps.txt

Usage:
  python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \\
    --maps /tmp/ds_maps.txt \\
    workspace/observability/bpftrace/trace_XXX_stacks.txt \\
    > workspace/observability/bpftrace/trace_XXX_stacks.sym.txt

Uses llvm-symbolizer if LLVM_SYMBOLIZER_PATH or `llvm-symbolizer` is available; else addr2line.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass


HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")


@dataclass(frozen=True)
class MapSeg:
    start: int
    end: int
    path: str
    file_offset: int  # from maps column 3 (hex pages into file for this vma start)


def parse_maps(path: str) -> list[MapSeg]:
    segs: list[MapSeg] = []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            parts = line.split()
            if len(parts) < 6:
                continue
            range_part = parts[0]
            off = parts[2]
            rest = parts[5:]
            if "-" not in range_part:
                continue
            a, b = range_part.split("-", 1)
            try:
                start = int(a, 16)
                end = int(b, 16)
                file_off = int(off, 16)
            except ValueError:
                continue
            path_str = " ".join(rest) if rest else ""
            if path_str.startswith("["):
                continue
            if not path_str.startswith("/"):
                continue
            segs.append(MapSeg(start=start, end=end, path=path_str, file_offset=file_off))
    return segs


def find_seg(segs: list[MapSeg], addr: int) -> MapSeg | None:
    for s in segs:
        if s.start <= addr < s.end:
            return s
    return None


def try_llvm_symbolizer(obj: str, addr_in_mapping: int) -> str | None:
    exe = shutil.which("llvm-symbolizer") or None
    if not exe:
        lp = __import__("os").environ.get("LLVM_SYMBOLIZER_PATH")
        if lp and __import__("os").path.isfile(lp):
            exe = lp
    if not exe:
        return None
    # Offset within this mmap; works for many ET_DYN mappings.
    rel = addr_in_mapping
    try:
        p = subprocess.run(
            [exe, "--obj", obj, hex(rel)],
            capture_output=True,
            text=True,
            timeout=0.4,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "").strip()
    if not out or "??" in out.split("\n", 1)[0]:
        return None
    return out.replace("\n", " @ ")


def try_addr2line(obj: str, addr_in_mapping: int) -> str | None:
    exe = shutil.which("addr2line")
    if not exe:
        return None
    try:
        p = subprocess.run(
            [exe, "-C", "-f", "-p", "-e", obj, hex(addr_in_mapping)],
            capture_output=True,
            text=True,
            timeout=0.4,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (p.stdout or "").strip()
    if not out or "??:0" in out:
        return None
    return out


def resolve_addr(addr: int, segs: list[MapSeg]) -> str:
    seg = find_seg(segs, addr)
    if not seg:
        return hex(addr)
    off_in_vma = addr - seg.start
    # Prefer offset from mapping base (common for shared objects).
    for fn in (try_llvm_symbolizer, try_addr2line):
        sym = fn(seg.path, off_in_vma)
        if sym:
            return sym
    return f"{hex(addr)} ({seg.path}+0x{off_in_vma:x})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Symbolize bpftrace ustack hex lines using /proc maps.")
    ap.add_argument("--maps", required=True, help="/proc/<pid>/maps snapshot")
    ap.add_argument("input", help="bpftrace text output")
    ap.add_argument("-o", "--output", help="write here (default: stdout)")
    args = ap.parse_args()
    segs = parse_maps(args.maps)
    if not segs:
        print("No usable map segments found.", file=sys.stderr)
        return 1
    with open(args.input, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    cache: dict[int, str] = {}

    def repl(m: re.Match[str]) -> str:
        raw = m.group(0)
        addr = int(raw, 16)
        if addr not in cache:
            cache[addr] = resolve_addr(addr, segs)
        return cache[addr]

    out = HEX_RE.sub(repl, text)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as wf:
            wf.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
