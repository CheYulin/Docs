#!/usr/bin/env python3
"""
DataSystem Smoke Test
- 1 etcd
- 4 workers (31501~31504)
- 16 dsclient processes (4 tenants x 4 clients/tenant)
- Cross-tenant reads trigger remote worker pulls
- Value sizes: 0.5MB, 2MB, 8MB (mixed per key)

Usage:
  python3 run_smoke.py [--skip-build] [--workers <n>] [--tenants <n>] [--clients-per-tenant <n>]

Paths are auto-discovered relative to this script's location.
"""

import subprocess
import time
import os
import json
import signal
import sys
import random
import string
import shutil
import re
import argparse
from datetime import datetime
from pathlib import Path

# ============ Path Resolution ============
# Discover paths relative to this script's location.
# Script lives in: .../yuanrong-datasystem-agent-workbench/scripts/testing/verify/smoke/
SCRIPT_PATH = Path(__file__).resolve()
WORKBENCH_ROOT = SCRIPT_PATH.parents[4]  # .../yuanrong-datasystem-agent-workbench/
DS_ROOT = WORKBENCH_ROOT.parent / "yuanrong-datasystem"  # sibling repo

# Results output
LOG_BASE = WORKBENCH_ROOT / "results"
SCRIPT_DIR = WORKBENCH_ROOT / "scripts"

# ============ ZMQ Metrics Registry ============
# These must match KvMetricId enum in kv_metrics.h
ZMQ_METRIC_PATTERNS = {
    "ZMQ_SEND_IO_LATENCY":          re.compile(r"ZMQ_SEND_IO_LATENCY\s+(\S+)"),
    "ZMQ_RECEIVE_IO_LATENCY":        re.compile(r"ZMQ_RECEIVE_IO_LATENCY\s+(\S+)"),
    "ZMQ_RPC_SERIALIZE_LATENCY":     re.compile(r"ZMQ_RPC_SERIALIZE_LATENCY\s+(\S+)"),
    "ZMQ_RPC_DESERIALIZE_LATENCY":   re.compile(r"ZMQ_RPC_DESERIALIZE_LATENCY\s+(\S+)"),
    "ZMQ_SEND_FAILURE_TOTAL":       re.compile(r"ZMQ_SEND_FAILURE_TOTAL\s+(\S+)"),
    "ZMQ_RECEIVE_FAILURE_TOTAL":     re.compile(r"ZMQ_RECEIVE_FAILURE_TOTAL\s+(\S+)"),
    "ZMQ_SEND_TRY_AGAIN_TOTAL":      re.compile(r"ZMQ_SEND_TRY_AGAIN_TOTAL\s+(\S+)"),
    "ZMQ_RECEIVE_TRY_AGAIN_TOTAL":   re.compile(r"ZMQ_RECEIVE_TRY_AGAIN_TOTAL\s+(\S+)"),
    "ZMQ_NETWORK_ERROR_TOTAL":        re.compile(r"ZMQ_NETWORK_ERROR_TOTAL\s+(\S+)"),
    "ZMQ_LAST_ERROR_NUMBER":          re.compile(r"ZMQ_LAST_ERROR_NUMBER\s+(\S+)"),
    "ZMQ_GATEWAY_RECREATE_TOTAL":    re.compile(r"ZMQ_GATEWAY_RECREATE_TOTAL\s+(\S+)"),
    "ZMQ_EVENT_DISCONNECT_TOTAL":     re.compile(r"ZMQ_EVENT_DISCONNECT_TOTAL\s+(\S+)"),
    "ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL": re.compile(r"ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL\s+(\S+)"),
}

# ============ Config ============
WORKER_PORTS = [31501, 31502, 31503, 31504]
WORKER_NUMS = 4
NUM_TENANTS = 4
CLIENTS_PER_TENANT = 4
KEYS_PER_CLIENT = 100
VALUE_SIZE_LIST = [512 * 1024, 2 * 1024 * 1024, 8 * 1024 * 1024]  # 0.5MB, 2MB, 8MB
ETCD_PORT = 2379
ETCD_DATA_DIR = "/tmp/etcd-data-smoke"

# ============ Environment Discovery ============
def find_python_bin():
    """Find a suitable Python 3 interpreter."""
    candidates = [
        Path(sys.executable),
        Path("/usr/local/bin/python3"),
        Path("/usr/bin/python3"),
        Path("/root/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11"),
    ]
    for p in candidates:
        try:
            if p.exists() and p.is_file():
                result = subprocess.run([str(p), "--version"], capture_output=True, text=True)
                if result.returncode == 0 and "3.11" in result.stdout:
                    return str(p)
        except (OSError, PermissionError):
            continue
    return str(Path(sys.executable))

