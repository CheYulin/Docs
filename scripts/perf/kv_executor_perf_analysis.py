#!/usr/bin/env python3
import argparse
import csv
import os
import re
import statistics
import subprocess
from pathlib import Path

import matplotlib.pyplot as plt


def _vibe_coding_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "lib" / "datasystem_root.py").is_file():
            return p.parent
        p = p.parent
    raise RuntimeError("Could not find vibe-coding-files root (scripts/lib marker missing)")


_VIBE_ROOT = _vibe_coding_root()
_DEFAULT_PERF_OUT = _VIBE_ROOT / "workspace" / "observability" / "perf"

PERF_RE = re.compile(
    r"PERF_RESULT mode=(?P<mode>\w+)\s+set_avg_us=(?P<set_avg>[0-9.]+)\s+set_p95_us=(?P<set_p95>[0-9.]+)\s+"
    r"get_avg_us=(?P<get_avg>[0-9.]+)\s+get_p95_us=(?P<get_p95>[0-9.]+)"
)
RATIO_RE = re.compile(r"PERF_RATIO set_avg_ratio=(?P<set_ratio>[0-9.]+)\s+get_avg_ratio=(?P<get_ratio>[0-9.]+)")


def parse_args():
    p = argparse.ArgumentParser(description="Collect kv set/get executor overhead and draw charts.")
    p.add_argument("--build-dir", default="build", help="CMake build directory.")
    p.add_argument("--runs", type=int, default=5, help="How many repeated runs.")
    p.add_argument("--ops", type=int, default=120, help="Measured set/get operation count per mode.")
    p.add_argument("--warmup", type=int, default=20, help="Warmup operation count per mode.")
    p.add_argument(
        "--output-dir",
        default=str(_DEFAULT_PERF_OUT),
        help="Directory for csv and figures (default: workspace/observability/perf under vibe-coding-files).",
    )
    return p.parse_args()


def run_once(binary: Path, ops: int, warmup: int):
    env = os.environ.copy()
    env["DS_KV_EXEC_PERF_OPS"] = str(ops)
    env["DS_KV_EXEC_PERF_WARMUP"] = str(warmup)
    tests_desc = binary.parent / "ds_st_kv_cache_tests.cmake"
    if tests_desc.exists():
        text = tests_desc.read_text(errors="ignore")
        start = text.find("LD_LIBRARY_PATH=")
        marker = f"]==] {binary}"
        end = text.find(marker, start)
        if start >= 0 and end > start:
            env["LD_LIBRARY_PATH"] = text[start + len("LD_LIBRARY_PATH=") : end]
    cmd = [
        str(binary),
        "--gtest_filter=KVClientExecutorRuntimeE2ETest.PerfSetGetInlineVsInjectedExecutor",
        "--gtest_color=no",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"benchmark test failed:\n{proc.stdout}\n{proc.stderr}")

    result = {}
    ratios = {}
    for line in proc.stdout.splitlines():
        m = PERF_RE.search(line)
        if m:
            mode = m.group("mode")
            result[mode] = {
                "set_avg_us": float(m.group("set_avg")),
                "set_p95_us": float(m.group("set_p95")),
                "get_avg_us": float(m.group("get_avg")),
                "get_p95_us": float(m.group("get_p95")),
            }
        r = RATIO_RE.search(line)
        if r:
            ratios = {
                "set_avg_ratio": float(r.group("set_ratio")),
                "get_avg_ratio": float(r.group("get_ratio")),
            }

    if "inline" not in result or "injected" not in result:
        raise RuntimeError(f"failed to parse PERF_RESULT lines.\nstdout:\n{proc.stdout}")
    if not ratios:
        raise RuntimeError(f"failed to parse PERF_RATIO line.\nstdout:\n{proc.stdout}")
    return result, ratios


def main():
    args = parse_args()
    build_dir = Path(args.build_dir).resolve()
    binary = build_dir / "tests" / "st" / "ds_st_kv_cache"
    if not binary.exists():
        raise FileNotFoundError(f"missing benchmark binary: {binary}")

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(args.runs):
        perf, ratios = run_once(binary, args.ops, args.warmup)
        rows.append(
            {
                "run": i + 1,
                "inline_set_avg_us": perf["inline"]["set_avg_us"],
                "inline_get_avg_us": perf["inline"]["get_avg_us"],
                "injected_set_avg_us": perf["injected"]["set_avg_us"],
                "injected_get_avg_us": perf["injected"]["get_avg_us"],
                "set_avg_ratio": ratios["set_avg_ratio"],
                "get_avg_ratio": ratios["get_avg_ratio"],
            }
        )

    csv_path = out_dir / "kv_executor_perf_runs.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    set_ratios = [r["set_avg_ratio"] for r in rows]
    get_ratios = [r["get_avg_ratio"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(range(1, args.runs + 1), set_ratios, marker="o", label="Set avg ratio (injected/inline)")
    ax.plot(range(1, args.runs + 1), get_ratios, marker="s", label="Get avg ratio (injected/inline)")
    ax.axhline(1.0, linestyle="--", linewidth=1, color="gray")
    ax.set_xlabel("Run")
    ax.set_ylabel("Overhead ratio")
    ax.set_title("KV Set/Get Executor Overhead")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    ratio_png = out_dir / "kv_executor_overhead_ratio.png"
    fig.savefig(ratio_png, dpi=150)
    plt.close(fig)

    inline_set_avgs = [r["inline_set_avg_us"] for r in rows]
    inline_get_avgs = [r["inline_get_avg_us"] for r in rows]
    injected_set_avgs = [r["injected_set_avg_us"] for r in rows]
    injected_get_avgs = [r["injected_get_avg_us"] for r in rows]

    summary_path = out_dir / "kv_executor_perf_summary.txt"
    with summary_path.open("w") as f:
        f.write(f"runs={args.runs}, ops={args.ops}, warmup={args.warmup}\n")
        f.write("# Absolute latency (microseconds), mean over runs — required for lock-governance acceptance\n")
        f.write(f"inline_set_avg_us_mean={statistics.mean(inline_set_avgs):.2f}\n")
        f.write(f"inline_get_avg_us_mean={statistics.mean(inline_get_avgs):.2f}\n")
        f.write(f"injected_set_avg_us_mean={statistics.mean(injected_set_avgs):.2f}\n")
        f.write(f"injected_get_avg_us_mean={statistics.mean(injected_get_avgs):.2f}\n")
        f.write("# Ratio (injected/inline) — supplementary only\n")
        f.write(f"set_ratio_mean={statistics.mean(set_ratios):.4f}\n")
        f.write(f"set_ratio_p95={sorted(set_ratios)[max(0, int(0.95 * (len(set_ratios)-1)))]:.4f}\n")
        f.write(f"get_ratio_mean={statistics.mean(get_ratios):.4f}\n")
        f.write(f"get_ratio_p95={sorted(get_ratios)[max(0, int(0.95 * (len(get_ratios)-1)))]:.4f}\n")

    print(f"[DONE] csv={csv_path}")
    print(f"[DONE] chart={ratio_png}")
    print(f"[DONE] summary={summary_path}")


if __name__ == "__main__":
    main()
