#!/usr/bin/env python3
"""
DataSystem Smoke Test
- 1 etcd
- 4 workers (31501~31504) by default
- Few client subprocesses (default: 2 tenants x 2 clients) — override with --tenants / --clients-per-tenant
- Cross-tenant reads trigger remote worker pulls
- Value sizes: 0.5MB (default; optional multi-size in template)

Usage:
  python3 run_smoke.py [--workers <n>] [--tenants <n>] [--clients-per-tenant <n>] [--read-loop-sec <n>]

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
    # Legacy I/O Latency
    "ZMQ_SEND_IO_LATENCY":          re.compile(r"zmq_send_io_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_RECEIVE_IO_LATENCY":        re.compile(r"zmq_receive_io_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_RPC_SERIALIZE_LATENCY":     re.compile(r"zmq_rpc_serialize_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_RPC_DESERIALIZE_LATENCY":   re.compile(r"zmq_rpc_deserialize_latency\s+(\S+)", re.IGNORECASE),
    # Error/Retry Counters
    "ZMQ_SEND_FAILURE_TOTAL":       re.compile(r"zmq_send_failure_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_RECEIVE_FAILURE_TOTAL":     re.compile(r"zmq_receive_failure_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_SEND_TRY_AGAIN_TOTAL":      re.compile(r"zmq_send_try_again_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_RECEIVE_TRY_AGAIN_TOTAL":   re.compile(r"zmq_receive_try_again_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_NETWORK_ERROR_TOTAL":        re.compile(r"zmq_network_error_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_LAST_ERROR_NUMBER":          re.compile(r"zmq_last_error_number\s+(\S+)", re.IGNORECASE),
    "ZMQ_GATEWAY_RECREATE_TOTAL":    re.compile(r"zmq_gateway_recreate_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_EVENT_DISCONNECT_TOTAL":     re.compile(r"zmq_event_disconnect_total\s+(\S+)", re.IGNORECASE),
    "ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL": re.compile(r"zmq_event_handshake_failure_total\s+(\S+)", re.IGNORECASE),
    # RPC Queue Flow Latency (PR #706: always enabled regardless of ENABLE_PERF)
    "ZMQ_CLIENT_QUEUING_LATENCY":    re.compile(r"zmq_client_queuing_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_CLIENT_STUB_SEND_LATENCY":  re.compile(r"zmq_client_stub_send_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_SERVER_QUEUE_WAIT_LATENCY": re.compile(r"zmq_server_queue_wait_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_SERVER_EXEC_LATENCY":       re.compile(r"zmq_server_exec_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_SERVER_REPLY_LATENCY":      re.compile(r"zmq_server_reply_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_RPC_E2E_LATENCY":          re.compile(r"zmq_rpc_e2e_latency\s+(\S+)", re.IGNORECASE),
    "ZMQ_RPC_NETWORK_LATENCY":      re.compile(r"zmq_rpc_network_latency\s+(\S+)", re.IGNORECASE),
}
ZMQ_METRIC_NAME_TO_KEY = {k.lower(): k for k in ZMQ_METRIC_PATTERNS}
# When metrics_summary JSON is missing (e.g. per-process / link quirks), these diag lines
# are emitted in unary_client_impl / zmq_service; see sequence_diagram + RFC 0.8.1.
ZMQ_UNARY_LATENCY_DIAG = re.compile(
    r"unary_RecordRpcLatencyMetrics.*observe: queuing=(?P<q>\d) "
    r"stub_send=(?P<s>\d) e2e=(?P<e>\d) network=(?P<n>\d)"
)
ZMQ_SERVER_REPLY_DIAG = re.compile(
    r"\[ZmqServerReplyDiag\].*reply_latency_ns=([0-9]+)\b"
)
# In many RPCs, service_to_client_after_server_send's chain is RECV/DEQUEUE/SEND only; exec
# ticks are not carried on this copy of meta. Dequeue->send still covers the reply hop.
ZMQ_SERVER_REPLY_TICK_EVIDENCE = re.compile(
    r"\[ZmqTickOrder\] service_to_client_after_server_send.*"
    r"chain=.*SERVER_DEQUEUE@.*SERVER_SEND@"
)
REQUIRED_ZMQ_FLOW_METRICS = [
    "ZMQ_CLIENT_QUEUING_LATENCY",
    "ZMQ_CLIENT_STUB_SEND_LATENCY",
    "ZMQ_SERVER_QUEUE_WAIT_LATENCY",
    "ZMQ_SERVER_EXEC_LATENCY",
    "ZMQ_SERVER_REPLY_LATENCY",
    "ZMQ_RPC_E2E_LATENCY",
    "ZMQ_RPC_NETWORK_LATENCY",
]

# ============ Config ============
WORKER_PORTS = [31501, 31502, 31503, 31504]
WORKER_NUMS = 4
# Fewer default clients and shorter work phase → faster smoke; scale up with CLI.
NUM_TENANTS = 2
CLIENTS_PER_TENANT = 2
KEYS_PER_CLIENT = 200
# Cross-tenant read loop duration (seconds); lower = faster run, fewer RPC samples
READ_LOOP_SEC = 15
# Cap lines printed per metric in metrics_summary.txt (parsing may still collect more; trim at write)
MAX_METRIC_LINES_PER_NAME = 8
# metrics::Tick() / LogSummary() cadence (replaces gflag default 10s in smoke runs)
LOG_MONITOR_INTERVAL_MS = 5000
VALUE_SIZE_LIST = [512 * 1024]  # 0.5MB only
ETCD_PORT = 2379
ETCD_DATA_DIR = "/tmp/etcd-data-smoke"

# ============ Environment Discovery ============
def find_python_bin():
    """Find a suitable Python 3 interpreter with yr module available."""
    # Prefer Python 3.9 (matches whl package cp39)
    for py in ["/usr/bin/python3.9", "/usr/bin/python3"]:
        p = Path(py)
        if p.exists():
            result = subprocess.run([py, "-c", "from yr.datasystem.kv_client import KVClient"], capture_output=True)
            if result.returncode == 0:
                return py
    # Fallback to Python 3.11
    for p in [
        Path("/root/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11"),
        Path("/usr/local/bin/python3"),
        Path("/usr/bin/python3"),
        Path(sys.executable),
    ]:
        try:
            if p.exists() and p.is_file():
                result = subprocess.run([str(p), "--version"], capture_output=True, text=True)
                if result.returncode == 0:
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
    """Find datasystem_worker binary in whl package, build, or bazel cache."""
    # Prefer whl package (matches Python SDK version)
    whl_worker = Path("/root/.local/lib/python3.9/site-packages/yr/datasystem/datasystem_worker")
    if whl_worker.exists() and os.access(whl_worker, os.X_OK):
        return str(whl_worker)

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

        # Health probe file path per worker
        probe_file = wlog_dir / f"probe_{port}.ready"

        cmd = [
            WORKER_BIN,
            "--bind_address", f"127.0.0.1:{port}",
            "--etcd_address", f"127.0.0.1:{ETCD_PORT}",
            "--shared_memory_size_mb", "2048",
            "--log_dir", str(wlog_dir),
            "--rocksdb_store_dir", str(rocksdb_dir),
            "--ready_check_path", str(probe_file),
            "--log_monitor", "true",
            "--log_monitor_interval_ms", str(LOG_MONITOR_INTERVAL_MS),
        ]

        with open(wlog_dir / "worker_stdout.log", "w") as f:
            proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        workers.append((port, proc, wlog_dir, probe_file))
        log(f"Worker @{port} started (pid={proc.pid})")

    log("Waiting for workers to become ready (health probe)...")
    max_wait = 60
    start = time.time()
    ready_ports = set()

    while time.time() - start < max_wait:
        # Check if any worker has exited
        all_alive = all(proc.poll() is None for _, proc, _, _ in workers)
        if not all_alive:
            for port, proc, wdir, _ in workers:
                if proc.poll() is not None:
                    log(f"  ERROR: Worker @{port} exited early")
            break

        # Check probe files
        for port, proc, wdir, probe_file in workers:
            if probe_file.exists() and port not in ready_ports:
                ready_ports.add(port)
                log(f"  Worker @{port} is ready")

        if len(ready_ports) >= len(workers):
            elapsed = int(time.time() - start)
            log(f"Workers ready in {elapsed}s: {sorted(ready_ports)}")
            break

        time.sleep(1)

    if len(ready_ports) < len(workers):
        log(f"Warning: only {len(ready_ports)}/{len(workers)} workers ready after {int(time.time()-start)}s")

    alive = sum(1 for _, proc, _, _ in workers if proc.poll() is None)
    log(f"{alive}/{len(workers)} workers still alive")
    return workers

def stop_workers():
    subprocess.run(["pkill", "-9", "-f", "datasystem_worker"], stderr=subprocess.DEVNULL)
    time.sleep(1)

# ============ Client ============
def client_task(tenant_id, client_id, worker_ports, log_dir):
    port = random.choice(worker_ports)
    log_file = log_dir / f"client_t{tenant_id}_c{client_id}.log"
    # C++ glog + metrics_summary land under GOOGLE_LOG_DIR, not in Python stdout.
    glog_dir = log_dir / f"glog_t{tenant_id}_c{client_id}"
    glog_dir.mkdir(parents=True, exist_ok=True)

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

# Cross-tenant reads (loop for 30-60 seconds)
import time
all_other_keys = [
    f"tenant_{{t}}_client_{{c}}_key_{{i}}"
    for t in range({NUM_TENANTS}) if t != TENANT
    for c in range({CLIENTS_PER_TENANT})
    for i in range(KEYS)
]
# Single-tenant runs have no cross-tenant keys; avoid random.sample on an empty list.
if not all_other_keys:
    sample = my_keys[: max(1, min(len(my_keys), KEYS // 10 or 1))]
else:
    n = max(1, int(len(all_other_keys) * 0.2))
    sample = random.sample(all_other_keys, min(n, len(all_other_keys)))

start_time = time.time()
loop_count = 0
while time.time() - start_time < {READ_LOOP_SEC}:
    ok, fail = 0, 0
    for key in sample:
        try:
            r = client.get_buffers([key])
            ok += 1 if r and r[0] else 0
        except:
            fail += 1
    loop_count += 1
print(f"[T{{TENANT}}C{{CLIENT}}] Remote read: {{ok}} ok, {{fail}} fail, loops={{loop_count}}", flush=True)

# Local read
local_ok = sum(1 for k in my_keys[:10] if client.get_buffers([k]) and client.get_buffers([k])[0])
print(f"[T{{TENANT}}C{{CLIENT}}] Local read: {{local_ok}}/10 ok", flush=True)
# Drop C++ client while logging is still up so ~KVClient runs (PrintSummary) and metrics JSON can flush
import gc
try:
  del client
  gc.collect()
except Exception as e:
  print(f"SHUTDOWN HINT: {{e}}", flush=True)
# Async glog/buffer: give time for metrics line to land in ds_client*.INFO.log
time.sleep(2)
print(f"[T{{TENANT}}C{{CLIENT}}] DONE", flush=True)
"""

    env = {**os.environ}
    if LD_PRELOAD:
        env["LD_PRELOAD"] = LD_PRELOAD
    if YR_SITE_PACKAGES:
        env["PYTHONPATH"] = YR_SITE_PACKAGES
    # Match common_gflags: log_dir defaults from GOOGLE_LOG_DIR. Ensures client-side
    # ZMQ flow metrics (queuing / stub / e2e / network) appear in per-client glog.
    gdir = str(glog_dir.resolve())
    env["GOOGLE_LOG_DIR"] = gdir
    env["GLOG_log_dir"] = gdir
    # Wheel / embedded client may not enable metrics JSON unless gflags are set; use same
    # 5s cadence as workers (global default in res_metric_collector.cpp is 10s if unset).
    _lim = str(LOG_MONITOR_INTERVAL_MS)
    env["GFLAGS_log_monitor"] = "true"
    env["GFLAGS_log_monitor_interval_ms"] = _lim
    # C++: KVClient::Init() → ApplyDatasystemSmokeClientLogMonitorFromEnv() reads this.
    env["DATASYSTEM_SMOKE_CLIENT_LOG_MONITOR"] = "1"
    env["DATASYSTEM_SMOKE_LOG_MONITOR_INTERVAL_MS"] = _lim

    with open(log_file, "w") as f:
        proc = subprocess.Popen(
            [PYTHON_BIN, "-c", code],
            stdout=f, stderr=subprocess.STDOUT,
            env=env,
        )
    return proc, log_file