def find_uv_python():
    """Find Python interpreter in uv cache or .venv."""
    # Check uv virtual environment
    uv_venv = DS_ROOT / ".venv"
    if uv_venv.exists():
        py = uv_venv / "bin/python3"
        if py.exists():
            return str(py)

    # Check system python with yr package accessible
    for py in ["/usr/bin/python3", "/usr/local/bin/python3"]:
        p = Path(py)
        if p.exists():
            result = subprocess.run([py, "-c", "from yr.datasystem.kv_client import KVClient"], capture_output=True)
            if result.returncode == 0:
                return py

    # Fallback to sys.executable
    return str(Path(sys.executable))

def find_python_site_packages(py_bin):
    """Find PYTHONPATH / site-packages for yr package."""
    result = subprocess.run(
        [py_bin, "-c", "import yr; print(yr.__file__)"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        pkg_path = Path(result.stdout.strip()).parent.parent
        site = pkg_path / "lib"
        for s in site.glob("python*/site-packages"):
            return str(s)
    return ""

def find_yr_so():
    """Find libds_client_py.so for LD_PRELOAD."""
    candidates = [
        DS_ROOT / ".venv/lib/python3.11/site-packages/yr/datasystem/libds_client_py.so",
        DS_ROOT / "build/lib/libds_client_py.so",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return ""

def find_worker_binary():
    """Find datasystem_worker binary in build or bazel cache."""
    candidates = [
        DS_ROOT / "build/bin/datasystem_worker",
        DS_ROOT / "bazel-bin/src/datasystem/worker/datasystem_worker",
    ]
    for p in candidates:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)

    # Search bazel cache
    result = subprocess.run(
        ["find", str(Path.home() / ".cache/bazel"), "-name", "datasystem_worker", "-type", "f"],
        capture_output=True, text=True
    )
    matches = [m for m in result.stdout.strip().split("\n") if m and "bin/src/datasystem/worker/datasystem_worker" in m]
    if matches:
        return matches[0]

    raise RuntimeError("datasystem_worker binary not found. Build with: cd $DS_ROOT && bash build.sh -t build")


# ============ Logger ============
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_timestamp_dir():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return LOG_BASE / f"smoke_test_{ts}"

# ============ Cleanup ============
def cleanup_all():
    """Kill all datasystem workers and etcd. Idempotent."""
    subprocess.run(["pkill", "-9", "-f", "datasystem_worker"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-9", "-f", "etcd-smoke"], stderr=subprocess.DEVNULL)
    time.sleep(1)

# ============ Signal handler ============
def signal_handler(signum, frame):
    log(f"SIGNAL {signum} received, cleaning up...")
    cleanup_all()
    sys.exit(130)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ============ Etcd ============
def start_etcd(log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    os.makedirs(ETCD_DATA_DIR, exist_ok=True)

    cleanup_all()
    time.sleep(2)

    env = os.environ.copy()
    proc = subprocess.Popen(
        [
            "etcd",
            "--name", "etcd-smoke",
            "--data-dir", ETCD_DATA_DIR,
            "--listen-client-urls", "http://0.0.0.0:2379",
            "--advertise-client-urls", "http://127.0.0.1:2379",
            "--listen-peer-urls", "http://0.0.0.0:2380",
            "--initial-advertise-peer-urls", "http://127.0.0.1:2380",
            "--initial-cluster", "etcd-smoke=http://127.0.0.1:2380",
        ],
        stdout=open(log_dir / "etcd.log", "w"),
        stderr=subprocess.STDOUT,
        env=env,
    )
    time.sleep(3)

    for attempt in range(5):
        try:
            result = subprocess.run(
                ["etcdctl", "--endpoints", "127.0.0.1:2379", "put", "__test__", "ok"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                subprocess.run(["etcdctl", "--endpoints", "127.0.0.1:2379", "del", "__test__"], timeout=5)
                log(f"etcd started @ 127.0.0.1:{ETCD_PORT}")
                return proc
        except Exception:
            pass
        time.sleep(1)

    raise RuntimeError("etcd failed to start")

def stop_etcd():
    subprocess.run(["pkill", "-9", "-f", "etcd-smoke"], stderr=subprocess.DEVNULL)
    log("etcd stopped")

# ============ Workers ============
def start_workers(log_dir):
    """Start N workers in parallel using the worker binary directly (NOT dscli).

    dscli injects --metastore_address which conflicts with --etcd_address,
    causing worker to exit with "Only one of etcd_address or metastore_address
    can be specified". We use the binary directly with correct flags.
    """
    workers = []

    for subdir in ["uds", "rocksdb", "config"]:
        os.makedirs(DS_ROOT / subdir, exist_ok=True)

    for port in WORKER_PORTS:
        wlog_dir = log_dir / f"worker-{port}"
        wlog_dir.mkdir(parents=True, exist_ok=True)
        # Each worker needs its own rocksdb dir
        rocksdb_dir = log_dir / f"worker-{port}_rocksdb"
        rocksdb_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            WORKER_BIN,
            "--bind_address", f"127.0.0.1:{port}",
            "--etcd_address", f"127.0.0.1:{ETCD_PORT}",
            "--shared_memory_size_mb", "2048",
            "--log_dir", str(wlog_dir),
            "--rocksdb_store_dir", str(rocksdb_dir),
        ]

        with open(wlog_dir / "worker_stdout.log", "w") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        workers.append((port, proc, wlog_dir))
        log(f"Worker @{port} started (pid={proc.pid})")

    log("Waiting for workers to stabilize (40s)...")
    time.sleep(40)

    alive = 0
    for port, proc, wdir in workers:
        if proc.poll() is None:
            alive += 1
        else:
            log(f"  WARNING: Worker @{port} exited early, check {wdir}/worker_stdout.log")

    log(f"{alive}/{len(workers)} workers still alive")
    return workers

def stop_workers():
    subprocess.run(["pkill", "-9", "-f", "datasystem_worker"], stderr=subprocess.DEVNULL)
    time.sleep(1)

# ============ Client ============
def client_task(tenant_id, client_id, worker_ports, log_dir):
    port = random.choice(worker_ports)
    log_file = log_dir / f"client_t{tenant_id}_c{client_id}.log"

    random.seed(tenant_id * 1000 + client_id)
    sizes_json = str(VALUE_SIZE_LIST)

    code = f"""
import sys
import random, string
from yr.datasystem.kv_client import KVClient, WriteMode

def random_text(size):
    chunk = ''.join(random.choices(string.ascii_letters + string.digits, k=500))
    return (chunk * (size // 500 + 1))[:size]

random.seed({tenant_id * 1000 + client_id})
TENANT = {tenant_id}
CLIENT = {client_id}
PORT = {port}
KEYS = {KEYS_PER_CLIENT}
VALUE_SIZES = {sizes_json}

client = KVClient(host="127.0.0.1", port=PORT)
try:
    client.init()
except Exception as e:
    print(f"INIT ERROR: {{e}}", flush=True)
    sys.exit(1)

my_keys = [f"tenant_{{TENANT}}_client_{{CLIENT}}_key_{{i}}" for i in range(KEYS)]
my_vals = [random_text(random.choice(VALUE_SIZES)) for _ in range(KEYS)]

try:
    client.mset(my_keys, my_vals, WriteMode.NONE_L2_CACHE)
    print(f"[T{{TENANT}}C{{CLIENT}}] Wrote {{len(my_keys)}} keys (0.5MB/2MB/8MB)", flush=True)
except Exception as e:
    print(f"WRITE ERROR: {{e}}", flush=True)
    sys.exit(1)

# Cross-tenant reads
all_other_keys = [
    f"tenant_{{t}}_client_{{c}}_key_{{i}}"
    for t in range({NUM_TENANTS}) if t != TENANT
    for c in range({CLIENTS_PER_TENANT})
    for i in range(KEYS)
]
sample = random.sample(all_other_keys, max(1, int(len(all_other_keys) * 0.2)))

ok, fail = 0, 0
for key in sample:
    try:
        r = client.get_buffers([key])
        ok += 1 if r and r[0] else 0
    except:
        fail += 1
print(f"[T{{TENANT}}C{{CLIENT}}] Remote read: {{ok}} ok, {{fail}} fail", flush=True)

# Local read
local_ok = sum(1 for k in my_keys[:10] if client.get_buffers([k]) and client.get_buffers([k])[0])
print(f"[T{{TENANT}}C{{CLIENT}}] Local read: {{local_ok}}/10 ok", flush=True)
print(f"[T{{TENANT}}C{{CLIENT}}] DONE", flush=True)
"""

    env = {**os.environ}
    if LD_PRELOAD:
        env["LD_PRELOAD"] = LD_PRELOAD
    if YR_SITE_PACKAGES:
        env["PYTHONPATH"] = YR_SITE_PACKAGES

    with open(log_file, "w") as f:
        proc = subprocess.Popen(
            [PYTHON_BIN, "-c", code],
            stdout=f, stderr=subprocess.STDOUT,
            env=env,
        )
    return proc, log_file

# ============ ZMQ Metrics Parser ============
def parse_zmq_metrics(log_dir):
    """Parse ZMQ metrics from worker log files.

    Looks for patterns like:
      ZMQ_SEND_IO_LATENCY <value>
      ZMQ_RECEIVE_FAILURE_TOTAL <count>

    Returns dict of metric_name -> list of values found across all logs.
    """
    results = {name: [] for name in ZMQ_METRIC_PATTERNS}

    log_glob_patterns = [
        "*.INFO.log",
        "*.log",
        "worker.log",
        "stderr.log",
        "stdout.log",
    ]

    for port in WORKER_PORTS:
        wdir = log_dir / "workers" / f"worker-{port}"
        if not wdir.exists():
            continue
        for pattern in log_glob_patterns:
            for log_file in wdir.glob(pattern):
                try:
                    text = log_file.read_text(errors="ignore")
                except Exception:
                    continue
                for name, pat in ZMQ_METRIC_PATTERNS.items():
                    for m in pat.finditer(text):
                        val = m.group(1).strip()
                        if val:
                            results[name].append((str(log_file.name), val))

    return {k: v for k, v in results.items() if v}

def write_metrics_summary(log_dir, metrics_data):
    """Write ZMQ metrics summary to metrics_summary.txt."""
    lines = [
        "=" * 60,
        "ZMQ Metrics Summary",
        "=" * 60,
        f"Generated: {datetime.now().isoformat()}",
        "",
    ]

    if not metrics_data:
        lines.append("(no ZMQ metrics found in worker logs)")
    else:
        for name, occurrences in sorted(metrics_data.items()):
            lines.append(f"\n{name}:")
            # Deduplicate by value, preserve order
            seen = set()
            for fname, val in occurrences:
                key = (fname, val)
                if key not in seen:
                    lines.append(f"  {val}  (from {fname})")
                    seen.add(key)

    summary = "\n".join(lines) + "\n"
    out_path = log_dir / "metrics_summary.txt"
    out_path.write_text(summary)
    log(f"ZMQ metrics summary written to metrics_summary.txt")

    # Also print key metrics to stdout
    log("\n=== ZMQ Metrics (sample) ===")
    if not metrics_data:
        log("  (none detected in worker logs)")
    else:
        for name, occurrences in sorted(metrics_data.items())[:10]:
            uniq_vals = list(dict.fromkeys(v for _, v in occurrences))
            log(f"  {name}: {', '.join(uniq_vals[:3])}")

    return out_path

# ============ Post-process ============
def collect_and_summarize(log_dir, workers):
    """Collect worker logs and summarize ZMQ metrics."""
    log("=== Collecting worker logs ===")
    total_metrics = 0
    for port, proc, wdir in workers:
        if not wdir.exists():
            continue
        for mf in wdir.glob("*"):
            if mf.is_file():
                dest = log_dir / f"worker-{port}_{mf.name}"
                shutil.copy2(mf, dest)
                if any(x in mf.name for x in ["metrics", "access", "resource", "request_out"]):
                    total_metrics += 1
    log(f"  Collected {total_metrics} metrics/log files")

    # Write test summary JSON
    summary = {
        "test_time": datetime.now().isoformat(),
        "workers": WORKER_PORTS,
        "tenants": NUM_TENANTS,
        "clients_per_tenant": CLIENTS_PER_TENANT,
        "keys_per_client": KEYS_PER_CLIENT,
        "value_sizes": ["0.5MB", "2MB", "8MB"],
        "worker_binary": WORKER_BIN,
        "python_bin": PYTHON_BIN,
        "ds_root": str(DS_ROOT),
    }
    with open(log_dir / "test_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Parse and write ZMQ metrics
    log("=== Parsing ZMQ metrics ===")
    zmq_data = parse_zmq_metrics(log_dir)
    write_metrics_summary(log_dir, zmq_data)

    log(f"Results at {log_dir}")

# ============ Main test ============
def run_smoke_test(log_dir):
    worker_log_dir = log_dir / "workers"
    worker_log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Start etcd
    log("=== Step 1: Starting etcd ===")
    etcd_proc = start_etcd(log_dir)

    # 2. Start workers
    log(f"=== Step 2: Starting {WORKER_NUMS} workers (binary mode) ===")
    workers = start_workers(worker_log_dir)

    # 3. Start clients
    log(f"=== Step 3: Starting {NUM_TENANTS * CLIENTS_PER_TENANT} clients ===")
    client_log_dir = log_dir / "clients"
    client_log_dir.mkdir(parents=True, exist_ok=True)
    clients = []
    for tenant_id in range(NUM_TENANTS):
        for client_id in range(CLIENTS_PER_TENANT):
            proc, lf = client_task(tenant_id, client_id, WORKER_PORTS, client_log_dir)
            clients.append((tenant_id, client_id, proc, lf))
            time.sleep(0.3)

    # 4. Wait for clients
    log("=== Step 4: Waiting for clients ===")
    all_ok = True
    for tenant_id, client_id, proc, lf in clients:
        try:
            proc.wait(timeout=120)
            status = "OK" if proc.returncode == 0 else f"EXIT={proc.returncode}"
            log(f"  T{tenant_id}C{client_id}: {status}")
            if proc.returncode != 0:
                all_ok = False
        except subprocess.TimeoutExpired:
            proc.kill()
            log(f"  T{tenant_id}C{client_id}: TIMEOUT")
            all_ok = False

    if not all_ok:
        log("WARNING: Some clients failed, continuing to collect logs...")

    # 5-7: Collect, summarize
    log("=== Step 5-7: Collecting logs & summarizing ===")
    collect_and_summarize(log_dir, workers)

    return log_dir, workers, etcd_proc

# ============ Entry ============
def main():
    global WORKER_NUMS, NUM_TENANTS, CLIENTS_PER_TENANT, WORKER_PORTS
    global PYTHON_BIN, YR_SITE_PACKAGES, LD_PRELOAD, WORKER_BIN

    # 1. Parse args FIRST (--help exits here before binary discovery)
    parser = argparse.ArgumentParser(description="DataSystem Smoke Test")
    parser.add_argument("--workers", type=int, default=WORKER_NUMS,
                        help=f"Number of workers (default: {WORKER_NUMS})")
    parser.add_argument("--tenants", type=int, default=NUM_TENANTS,
                        help=f"Number of tenants (default: {NUM_TENANTS})")
    parser.add_argument("--clients-per-tenant", type=int, default=CLIENTS_PER_TENANT,
                        help=f"Clients per tenant (default: {CLIENTS_PER_TENANT})")
    args = parser.parse_args()

    # 2. Apply CLI overrides to globals
    WORKER_NUMS = args.workers
    NUM_TENANTS = args.tenants
    CLIENTS_PER_TENANT = args.clients_per_tenant
    WORKER_PORTS = WORKER_PORTS[:WORKER_NUMS]

    # 3. Discover binaries and paths (fail here if not found)
    PYTHON_BIN = find_python_bin()
    YR_SITE_PACKAGES = find_python_site_packages(PYTHON_BIN)
    LD_PRELOAD = find_yr_so()
    WORKER_BIN = find_worker_binary()

    LOG_BASE.mkdir(parents=True, exist_ok=True)
    log_dir = get_timestamp_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    log(f"Log output: {log_dir}")
    log(f"DS root: {DS_ROOT}")
    log(f"Worker binary: {WORKER_BIN}")
    log(f"Python: {PYTHON_BIN}")
    log(f"Workers: {WORKER_NUMS}, Tenants: {NUM_TENANTS}, Clients/tenant: {CLIENTS_PER_TENANT}")

    cleanup_all()
    time.sleep(1)

    workers = []
    etcd_proc = None

    try:
        log_dir, workers, etcd_proc = run_smoke_test(log_dir)
    except Exception as e:
        log(f"SMOKE TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if etcd_proc:
            try:
                etcd_proc.terminate()
                etcd_proc.wait(timeout=5)
            except Exception:
                etcd_proc.kill()
        stop_etcd()
        stop_workers()
        cleanup_all()
        subprocess.run(["rm", "-rf", ETCD_DATA_DIR], stderr=subprocess.DEVNULL)
        log(f"=== Smoke test DONE. Results at {log_dir} ===")

if __name__ == "__main__":
    main()
