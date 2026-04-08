#!/usr/bin/env python3
import argparse
import glob
import json
import os
import re
from collections import defaultdict

SYSCALL_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d+\s+([a-zA-Z0-9_]+)\(")
DURATION_RE = re.compile(r"<([0-9]+\.[0-9]+)>$")
CONNECT_RE = re.compile(r"connect\([^)]*?\)\s+=\s+(-?\d+).*")

LOCK_SYSCALLS = {"futex", "flock", "fcntl"}
IO_SYSCALLS = {
    "read",
    "write",
    "pread64",
    "pwrite64",
    "recvfrom",
    "sendto",
    "recvmsg",
    "sendmsg",
    "connect",
    "accept",
    "poll",
    "ppoll",
    "epoll_wait",
    "epoll_pwait",
}


def parse_args():
    p = argparse.ArgumentParser(description="Analyze strace lock/io footprint.")
    p.add_argument("--trace-prefix", required=True, help="Prefix passed to strace -o")
    p.add_argument("--summary", required=True, help="Output summary json")
    p.add_argument("--report", required=True, help="Output markdown report")
    return p.parse_args()


def main():
    args = parse_args()
    files = sorted(glob.glob(args.trace_prefix + "*"))
    if not files:
        raise FileNotFoundError(f"no trace file found for prefix: {args.trace_prefix}")

    stats = defaultdict(lambda: {"count": 0, "total_s": 0.0})
    connect_lines = []
    total_lines = 0

    for fpath in files:
        with open(fpath, "r", errors="ignore") as f:
            for line in f:
                total_lines += 1
                m = SYSCALL_RE.search(line)
                if not m:
                    continue
                name = m.group(1)
                d = DURATION_RE.search(line.strip())
                dur = float(d.group(1)) if d else 0.0
                stats[name]["count"] += 1
                stats[name]["total_s"] += dur
                if name == "connect":
                    if CONNECT_RE.search(line):
                        connect_lines.append(line.strip())

    lock_stats = {k: stats[k] for k in LOCK_SYSCALLS if k in stats}
    io_stats = {k: stats[k] for k in IO_SYSCALLS if k in stats}

    def rank(d):
        return sorted(
            [{"syscall": k, "count": v["count"], "total_s": round(v["total_s"], 6)} for k, v in d.items()],
            key=lambda x: (-x["total_s"], -x["count"], x["syscall"]),
        )

    summary = {
        "trace_prefix": args.trace_prefix,
        "trace_files": files,
        "total_lines": total_lines,
        "lock_syscalls": rank(lock_stats),
        "io_syscalls": rank(io_stats),
        "top_connect_samples": connect_lines[:20],
    }

    os.makedirs(os.path.dirname(args.summary), exist_ok=True)
    with open(args.summary, "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w") as f:
        f.write("# Strace Lock/IO Trace Report\n\n")
        f.write(f"- trace prefix: `{args.trace_prefix}`\n")
        f.write(f"- trace file count: `{len(files)}`\n")
        f.write(f"- parsed lines: `{total_lines}`\n\n")

        f.write("## Lock syscalls (by total time)\n\n")
        for item in summary["lock_syscalls"]:
            f.write(
                f"- `{item['syscall']}`: count={item['count']}, total_s={item['total_s']}\n"
            )
        if not summary["lock_syscalls"]:
            f.write("- none\n")

        f.write("\n## IO/syscall wait surface (by total time)\n\n")
        for item in summary["io_syscalls"][:12]:
            f.write(
                f"- `{item['syscall']}`: count={item['count']}, total_s={item['total_s']}\n"
            )
        if not summary["io_syscalls"]:
            f.write("- none\n")

        f.write("\n## Connect samples (for 3rd-party path hints)\n\n")
        if summary["top_connect_samples"]:
            for line in summary["top_connect_samples"]:
                f.write(f"- `{line}`\n")
        else:
            f.write("- none\n")


if __name__ == "__main__":
    main()