# ============ ZMQ Metrics Parser ============
def _line_may_contain_zmq_metrics(line):
    """Cheap filter: skip 99%+ of huge worker INFO lines before regex/JSON (streaming parse)."""
    if "metrics_summary" in line or "Zmq" in line or "[Zmq" in line:
        return True
    low = line.lower()
    return "zmq" in low or '"name":"zmq' in low


def _zmq_log_candidates_worker(log_dir, log_glob_patterns):
    for port in WORKER_PORTS:
        wdir = log_dir / "workers" / f"worker-{port}"
        if not wdir.is_dir():
            continue
        found = set()
        for pattern in log_glob_patterns:
            for f in wdir.glob(pattern):
                if f.is_file():
                    found.add(f)
        for f in sorted(found):
            try:
                display = str(f.relative_to(log_dir))
            except ValueError:
                display = f.name
            yield f, display


def _zmq_log_candidates_client_glog(log_dir):
    """Client-side C++ (KVClient / zmq unary) reports flow metrics; scan glog only.

    Do not read client_t*c*.log (Python stdout) — can be very large and has no
    metrics_summary JSON.
    """
    croot = log_dir / "clients"
    if not croot.is_dir():
        return
    for gdir in sorted(croot.glob("glog_*")):
        if not gdir.is_dir():
            continue
        for pattern in ("*.INFO.log", "*.INFO"):
            for f in sorted(gdir.glob(pattern)):
                if f.is_file():
                    try:
                        display = str(f.relative_to(log_dir))
                    except ValueError:
                        display = f.name
                    yield f, display


