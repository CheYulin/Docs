# Trace Analysis Summary Report

**Date**: May 8, 2026
**Source**: `942b6006760d41899d226bb1ff4cdd22.gz` - normal_traces
**Analysis Approach**: client->worker, worker->meta, worker->worker (URMA write/wait)

---

## Directory Structure

```
2026-05-08-analysis/
├── ANALYSIS_01_client_req_framework/  # client_req_framework_us: 662-3668us
├── ANALYSIS_02_e2e_latency/          # e2e_us: 41037-83567us
├── ANALYSIS_03_framework_breakdown/  # framework_us: 40972-83486us
├── ANALYSIS_04_network_residual/     # network_residual_us: 40664-83252us
├── ANALYSIS_05_server_exec/          # server_exec_us: 1527-3685us
├── ANALYSIS_06_server_req_queue/    # server_req_queue_us: 585-3149us
└── ANALYSIS_07_server_rsp_queue/     # server_rsp_queue_us: 4084-8810us
```

---

## Executive Summary

### Key Findings

1. **Network Dominates E2E Latency (99%+)**
   - `network_residual_us` accounts for 99.4-99.8% of total end-to-end latency
   - URMA/RDMA transfers are the primary bottleneck

2. **URMA Connection Overhead (~8ms per new connection)**
   - Full connection establishment takes 7-8ms
   - Jetty creation, segment import, connection handshake

3. **Request Queue Bottlenecks on Specific Workers**
   - Worker 192.168.42.114 shows high server_req_queue (3068us)
   - Despite idle threads, requests queue

4. **Response Queue Issues on Specific Path**
   - Path 192.168.45.216 -> 192.168.219.66 shows high server_rsp_queue (4084us+)
   - Suggests network path congestion

5. **URMA Infight Write Count Variability**
   - Ranges from 1 to 10
   - High values (10) may indicate congestion

---

## Trace Flow Analysis

### Flow: Client -> Worker -> Meta -> Worker -> Worker (URMA)

```
┌─────────┐     ┌─────────────┐     ┌─────────┐
│ Client  │────>│   Worker1   │────>│  Meta   │
│         │     │ 192.168.x.x │     │ Master  │
└─────────┘     └──────┬──────┘     └─────────┘
                      │
                      │ Remote Pull (URMA)
                      ▼
               ┌─────────────┐
               │   Worker2   │
               │ 192.168.y.y │
               └──────┬──────┘
                      │
                      │ URMA Write
                      ▼
               ┌─────────────┐
               │   Worker3   │ (Target)
               │ 192.168.z.z │
               └─────────────┘
```

### Trace Example: 0c3d819d (82.7ms E2E)

| Stage | Component | Duration | Percentage |
|-------|-----------|----------|------------|
| 1 | client_req_framework | 49us | 0.06% |
| 2 | server_req_queue | 65us | 0.08% |
| 3 | server_exec | 42us | 0.05% |
| 4 | server_rsp_queue | 21us | 0.03% |
| 5 | **network_residual** | **82509us** | **99.8%** |
| 6 | client_rsp_framework | 12us | 0.01% |
| **Total** | | **82701us** | 100% |

---

## Per-Category Findings

### 1. metrics_client_req_framework (min: 662us, max: 3668us)

**Finding**: Client framework overhead is minimal. Most latency is in subsequent stages.

**Flow Patterns**:
- Worker 192.168.219.66 frequently appears as first worker
- Masters involved: 192.168.210.150, 192.168.233.88, 192.168.102.88

**Key Issue**: Trace 278d4f06 shows 1226 items in eviction list, causing ~4ms master query delay.

---

### 2. metrics_e2e (min: 41037us, max: 83567us)

**Finding**: E2E latency is **network-bound**. Focus should be on RDMA/URMA optimization.

**Latency Breakdown**:
- 0c3d819d: 82701us total, 82509us (99.8%) in network
- 776cfbc9: 83567us total, 83252us (99.6%) in network

**URMA Connection Patterns**:
| Connection Type | Overhead |
|----------------|----------|
| New Connection | ~8ms |
| Reused Connection | Minimal |

