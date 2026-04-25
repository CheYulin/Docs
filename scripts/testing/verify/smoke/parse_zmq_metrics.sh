#!/bin/bash
# Parse ZMQ metrics from worker INFO logs
# Usage: ./parse_zmq_metrics.sh <log_dir> [worker_port...]

LOG_DIR="${1:-.}"
WORKER_PORTS="${2:-31501 31502}"

echo "=============================================="
echo "ZMQ Metrics Summary"
echo "=============================================="
echo ""

for port in $WORKER_PORTS; do
    LOG_FILE="$LOG_DIR/worker-${port}_datasystem_worker.INFO.log"
    if [[ -f "$LOG_FILE" ]]; then
        echo "--- Worker $port ---"
        # Extract all metrics_summary lines and parse with python
        grep "metrics_summary" "$LOG_FILE" | tail -1 | python3 -c "
import sys, json

line = sys.stdin.read().strip()
if '| I | metrics.cpp' in line:
    line = line.split('| I | metrics.cpp')[1].split('|', 1)[1].lstrip()
    if line.startswith('205'):
        line = line[3:].lstrip()

data = json.loads(line)
metrics = data.get('metrics', [])

zmq_metrics = [m for m in metrics if m['name'].startswith('zmq_')]
if zmq_metrics:
    print(f\"  {'Metric':<35} {'Count':>10} {'Avg(us)':>10} {'Max(us)':>10}\")
    print(f\"  {'-'*35:>35} {'-'*10:>10} {'-'*10:>10} {'-'*10:>10}\")
    for m in zmq_metrics:
        total = m.get('total', {})
        count = total.get('count', 0)
        avg = total.get('avg_us', 0)
        max_val = total.get('max_us', 0)
        print(f\"  {m['name']:<35} {count:>10} {avg:>10} {max_val:>10}\")
else:
    print('  No ZMQ metrics found')
"
        echo ""
    else
        echo "--- Worker $port ---"
        echo "  Log file not found: $LOG_FILE"
        echo ""
    fi
done
