#!/usr/bin/env python3
import json
import re
import subprocess
import sys

def parse_worker(log_file, port):
    result = subprocess.run(
        ["grep", "-a", "metrics_summary", log_file],
        capture_output=True, text=True
    )
    lines = result.stdout.strip().split('\n')
    if not lines:
        return None

    last_line = None
    for line in reversed(lines):
        if 'zmq_' in line:
            last_line = line
            break

    if not last_line:
        return None

    match = re.search(r'\{\"event\":\"metrics_summary\".*\}', last_line)
    if match:
        json_str = match.group(0)
        data = json.loads(json_str)
        return data.get("metrics", [])
    return None

log_dir = "/root/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_20260425_080203"
workers = ["31501", "31502"]

print("=" * 90)
print("ALL Metrics Summary (All Workers)")
print("=" * 90)
print("  {:<45} {:>12} {:>12} {:>12}".format("Metric", "Count", "Avg(us)", "Max(us)"))
print("  " + "-"*45 + "  " + "-"*10 + "  " + "-"*10 + "  " + "-"*10)

all_metrics = {}

for port in workers:
    log_file = f"{log_dir}/worker-{port}_datasystem_worker.INFO.log"
    metrics = parse_worker(log_file, port)
    if metrics:
        for m in metrics:
            name = m["name"]
            t = m.get("total", {})
            if isinstance(t, dict):
                count = t.get("count", 0)
                avg = t.get("avg_us", 0)
                max_val = t.get("max_us", 0)
                if name not in all_metrics:
                    all_metrics[name] = {"count": 0, "avg": avg, "max": max_val}
                else:
                    all_metrics[name]["count"] += count
                    all_metrics[name]["max"] = max(all_metrics[name]["max"], max_val)

for name in sorted(all_metrics.keys()):
    m = all_metrics[name]
    print("  {:<45} {:>12} {:>12} {:>12}".format(name, m["count"], m["avg"], m["max"]))
