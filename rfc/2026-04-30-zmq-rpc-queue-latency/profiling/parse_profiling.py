#!/usr/bin/env python3
"""
parse_profiling.py — Unified parser for OS-level profiling data collected by run_profiling_pipeline.sh.

Reads all *_report.txt files in the profiling results directory and produces a structured
summary suitable for human review or CI ingestion.

Usage:
    python3 parse_profiling.py <results_dir>
    python3 parse_profiling.py /path/to/profiling_20260506_020300/

Output: prints to stdout, exits 0 on success.
"""

import sys
import os
import re
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def red(s: str) -> str:
    return f"\033[31m{s}\033[0m"


def green(s: str) -> str:
    return f"\033[32m{s}\033[0m"


def yellow(s: str) -> str:
    return f"\033[33m{s}\033[0m"


def bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


def section(title: str) -> None:
    print()
    print(bold(f"{'=' * 70}"))
    print(bold(f"  {title}"))
    print(bold(f"{'=' * 70}"))


def sub(title: str) -> None:
    print()
    print(bold(f"--- {title} ---"))


# ---------------------------------------------------------------------------
# TCP Profile Parser
# ---------------------------------------------------------------------------

def parse_tcp_report(path: Path) -> Dict:
    """Parse tcp_profile_report.txt into a structured dict."""
    content = path.read_text()
    result = {
        "retrans_before": None,
        "retrans_after": None,
        "retrans_delta": None,
        "ss_samples": [],
        "errors": [],
    }

    # Extract RetransSegs: the Tcp data line is:
    #   Tcp: RtoAlgorithm RtoMin RtoMax MaxConn ActiveOpens PassiveOpens AttemptFails
    #        EstabResets CurrEstab InSegs OutSegs RetransSegs InErrs OutRsts InCsumErrors
    #   Tcp: 1 200 120000 -1 93490 84298 78610 27822 55 17204199 16470056 66426 196 1806892 0
    # RetransSegs is at field index 11 (0-based).
    retrans_vals = []
    for line in content.splitlines():
        if line.startswith("Tcp:") and "RetransSegs" not in line and len(line.split()) >= 12:
            parts = line.split()
            try:
                retrans_vals.append(int(parts[11]))
            except (ValueError, IndexError):
                pass

    if retrans_vals:
        result["retrans_before"] = retrans_vals[0]
        result["retrans_after"] = retrans_vals[-1]
        result["retrans_delta"] = result["retrans_after"] - result["retrans_before"]

    # Extract ss samples (rough parsing for rtt, snd_cwnd, rcv_space)
    ss_pattern = re.compile(
        r"rtt:\s*([\d.]+)\s*([\w]+).*snd_cwnd:\s*(\d+).*rcv_space:\s*(\d+)"
    )
    for line in content.splitlines():
        m = ss_pattern.search(line)
        if m:
            result["ss_samples"].append({
                "rtt": m.group(1),
                "rtt_unit": m.group(2),
                "snd_cwnd": m.group(3),
                "rcv_space": m.group(4),
            })

    # Capture errors or warnings
    for line in content.splitlines():
        if any(kw in line.lower() for kw in ["error", "fail", "warn", "retrans"]):
            result["errors"].append(line.strip())

    return result


def print_tcp_summary(data: Dict) -> None:
    sub("TCP Stack Summary")

    if data["retrans_delta"] is not None:
        delta = data["retrans_delta"]
        if delta > 0:
            print(f"  Retransmits delta (during test): {red(delta)} segments")
            print(f"  → Network layer issues detected. Correlate with ZMQ_SEND_IO_LATENCY spikes.")
        else:
            print(f"  Retransmits delta: {green(f'{delta} (no new retransmits)')}")
    else:
        print("  Retransmits: unable to parse (no RetransSegs lines found)")

    if data["ss_samples"]:
        print(f"\n  Socket buffer samples ({len(data['ss_samples'])} collected):")
        for i, s in enumerate(data["ss_samples"][:5]):
            print(
                f"    sample[{i}]: rtt={s['rtt']} {s['rtt_unit']}, "
                f"snd_cwnd={s['snd_cwnd']}, rcv_space={s['rcv_space']}"
            )
        if len(data["ss_samples"]) > 5:
            print(f"    ... and {len(data['ss_samples']) - 5} more samples")
    else:
        print("  Socket samples (ss -ti): none parsed")

    if data["errors"]:
        print(f"\n  Notable events ({len(data['errors'])}):")
        for e in data["errors"][:10]:
            print(f"    {e}")