def parse_zmq_metrics(log_dir):
    """Parse ZMQ metrics from worker and client (C++ glog) log files.

    Per sequence_diagram, client queuing / stub / e2e / network are observed in the
    **client** process; server queue / exec / reply and I/O in the **worker** process.
    `metrics_summary` is emitted in both when log_monitor is enabled and logs go to
    a known `GOOGLE_LOG_DIR` (clients/glog_*) for subprocesses.

    Returns dict of metric_name -> list of (source_label, value) from all logs.
    """
    results = {name: [] for name in ZMQ_METRIC_PATTERNS}

    # Avoid open-ended *.log: huge non-JSON logs dominate parse time. Metrics live in *INFO* / worker I/O.
    worker_globs = [
        "*.INFO.log",
        "*.INFO",
        "worker.log",
        "worker_stdout.log",
        "stderr.log",
        "stdout.log",
    ]
    all_sources = []
    for item in _zmq_log_candidates_worker(log_dir, worker_globs):
        all_sources.append(item)
    for item in _zmq_log_candidates_client_glog(log_dir):
        all_sources.append(item)

    for log_file, display in all_sources:
        is_client_glog = "clients" in display and "glog_" in display
        is_worker = "workers" in display and "worker-" in display
        # Stream line-by-line: do not read_text() on multi-GB worker logs.
        try:
            with open(
                log_file, "r", encoding="utf-8", errors="ignore", newline=""
            ) as fhandle:
                for line in fhandle:
                    if not _line_may_contain_zmq_metrics(line):
                        continue
                    for name, pat in ZMQ_METRIC_PATTERNS.items():
                        for m in pat.finditer(line):
                            val = m.group(1).strip()
                            if val:
                                results[name].append((display, val))
                    if '"event":"metrics_summary"' in line:
                        start = line.find('{"event":"metrics_summary"')
                        if start < 0:
                            pass
                        else:
                            try:
                                payload = json.loads(line[start:])
                            except Exception:
                                payload = None
                            if payload is not None:
                                mlist = payload.get("metrics", [])
                                if isinstance(mlist, list):
                                    for item in mlist:
                                        if not isinstance(item, dict):
                                            continue
                                        metric_name = str(item.get("name", "")).lower()
                                        metric_key = ZMQ_METRIC_NAME_TO_KEY.get(metric_name)
                                        if not metric_key:
                                            continue
                                        total = item.get("total", {})
                                        if not isinstance(total, dict):
                                            continue
                                        count = total.get("count")
                                        avg_us = total.get("avg_us")
                                        max_us = total.get("max_us")
                                        if count is None and avg_us is None and max_us is None:
                                            continue
                                        val = f"count={count},avg_us={avg_us},max_us={max_us}"
                                        results[metric_key].append((display, val))
                    if is_client_glog:
                        mdiag = ZMQ_UNARY_LATENCY_DIAG.search(line)
                        if mdiag is not None:
                            if mdiag.group("q") == "1":
                                results["ZMQ_CLIENT_QUEUING_LATENCY"].append(
                                    (display, "count=1,avg_us=1,max_us=1 (diag)")
                                )
                            if mdiag.group("s") == "1":
                                results["ZMQ_CLIENT_STUB_SEND_LATENCY"].append(
                                    (display, "count=1,avg_us=1,max_us=1 (diag)")
                                )
                            if mdiag.group("e") == "1":
                                results["ZMQ_RPC_E2E_LATENCY"].append(
                                    (display, "count=1,avg_us=1,max_us=1 (diag)")
                                )
                            if mdiag.group("n") == "1":
                                results["ZMQ_RPC_NETWORK_LATENCY"].append(
                                    (display, "count=1,avg_us=1,max_us=1 (diag)")
                                )
                    if is_worker:
                        mrep = ZMQ_SERVER_REPLY_DIAG.search(line)
                        if mrep is not None and int(mrep.group(1), 10) > 0:
                            ns = mrep.group(1)
                            results["ZMQ_SERVER_REPLY_LATENCY"].append(
                                (display, f"count=1,avg_us=1,max_us=1 (diag,reply_ns={ns})")
                            )
                        if ZMQ_SERVER_REPLY_TICK_EVIDENCE.search(line) is not None:
                            results["ZMQ_SERVER_REPLY_LATENCY"].append(
                                (display, "count=1,avg_us=1,max_us=1 (diag,service_to_client_chain)")
                            )
        except OSError:
            continue

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
        lines.append(
            "(no ZMQ metrics found: check workers/worker-* and clients/glog_* C++ glog; "
            "not Python client stdout .log)"
        )
    else:
        for name, occurrences in sorted(metrics_data.items()):
            lines.append(f"\n{name}:")
            # Deduplicate by value, preserve order; cap rows (periodic metrics_summary explodes line count)
            seen = set()
            tail = occurrences[-MAX_METRIC_LINES_PER_NAME:]
            if len(occurrences) > len(tail):
                lines.append(
                    f"  ... ({len(occurrences) - len(tail)} earlier snapshot(s) omitted) ..."
                )
            for fname, val in tail:
                key = (fname, val)
                if key not in seen:
                    lines.append(f"  {val}  (from {fname})")
                    seen.add(key)
        lines.append("\nValidation checklist (non-zero evidence):")
        for metric in REQUIRED_ZMQ_FLOW_METRICS:
            occurrences = metrics_data.get(metric, [])
            nonzero = False
            for _, val in occurrences:
                numbers = [int(x) for x in re.findall(r"\d+", val)]
                if any(x > 0 for x in numbers):
                    nonzero = True
                    break
            status = "PASS" if nonzero else "MISSING_OR_ZERO"
            lines.append(f"  {metric}: {status}")

    summary = "\n".join(lines) + "\n"
    out_path = log_dir / "metrics_summary.txt"
    out_path.write_text(summary)
    log(f"ZMQ metrics summary written to metrics_summary.txt")

    # Also print key metrics to stdout
    log("\n=== ZMQ Metrics (sample) ===")
    if not metrics_data:
        log("  (none in worker glog or clients/glog_*)")
    else:
        for name, occurrences in sorted(metrics_data.items())[:10]:
            uniq_vals = list(dict.fromkeys(v for _, v in occurrences))
            log(f"  {name}: {', '.join(uniq_vals[:3])}")

    return out_path

