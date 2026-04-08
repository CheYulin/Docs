#!/usr/bin/env python3
"""Summarize and compare KV bpftrace stack reports."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from dataclasses import dataclass
from typing import Dict, List

SECTION_RE = re.compile(r"^---\s+([a-z_]+)\s+\(top\s+\d+\)\s+---\s*$")
COUNT_RE = re.compile(r"\]:\s*([0-9]+)\s*$")
FAILED_STACK_RE = re.compile(r"failed to look up stack id", re.IGNORECASE)


@dataclass
class SectionStats:
    name: str
    counts: List[int]
    failed_stack_lines: int = 0

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def top1(self) -> int:
        return self.counts[-1] if self.counts else 0

    @property
    def top3(self) -> int:
        return sum(self.counts[-3:]) if self.counts else 0

    @property
    def entries(self) -> int:
        return len(self.counts)

    @property
    def top1_ratio(self) -> float:
        return (self.top1 / self.total) if self.total else 0.0

    @property
    def top3_ratio(self) -> float:
        return (self.top3 / self.total) if self.total else 0.0


def parse_report(path: pathlib.Path) -> Dict[str, SectionStats]:
    sections: Dict[str, SectionStats] = {}
    current: SectionStats | None = None

    for raw in path.read_text(errors="replace").splitlines():
        line = raw.rstrip("\n")
        match = SECTION_RE.match(line)
        if match:
            name = match.group(1)
            current = SectionStats(name=name, counts=[])
            sections[name] = current
            continue

        if current is None:
            continue

        if FAILED_STACK_RE.search(line):
            current.failed_stack_lines += 1
            continue

        count_match = COUNT_RE.search(line)
        if count_match:
            current.counts.append(int(count_match.group(1)))

    return sections


def pct_delta(base: int, cur: int) -> str:
    if base == 0 and cur == 0:
        return "0.0%"
    if base == 0:
        return "n/a(base=0)"
    return f"{(cur - base) * 100.0 / base:+.1f}%"


def print_single(title: str, data: Dict[str, SectionStats]) -> None:
    print(f"== {title} ==")
    if not data:
        print("No syscall sections found. Check input report format.")
        return
    print("section,total,entries,top1,top1_ratio,top3,top3_ratio,failed_stack_lines")
    for name in sorted(data.keys()):
        s = data[name]
        print(
            f"{name},{s.total},{s.entries},{s.top1},{s.top1_ratio:.3f},"
            f"{s.top3},{s.top3_ratio:.3f},{s.failed_stack_lines}"
        )


def print_compare(
    baseline: Dict[str, SectionStats],
    current: Dict[str, SectionStats],
) -> None:
    names = sorted(set(baseline.keys()) | set(current.keys()))
    print("== baseline_vs_current ==")
    print("section,baseline_total,current_total,delta_total,baseline_top1_ratio,current_top1_ratio")
    for name in names:
        b = baseline.get(name, SectionStats(name=name, counts=[]))
        c = current.get(name, SectionStats(name=name, counts=[]))
        print(
            f"{name},{b.total},{c.total},{pct_delta(b.total, c.total)},"
            f"{b.top1_ratio:.3f},{c.top1_ratio:.3f}"
        )

    print("")
    print("heuristics:")
    futex_b = baseline.get("futex", SectionStats(name="futex", counts=[])).total
    futex_c = current.get("futex", SectionStats(name="futex", counts=[])).total
    poll_b = baseline.get("epoll", SectionStats(name="epoll", counts=[])).total + baseline.get(
        "poll", SectionStats(name="poll", counts=[])
    ).total
    poll_c = current.get("epoll", SectionStats(name="epoll", counts=[])).total + current.get(
        "poll", SectionStats(name="poll", counts=[])
    ).total
    print(f"- futex total delta: {pct_delta(futex_b, futex_c)}")
    print(f"- epoll+poll total delta: {pct_delta(poll_b, poll_c)}")
    print("- Interpretation should combine with test pass status and stack symbolization.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize and compare bpftrace stack reports for KV lock analysis."
    )
    parser.add_argument("--baseline", type=pathlib.Path, help="Baseline trace_*_stacks.txt")
    parser.add_argument("--current", type=pathlib.Path, required=True, help="Current trace file")
    args = parser.parse_args()

    if not args.current.exists():
        print(f"Missing current file: {args.current}", file=sys.stderr)
        return 2

    cur_data = parse_report(args.current)
    print_single(f"current: {args.current}", cur_data)

    if args.baseline:
        if not args.baseline.exists():
            print(f"Missing baseline file: {args.baseline}", file=sys.stderr)
            return 2
        base_data = parse_report(args.baseline)
        print("")
        print_single(f"baseline: {args.baseline}", base_data)
        print("")
        print_compare(base_data, cur_data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