# ---------------------------------------------------------------------------
# Syscall Profile Parser
# ---------------------------------------------------------------------------

def parse_syscall_report(path: Path) -> Dict:
    """Parse syscall_profile_report.txt (strace -c output) into a structured dict."""
    content = path.read_text()
    lines = content.splitlines()

    result = {
        "total_time_sec": None,
        "syscalls": [],  # list of {name, calls, errors, time_sec, time_pct, usecs_per_call}
    }

    # Parse the summary table lines, e.g.:
    # % time     seconds  usecs/call     calls    errors  syscall
    #   3.33    0.000012       123       100       12     write
    syscall_re = re.compile(
        r"\s*([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?\s+(\w+)"
    )

    for line in lines:
        m = syscall_re.match(line.strip())
        if m:
            time_pct = float(m.group(1))
            time_sec = float(m.group(2))
            usecs_per_call = int(m.group(3))
            calls = int(m.group(4))
            errors = int(m.group(5)) if m.group(5) else 0
            name = m.group(6)
            result["syscalls"].append({
                "name": name,
                "time_pct": time_pct,
                "time_sec": time_sec,
                "usecs_per_call": usecs_per_call,
                "calls": calls,
                "errors": errors,
            })
            if result["total_time_sec"] is None or time_sec > result["total_time_sec"]:
                result["total_time_sec"] = time_sec

    return result


def print_syscall_summary(data: Dict) -> None:
    sub("Syscall Summary (strace -c)")

    if not data["syscalls"]:
        print("  No syscall summary found — strace may have failed.")
        return

    # Sort by time descending
    by_time = sorted(data["syscalls"], key=lambda x: x["time_sec"], reverse=True)

    print(f"  Total syscalls captured: {sum(s['calls'] for s in data['syscalls'])}")
    print(f"  Unique syscall types: {len(data['syscalls'])}")
    print()
    print(f"  {'%-12s'.strip()} {'%time':>7}  {'sec':>10}  {'us/call':>8}  {'calls':>10}  {'errors':>7}  {'syscall name'}")
    print(f"  {'-'*12} {'-'*7}  {'-'*10}  {'-'*8}  {'-'*10}  {'-'*7}  {'-'*20}")

    for s in by_time[:25]:
        pct_color = red if s["time_pct"] > 20 else (yellow if s["time_pct"] > 5 else "")
        pct_str = f"{pct_color}{s['time_pct']:>7.2f}\033[0m" if pct_color else f"{s['time_pct']:>7.2f}"
        err_str = red(f"{s['errors']:>7}") if s["errors"] > 0 else f"{s['errors']:>7}"
        print(
            f"  {pct_str}  {s['time_sec']:>10.6f}  {s['usecs_per_call']:>8}  "
            f"{s['calls']:>10}  {err_str}  {s['name']}"
        )

    # Key signals
    network_syscalls = ["sendmsg", "recvmsg", "write", "read", "sendto", "recvfrom"]
    wait_syscalls = ["epoll_wait", "ppoll", "poll", "pselect6"]
    sync_syscalls = ["futex", "clock_gettime", "nanosleep", "rt_sigreturn"]

    network_time = sum(s["time_sec"] for s in by_time if s["name"] in network_syscalls)
    wait_time = sum(s["time_sec"] for s in by_time if s["name"] in wait_syscalls)
    sync_time = sum(s["time_sec"] for s in by_time if s["name"] in sync_syscalls)

    print()
    print(f"  Aggregated time by category:")
    print(f"    Network I/O (sendmsg/recvmsg/read/write): {network_time*1000:.3f} ms")
    print(f"    Wait/poll (epoll_wait/ppoll):              {wait_time*1000:.3f} ms")
    print(f"    Sync (futex/clock_gettime):                {sync_time*1000:.3f} ms")

    top = by_time[0] if by_time else None
    if top:
        if top["name"] in network_syscalls and top["time_pct"] > 30:
            print(f"\n  {red('⚠ High network syscall time:')} {top['name']} = {top['time_pct']:.1f}% of total")
            print("    → Likely ZMQ_SEND_IO_LATENCY contributor. Correlate with perf stat.")
        elif top["name"] in wait_syscalls and top["time_pct"] > 30:
            print(f"\n  {yellow('⚠ High wait time:')} {top['name']} = {top['time_pct']:.1f}% of total")
            print("    → Threads blocked on I/O. Check TCP retransmits and socket buffers.")