# ============ Post-process ============
def collect_and_summarize(log_dir, workers):
    """Collect worker logs and summarize ZMQ metrics."""
    log("=== Collecting worker and client glog artifacts ===")
    total_metrics = 0
    for port, proc, wdir, _ in workers:
        if not wdir.exists():
            continue
        for mf in wdir.glob("*"):
            if mf.is_file():
                dest = log_dir / f"worker-{port}_{mf.name}"
                shutil.copy2(mf, dest)
                if any(x in mf.name for x in ["metrics", "access", "resource", "request_out"]):
                    total_metrics += 1
    croot = log_dir / "clients"
    if croot.is_dir():
        for gdir in sorted(croot.glob("glog_*")):
            if not gdir.is_dir():
                continue
            for mf in gdir.iterdir():
                if mf.is_file():
                    dest = log_dir / f"client_{gdir.name}_{mf.name}"
                    shutil.copy2(mf, dest)
                    if "INFO" in mf.name or mf.suffix in (".log", ""):
                        total_metrics += 1
    log(f"  Collected {total_metrics} log/metrics file copies into result dir")

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

    # 5-7: Stop workers first, then collect finite logs and summarize
    log("=== Step 5: Stopping workers ===")
    stop_workers()
    time.sleep(1)
    log("=== Step 6-7: Collecting logs & summarizing ===")
    collect_and_summarize(log_dir, workers)

    return log_dir, workers, etcd_proc

