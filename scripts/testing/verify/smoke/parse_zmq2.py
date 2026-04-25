#!/usr/bin/env python3
import json
import re

log_file = "/root/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_20260425_080203/worker-31502_datasystem_worker.INFO.log"

# Read line 543735
with open(log_file, "r") as f:
    for i, line in enumerate(f):
        if i == 543734:  # 0-indexed
            # Extract JSON after the log prefix
            match = re.search(r'\{\"event\":\"metrics_summary\".*\}', line)
            if match:
                json_str = match.group(0)
                try:
                    data = json.loads(json_str)
                    metrics = data.get("metrics", [])
                    zmq_metrics = [m for m in metrics if m["name"].startswith("zmq_")]
                    print("=" * 80)
                    print("ZMQ Metrics Summary (Worker 31502)")
                    print("=" * 80)
                    print("  {:<35} {:>12} {:>12} {:>12}".format("Metric", "Count", "Avg(us)", "Max(us)"))
                    print("  " + "-"*35 + "  " + "-"*10 + "  " + "-"*10 + "  " + "-"*10)
                    for m in zmq_metrics:
                        t = m.get("total", {})
                        print("  {:<35} {:>12} {:>12} {:>12}".format(
                            m["name"], t.get("count", 0), t.get("avg_us", 0), t.get("max_us", 0)))
                except json.JSONDecodeError as e:
                    print("JSON error:", e)
                    print("JSON string length:", len(json_str))
            break