# ---------------------------------------------------------------------------
# Perf Stat Parser
# ---------------------------------------------------------------------------

def parse_perf_stat(path: Path) -> Dict:
    """Parse perf_stat_report.txt into structured data."""
    content = path.read_text()
    lines = content.splitlines()

    result = {
        "intervals": [],
        "summary": {},
        "errors": [],
    }

    # Parse interval lines like:
    #     1000.561393723      123456789 cycles
    #     1000.561393723      123456789 instructions
    #     ...
    # Or:
    #  #          time   cycles:pp   instructions:pp   ...
    interval_re = re.compile(r"^\s*([\d.]+)\s+(\d+)\s+(\S+.*)")
    summary_re = re.compile(r"^\s*#\s*Totals:\s*$")
    # Also handle the "not supported" lines
    not_supported_re = re.compile(r"^\s*[^\s]+\s+([^\s]+)\s+.*\s+#\s+([\S]+)\s+.*\s+not supported")

    current_interval_time = None
    current_interval_events = {}

    for line in lines:
        # Skip empty/comment lines
        if not line.strip() or line.strip().startswith("#") or line.strip().startswith("Performance"):
            continue

        m = interval_re.match(line)
        if m:
            t = float(m.group(1))
            val = int(m.group(2))
            # Event name may include perf annotation comment after '#', e.g.
            # "cycles                           #    0.560 GHz"
            # Strip everything from '#' onward so key is just "cycles".
            event = m.group(3).strip().split("#")[0].strip()
            current_interval_time = t
            current_interval_events[event] = val
        else:
            # End of interval?
            if current_interval_time is not None and current_interval_events:
                result["intervals"].append({
                    "time": current_interval_time,
                    "events": dict(current_interval_events),
                })
            current_interval_time = None
            current_interval_events = {}

        if "not supported" in line.lower():
            result["errors"].append(f"Event not supported: {line.strip()}")

    if current_interval_time is not None and current_interval_events:
        result["intervals"].append({
            "time": current_interval_time,
            "events": dict(current_interval_events),
        })

    return result