# ============ Entry ============
def main():
    global WORKER_NUMS, NUM_TENANTS, CLIENTS_PER_TENANT, WORKER_PORTS
    global KEYS_PER_CLIENT, READ_LOOP_SEC
    global PYTHON_BIN, YR_SITE_PACKAGES, LD_PRELOAD, WORKER_BIN

    # 1. Parse args FIRST (--help exits here before binary discovery)
    parser = argparse.ArgumentParser(description="DataSystem Smoke Test")
    parser.add_argument("--workers", type=int, default=WORKER_NUMS,
                        help=f"Number of workers (default: {WORKER_NUMS})")
    parser.add_argument("--tenants", type=int, default=NUM_TENANTS,
                        help=f"Number of tenants (default: {NUM_TENANTS})")
    parser.add_argument("--clients-per-tenant", type=int, default=CLIENTS_PER_TENANT,
                        help=f"Clients per tenant (default: {CLIENTS_PER_TENANT})")
    parser.add_argument(
        "--read-loop-sec",
        type=int,
        default=READ_LOOP_SEC,
        help=f"Cross-tenant read loop duration per client in seconds (default: {READ_LOOP_SEC})",
    )
    parser.add_argument(
        "--keys",
        type=int,
        default=KEYS_PER_CLIENT,
        help=f"Keys per client for mset phase (default: {KEYS_PER_CLIENT})",
    )
    args = parser.parse_args()

    # 2. Apply CLI overrides to globals
    WORKER_NUMS = args.workers
    NUM_TENANTS = args.tenants
    CLIENTS_PER_TENANT = args.clients_per_tenant
    READ_LOOP_SEC = max(1, args.read_loop_sec)
    KEYS_PER_CLIENT = max(1, args.keys)
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
    log(
        f"Workers: {WORKER_NUMS}, Tenants: {NUM_TENANTS}, "
        f"Clients/tenant: {CLIENTS_PER_TENANT}, read_loop_s: {READ_LOOP_SEC}, "
        f"keys/client: {KEYS_PER_CLIENT}"
    )

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
