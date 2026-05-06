#!/usr/bin/env python3
"""DataSystem log analyzer.

Subcommands:
  collect   Collect SDK/Worker logs from k8s pods
  parse     Parse logs and correlate latency segments to CSV
  plot      Generate per-node P99 latency charts from CSV
  latency   Latency stats and trend chart from access logs
"""

import argparse
import concurrent.futures
import csv
import gzip
import glob
import math
import os
import re
import shutil
import subprocess
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SDK_GET_OPS = frozenset({'DS_KV_CLIENT_GET', 'DS_OBJECT_CLIENT_GET'})
WORKER_GET_OPS = frozenset({'DS_POSIX_GET'})

OBJECT_KEY_RE = re.compile(r'Object_key:\[?([^,}\]]+)')
NOT_FOUND_RE = re.compile(r'\bK_NOT_FOUND\b|not\s+found|notfound', re.IGNORECASE)

URMA_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}).*?'
    r'\[URMA_ELAPSED_TOTAL\].*?cost\s+([\d.]+)ms.*?'
    r'src address:([^,]*?)\s*,\s*target address:([^,]*?)\s*,.*?'
    r'urma_inflight_wr_count:\s*(\d+)'
)
REMOTE_PULL_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}).*?'
    r'Processing pull object\[(.*?)\](?:\s+request\[(.*?)\])?\s+src\[(.*?)\]\s+dst\[(.*?)\]'
)
REMOTE_GET_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}).*?'
    r'Remote get request:\[.*?\]\s+src\[(.*?)\]\s+--dst\((.*?)\)-->'
)
URMA_LINK_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}).*?'
    r'(?:WorkerWorkerExchangeUrmaConnectInfo finish|Worker-worker transport connection exchange success),\s*'
    r'elapsed ms:\s*([\d.]+)'
)
QUERY_META_RE = re.compile(
    r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}).*?'
    r'Query meta success:\s+target num\s+\d+,\s+success num\s+\d+,\s+elapsed\s+([\d.]+)\s+ms'
)
TRACE_ID_RE = re.compile(r'(?:trace[_ ]?id|traceId)\s*[:=]\s*([^,\s|]+)', re.IGNORECASE)
LEADING_FLOAT_RE = re.compile(r'^\s*([\d.]+)(?:ms)?(?:\(|\s*$)')

COL_TIMESTAMP = 0
COL_TRACE_ID = 5
COL_STATUS_CODE = 7
COL_HANDLE = 8
COL_ELAPSED = 9
COL_SIZE = 10
COL_REQ_MSG = 11
COL_RESP_MSG = 12
COL_MIN_PARTS = 13
STATUS_OK = 0
SLOW_P99_THRESHOLD_US = 2000.0
PROGRESS_UPDATE_LINES = 100_000


class _Progress:
    def __init__(self, label: str, total_files=None):
        self.label = label
        self.total_files = total_files
        self.last_len = 0

    def update(self, file_idx=None, path='', lines=None, rows=None, matched=None):
        parts = [self.label]
        if file_idx is not None and self.total_files is not None:
            parts.append(f'file {file_idx}/{self.total_files}')
        if path:
            parent = os.path.basename(os.path.dirname(path))
            parts.append(f'{parent}/{os.path.basename(path)}')
        if lines is not None:
            parts.append(f'lines {lines:,}')
        if rows is not None:
            parts.append(f'rows {rows:,}')
        if matched is not None:
            parts.append(f'matched {matched:,}')
        msg = '  ' + ' | '.join(parts)
        sys.stderr.write('\r' + msg + ' ' * max(0, self.last_len - len(msg)))
        sys.stderr.flush()
        self.last_len = len(msg)

    def done(self, matched=None, rows=None):
        parts = [self.label, 'done']
        if rows is not None:
            parts.append(f'rows {rows:,}')
        if matched is not None:
            parts.append(f'matched {matched:,}')
        msg = '  ' + ' | '.join(parts)
        sys.stderr.write('\r' + msg + ' ' * max(0, self.last_len - len(msg)) + '\n')
        sys.stderr.flush()
        self.last_len = 0


def _glob_paths(patterns: list[str]) -> list[str]:
    paths = []
    seen = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
    return paths


def _parse_timestamp(ts: str) -> datetime:
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S'):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise ValueError(f'Invalid timestamp: {ts}')


def _open_log(path: str):
    """Open a log file, transparently handling .gz compression."""
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', errors='replace')
    return open(path, 'r', errors='replace')


# ===========================================================================
# COLLECT module
# ===========================================================================

def _kubectl(args, namespace, timeout=120):
    cmd = ['kubectl', '-n', namespace] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _discover_pods(name_pattern, namespace):
    try:
        pod_name_re = re.compile(name_pattern)
    except re.error as exc:
        print(f'ERROR: invalid pod name regex "{name_pattern}": {exc}', file=sys.stderr)
        sys.exit(1)

    cp = _kubectl([
        'get', 'pods', '--no-headers',
        '-o', 'custom-columns=NAME:.metadata.name,IP:.status.podIP,STATUS:.status.phase',
    ], namespace)
    if cp.returncode != 0:
        return []
    pods = []
    for line in cp.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) >= 3 and pod_name_re.search(parts[0]) and parts[2] == 'Running':
            pods.append((parts[0], parts[1]))
    return pods


def _resolve_log_dir(pod_name, namespace, log_dir_pattern):
    """Resolve log_dir wildcard on the remote pod via kubectl.

    If log_dir_pattern contains wildcards, use 'ls -d' to expand them.
    Returns the first matching directory, or the original pattern if no match.
    """
    if '*' not in log_dir_pattern and '?' not in log_dir_pattern:
        return log_dir_pattern
    ls_cp = _kubectl(
        ['exec', pod_name, '--', 'bash', '-c',
         f'ls -1d {log_dir_pattern} 2>/dev/null'],
        namespace, timeout=15,
    )
    if ls_cp.returncode == 0:
        lines = [l.strip() for l in ls_cp.stdout.strip().splitlines() if l.strip()]
        if lines:
            return lines[0]
    return log_dir_pattern