def print_perf_stat_summary(data: Dict) -> None:
    sub("Perf Stat Summary (hardware counters)")

    if data["errors"]:
        print(f"  {yellow('⚠ Some events not supported:')}")
        for e in data["errors"][:5]:
            print(f"    {e}")
        print()

    if not data["intervals"]:
        print("  No perf stat intervals parsed — perf may not be installed on remote.")
        return

    intervals = data["intervals"]
    print(f"  Captured {len(intervals)} interval(s)")

    # Aggregate per event
    all_events = set()
    for iv in intervals:
        all_events.update(iv["events"].keys())

    if not all_events:
        print("  No events captured.")
        return

    event_aggregates = {}
    for ev in all_events:
        vals = [iv["events"].get(ev, 0) for iv in intervals]
        event_aggregates[ev] = {
            "min": min(vals),
            "max": max(vals),
            "avg": sum(vals) / len(vals),
            "total": sum(vals),
        }

    # Show key events
    key_events = ["cycles", "instructions", "cache-references", "cache-misses",
                  "branches", "branch-misses", "context-switches", "cpu-clock", "task-clock"]

    print()
    print(f"  {'Event':<25} {'Total':>15}  {'Avg/interval':>15}  {'Min':>15}  {'Max':>15}")
    print(f"  {'-'*25} {'-'*15}  {'-'*15}  {'-'*15}  {'-'*15}")

    shown = 0
    for ev in key_events:
        if ev in event_aggregates:
            a = event_aggregates[ev]
            # Human-readable for large numbers
            def fmt(v):
                if v >= 1e9:
                    return f"{v/1e9:.2f}B"
                elif v >= 1e6:
                    return f"{v/1e6:.2f}M"
                elif v >= 1e3:
                    return f"{v/1e3:.2f}K"
                return f"{v:.0f}"
            print(f"  {ev:<25} {fmt(a['total']):>15}  {fmt(a['avg']):>15}  {fmt(a['min']):>15}  {fmt(a['max']):>15}")
            shown += 1

    # Derived ratios
    if "cycles" in event_aggregates and "instructions" in event_aggregates:
        total_cycles = sum(iv["events"].get("cycles", 0) for iv in intervals)
        total_instructions = sum(iv["events"].get("instructions", 0) for iv in intervals)
        if total_cycles > 0 and total_instructions > 0:
            cpi = total_cycles / total_instructions
            print(f"\n  Derived CPI (cycles/instruction): {cpi:.3f}")
            if cpi > 2.0:
                print(f"  {red('⚠ High CPI (>2.0):')} possible memory-bound workload or cache stalls.")
            elif cpi < 0.5:
                print(f"  {yellow('⚠ Unusually low CPI:')} check if cycles event is accurate.")

    if "cache-misses" in event_aggregates and "cache-references" in event_aggregates:
        total_misses = sum(iv["events"].get("cache-misses", 0) for iv in intervals)
        total_refs = sum(iv["events"].get("cache-references", 0) for iv in intervals)
        if total_refs > 0:
            miss_rate = total_misses / total_refs * 100
            print(f"  L1/LLC cache miss rate: {miss_rate:.2f}%")
            if miss_rate > 10:
                print(f"  {red('⚠ High cache miss rate (>10%):')} memory-bound. Correlate with branch-misses.")


# ---------------------------------------------------------------------------
# Perf Record Parser
# ---------------------------------------------------------------------------

def parse_perf_record(path: Path) -> Dict:
    """Parse perf_record_report.txt (perf report --stdio output)."""
    content = path.read_text()
    lines = content.splitlines()

    result = {
        "top_functions": [],  # list of {pct, symbol, module}
        "overhead_lines": [],
    }

    # Parse lines like:
    #   12.34%  func_name  module  [.]  0x...
    func_re = re.compile(r"^\s*([\d.]+)%\s+(\S+)\s+(\S+)\s+(.+)$")

    for line in lines:
        m = func_re.match(line.strip())
        if m:
            pct = float(m.group(1))
            symbol = m.group(2)
            module = m.group(3)
            rest = m.group(4).strip()
            result["top_functions"].append({
                "pct": pct,
                "symbol": symbol,
                "module": module,
                "rest": rest,
            })

    return result


def print_perf_record_summary(data: Dict) -> None:
    sub("Perf Record Summary (flamegraph top callers)")

    if not data["top_functions"]:
        print("  No perf record data parsed — perf record may not have succeeded.")
        print("  (perf.data may be empty or perf not installed)")
        return

    print(f"  Top 30 functions by CPU overhead:")
    print()
    print(f"  {'%':>7}  {'Function':<40} {'Module':<25}")
    print(f"  {'-'*7}  {'-'*40}  {'-'*25}")

    for entry in data["top_functions"][:30]:
        pct = entry["pct"]
        pct_str = red(f"{pct:>6.2f}%") if pct > 10 else (yellow(f"{pct:>6.2f}%") if pct > 5 else f"{pct:>6.2f}%")
        symbol = entry["symbol"][:40]
        module = entry["module"][:25]
        print(f"  {pct_str}  {symbol:<40} {module:<25}")

    # Check for notable functions
    notable = {
        "zmq": "ZMQ library (socket send/recv path)",
        "send": "syscall sendmsg/send",
        "recv": "syscall recvmsg/recv",
        "epoll": "epoll I/O multiplexing",
        "write": "write syscall",
        "read": "read syscall",
        "memcpy": "memory copy (serialization?)",
        "serial": "serialization (protobuf?)",
        "parse": "parsing (protobuf?)",
        "queue": "queue operations",
        "lock": "lock contention",
        "futex": "futex wait/wake",
    }

    print()
    notable_found = []
    for entry in data["top_functions"][:50]:
        sym_lower = entry["symbol"].lower()
        for kw, desc in notable.items():
            if kw in sym_lower:
                notable_found.append((entry["symbol"], kw, desc, entry["pct"]))
                break

    if notable_found:
        print(f"  Notable function groups ({len(notable_found)} matched):")
        for sym, kw, desc, pct in notable_found[:15]:
            print(f"    [{kw}] {sym}: {desc} ({pct:.2f}%)")
    else:
        print("  No obvious ZMQ/network/serialization hotspots in top 50.")