---

### 3. metrics_framework (min: 40972us, max: 83486us)

**Finding**: Server-side processing (queue + exec) is <200us combined. No server-side bottleneck.

**Breakdown**:
- client_req_framework: 49-92us
- server_req_queue: 65-97us
- server_exec: 42-58us
- server_rsp_queue: 18-24us
- network_residual: **46524-83252us (DOMINANT)**

---

### 4. metrics_network_residual (min: 40664us, max: 83252us)

**Finding**: Network transfer is the root cause of high latency.

**URMA Details**:
- Memory regions: 12GB registered per connection
- Segment import: 4 segments (6, 7, 15, 16)
- NUMA affinity: All use `useNumaAffinity:1` (optimal)

**Segment Addresses**:
```
Local:  eid 4645:4944:2500:0000:2f00:0000:3000:0000, va 281367602528256
Remote: eid 4545:4944:2000:0000:2100:0000:2200:0000, va 281362233819136
```

**Possible Causes**:
1. Cross-switch network topology
2. RDMA QP/CQ saturation
3. URMA protocol overhead
4. 8MB object size not optimal for RDMA

---

### 5. metrics_server_exec (min: 1527us, max: 3685us)

**Finding**: Server execution varies; eviction manager adds latency.

**High Exec Trace (0d34feb8)**:
- server_exec: 3654us
- Object: 8MB
- URMA wait: 3.57ms

**High Queue Trace (1051ba83)**:
- server_req_queue: 3068us
- Eviction list: 1226 items
- Despite 12 idle threads

---

### 6. metrics_server_req_queue (min: 585us, max: 3149us)

**Finding**: Worker 192.168.42.114 shows significant queueing delay.

**Root Cause**:
- Thread pool has idle threads but requests still queue
- Possible thread affinity or scheduling issues

**Pattern**:
- Traces 1051ba83, 3ec5259c both show ~3000us queue
- Z=0 in threadPool indicates no visible queue, but requests delayed

---

### 7. metrics_server_rsp_queue (min: 4084us, max: 8810us)

**Finding**: Path 192.168.45.216 -> 192.168.219.66 has high response queue latency.

**Breakdown**:
- server_req_queue: 17-19us (LOW)
- server_exec: 320us (LOW)
- **server_rsp_queue: 4084us (89%+) (VERY HIGH)**
- network_residual: 155-316us

**Root Cause**:
- Response sending is the bottleneck
- Suggests outbound network congestion or RDMA completion queue pressure

---

## Key Worker IPs Observed

| Role | IP Address |
|------|------------|
| Client/Worker | 192.168.219.66 (frequent) |
| Worker | 192.168.42.114 (high queue) |
| Worker | 192.168.45.216 (high rsp queue) |
| Worker | 192.168.102.88 |
| Worker | 192.168.182.24 |
| Worker | 192.168.215.24 |
| Worker | 192.168.235.151 |
| Master | 192.168.210.150 |
| Master | 192.168.233.88 |
| Master | 192.168.199.152 |
| Master | 192.168.215.24 |

---

## Recommendations Summary

| Priority | Issue | Recommendation |
|----------|-------|----------------|
| P0 | Network latency 99%+ | Profile RDMA stack, check network topology |
| P0 | URMA connection overhead | Implement connection pooling/caching |
| P1 | Worker 192.168.42.114 high queue | Investigate thread affinity, add threads |
| P1 | Path 192.168.45.216->219.66 high rsp_q | Check network path congestion |
| P2 | High urma_inflight_wr_count | Monitor threshold, increase QP depth |
| P2 | 8MB object size | Consider RDMA batch optimization |

---

## Conclusion

The traces reveal a **network-bound system** where distributed object cache operations are dominated by RDMA/URMA transfer times (99%+). While server-side processing is efficient (<200us), the network path and connection establishment overhead are the primary optimization targets.

**Next Steps**:
1. Profile RDMA performance on affected network paths
2. Implement URMA connection pooling
3. Investigate thread scheduling on Worker 192.168.42.114
4. Check network topology between worker pairs
