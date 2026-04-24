#!/usr/bin/env python3
"""
DataSystem Smoke Test
- 1 etcd
- 4 workers (31501~31504)
- 16 dsclient processes (4 tenants x 4 clients/tenant)
- Cross-tenant reads trigger remote worker pulls
- Value sizes: 0.5MB, 2MB, 8MB (mixed per key)
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
from datetime import datetime
from pathlib import Path

# Make yr available in script's own Python process (uv cache is cross-namespace accessible)
sys.path.insert(0, "/root/.cache/uv/archive-v0/-X94UpqFRUv-WlFmY9UF-")

# ============ Config ============
WORKER_PORTS = [31501, 31502, 31503, 31504]
WORKER_NUMS = 4
NUM_TENANTS = 4
CLIENTS_PER_TENANT = 4
KEYS_PER_CLIENT = 100
VALUE_SIZE_LIST = [512 * 1024, 2 * 1024 * 1024, 8 * 1024 * 1024]  # 0.5MB, 2MB, 8MB
ETCD_PORT = 2379
ETCD_DATA_DIR = "/tmp/etcd-data-smoke"
LOG_BASE = Path("/root/workspace/git-repos/vibe-coding-files/results")
SCRIPT_DIR = Path("/root/workspace/git-repos/vibe-coding-files/scripts")
PYTHON_BIN = "/root/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11"
DS_HOME = "/root/workspace/git-repos/vibe-coding-files/datasystem"
# libds_client_py.so lives in uv cache (accessible from main mount namespace)
LD_PRELOAD = "/root/.cache/uv/archive-v0/-X94UpqFRUv-WlFmY9UF-/yr/datasystem/lib/libds_client_py.so"
# uv cache path is accessible across mount namespaces (unlike .venv which is bind-mounted)
PYTHON_SITE = "/root/.cache/uv/archive-v0/-X94UpqFRUv-WlFmY9UF-"

# Discover worker binary from bazel cache
def find_worker_binary():
    matches = subprocess.run(
        ["find", "/root/.cache/bazel", "-name", "datasystem_worker", "-type", "f"],
        capture_output=True, text=True
    ).stdout.strip().split("\n")
    matches = [m for m in matches if m and "bin/src/datasystem/worker/datasystem_worker" in m]
    if not matches:
        raise RuntimeError("datasystem_worker binary not found in bazel cache")
    return matches[0]

WORKER_BIN = find_worker_binary()

# Global state
_cleaned_up = False

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

# ============ Random text ============
def random_text(size):
    chunk = ''.join(random.choices(string.ascii_letters + string.digits, k=500))
    repeat = size // 500 + 1
    return (chunk * repeat)[:size]

# ============ Etcd ============
def start_etcd(log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    os.makedirs(ETCD_DATA_DIR, exist_ok=True)

    # Ensure clean state
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

    # Verify etcd is responding
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
    """Start 4 workers in parallel using the worker binary directly (NOT dscli).

    dscli injects --metastore_address which conflicts with --etcd_address,
    causing worker to exit with "Only one of etcd_address or metastore_address
    can be specified". We use the binary directly with correct flags.
    """
    workers = []

    # Pre-create directories (worker creates probe files as files, not dirs)
    for subdir in ["uds", "rocksdb", "config"]:
        os.makedirs(f"{DS_HOME}/{subdir}", exist_ok=True)

    for port in WORKER_PORTS:
        worker_log_dir = log_dir / f"worker-{port}"
        worker_log_dir.mkdir(parents=True, exist_ok=True)
        # Each worker needs its own rocksdb dir to avoid lock conflicts
        worker_rocksdb_dir = log_dir / f"worker-{port}_rocksdb"
        worker_rocksdb_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            WORKER_BIN,
            "--bind_address", f"127.0.0.1:{port}",
            "--etcd_address", f"127.0.0.1:{ETCD_PORT}",
            "--shared_memory_size_mb", "2048",
            "--log_dir", str(worker_log_dir),
            "--rocksdb_store_dir", str(worker_rocksdb_dir),
        ]

        with open(worker_log_dir / "worker_stdout.log", "w") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        workers.append((port, proc, worker_log_dir))
        log(f"Worker @{port} started (pid={proc.pid})")

    # Wait for all workers to stabilize (hash ring + metrics reporting)
    log("Waiting for workers to stabilize (40s)...")
    time.sleep(40)

    # Verify workers are alive
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

    # Use a fixed seed for reproducibility of size choices
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

# Read other tenants' keys (cross-tenant triggers remote pulls)
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

    with open(log_file, "w") as f:
        env = {**os.environ, "LD_PRELOAD": LD_PRELOAD, "PYTHONPATH": PYTHON_SITE}
        proc = subprocess.Popen(
            [PYTHON_BIN, "-c", code],
            stdout=f, stderr=subprocess.STDOUT,
            env=env,
        )
    return proc, log_file

# ============ Summarize metrics ============
def summarize_metrics(log_dir):
    summarize_sh = SCRIPT_DIR / "testing/verify/summarize_observability_log.sh"
    if not summarize_sh.exists():
        log("Summarize script not found, skipping")
        return

    # Collect all worker log files
    log_files = []
    for port in WORKER_PORTS:
        wdir = log_dir / "workers" / f"worker-{port}"
        if not wdir.exists():
            continue
        for pattern in ["*.INFO.log", "*.WARNING.log", "*.ERROR.log",
                        "access.log", "resource.log", "request_out.log"]:
            log_files.extend([str(f) for f in wdir.glob(pattern)])

    if not log_files:
        log("No worker log files found for summarize")
        return

    log(f"Summarizing {len(log_files)} log files...")
    result = subprocess.run(
        ["bash", str(summarize_sh)] + log_files,
        capture_output=True, text=True, timeout=30
    )
    if result.stdout:
        with open(log_dir / "metrics_summary.txt", "w") as f:
            f.write(result.stdout)
        log("Metrics summary written to metrics_summary.txt")
    if result.returncode != 0 and result.stderr:
        log(f"Summarize warning: {result.stderr[:200]}")

# ============ Post-process ============
def collect_and_summarize(log_dir, workers):
    """Step 5-7: collect worker logs, gather metrics, run summarize."""
    # Step 5: Collect worker logs & metrics
    log("=== Collecting worker logs & metrics ===")
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

    # Step 6: Write test summary
    summary = {
        "test_time": datetime.now().isoformat(),
        "workers": WORKER_PORTS,
        "tenants": NUM_TENANTS,
        "clients_per_tenant": CLIENTS_PER_TENANT,
        "keys_per_client": KEYS_PER_CLIENT,
        "value_sizes": ["0.5MB", "2MB", "8MB"],
        "worker_binary": WORKER_BIN,
    }
    with open(log_dir / "test_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Step 7: Summarize metrics
    log("=== Summarizing metrics ===")
    summarize_metrics(log_dir)
    log(f"Results at {log_dir}")

# ============ Main test ============
def run_smoke_test(log_dir):
    worker_log_dir = log_dir / "workers"
    worker_log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Start etcd
    log("=== Step 1: Starting etcd ===")
    etcd_proc = start_etcd(log_dir)

    # 2. Start workers
    log("=== Step 2: Starting 4 workers (binary mode) ===")
    workers = start_workers(worker_log_dir)

    # 3. Start clients
    log("=== Step 3: Starting 16 clients ===")
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
    log_dir = get_timestamp_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log(f"Log output: {log_dir}")
    log(f"Worker binary: {WORKER_BIN}")

    # Ensure clean environment at start
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
        # Always stop etcd first
        if etcd_proc:
            try:
                etcd_proc.terminate()
                etcd_proc.wait(timeout=5)
            except:
                etcd_proc.kill()
        stop_etcd()

        # Stop workers
        stop_workers()

        # Final cleanup
        cleanup_all()

        # Remove etcd data dir
        subprocess.run(["rm", "-rf", ETCD_DATA_DIR], stderr=subprocess.DEVNULL)

        log(f"=== Smoke test DONE. Results at {log_dir} ===")

if __name__ == "__main__":
    main()