# ---------------------------------------------------------------------------
# REPL Histogram Parser (reuse from parse_repl_log.py)
# ---------------------------------------------------------------------------

def parse_repl_log(path: Path) -> Dict:
    """Parse zmq_rpc_queue_latency_repl.log for histogram summaries."""
    content = path.read_text()
    lines = content.splitlines()

    result = {
        "completed_rpcs": None,
        "histograms": {},
        "raw_lines": [],
        "json_metrics": None,
    }

    for line in lines:
        if "Completed" in line and "RPCs" in line:
            m = re.search(r"Completed\s+(\d+)\s+RPCs", line)
            if m:
                result["completed_rpcs"] = int(m.group(1))
        if "===" in line or "METRICS" in line:
            result["raw_lines"].append(line)
        # Parse the inline JSON metrics summary
        if '"name"' in line and '"delta"' in line and '"p50"' in line:
            try:
                result["json_metrics"] = json.loads(line)
            except Exception:
                pass

    return result


def print_repl_summary(data: Dict) -> None:
    sub("REPL Application Metrics (6 Histograms + 2 IO)")

    if data["completed_rpcs"]:
        print(f"  Completed RPCs: {data['completed_rpcs']}")
    else:
        print("  Completed RPCs: not found in log")

    jm = data.get("json_metrics")
    if jm:
        metrics = jm.get("metrics", [])
        interval_ms = jm.get("interval_ms", "?")
        print(f"\n  Interval: {interval_ms} ms")
        print()
        print(f"  {'Metric':<40} {'p50 μs':>8} {'p90 μs':>8} {'p99 μs':>8} {'avg μs':>8} {'max μs':>8} {'count':>10}")
        print(f"  {'-'*40} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} {'--------':>8} {'-'*10}")
        for m in metrics:
            name = m.get("name", "?")
            delta = m.get("delta", {})
            total = m.get("total", {})
            p50 = delta.get("p50", total.get("p50", 0))
            p90 = delta.get("p90", total.get("p90", 0))
            p99 = delta.get("p99", total.get("p99", 0))
            avg = delta.get("avg_us", total.get("avg_us", 0))
            mx = delta.get("max_us", total.get("max_us", 0))
            cnt = delta.get("count", total.get("count", 0))
            # Color for queue-related
            if "queue" in name or "queuing" in name or "e2e" in name or "network" in name:
                print(f"  {green(name):<40} {p50:>8} {p90:>8} {p99:>8} {avg:>8} {mx:>8} {cnt:>10}")
            elif "exec" in name:
                print(f"  {yellow(name):<40} {p50:>8} {p90:>8} {p99:>8} {avg:>8} {mx:>8} {cnt:>10}")
            else:
                print(f"  {name:<40} {p50:>8} {p90:>8} {p99:>8} {avg:>8} {mx:>8} {cnt:>10}")

    if data["raw_lines"]:
        print("\n  Raw log lines:")
        for l in data["raw_lines"][:5]:
            print(f"    {l[:120]}")
    else:
        print("  (no raw log lines)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(results_dir: str) -> int:
    results_path = Path(results_dir)
    if not results_path.is_dir():
        print(f"ERROR: {results_dir} is not a directory", file=sys.stderr)
        return 1

    section(f"ZMQ RPC Latency — Profiling Results")
    print(f"Results directory: {results_path}")
    print(f"Generated: {__import__('datetime').datetime.now().isoformat()}")

    # TCP
    tcp_path = results_path / "tcp_profile_report.txt"
    tcp_data = {}
    if tcp_path.exists():
        try:
            tcp_data = parse_tcp_report(tcp_path)
            print_tcp_summary(tcp_data)
        except Exception as e:
            print(f"\n  {red('ERROR parsing tcp_profile_report:')} {e}")
    else:
        print(f"\n  {yellow('tcp_profile_report.txt not found — skipped')}")

    # Syscall
    sc_path = results_path / "syscall_profile_report.txt"
    sc_data = {}
    if sc_path.exists():
        try:
            sc_data = parse_syscall_report(sc_path)
            print_syscall_summary(sc_data)
        except Exception as e:
            print(f"\n  {red('ERROR parsing syscall_profile_report:')} {e}")
    else:
        print(f"\n  {yellow('syscall_profile_report.txt not found — skipped')}")

    # Perf stat
    perf_stat_path = results_path / "perf_stat_report.txt"
    perf_stat_data = {}
    if perf_stat_path.exists():
        try:
            perf_stat_data = parse_perf_stat(perf_stat_path)
            print_perf_stat_summary(perf_stat_data)
        except Exception as e:
            print(f"\n  {red('ERROR parsing perf_stat_report:')} {e}")
    else:
        print(f"\n  {yellow('perf_stat_report.txt not found — skipped (perf may not be installed)')}")

    # Perf record
    perf_rec_path = results_path / "perf_record_report.txt"
    perf_rec_data = {}
    if perf_rec_path.exists():
        try:
            perf_rec_data = parse_perf_record(perf_rec_path)
            print_perf_record_summary(perf_rec_data)
        except Exception as e:
            print(f"\n  {red('ERROR parsing perf_record_report:')} {e}")
    else:
        print(f"\n  {yellow('perf_record_report.txt not found — skipped (perf may not be installed)')}")

    # REPL log
    repl_path = results_path / "zmq_rpc_queue_latency_repl.log"
    repl_data = {}
    if repl_path.exists():
        try:
            repl_data = parse_repl_log(repl_path)
            print_repl_summary(repl_data)
        except Exception as e:
            print(f"\n  {red('ERROR parsing REPL log:')} {e}")
    else:
        print(f"\n  {yellow('zmq_rpc_queue_latency_repl.log not found — skipped')}")

    # ---- Cross-section correlation ----
    section("Cross-Section Correlation")

    findings = []

    # TCP retrans + syscall
    retrans_delta = tcp_data.get("retrans_delta")
    if retrans_delta is not None and retrans_delta > 0:
        findings.append(f"TCP retransmits detected: {retrans_delta} segments during test")
    else:
        findings.append("TCP retransmits: none detected")

    # Syscall + perf
    if sc_data.get("syscalls"):
        top = sorted(sc_data["syscalls"], key=lambda x: x["time_sec"], reverse=True)
        if top and top[0]["time_pct"] > 20:
            findings.append(f"Top syscall: {top[0]['name']} = {top[0]['time_pct']:.1f}% of CPU time")

    # Perf CPI
    if perf_stat_data.get("intervals"):
        intervals = perf_stat_data["intervals"]
        if all("cycles" in iv["events"] and "instructions" in iv["events"] for iv in intervals):
            total_cycles = sum(iv["events"]["cycles"] for iv in intervals)
            total_instructions = sum(iv["events"]["instructions"] for iv in intervals)
            if total_instructions > 0:
                cpi = total_cycles / total_instructions
                findings.append(f"Derived CPI: {cpi:.3f} (cycles/instruction)")

    if findings:
        print("  Key findings:")
        for f in findings:
            print(f"    • {f}")
    else:
        print("  No strong correlation signals found — check that all profiles ran successfully.")

    print()
    print(f"{bold('Done.')} Results in: {results_path}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results_dir>", file=sys.stderr)
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
