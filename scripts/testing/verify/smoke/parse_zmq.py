#!/usr/bin/env python3
import json

log_file = "/root/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_20260425_080203/worker-31502_datasystem_worker.INFO.log"

with open(log_file, "r") as f:
    for line in f:
        if "metrics_summary" in line and "zmq_server" in line:
            idx = line.find('"event":"metrics_summary"')
            if idx >= 0:
                json_str = line[idx:]
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
                    break
                except json.JSONDecodeError as e:
                    print("JSON error:", e)
