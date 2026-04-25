#!/usr/bin/env python3
import json
import re

log_file = "/root/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_20260425_080203/worker-31502_datasystem_worker.INFO.log"

# Read line 543735
with open(log_file, "r") as f:
    for i, line in enumerate(f):
        if i == 543734:  # 0-indexed
            match = re.search(r'\{\"event\":\"metrics_summary\".*\}', line)
            if match:
                json_str = match.group(0)
                try:
                    data = json.loads(json_str)
                    metrics = data.get("metrics", [])
                    print("=" * 80)
                    print("ALL Metrics Summary (Worker 31502)")
                    print("=" * 80)
                    print("  {:<45} {:>12} {:>12} {:>12}".format("Metric", "Count", "Avg(us)", "Max(us)"))
                    print("  " + "-"*45 + "  " + "-"*10 + "  " + "-"*10 + "  " + "-"*10)
                    for m in metrics:
                        t = m.get("total", {})
                        if isinstance(t, dict):
                            print("  {:<45} {:>12} {:>12} {:>12}".format(
                                m["name"], t.get("count", 0), t.get("avg_us", 0), t.get("max_us", 0)))
                        else:
                            print("  {:<45} {:>12}".format(m["name"], t))
                except json.JSONDecodeError as e:
                    print("JSON error:", e)
            break
