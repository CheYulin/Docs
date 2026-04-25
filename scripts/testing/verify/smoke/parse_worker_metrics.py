#!/usr/bin/env python3
"""Parse ZMQ metrics from worker INFO logs."""
import json
import sys
import glob
import os

def parse_metrics_log(log_file):
    """Parse metrics from a single worker log file."""
    results = []
    try:
        with open(log_file, 'r') as f:
            for line in f:
                if 'metrics_summary' in line and 'zmq_' in line:
                    try:
                        # Split on the metrics log format
                        marker = '| I | metrics.cpp:205 |'
                        if marker in line:
                            json_str = line.split(marker)[1].strip()
                            data = json.loads(json_str)
                            metrics = data.get('metrics', [])
                            zmq_metrics = [m for m in metrics if m['name'].startswith('zmq_')]
                            if zmq_metrics:
                                for m in zmq_metrics:
                                    t = m.get('total', {})
                                    results.append({
                                        'name': m['name'],
                                        'count': t.get('count', 0),
                                        'avg_us': t.get('avg_us', 0),
                                        'max_us': t.get('max_us', 0)
                                    })
                                break  # Only take last metrics_summary
                    except Exception as e:
                        print(f"Error parsing: {e}", file=sys.stderr)
    except Exception as e:
        print(f"Error reading {log_file}: {e}", file=sys.stderr)
    return results

def main():
    if len(sys.argv) > 1:
        log_dir = sys.argv[1]
    else:
        log_dir = '.'

    # Find all worker logs
    pattern = os.path.join(log_dir, 'worker-*_datasystem_worker.INFO.log')
    log_files = sorted(glob.glob(pattern))

    if not log_files:
        print(f"No worker logs found in {log_dir}")
        return

    all_metrics = {}  # name -> {'count': sum, 'avg': last, 'max': max}

    for log_file in log_files:
        port = os.path.basename(log_file).split('-')[1]
        print(f"\n{'='*80}")
        print(f"Worker {port}")
        print(f"{'='*80}")

        metrics = parse_metrics_log(log_file)
        if metrics:
            print(f"  {'Metric':<35} {'Count':>12} {'Avg(us)':>12} {'Max(us)':>12}")
            print(f"  {'-'*35:<35} {'-'*12:>12} {'-'*12:>12} {'-'*12:>12}")
            for m in metrics:
                name = m['name']
                if name not in all_metrics:
                    all_metrics[name] = {'count': 0, 'avg': 0, 'max': 0}
                all_metrics[name]['count'] += m['count']
                all_metrics[name]['avg'] = m['avg_us']
                all_metrics[name]['max'] = max(all_metrics[name]['max'], m['max_us'])
                print(f"  {name:<35} {m['count']:>12} {m['avg_us']:>12} {m['max_us']:>12}")
        else:
            print("  No ZMQ metrics found")

    if len(log_files) > 1 and all_metrics:
        print(f"\n{'='*80}")
        print("Combined Totals")
        print(f"{'='*80}")
        print(f"  {'Metric':<35} {'Total Count':>15}")
        print(f"  {'-'*35:<35} {'-'*15:>15}")
        for name in sorted(all_metrics.keys()):
            print(f"  {name:<35} {all_metrics[name]['count']:>15}")

if __name__ == '__main__':
    main()