def _collect_pod(pod_name, pod_ip, dest_dir, patterns, latest_patterns, namespace, log_dir):
    """Collect log files from a single pod.

    Args:
        patterns: glob patterns to collect all matching files.
        latest_patterns: glob patterns where only the most recently modified file
                         should be collected (e.g. SDK access logs with multiple PIDs).
        log_dir: log directory path inside container, may contain wildcards.
    """
    os.makedirs(dest_dir, exist_ok=True)

    # Resolve wildcards in log_dir on the remote pod
    log_dir = _resolve_log_dir(pod_name, namespace, log_dir)

    # For latest_patterns, resolve to the single newest file per pattern via kubectl
    resolved_latest = []
    for pat in latest_patterns:
        # Use ls -t to find newest file matching this pattern, take first line
        ls_cp = _kubectl(
            ['exec', pod_name, '--', 'bash', '-c',
             f'ls -1t {log_dir}/{pat} {log_dir}/{pat}.gz 2>/dev/null | head -1'],
            namespace, timeout=30,
        )
        if ls_cp.returncode == 0:
            first = ls_cp.stdout.strip().splitlines()
            if first and first[0].strip():
                resolved_latest.append(first[0].strip())

    # Build file list: all from normal patterns + resolved latest files
    # Primary: tar stream for normal patterns + explicit files for latest
    glob_exprs = ' '.join(f'{log_dir}/{p}' for p in patterns)
    # Also add .gz variants for normal patterns
    glob_exprs_gz = ' '.join(f'{log_dir}/{p}.gz' for p in patterns)

    try:
        tar_cmd = f'tar cf - {glob_exprs} {glob_exprs_gz} 2>/dev/null'
        tar_cp = subprocess.Popen(
            ['kubectl', '-n', namespace, 'exec', pod_name, '--',
             'bash', '-c', tar_cmd],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        untar_cp = subprocess.Popen(
            ['tar', 'xf', '-', '-C', dest_dir,
             f'--strip-components={log_dir.count("/")}'],
            stdin=tar_cp.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        tar_cp.stdout.close()
        untar_cp.wait(timeout=120)
        tar_cp.wait(timeout=5)
    except (subprocess.TimeoutExpired, Exception):
        pass

    # Collect resolved latest files individually
    for f in resolved_latest:
        fname = os.path.basename(f)
        try:
            cat_cp = _kubectl(['exec', pod_name, '--', 'cat', f], namespace, timeout=60)
            if cat_cp.returncode == 0:
                with open(os.path.join(dest_dir, fname), 'wb') as out:
                    out.write(cat_cp.stdout.encode() if isinstance(cat_cp.stdout, str) else cat_cp.stdout)
        except Exception:
            pass

    file_count = sum(1 for _, _, files in os.walk(dest_dir) for _ in files)
    if file_count > 0:
        return pod_name, file_count, None

    # Fallback: cat all files individually
    try:
        all_ls_patterns = [f'{log_dir}/{p}' for p in patterns] + \
                          [f'{log_dir}/{p}.gz' for p in patterns]
        ls_cp = _kubectl(
            ['exec', pod_name, '--', 'bash', '-c',
             ' '.join(f'ls -1 {p}' for p in all_ls_patterns) + ' 2>/dev/null'],
            namespace, timeout=30,
        )
        for f in ls_cp.stdout.strip().splitlines():
            f = f.strip()
            if not f:
                continue
            fname = os.path.basename(f)
            try:
                cat_cp = _kubectl(['exec', pod_name, '--', 'cat', f], namespace, timeout=60)
                if cat_cp.returncode == 0:
                    with open(os.path.join(dest_dir, fname), 'wb') as out:
                        out.write(cat_cp.stdout.encode() if isinstance(cat_cp.stdout, str) else cat_cp.stdout)
            except Exception:
                pass
    except Exception as exc:
        return pod_name, 0, str(exc)

    file_count = sum(1 for _, _, files in os.walk(dest_dir) for _ in files)
    return pod_name, file_count, None if file_count > 0 else '0 files collected'


def _collect_type(type_label, name_pattern, patterns, latest_patterns, namespace, output_dir, log_dir, max_parallel):
    pods = _discover_pods(name_pattern, namespace)
    if not pods:
        print(f'  No Running pods found matching regex: {name_pattern}')
        return 0

    failed = 0
    count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {}
        for pod_name, pod_ip in pods:
            dest = os.path.join(output_dir, f'{type_label}_{pod_ip}')
            print(f'  {type_label} Pod: {pod_name} ({pod_ip})')
            fut = executor.submit(
                _collect_pod, pod_name, pod_ip, dest, patterns, latest_patterns, namespace, log_dir,
            )
            futures[fut] = pod_name
            count += 1

        for fut in concurrent.futures.as_completed(futures):
            pod_name, file_count, err = fut.result()
            if err:
                print(f'  [WARN] {pod_name}: {err}')
                failed += 1
            else:
                print(f'  [OK] {pod_name}: {file_count} file(s)')

    if failed:
        print(f'  [WARN] {failed}/{count} pods failed')
    return count


def collect_cmd(args):
    if not shutil.which('kubectl'):
        print('ERROR: kubectl not found in PATH', file=sys.stderr)
        sys.exit(1)

    print(f'=== Collecting SDK logs (pod regex: {args.sdk_prefix}) ===')
    sdk_count = _collect_type(
        'SDK', args.sdk_prefix,
        # normal patterns (collect all, including .gz)
        ['ds_client.INFO.*', 'ds_client.INFO.log'],
        # latest-only patterns (only newest modified file)
        ['ds_client_access_*.log'],
        args.namespace, args.output_dir, args.sdk_log_dir, args.parallel,
    )

    print(f'\n=== Collecting Worker logs (pod regex: {args.worker_prefix}) ===')
    worker_count = _collect_type(
        'worker', args.worker_prefix,
        ['access.log', 'datasystem_worker.INFO.*', 'datasystem_worker.INFO.log'],
        [],
        args.namespace, args.output_dir, args.worker_log_dir, args.parallel,
    )

    print(f'\n=== Collection Summary ===')
    print(f'SDK pods collected:    {sdk_count}')
    print(f'Worker pods collected: {worker_count}')
    print(f'Output directory:      {args.output_dir}')


# ===========================================================================
# PARSE module
# ===========================================================================

@dataclass
class SdkGetEntry:
    timestamp: datetime
    operation: str
    total_time_us: int
    data_size: str
    object_key: str
    trace_id: str
    pod_ip: str
    status_code: int
    resp_msg: str


@dataclass
class WorkerGetEntry:
    timestamp: datetime
    worker_time_us: int
    object_key: str
    trace_id: str
    pod_ip: str
    status_code: int
    resp_msg: str


@dataclass
class UrmaEntry:
    timestamp: datetime
    elapsed_ms: float
    src_addr: str
    dst_addr: str
    inflight_count: int
    pod_ip: str
    trace_id: str


@dataclass
class RemotePullEntry:
    timestamp: datetime
    object_key: str
    request_id: str
    read_src_addr: str
    read_dst_addr: str
    pod_ip: str
    trace_id: str


@dataclass
class LinkEntry:
    timestamp: datetime
    elapsed_ms: float
    pod_ip: str
    trace_id: str


@dataclass
class QueryMetaEntry:
    timestamp: datetime
    elapsed_ms: float
    pod_ip: str
    trace_id: str


def _parse_status_code(raw: str) -> int:
    try:
        return int(raw)
    except (ValueError, TypeError):
        return STATUS_OK


def _is_success_status(status_code: int, resp_msg: str) -> bool:
    # Some K_NOT_FOUND GET results are recorded with status_code=0 in ds_client_access logs.
    return status_code == STATUS_OK and NOT_FOUND_RE.search(resp_msg or '') is None


def _infer_local_host_port(pod_ip: str, peer_addr: str) -> str:
    if not pod_ip:
        return ''
    port = ''
    if ':' in peer_addr:
        port = peer_addr.rsplit(':', 1)[1].strip()
    return f'{pod_ip}:{port}' if port else pod_ip


def _parse_access_line(line: str):
    if len(line) < 80 or line[0] != '2':
        return None
    parts = line.split('|')
    if len(parts) < COL_MIN_PARTS:
        return None
    handle = parts[COL_HANDLE].strip()
    return {
        'timestamp': parts[COL_TIMESTAMP].strip(),
        'trace_id': parts[COL_TRACE_ID].strip(),
        'status_code': parts[COL_STATUS_CODE].strip(),
        'handle': handle,
        'elapsed': parts[COL_ELAPSED].strip(),
        'size': parts[COL_SIZE].strip(),
        'req_msg': parts[COL_REQ_MSG].strip(),
        'resp_msg': parts[COL_RESP_MSG].strip(),
    }


def _extract_object_key(req_msg: str) -> str:
    key_m = OBJECT_KEY_RE.search(req_msg or '')
    return key_m.group(1).strip() if key_m else ''


def _extract_trace_id_from_log_line(line: str) -> str:
    parts = line.split('|')
    if len(parts) > COL_TRACE_ID:
        trace_id = parts[COL_TRACE_ID].strip()
        if trace_id:
            return trace_id
    match = TRACE_ID_RE.search(line)
    return match.group(1).strip() if match else ''


def _parse_sdk_logs(input_dir: str) -> list[SdkGetEntry]:
    entries = []
    patterns = [os.path.join(input_dir, 'SDK_*', 'ds_client_access_*.log'),
                os.path.join(input_dir, 'SDK_*', 'ds_client_access_*.log.gz')]
    paths = _glob_paths(patterns)
    progress = _Progress('SDK access parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        pod_ip = os.path.basename(os.path.dirname(path)).replace('SDK_', '')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                p = _parse_access_line(line)
                if not p or p['handle'] not in SDK_GET_OPS:
                    continue
                try:
                    elapsed = int(p['elapsed'])
                except (ValueError, TypeError):
                    continue
                trace_id = p['trace_id']
                if not trace_id:
                    continue
                entries.append(SdkGetEntry(
                    timestamp=_parse_timestamp(p['timestamp']),
                    operation=p['handle'],
                    total_time_us=elapsed,
                    data_size=p['size'],
                    object_key=_extract_object_key(p['req_msg']),
                    trace_id=trace_id,
                    pod_ip=pod_ip,
                    status_code=_parse_status_code(p['status_code']),
                    resp_msg=p['resp_msg'],
                ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _parse_worker_access_logs(input_dir: str) -> list[WorkerGetEntry]:
    entries = []
    patterns = [os.path.join(input_dir, '*worker_*', 'access.log'),
                os.path.join(input_dir, '*worker_*', 'access.log.gz')]
    paths = _glob_paths(patterns)
    progress = _Progress('Worker access parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        _dir = os.path.basename(os.path.dirname(path))
        pod_ip = _dir.removeprefix('dsworker_').removeprefix('worker_')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                p = _parse_access_line(line)
                if not p or p['handle'] not in WORKER_GET_OPS:
                    continue
                try:
                    elapsed = int(p['elapsed'])
                except (ValueError, TypeError):
                    continue
                trace_id = p['trace_id']
                if not trace_id:
                    continue
                entries.append(WorkerGetEntry(
                    timestamp=_parse_timestamp(p['timestamp']),
                    worker_time_us=elapsed,
                    object_key=_extract_object_key(p['req_msg']),
                    trace_id=trace_id,
                    pod_ip=pod_ip,
                    status_code=_parse_status_code(p['status_code']),
                    resp_msg=p['resp_msg'],
                ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _parse_worker_urma_logs(input_dir: str) -> list[UrmaEntry]:
    entries = []
    paths = _glob_paths([os.path.join(input_dir, '*worker_*', 'datasystem_worker.INFO.*')])
    progress = _Progress('Worker URMA parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        _dir = os.path.basename(os.path.dirname(path))
        pod_ip = _dir.removeprefix('dsworker_').removeprefix('worker_')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                if 'URMA_ELAPSED_TOTAL' not in line:
                    continue
                m = URMA_RE.search(line)
                if not m:
                    continue
                ts_str, elapsed_ms, src, dst, inflight = m.groups()
                entries.append(UrmaEntry(
                    timestamp=_parse_timestamp(ts_str),
                    elapsed_ms=float(elapsed_ms),
                    src_addr=src.strip(),
                    dst_addr=dst.strip(),
                    inflight_count=int(inflight),
                    pod_ip=pod_ip,
                    trace_id=_extract_trace_id_from_log_line(line),
                ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _parse_worker_remote_pull_logs(input_dir: str) -> list[RemotePullEntry]:
    entries = []
    paths = _glob_paths([os.path.join(input_dir, '*worker_*', 'datasystem_worker.INFO.*')])
    progress = _Progress('Worker remote pull parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        _dir = os.path.basename(os.path.dirname(path))
        pod_ip = _dir.removeprefix('dsworker_').removeprefix('worker_')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                if 'Remote get request:' in line:
                    m = REMOTE_GET_RE.search(line)
                    if not m:
                        continue
                    ts_str, src_addr, dst_addr = m.groups()
                    entries.append(RemotePullEntry(
                        timestamp=_parse_timestamp(ts_str),
                        object_key='',
                        request_id='',
                        read_src_addr=src_addr.strip(),
                        read_dst_addr=dst_addr.strip(),
                        pod_ip=pod_ip,
                        trace_id=_extract_trace_id_from_log_line(line),
                    ))
                    continue

                if 'Processing pull object[' in line:
                    m = REMOTE_PULL_RE.search(line)
                    if not m:
                        continue
                    ts_str, object_key, request_id, src_addr, dst_addr = m.groups()
                    src_addr = src_addr.strip()
                    dst_addr = dst_addr.strip() or _infer_local_host_port(pod_ip, src_addr)
                    entries.append(RemotePullEntry(
                        timestamp=_parse_timestamp(ts_str),
                        object_key=object_key.strip(),
                        request_id=(request_id or '').strip(),
                        read_src_addr=src_addr,
                        read_dst_addr=dst_addr,
                        pod_ip=pod_ip,
                        trace_id=_extract_trace_id_from_log_line(line),
                    ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _parse_worker_link_logs(input_dir: str) -> list[LinkEntry]:
    entries = []
    paths = _glob_paths([os.path.join(input_dir, '*worker_*', 'datasystem_worker.INFO.*')])
    progress = _Progress('Worker URMA link parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        _dir = os.path.basename(os.path.dirname(path))
        pod_ip = _dir.removeprefix('dsworker_').removeprefix('worker_')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                if 'elapsed ms:' not in line:
                    continue
                if ('WorkerWorkerExchangeUrmaConnectInfo finish' not in line
                        and 'Worker-worker transport connection exchange success' not in line):
                    continue
                if 'WorkerWorkerExchangeUrmaConnectInfo finish' in line and 'status=code: [OK]' not in line:
                    continue
                m = URMA_LINK_RE.search(line)
                if not m:
                    continue
                ts_str, elapsed_ms = m.groups()
                trace_id = _extract_trace_id_from_log_line(line)
                if not trace_id:
                    continue
                entries.append(LinkEntry(
                    timestamp=_parse_timestamp(ts_str),
                    elapsed_ms=float(elapsed_ms),
                    pod_ip=pod_ip,
                    trace_id=trace_id,
                ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _parse_worker_query_meta_logs(input_dir: str) -> list[QueryMetaEntry]:
    entries = []
    paths = _glob_paths([os.path.join(input_dir, '*worker_*', 'datasystem_worker.INFO.*')])
    progress = _Progress('Worker query meta parse', len(paths))
    for file_idx, path in enumerate(paths, 1):
        _dir = os.path.basename(os.path.dirname(path))
        pod_ip = _dir.removeprefix('dsworker_').removeprefix('worker_')
        progress.update(file_idx, path, lines=0, matched=len(entries))
        with _open_log(path) as f:
            for line_no, line in enumerate(f, 1):
                if line_no % PROGRESS_UPDATE_LINES == 0:
                    progress.update(file_idx, path, lines=line_no, matched=len(entries))
                if 'Query meta success:' not in line:
                    continue
                m = QUERY_META_RE.search(line)
                if not m:
                    continue
                ts_str, elapsed_ms = m.groups()
                trace_id = _extract_trace_id_from_log_line(line)
                if not trace_id:
                    continue
                entries.append(QueryMetaEntry(
                    timestamp=_parse_timestamp(ts_str),
                    elapsed_ms=float(elapsed_ms),
                    pod_ip=pod_ip,
                    trace_id=trace_id,
                ))
        progress.update(file_idx, path, matched=len(entries))
    entries.sort(key=lambda e: e.timestamp)
    progress.done(matched=len(entries))
    return entries


def _correlate_sdk_worker(sdk_entries, worker_entries, time_window_ms, no_time_window=False):
    worker_by_trace: dict[str, list[WorkerGetEntry]] = {}
    for w in worker_entries:
        worker_by_trace.setdefault(w.trace_id, []).append(w)

    window_us = time_window_ms * 1000
    result = {}
    for i, sdk in enumerate(sdk_entries):
        candidates = worker_by_trace.get(sdk.trace_id)
        if not candidates:
            continue
        if no_time_window:
            key_matched = [w for w in candidates if w.object_key == sdk.object_key]
            choices = key_matched or candidates
            result[i] = min(
                choices,
                key=lambda w: abs((w.timestamp - sdk.timestamp).total_seconds()),
            )
            continue
        best = None
        best_dt = None
        for w in candidates:
            dt_us = (w.timestamp - sdk.timestamp).total_seconds() * 1_000_000
            if 0 <= dt_us <= window_us:
                if best is None or dt_us < best_dt:
                    best = w
                    best_dt = dt_us
        if best is not None:
            result[i] = best
            continue

        # Cross-node SDK and Worker clocks can be skewed by more than the
        # correlation window. If the trace_id is unique, or the object key
        # narrows it to one worker entry, keep the trace correlation instead
        # of dropping all downstream URMA analysis.
        key_matched = [w for w in candidates if w.object_key and w.object_key == sdk.object_key]
        if len(key_matched) == 1:
            result[i] = key_matched[0]
        elif len(candidates) == 1:
            result[i] = candidates[0]
    return result


def _format_unmatched_reason(sdk: SdkGetEntry, candidates: list[WorkerGetEntry], time_window_ms: int,
                             no_time_window: bool) -> str:
    if not _is_success_status(sdk.status_code, sdk.resp_msg):
        return _format_failure_remark('SDK', sdk.status_code, sdk.resp_msg)
    if not candidates:
        return 'no worker access entry has the same trace_id'
    if no_time_window:
        return 'unexpected: worker candidates exist but no-time-window mode did not match'

    dt_values_ms = [(w.timestamp - sdk.timestamp).total_seconds() * 1000 for w in candidates]
    closest = min(dt_values_ms, key=lambda v: abs(v))
    key_match_count = sum(1 for w in candidates if w.object_key == sdk.object_key)
    key_info = f', object_key_matched_candidates={key_match_count}/{len(candidates)}'
    if all(dt < 0 for dt in dt_values_ms):
        return (f'all worker candidates are earlier than SDK timestamp; closest_dt={closest:.3f}ms'
                f'{key_info}; likely clock skew')
    if all(dt > time_window_ms for dt in dt_values_ms):
        return (f'all worker candidates are later than time window; closest_dt={closest:.3f}ms, '
                f'window={time_window_ms}ms{key_info}')
    return (f'worker candidates exist but none are within [0,{time_window_ms}]ms; '
            f'closest_dt={closest:.3f}ms{key_info}')


def _print_unmatched_sdk_samples(sdk_entries, worker_entries, sdk_worker_map, time_window_ms, no_time_window,
                                 limit=10):
    unmatched_total = len(sdk_entries) - len(sdk_worker_map)
    if unmatched_total <= 0:
        return

    worker_by_trace: dict[str, list[WorkerGetEntry]] = {}
    for w in worker_entries:
        worker_by_trace.setdefault(w.trace_id, []).append(w)

    print(f'  Unmatched SDK entries: {unmatched_total}; first {min(limit, unmatched_total)} sample(s):')
    printed = 0
    for i, sdk in enumerate(sdk_entries):
        if i in sdk_worker_map:
            continue
        candidates = worker_by_trace.get(sdk.trace_id, [])
        reason = _format_unmatched_reason(sdk, candidates, time_window_ms, no_time_window)
        print(
            f'    trace_id={sdk.trace_id}, sdk_time={sdk.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")}, '
            f'sdk_pod={sdk.pod_ip}, op={sdk.operation}, object_key={sdk.object_key or "-"}, '
            f'worker_candidates={len(candidates)}, reason={reason}'
        )
        printed += 1
        if printed >= limit:
            break


def _match_urma_by_remote_pull(urma_candidates: list[UrmaEntry],
                               remote_pulls: list[RemotePullEntry]) -> list[UrmaEntry]:
    if not urma_candidates or not remote_pulls:
        return []

    write_endpoints = set()
    for pull in remote_pulls:
        if not pull.read_src_addr or not pull.read_dst_addr:
            continue
        # Historical and current "Processing pull object" logs have used both
        # source/destination orientations. Accept either direction and let the
        # actual URMA src/dst pair disambiguate the matched transfer.
        write_endpoints.add((pull.read_dst_addr, pull.read_src_addr))
        write_endpoints.add((pull.read_src_addr, pull.read_dst_addr))
    if not write_endpoints:
        return []
    return [u for u in urma_candidates if (u.src_addr, u.dst_addr) in write_endpoints]


def _dedupe_urma_entries(*groups: list[UrmaEntry]) -> list[UrmaEntry]:
    result = []
    seen = set()
    for group in groups:
        for entry in group or []:
            key = (entry.timestamp, entry.elapsed_ms, entry.src_addr, entry.dst_addr, entry.trace_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(entry)
    result.sort(key=lambda e: e.timestamp)
    return result


def _correlate_worker_urma(worker_entries, urma_entries, worker_remote_pull_map=None):
    traced_urma_by_pod_trace: dict[tuple[str, str], list[UrmaEntry]] = {}
    traced_urma_by_trace: dict[str, list[UrmaEntry]] = {}
    untraced_urma_by_pod: dict[str, tuple[list[UrmaEntry], list[datetime]]] = {}
    worker_remote_pull_map = worker_remote_pull_map or {}
    for u in urma_entries:
        if u.trace_id:
            traced_urma_by_pod_trace.setdefault((u.pod_ip, u.trace_id), []).append(u)
            traced_urma_by_trace.setdefault(u.trace_id, []).append(u)
            continue
        if u.pod_ip not in untraced_urma_by_pod:
            entries = []
            untraced_urma_by_pod[u.pod_ip] = (entries, None)
        untraced_urma_by_pod[u.pod_ip][0].append(u)
    for entries in traced_urma_by_pod_trace.values():
        entries.sort(key=lambda e: e.timestamp)
    for entries in traced_urma_by_trace.values():
        entries.sort(key=lambda e: e.timestamp)
    for pod_ip in untraced_urma_by_pod:
        entries = untraced_urma_by_pod[pod_ip][0]
        entries.sort(key=lambda e: e.timestamp)
        untraced_urma_by_pod[pod_ip] = (entries, [e.timestamp for e in entries])

    result = {}
    client_worker_result = {}
    worker_worker_result = {}
    for i, w in enumerate(worker_entries):
        remote_matched = _match_urma_by_remote_pull(
            traced_urma_by_trace.get(w.trace_id, []),
            worker_remote_pull_map.get(i, []),
        )
        if remote_matched:
            worker_worker_result[i] = remote_matched

        traced = traced_urma_by_pod_trace.get((w.pod_ip, w.trace_id), [])
        if traced:
            client_worker_result[i] = traced

        untraced = []
        cached = untraced_urma_by_pod.get(w.pod_ip)
        if cached:
            urma_list, urma_ts = cached
            w_end = w.timestamp + timedelta(microseconds=w.worker_time_us)
            lo = bisect_left(urma_ts, w.timestamp)
            hi = bisect_right(urma_ts, w_end)
            if lo < hi:
                untraced = urma_list[lo:hi]

        matched = _dedupe_urma_entries(remote_matched, traced, untraced)
        if matched:
            result[i] = matched
    return result, client_worker_result, worker_worker_result

def _correlate_worker_remote_pulls(worker_entries, remote_pull_entries):
    pulls_by_trace: dict[str, list[RemotePullEntry]] = {}
    for pull in remote_pull_entries:
        if pull.trace_id:
            pulls_by_trace.setdefault(pull.trace_id, []).append(pull)

    result = {}
    for i, worker in enumerate(worker_entries):
        candidates = pulls_by_trace.get(worker.trace_id, [])
        if not candidates:
            continue
        key_matched = [p for p in candidates if not worker.object_key or p.object_key == worker.object_key]
        choices = key_matched or candidates
        if choices:
            result[i] = choices
    return result


def _correlate_worker_links(worker_entries, link_entries):
    links_by_pod_trace: dict[tuple[str, str], list[LinkEntry]] = {}
    links_by_trace: dict[str, list[LinkEntry]] = {}
    for link in link_entries:
        links_by_pod_trace.setdefault((link.pod_ip, link.trace_id), []).append(link)
        links_by_trace.setdefault(link.trace_id, []).append(link)

    result = {}
    for i, worker in enumerate(worker_entries):
        candidates = links_by_pod_trace.get((worker.pod_ip, worker.trace_id))
        if not candidates:
            candidates = links_by_trace.get(worker.trace_id, [])
        if candidates:
            result[i] = max(link.elapsed_ms for link in candidates)
    return result


def _correlate_worker_query_meta(worker_entries, query_meta_entries):
    metas_by_pod_trace: dict[tuple[str, str], list[QueryMetaEntry]] = {}
    for entry in query_meta_entries:
        metas_by_pod_trace.setdefault((entry.pod_ip, entry.trace_id), []).append(entry)
    for entries in metas_by_pod_trace.values():
        entries.sort(key=lambda e: e.timestamp)

    result = {}
    for i, worker in enumerate(worker_entries):
        candidates = metas_by_pod_trace.get((worker.pod_ip, worker.trace_id), [])
        if not candidates:
            continue
        start = worker.timestamp - timedelta(microseconds=worker.worker_time_us)
        in_range = [entry for entry in candidates if start <= entry.timestamp <= worker.timestamp]
        choices = in_range or candidates
        best = min(choices, key=lambda entry: abs((entry.timestamp - worker.timestamp).total_seconds()))
        result[i] = best.elapsed_ms
    return result


def _join_unique(values) -> str:
    seen = set()
    result = []
    for value in values:
        value = str(value).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return ';'.join(result)


def _serialize_urma(urma_list: list[UrmaEntry]) -> tuple[str, str, str, str]:
    if not urma_list:
        return '', '', '', ''

    return (
        ';'.join(f'{u.elapsed_ms:.3f}' for u in urma_list),
        _join_unique(str(u.inflight_count) for u in urma_list),
        _join_unique(u.src_addr for u in urma_list),
        _join_unique(u.dst_addr for u in urma_list),
    )


def _serialize_urma_elapsed(urma_list: list[UrmaEntry]) -> str:
    if not urma_list:
        return ''
    return ';'.join(f'{u.elapsed_ms:.3f}' for u in urma_list)


def _serialize_remote_pull_as_urma_endpoints(remote_pulls: list[RemotePullEntry]) -> tuple[str, str]:
    if not remote_pulls:
        return '', ''
    write_src = _join_unique(p.read_src_addr for p in remote_pulls)
    write_dst = _join_unique(p.read_dst_addr for p in remote_pulls)
    if write_src and write_dst:
        return write_src, write_dst
    return '', ''


def _format_link_ms(link_ms) -> str:
    return f'{link_ms:.3f}' if link_ms is not None else '0'


def _format_optional_ms(elapsed_ms) -> str:
    return f'{elapsed_ms:.3f}' if elapsed_ms is not None else ''


def _format_failure_remark(source: str, status_code: int, resp_msg: str) -> str:
    msg = resp_msg.strip() if resp_msg else ''
    if status_code == STATUS_OK and NOT_FOUND_RE.search(msg):
        return f'Request failed: {source} K_NOT_FOUND, message={msg}'
    if msg:
        return f'Request failed: {source} status_code={status_code}, message={msg}'
    return f'Request failed: {source} status_code={status_code}'


def _merge_remark(current: str, extra: str) -> str:
    if not current:
        return extra
    if current == 'OK':
        return f'OK; {extra}' if extra and extra != 'OK' else current
    if not extra or extra == 'OK':
        return current
    return f'{current}; {extra}'


def _build_worker_urma_empty_reasons(worker_entries, urma_entries, worker_urma_map) -> dict[int, str]:
    urma_count_by_pod: dict[str, int] = defaultdict(int)
    traced_count_by_pod: dict[str, int] = defaultdict(int)
    untraced_count_by_pod: dict[str, int] = defaultdict(int)
    traced_count_by_pod_trace: dict[tuple[str, str], int] = defaultdict(int)

    for u in urma_entries:
        urma_count_by_pod[u.pod_ip] += 1
        if u.trace_id:
            traced_count_by_pod[u.pod_ip] += 1
            traced_count_by_pod_trace[(u.pod_ip, u.trace_id)] += 1
        else:
            untraced_count_by_pod[u.pod_ip] += 1

    reasons = {}
    for i, worker in enumerate(worker_entries):
        if i in worker_urma_map:
            continue
        if urma_count_by_pod[worker.pod_ip] == 0:
            reasons[i] = 'URMA fields empty: no URMA logs collected for worker pod'
        elif traced_count_by_pod_trace[(worker.pod_ip, worker.trace_id)] == 0 and traced_count_by_pod[worker.pod_ip] > 0:
            if untraced_count_by_pod[worker.pod_ip] > 0:
                reasons[i] = ('URMA fields empty: no URMA trace_id matched worker trace_id, and no untraced URMA '
                              'entry fell in worker time range')
            else:
                reasons[i] = 'URMA fields empty: no URMA trace_id matched worker trace_id'
        else:
            reasons[i] = 'URMA fields empty: URMA logs have no trace_id and none fell in worker time range'
    return reasons


def _write_csv(sdk_entries, sdk_worker_map, worker_urma_map, client_worker_urma_map, worker_worker_urma_map,
               worker_remote_pull_map, worker_link_map, worker_query_meta_map, worker_idx_map,
               worker_urma_empty_reasons, output_path):
    headers = [
        'time', 'Operation', 'TraceId', 'TotalTime(us)', 'DataSize', 'pod_ip',
        'Client2WorkerTime(us)', 'WorkerQueryMetaTime(ms)', 'URMA_LINK(ms)', 'URMA_TOTAL(ms)',
        'ClientWorkerURMA(ms)', 'WorkerWorkerURMA(ms)', 'urma_inflight_wr_count',
        'urma_write_source', 'urma_write_dst',
        'Remarks',
    ]
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        neg_count = 0
        progress = _Progress('CSV write')
        for i, sdk in enumerate(sdk_entries):
            if i and i % PROGRESS_UPDATE_LINES == 0:
                progress.update(rows=i)
            worker = sdk_worker_map.get(i)
            client2worker = ''
            worker_query_meta = ''
            urma_link = ''
            urma_total = ''
            client_worker_urma = ''
            worker_worker_urma = ''
            urma_inflight = '0'
            urma_src = ''
            urma_dst = ''
            remarks = ''

            if worker:
                client2worker = sdk.total_time_us - worker.worker_time_us
                if client2worker < 0:
                    neg_count += 1
                    remarks = _merge_remark(
                        remarks, 'negative Client2WorkerTime: worker_time is greater than SDK total time'
                    )
                sdk_success = _is_success_status(sdk.status_code, sdk.resp_msg)
                worker_success = _is_success_status(worker.status_code, worker.resp_msg)
                if not sdk_success:
                    remarks = _format_failure_remark('SDK', sdk.status_code, sdk.resp_msg)
                elif not worker_success:
                    remarks = _format_failure_remark('Worker', worker.status_code, worker.resp_msg)
                w_idx = worker_idx_map.get(i)
                if w_idx is not None:
                    worker_query_meta = _format_optional_ms(worker_query_meta_map.get(w_idx))
                    link_ms = worker_link_map.get(w_idx)
                    urma_link = _format_link_ms(link_ms)
                    urma_list = worker_urma_map.get(w_idx)
                    client_worker_urma = _serialize_urma_elapsed(client_worker_urma_map.get(w_idx, []))
                    worker_worker_urma = _serialize_urma_elapsed(worker_worker_urma_map.get(w_idx, []))
                    if urma_list:
                        urma_total, urma_inflight, urma_src, urma_dst = _serialize_urma(urma_list)
                    else:
                        if sdk_success and worker_success:
                            urma_total = '1'
                            urma_src, urma_dst = _serialize_remote_pull_as_urma_endpoints(
                                worker_remote_pull_map.get(w_idx, [])
                            )
                        elif not remarks:
                            remarks = worker_urma_empty_reasons.get(
                                w_idx, 'URMA fields empty: no matched URMA entry for worker request'
                            )
            else:
                if not _is_success_status(sdk.status_code, sdk.resp_msg):
                    remarks = _format_failure_remark('SDK', sdk.status_code, sdk.resp_msg)

            writer.writerow([
                sdk.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f'),
                sdk.operation,
                sdk.trace_id,
                sdk.total_time_us,
                sdk.data_size,
                sdk.pod_ip,
                client2worker,
                worker_query_meta,
                urma_link,
                urma_total,
                client_worker_urma,
                worker_worker_urma,
                urma_inflight,
                urma_src,
                urma_dst,
                remarks,
            ])
        progress.done(rows=len(sdk_entries))
    if neg_count > 0:
        print(f'  WARNING: {neg_count} entries had negative Client2WorkerTime '
              f'(worker_time > sdk_total_time, measurement skew)')


def _write_worker_only_csv(worker_entries, worker_urma_map, client_worker_urma_map, worker_worker_urma_map,
                           worker_remote_pull_map, worker_link_map, worker_query_meta_map,
                           worker_urma_empty_reasons, output_path):
    headers = [
        'time', 'Operation', 'TraceId', 'TotalTime(us)', 'DataSize', 'pod_ip',
        'Client2WorkerTime(us)', 'WorkerQueryMetaTime(ms)', 'URMA_LINK(ms)', 'URMA_TOTAL(ms)',
        'ClientWorkerURMA(ms)', 'WorkerWorkerURMA(ms)', 'urma_inflight_wr_count',
        'urma_write_source', 'urma_write_dst',
        'Remarks',
    ]
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        progress = _Progress('CSV write')
        for i, w in enumerate(worker_entries):
            if i and i % PROGRESS_UPDATE_LINES == 0:
                progress.update(rows=i)
            urma_list = worker_urma_map.get(i)
            urma_total, urma_inflight, urma_src, urma_dst = _serialize_urma(urma_list or [])
            if not urma_inflight:
                urma_inflight = '0'
            worker_query_meta = _format_optional_ms(worker_query_meta_map.get(i))
            urma_link = _format_link_ms(worker_link_map.get(i))
            client_worker_urma = _serialize_urma_elapsed(client_worker_urma_map.get(i, []))
            worker_worker_urma = _serialize_urma_elapsed(worker_worker_urma_map.get(i, []))
            if not _is_success_status(w.status_code, w.resp_msg):
                remarks = _format_failure_remark('Worker', w.status_code, w.resp_msg)
            elif urma_list:
                remarks = ''
            else:
                urma_total = '1'
                urma_src, urma_dst = _serialize_remote_pull_as_urma_endpoints(worker_remote_pull_map.get(i, []))
                remarks = ''
            writer.writerow([
                w.timestamp.strftime('%Y-%m-%dT%H:%M:%S.%f'),
                'DS_POSIX_GET',
                w.trace_id,
                w.worker_time_us,
                '',
                w.pod_ip,
                '',
                worker_query_meta,
                urma_link,
                urma_total,
                client_worker_urma,
                worker_worker_urma,
                urma_inflight,
                urma_src,
                urma_dst,
                remarks,
            ])
        progress.done(rows=len(worker_entries))


def parse_cmd(args):
    if not os.path.isdir(args.input_dir):
        print(f'ERROR: Input directory not found: {args.input_dir}', file=sys.stderr)
        sys.exit(1)
    if not args.no_time_window and args.time_window <= 0:
        print('ERROR: --time-window must be a positive integer', file=sys.stderr)
        sys.exit(1)

    print(f'Parsing SDK logs from: {args.input_dir}')
    sdk_entries = _parse_sdk_logs(args.input_dir)
    print(f'  SDK Get entries: {len(sdk_entries)}')

    print('Parsing Worker access logs...')
    worker_entries = _parse_worker_access_logs(args.input_dir)
    print(f'  Worker Get entries: {len(worker_entries)}')

    print('Parsing Worker URMA logs...')
    urma_entries = _parse_worker_urma_logs(args.input_dir)
    print(f'  URMA entries: {len(urma_entries)}')
    traced_urma_entries = sum(1 for u in urma_entries if u.trace_id)
    print(f'  URMA entries with trace_id: {traced_urma_entries}/{len(urma_entries)}')

    print('Parsing Worker remote pull endpoint logs...')
    remote_pull_entries = _parse_worker_remote_pull_logs(args.input_dir)
    print(f'  Remote pull endpoint entries: {len(remote_pull_entries)}')

    print('Parsing Worker URMA link logs...')
    link_entries = _parse_worker_link_logs(args.input_dir)
    print(f'  URMA link entries: {len(link_entries)}')

    print('Parsing Worker query meta logs...')
    query_meta_entries = _parse_worker_query_meta_logs(args.input_dir)
    print(f'  Worker query meta entries: {len(query_meta_entries)}')

    print('Correlating Worker <-> URMA...')
    worker_remote_pull_map = _correlate_worker_remote_pulls(worker_entries, remote_pull_entries)
    worker_urma_map, client_worker_urma_map, worker_worker_urma_map = _correlate_worker_urma(
        worker_entries, urma_entries, worker_remote_pull_map
    )
    worker_link_map = _correlate_worker_links(worker_entries, link_entries)
    worker_query_meta_map = _correlate_worker_query_meta(worker_entries, query_meta_entries)
    worker_urma_empty_reasons = _build_worker_urma_empty_reasons(worker_entries, urma_entries, worker_urma_map)
    matched_urma = sum(1 for v in worker_urma_map.values() if v)
    print(f'  Workers with URMA: {matched_urma}/{len(worker_entries)}')
    print(f'  Workers with client-worker URMA: {len(client_worker_urma_map)}/{len(worker_entries)}')
    print(f'  Workers with worker-worker URMA: {len(worker_worker_urma_map)}/{len(worker_entries)}')
    print(f'  Workers with URMA link: {len(worker_link_map)}/{len(worker_entries)}')
    print(f'  Workers with query meta time: {len(worker_query_meta_map)}/{len(worker_entries)}')

    if sdk_entries:
        if args.no_time_window:
            print('Correlating SDK <-> Worker (traceId, no time window)...')
        else:
            print(f'Correlating SDK <-> Worker (traceId, window={args.time_window}ms)...')
        sdk_worker_map = _correlate_sdk_worker(
            sdk_entries, worker_entries, args.time_window, args.no_time_window
        )
        print(f'  Matched: {len(sdk_worker_map)}/{len(sdk_entries)}')
        _print_unmatched_sdk_samples(
            sdk_entries, worker_entries, sdk_worker_map, args.time_window, args.no_time_window
        )

        worker_to_idx = {id(w): i for i, w in enumerate(worker_entries)}
        worker_idx_map = {}
        for sdk_i, w in sdk_worker_map.items():
            worker_idx_map[sdk_i] = worker_to_idx[id(w)]

        print(f'Writing CSV to: {args.output}')
        _write_csv(
            sdk_entries, sdk_worker_map, worker_urma_map, client_worker_urma_map, worker_worker_urma_map,
            worker_remote_pull_map, worker_link_map, worker_query_meta_map, worker_idx_map, worker_urma_empty_reasons,
            args.output
        )
    else:
        print('No SDK logs found, writing Worker-only CSV...')
        _write_worker_only_csv(
            worker_entries, worker_urma_map, client_worker_urma_map, worker_worker_urma_map, worker_remote_pull_map,
            worker_link_map, worker_query_meta_map, worker_urma_empty_reasons, args.output
        )
    print('Done.')


# ===========================================================================
# PLOT module
# ===========================================================================

def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    frac = k - lo
    return values[lo] + frac * (values[hi] - values[lo])


def _parse_semicolon_values(raw: str, converter: type) -> list:
    if not raw or not raw.strip():
        return []
    result = []
    for p in raw.split(';'):
        p = p.strip()
        if p:
            try:
                result.append(converter(p))
            except ValueError:
                pass
    return result


def _parse_semicolon_floats(raw: str) -> list[float]:
    if not raw or not raw.strip():
        return []
    result = []
    for part in raw.split(';'):
        part = part.strip()
        if not part or part.startswith('<'):
            continue
        match = LEADING_FLOAT_RE.match(part)
        if not match:
            continue
        try:
            result.append(float(match.group(1)))
        except ValueError:
            continue
    return result


def _parse_semicolon_ints(raw: str) -> list[int]:
    return _parse_semicolon_values(raw, int)


class _Bucket:
    __slots__ = ('window_start', 'count', 'worker_samples', 'client_samples',
                 'query_meta_samples', 'urma_samples', 'client_worker_urma_samples',
                 'worker_worker_urma_samples', 'inflight_counts')

    def __init__(self, window_start: datetime):
        self.window_start = window_start
        self.count = 0
        self.worker_samples: list[tuple[float, str]] = []
        self.client_samples: list[tuple[float, str]] = []
        self.query_meta_samples: list[tuple[float, str]] = []
        self.urma_samples: list[tuple[float, str]] = []
        self.client_worker_urma_samples: list[tuple[float, str]] = []
        self.worker_worker_urma_samples: list[tuple[float, str]] = []
        self.inflight_counts: list[int] = []


def _read_and_bucket(csv_path: str, window_sec: int) -> dict[str, list[_Bucket]]:
    node_buckets: dict[str, dict[int, _Bucket]] = defaultdict(dict)
    progress = _Progress('CSV bucket parse')

    with open(csv_path, 'r', newline='') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return {}
        header_idx = {name.strip(): i for i, name in enumerate(header)}
        required_headers = [
            'time', 'TraceId', 'TotalTime(us)', 'pod_ip', 'Client2WorkerTime(us)',
            'URMA_TOTAL(ms)', 'urma_inflight_wr_count',
        ]
        missing_headers = [name for name in required_headers if name not in header_idx]
        if missing_headers:
            print(f'ERROR: required column(s) not found: {missing_headers}. Header: {header}', file=sys.stderr)
            sys.exit(1)
        idx_time = header_idx['time']
        idx_trace = header_idx['TraceId']
        idx_total = header_idx['TotalTime(us)']
        idx_pod = header_idx['pod_ip']
        idx_c2w = header_idx['Client2WorkerTime(us)']
        idx_query_meta = header_idx.get('WorkerQueryMetaTime(ms)')
        idx_urma = header_idx['URMA_TOTAL(ms)']
        idx_client_worker_urma = header_idx.get('ClientWorkerURMA(ms)')
        idx_worker_worker_urma = header_idx.get('WorkerWorkerURMA(ms)')
        idx_inflight = header_idx['urma_inflight_wr_count']
        required_indexes = [idx_time, idx_trace, idx_total, idx_pod, idx_c2w, idx_urma, idx_inflight]
        if idx_query_meta is not None:
            required_indexes.append(idx_query_meta)
        if idx_client_worker_urma is not None:
            required_indexes.append(idx_client_worker_urma)
        if idx_worker_worker_urma is not None:
            required_indexes.append(idx_worker_worker_urma)
        required_cols = max(required_indexes) + 1

        row_count = 0
        for row in reader:
            if len(row) < required_cols:
                continue
            row_count += 1
            if row_count % PROGRESS_UPDATE_LINES == 0:
                progress.update(rows=row_count)

            ts_str = row[idx_time].strip()
            trace_id = row[idx_trace].strip()
            total_str = row[idx_total].strip()
            pod_ip = row[idx_pod].strip()
            c2w_str = row[idx_c2w].strip()
            query_meta_str = row[idx_query_meta].strip() if idx_query_meta is not None else ''
            urma_str = row[idx_urma].strip()
            client_worker_urma_str = row[idx_client_worker_urma].strip() if idx_client_worker_urma is not None else ''
            worker_worker_urma_str = row[idx_worker_worker_urma].strip() if idx_worker_worker_urma is not None else ''
            inflight_str = row[idx_inflight].strip()

            if not ts_str or not total_str:
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
                total_us = int(total_str)
            except (ValueError, TypeError):
                continue

            bucket_key = int(ts.timestamp()) // window_sec
            bucket_start = datetime.fromtimestamp(bucket_key * window_sec)

            buckets_map = node_buckets[pod_ip]
            if bucket_key not in buckets_map:
                buckets_map[bucket_key] = _Bucket(bucket_start)
            bucket = buckets_map[bucket_key]
            bucket.count += 1

            is_sdk_row = bool(c2w_str)
            if is_sdk_row:
                try:
                    c2w_us = int(c2w_str)
                    worker_time = total_us - c2w_us
                except (ValueError, TypeError):
                    worker_time = float(total_us)
                bucket.client_samples.append((float(total_us), trace_id))
            else:
                worker_time = total_us

            bucket.worker_samples.append((float(worker_time), trace_id))

            query_meta_vals = _parse_semicolon_floats(query_meta_str)
            if query_meta_vals:
                bucket.query_meta_samples.extend((v * 1000.0, trace_id) for v in query_meta_vals)

            urma_vals = _parse_semicolon_floats(urma_str)
            if urma_vals:
                bucket.urma_samples.extend((v * 1000.0, trace_id) for v in urma_vals)

            client_worker_urma_vals = _parse_semicolon_floats(client_worker_urma_str)
            if client_worker_urma_vals:
                bucket.client_worker_urma_samples.extend((v * 1000.0, trace_id) for v in client_worker_urma_vals)

            worker_worker_urma_vals = _parse_semicolon_floats(worker_worker_urma_str)
            if worker_worker_urma_vals:
                bucket.worker_worker_urma_samples.extend((v * 1000.0, trace_id) for v in worker_worker_urma_vals)

            inflight_vals = _parse_semicolon_ints(inflight_str)
            if inflight_vals:
                bucket.inflight_counts.extend(inflight_vals)

    if row_count == 0:
        progress.done(rows=row_count)
        return {}

    result: dict[str, list[_Bucket]] = {}
    for pod_ip, buckets_map in node_buckets.items():
        result[pod_ip] = sorted(buckets_map.values(), key=lambda b: b.window_start)
    progress.done(rows=row_count)
    return result


def _percentile_with_trace(samples: list[tuple[float, str]], pct: float):
    if not samples:
        return None, ''
    sorted_samples = sorted(samples, key=lambda item: item[0])
    values = [value for value, _ in sorted_samples]
    pct_value = _percentile(values, pct)
    sample_idx = min(math.ceil((len(sorted_samples) - 1) * pct / 100.0), len(sorted_samples) - 1)
    return pct_value, sorted_samples[sample_idx][1]


def _compute_metrics(buckets: list[_Bucket], min_samples: int) -> list[dict]:
    metrics = []
    for b in buckets:
        if b.count < min_samples:
            continue
        worker_p99, worker_trace = _percentile_with_trace(b.worker_samples, 99)
        client_p99, client_trace = _percentile_with_trace(b.client_samples, 99)
        query_meta_p99, query_meta_trace = _percentile_with_trace(b.query_meta_samples, 99)
        urma_p99, urma_trace = _percentile_with_trace(b.urma_samples, 99)
        client_worker_urma_p99, client_worker_urma_trace = _percentile_with_trace(b.client_worker_urma_samples, 99)
        worker_worker_urma_p99, worker_worker_urma_trace = _percentile_with_trace(b.worker_worker_urma_samples, 99)
        m = {
            'window_start': b.window_start,
            'worker_p99': worker_p99,
            'worker_p99_trace': worker_trace,
            'client_p99': client_p99,
            'client_p99_trace': client_trace,
            'query_meta_p99': query_meta_p99,
            'query_meta_p99_trace': query_meta_trace,
            'urma_p99': urma_p99,
            'urma_p99_trace': urma_trace,
            'client_worker_urma_p99': client_worker_urma_p99,
            'client_worker_urma_p99_trace': client_worker_urma_trace,
            'worker_worker_urma_p99': worker_worker_urma_p99,
            'worker_worker_urma_p99_trace': worker_worker_urma_trace,
            'inflight_max': max(b.inflight_counts) if b.inflight_counts else None,
        }
        metrics.append(m)
    return metrics


def _write_slow_p99_trace_log(pod_ip: str, metrics: list[dict], output_dir: str) -> int:
    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f'{pod_ip}.log')
    rows = []
    metric_fields = [
        ('Total P99', 'client_p99', 'client_p99_trace'),
        ('KVC Worker P99', 'worker_p99', 'worker_p99_trace'),
        ('KVC Master P99', 'query_meta_p99', 'query_meta_p99_trace'),
        ('URMA P99', 'urma_p99', 'urma_p99_trace'),
        ('Client-Worker URMA P99', 'client_worker_urma_p99', 'client_worker_urma_p99_trace'),
        ('Worker-Worker URMA P99', 'worker_worker_urma_p99', 'worker_worker_urma_p99_trace'),
    ]
    for m in metrics:
        for metric_name, value_key, trace_key in metric_fields:
            p99_value = m.get(value_key)
            if p99_value is None or p99_value <= SLOW_P99_THRESHOLD_US:
                continue
            rows.append([
                m['window_start'].strftime('%Y-%m-%dT%H:%M:%S'),
                metric_name,
                f'{p99_value:.3f}',
                m.get(trace_key, ''),
            ])

    with open(out_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['window_start', 'metric', 'p99_us', 'trace_id'])
        writer.writerows(rows)
    return len(rows)


def _plot_node(pod_ip: str, metrics: list[dict], output_dir: str, fmt: str, dpi: int):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    times = [m['window_start'] for m in metrics]

    worker_p99 = [m['worker_p99'] for m in metrics if m['worker_p99'] is not None]
    worker_times = [m['window_start'] for m in metrics if m['worker_p99'] is not None]

    client_p99 = [m['client_p99'] for m in metrics if m['client_p99'] is not None]
    client_times = [m['window_start'] for m in metrics if m['client_p99'] is not None]

    urma_p99 = [m['urma_p99'] for m in metrics if m['urma_p99'] is not None]
    urma_times = [m['window_start'] for m in metrics if m['urma_p99'] is not None]

    client_worker_urma_p99 = [
        m['client_worker_urma_p99'] for m in metrics if m['client_worker_urma_p99'] is not None
    ]
    client_worker_urma_times = [
        m['window_start'] for m in metrics if m['client_worker_urma_p99'] is not None
    ]

    worker_worker_urma_p99 = [
        m['worker_worker_urma_p99'] for m in metrics if m['worker_worker_urma_p99'] is not None
    ]
    worker_worker_urma_times = [
        m['window_start'] for m in metrics if m['worker_worker_urma_p99'] is not None
    ]

    query_meta_p99 = [m['query_meta_p99'] for m in metrics if m['query_meta_p99'] is not None]
    query_meta_times = [m['window_start'] for m in metrics if m['query_meta_p99'] is not None]

    inflight = [m['inflight_max'] for m in metrics if m['inflight_max'] is not None]
    inflight_times = [m['window_start'] for m in metrics if m['inflight_max'] is not None]

    has_latency = bool(
        worker_p99 or client_p99 or query_meta_p99 or urma_p99
        or client_worker_urma_p99 or worker_worker_urma_p99
    )
    has_inflight = bool(inflight)
    if not has_latency and not has_inflight:
        print(f'  WARNING: No plottable data for pod IP {pod_ip}, skipping chart')
        return

    fig, ax1 = plt.subplots(figsize=(14, 6))

    if client_p99:
        ax1.plot(client_times, client_p99, 'g-s', markersize=3, linewidth=1.2, label='Total P99')
    if worker_p99:
        ax1.plot(worker_times, worker_p99, 'b-o', markersize=3, linewidth=1.2, label='KVC Worker P99')
    if query_meta_p99:
        ax1.plot(query_meta_times, query_meta_p99, 'c-d', markersize=3, linewidth=1.2, label='KVC Master P99')
    if urma_p99:
        ax1.plot(urma_times, urma_p99, 'r-^', markersize=3, linewidth=1.0, alpha=0.45, label='URMA P99')
    if client_worker_urma_p99:
        ax1.plot(client_worker_urma_times, client_worker_urma_p99, 'r-^', markersize=3, linewidth=1.3,
                 label='Client-Worker URMA P99')
    if worker_worker_urma_p99:
        ax1.plot(worker_worker_urma_times, worker_worker_urma_p99, color='orange', marker='v', markersize=3,
                 linewidth=1.3, label='Worker-Worker URMA P99')

    ax1.set_ylabel('P99 Latency (us)', color='black')
    ax1.set_ylim(bottom=0)
    ax1.tick_params(axis='y', labelcolor='black')
    ax1.grid(alpha=0.3)

    lines_right = []
    if has_inflight:
        ax2 = ax1.twinx()
        line_inf = ax2.plot(inflight_times, inflight, 'm--x', markersize=3, linewidth=1.0,
                            alpha=0.7, label='inflight_wr_count (max)')[0]
        ax2.set_ylabel('inflight_wr_count (max)', color='magenta')
        ax2.set_ylim(bottom=0)
        ax2.tick_params(axis='y', labelcolor='magenta')
        lines_right.append(line_inf)

    if times:
        span_sec = (times[-1] - times[0]).total_seconds()
        date_fmt = '%H:%M' if span_sec <= 86400 else '%m-%d %H:%M'
        fig.autofmt_xdate()
        ax1.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

    ax1.set_title(f'Get Latency P99 - Pod IP {pod_ip}')

    lines_left, labels_left = ax1.get_legend_handles_labels()
    if lines_right:
        lines_all = lines_left + lines_right
        labels_all = labels_left + [l.get_label() for l in lines_right]
    else:
        lines_all = lines_left
        labels_all = labels_left
    ax1.legend(lines_all, labels_all, loc='upper right')

    fig.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, f'latency_{pod_ip}.{fmt}')
    fig.savefig(out_path, dpi=dpi, format=fmt)
    plt.close(fig)
    print(f'  Saved: {out_path}')


def plot_cmd(args):
    if args.window <= 0:
        print('ERROR: --window must be a positive integer', file=sys.stderr)
        sys.exit(1)
    if args.min_samples < 0:
        print('ERROR: --min-samples must be non-negative', file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile(args.input):
        print(f'ERROR: Input file not found: {args.input}', file=sys.stderr)
        sys.exit(1)

    print(f'Reading CSV: {args.input}')
    print(f'  Window: {args.window}s  Min samples: {args.min_samples}')

    node_buckets = _read_and_bucket(args.input, args.window)
    if not node_buckets:
        print('WARNING: No valid rows found in CSV. Nothing to plot.')
        sys.exit(0)

    print(f'  Pod IPs: {len(node_buckets)}')

    for pod_ip in sorted(node_buckets.keys()):
        buckets = node_buckets[pod_ip]
        print(f'\nPod IP {pod_ip}: {len(buckets)} time buckets')
        metrics = _compute_metrics(buckets, args.min_samples)
        if not metrics:
            print(f'  WARNING: No buckets with >= {args.min_samples} samples, skipping')
            continue
        print(f'  Plottable buckets: {len(metrics)}')
        slow_count = _write_slow_p99_trace_log(pod_ip, metrics, args.output_dir)
        if slow_count:
            print(f'  Slow P99 trace log: {os.path.join(args.output_dir, f"{pod_ip}.log")} ({slow_count} rows)')
        _plot_node(pod_ip, metrics, args.output_dir, args.format, args.dpi)

    print('\nDone.')


# ===========================================================================
# LATENCY module
# ===========================================================================

@dataclass
class _LatencyEntry:
    timestamp: datetime
    elapsed_us: float
    handle: str
    pod_ip: str


def _resolve_log_files(inputs: list[str]) -> list[tuple[str, str]]:
    """Resolve input paths to [(file_path, pod_ip), ...].

    Accepts files or directories. For directories, walks one level looking for
    access log files and extracts pod_ip from directory name (e.g. worker_10.0.0.1 or dsworker_10.0.0.1).
    """
    _IP_PREFIXES = ('SDK_', 'dsworker_', 'worker_')

    def _extract_ip(dir_name: str) -> str:
        for prefix in _IP_PREFIXES:
            if dir_name.startswith(prefix):
                return dir_name[len(prefix):]
        return dir_name

    result = []
    for path in inputs:
        if os.path.isfile(path):
            parent = os.path.basename(os.path.dirname(path))
            result.append((path, _extract_ip(parent)))
        elif os.path.isdir(path):
            for entry in sorted(os.listdir(path)):
                child = os.path.join(path, entry)
                if os.path.isdir(child):
                    pod_ip = _extract_ip(entry)
                    for fname in sorted(os.listdir(child)):
                        fpath = os.path.join(child, fname)
                        if os.path.isfile(fpath):
                            result.append((fpath, pod_ip))
                elif os.path.isfile(child):
                    parent = os.path.basename(path)
                    result.append((child, _extract_ip(parent)))
    return result


def _parse_latency_logs(inputs: list[str], op_filter: str) -> list[_LatencyEntry]:
    entries = []
    for fpath, pod_ip in _resolve_log_files(inputs):
        with open(fpath, 'r', errors='replace') as f:
            for line in f:
                p = _parse_access_line(line)
                if not p:
                    continue
                if op_filter and p['handle'] != op_filter:
                    continue
                try:
                    elapsed = int(p['elapsed'])
                except (ValueError, TypeError):
                    continue
                entries.append(_LatencyEntry(
                    timestamp=_parse_timestamp(p['timestamp']),
                    elapsed_us=float(elapsed),
                    handle=p['handle'],
                    pod_ip=pod_ip,
                ))
    entries.sort(key=lambda e: e.timestamp)
    return entries


def _bucket_latency(entries: list[_LatencyEntry], window_sec: int) -> dict[str, dict[int, list[float]]]:
    """Group entries by (pod_ip, bucket_key) → list of elapsed_us."""
    result: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for e in entries:
        bk = int(e.timestamp.timestamp()) // window_sec
        result[e.pod_ip][bk].append(e.elapsed_us)
    return result


def _compute_latency_stats(values: list[float]) -> dict:
    """Compute avg/p90/p99/max/min for a list of latency values."""
    return {
        'avg': sum(values) / len(values),
        'p90': _percentile(values, 90),
        'p99': _percentile(values, 99),
        'max': max(values),
        'min': min(values),
        'count': len(values),
    }


def _format_us(val: float) -> str:
    if val >= 1000:
        return f'{val / 1000:.2f}ms'
    return f'{val:.0f}us'


def _plot_latency_chart(label: str, stats_series: list[dict], output_dir: str, fmt: str, dpi: int):
    """Plot avg latency curve with P90/P99/max/min annotations."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    if not stats_series:
        print(f'  WARNING: No data for {label}')
        return

    times = [s['window_start'] for s in stats_series]
    avg_vals = [s['avg'] for s in stats_series]
    p99_vals = [s['p99'] for s in stats_series]

    fig, ax = plt.subplots(figsize=(14, 6))

    # Average line
    ax.plot(times, avg_vals, 'b-o', markersize=3, linewidth=1.2, label='Avg')

    # P99 as thin dashed reference
    ax.plot(times, p99_vals, 'r--', linewidth=0.8, alpha=0.6, label='P99')

    # Annotate overall stats in a text box
    all_elapsed = []
    for s in stats_series:
        all_elapsed.extend(s['values'])
    overall = _compute_latency_stats(all_elapsed)
    stats_text = (
        f"Overall  avg={_format_us(overall['avg'])}  "
        f"P90={_format_us(overall['p90'])}  "
        f"P99={_format_us(overall['p99'])}  "
        f"max={_format_us(overall['max'])}  "
        f"min={_format_us(overall['min'])}  "
        f"n={overall['count']}"
    )

    ax.set_ylabel('Latency (us)')
    ax.grid(alpha=0.3)
    ax.legend(loc='upper left')

    if times:
        span_sec = (times[-1] - times[0]).total_seconds()
        date_fmt = '%H:%M' if span_sec <= 86400 else '%m-%d %H:%M'
        fig.autofmt_xdate()
        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

    ax.set_title(f'Latency - {label}\n{stats_text}', fontsize=11)

    fig.tight_layout()

    os.makedirs(output_dir, exist_ok=True)
    safe_label = label.replace('.', '_')
    out_path = os.path.join(output_dir, f'stats_{safe_label}.{fmt}')
    fig.savefig(out_path, dpi=dpi, format=fmt)
    plt.close(fig)
    print(f'  Saved: {out_path}')


def latency_cmd(args):
    if args.window <= 0:
        print('ERROR: --window must be a positive integer', file=sys.stderr)
        sys.exit(1)
    if not args.input:
        print('ERROR: --input is required', file=sys.stderr)
        sys.exit(1)

    # Validate input paths
    for p in args.input:
        if not os.path.exists(p):
            print(f'ERROR: Path not found: {p}', file=sys.stderr)
            sys.exit(1)

    op_filter = args.op if args.op else ''
    print(f'Parsing access logs...')
    if op_filter:
        print(f'  Filter: {op_filter}')
    entries = _parse_latency_logs(args.input, op_filter)
    if not entries:
        print('ERROR: No valid log entries found', file=sys.stderr)
        sys.exit(1)

    # Time range filtering
    start_ts = _parse_timestamp(args.start) if args.start else None
    end_ts = _parse_timestamp(args.end) if args.end else None
    if start_ts or end_ts:
        before = len(entries)
        if start_ts:
            entries = [e for e in entries if e.timestamp >= start_ts]
        if end_ts:
            entries = [e for e in entries if e.timestamp <= end_ts]
        print(f'  Time range: {args.start or "..."} ~ {args.end or "..."}')
        print(f'  Filtered: {before} → {len(entries)} entries')

    if not entries:
        print('ERROR: No entries in selected time range', file=sys.stderr)
        sys.exit(1)

    handles = set(e.handle for e in entries)
    pods = set(e.pod_ip for e in entries)
    print(f'  Entries: {len(entries)}  Handles: {handles}  Pods: {pods}')
    print(f'  Window: {args.window}s')

    bucketed = _bucket_latency(entries, args.window)

    if args.merge:
        # Merge all pods into one series
        all_buckets: dict[int, list[float]] = defaultdict(list)
        for pod_buckets in bucketed.values():
            for bk, vals in pod_buckets.items():
                all_buckets[bk].extend(vals)

        stats_series = []
        for bk in sorted(all_buckets):
            ws = datetime.fromtimestamp(bk * args.window)
            vals = all_buckets[bk]
            s = _compute_latency_stats(vals)
            s['window_start'] = ws
            s['values'] = vals
            stats_series.append(s)

        if stats_series:
            _plot_latency_chart('all', stats_series, args.output_dir, args.format, args.dpi)
    else:
        for pod_ip in sorted(bucketed):
            pod_buckets = bucketed[pod_ip]
            stats_series = []
            for bk in sorted(pod_buckets):
                ws = datetime.fromtimestamp(bk * args.window)
                vals = pod_buckets[bk]
                s = _compute_latency_stats(vals)
                s['window_start'] = ws
                s['values'] = vals
                stats_series.append(s)

            if stats_series:
                _plot_latency_chart(pod_ip, stats_series, args.output_dir, args.format, args.dpi)

    # Print summary table
    print(f'\n{"="*80}')
    print(f'{"Pod":<18} {"Avg":>10} {"P90":>10} {"P99":>10} {"Max":>10} {"Min":>10} {"Count":>8}')
    print(f'{"-"*18} {"-"*10} {"-"*10} {"-"*10} {"-"*10} {"-"*10} {"-"*8}')
    if args.merge:
        all_vals = [e.elapsed_us for e in entries]
        s = _compute_latency_stats(all_vals)
        print(f'{"all":<18} {_format_us(s["avg"]):>10} {_format_us(s["p90"]):>10} '
              f'{_format_us(s["p99"]):>10} {_format_us(s["max"]):>10} {_format_us(s["min"]):>10} '
              f'{s["count"]:>8}')
    else:
        for pod_ip in sorted(bucketed):
            vals = [v for bk_vals in bucketed[pod_ip].values() for v in bk_vals]
            s = _compute_latency_stats(vals)
            print(f'{pod_ip:<18} {_format_us(s["avg"]):>10} {_format_us(s["p90"]):>10} '
                  f'{_format_us(s["p99"]):>10} {_format_us(s["max"]):>10} {_format_us(s["min"]):>10} '
                  f'{s["count"]:>8}')
    print(f'{"="*80}')

    print('\nDone.')


# ===========================================================================
# CLI entry point
# ===========================================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog='ds_log_analyzer',
        description='DataSystem log analyzer',
    )
    subparsers = parser.add_subparsers(dest='command', help='Available subcommands')

    # --- collect ---
    p_collect = subparsers.add_parser('collect', help='Collect SDK/Worker logs from k8s')
    p_collect.add_argument('-s', '--sdk-prefix', default='^ds-sdk',
                           help='SDK pod name regex (default: ^ds-sdk)')
    p_collect.add_argument('-w', '--worker-prefix', default='^dsworker',
                           help='Worker pod name regex (default: ^dsworker)')
    p_collect.add_argument('-n', '--namespace', default='default',
                           help='Kubernetes namespace (default: default)')
    p_collect.add_argument('-o', '--output-dir', default='./collected_logs',
                           help='Output directory (default: ./collected_logs)')
    p_collect.add_argument('--sdk-log-dir', default='/root/.datasystem/logs',
                           help='Log directory inside SDK containers (default: /root/.datasystem/logs)')
    p_collect.add_argument('--worker-log-dir', default='/root/.datasystem/logs',
                           help='Log directory inside Worker containers (default: /root/.datasystem/logs)')
    p_collect.add_argument('-p', '--parallel', type=int, default=10,
                           help='Max parallel pod collections (default: 10)')

    # --- parse ---
    p_parse = subparsers.add_parser('parse', help='Parse logs to CSV with latency segments')
    p_parse.add_argument('-i', '--input-dir', required=True,
                         help='Directory produced by collect')
    p_parse.add_argument('-o', '--output', default='get_latency.csv',
                         help='Output CSV file (default: get_latency.csv)')
    p_parse.add_argument('-t', '--time-window', type=int, default=100,
                         help='Correlation time window in ms (default: 100)')
    p_parse.add_argument('--no-time-window', action='store_true',
                         help='Correlate SDK and Worker by traceId without timestamp window')

    # --- plot ---
    p_plot = subparsers.add_parser('plot', help='Generate per-node P99 latency charts')
    p_plot.add_argument('-i', '--input', required=True,
                        help='CSV file from parse')
    p_plot.add_argument('-o', '--output-dir', default='./latency_charts',
                        help='Output directory for charts')
    p_plot.add_argument('-w', '--window', type=int, default=60,
                        help='Time window in seconds for bucketing (default: 60)')
    p_plot.add_argument('--min-samples', type=int, default=10,
                        help='Minimum samples per bucket (default: 10)')
    p_plot.add_argument('--format', default='png', choices=['png', 'svg'],
                        help='Output image format')
    p_plot.add_argument('--dpi', type=int, default=150,
                        help='Image DPI (default: 150)')

    # --- latency ---
    p_lat = subparsers.add_parser('latency', help='Latency stats from access logs')
    p_lat.add_argument('-i', '--input', required=True, nargs='+',
                       help='Access log file(s) or directory(ies)')
    p_lat.add_argument('-o', '--output-dir', default='./latency_stats',
                       help='Output directory for charts')
    p_lat.add_argument('-w', '--window', type=int, default=60,
                       help='Time window in seconds (default: 60)')
    p_lat.add_argument('--op', default='',
                       help='Filter by handle name (e.g. DS_KV_CLIENT_GET)')
    p_lat.add_argument('--start', default='',
                       help='Start time (format: YYYY-MM-DDTHH:MM:SS)')
    p_lat.add_argument('--end', default='',
                       help='End time (format: YYYY-MM-DDTHH:MM:SS)')
    p_lat.add_argument('--merge', action='store_true',
                       help='Merge all pods into one chart')
    p_lat.add_argument('--format', default='png', choices=['png', 'svg'],
                       help='Output image format')
    p_lat.add_argument('--dpi', type=int, default=150,
                       help='Image DPI (default: 150)')

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    {'collect': collect_cmd, 'parse': parse_cmd, 'plot': plot_cmd,
     'latency': latency_cmd}[args.command](args)


if __name__ == '__main__':
    main()

