# Analysis Report: metrics_client_req_framework (min: 662us, max: 3668us)

## Category: client_req_framework
This category captures the time spent in the client-side request framework processing.

## Trace Files Analyzed
- 0082e75d-983f-413c-a238-8cc7b20b61d5
- 1402f5f1-5a2c-47f1-8536-dff297446f9d
- 278d4f06-04e4-45f4-9ca2-b73c837b66fe
- 30e43339-32ea-4c82-b0d0-7cb6c0a092fe
- 2fd8e0c7-671e-4a1b-b9fb-47db0f4808ed
- de7e919b-9586-400b-a39c-c2d9fca16017
- c5cca999-8425-47a5-8e43-f5f71b709373
- cccd1dea-f114-4825-bf6b-215447645388
- f50308a6-92b2-4895-8426-247b3a58326f

## Flow Analysis

### 1. Client -> Worker Flow
The client sends requests to worker nodes. Key metrics observed:

| Trace ID | client_req_framework_us | e2e_us | Path |
|----------|------------------------|--------|------|
| 1402f5f1 | 2510 | 3985 | Worker(192.168.219.66) -> Master(192.168.210.150) |
| 30e43339 | 3529 | 5799 | Worker(192.168.219.66) -> Master(192.168.233.88) |
| 0082e75d | 1473 | 6768 | Worker(192.168.219.66) -> Master(192.168.210.150) |
| 278d4f06 | 3668 | 3930 | Worker(192.168.219.66) -> Master(192.168.102.88) |

### 2. Worker1 -> Meta Flow
Worker queries metadata from master node:

| Trace ID | Master IP | Query Cost | Object |
|----------|----------|------------|--------|
| 1402f5f1 | 192.168.210.150 | 0.575ms | kv_test_10_15_119383349847360_0 |
| 30e43339 | 192.168.233.88 | 5.874ms | kv_test_16_7_119043661125460_0 |
| 0082e75d | 192.168.210.150 | 6.837ms | kv_test_10_0_119023240872170_0 |
| 278d4f06 | 192.168.102.88 | 3.991ms | kv_test_6_8_119261860612510_0 |

### 3. Worker1 -> Worker2 (URMA) Flow
Worker initiates remote pull via URMA:

| Trace ID | Source Worker | Target Worker | URMA write | Object Size |
|----------|---------------|--------------|------------|-------------|
| 1402f5f1 | 192.168.219.66 | 192.168.45.216 | jetty id:1093 | 8388608 |
| 30e43339 | 192.168.219.66 | 192.168.182.24 | jetty id:1039 | 8388608 |
| 0082e75d | 192.168.219.66 | 192.168.45.216 | jetty id:1093 | 8388608 |
| 278d4f06 | 192.168.219.66 | 192.168.215.24 | jetty id:1097 | 8388608 |

### 4. Target Worker: URMA Write + Wait

#### Trace: 1402f5f1
```
URMA write: useNumaAffinity:1, src:1, dst:2, jetty id:1093, urma_inflight_wr_count:1
```
- Source NUMA: 1, Dest NUMA: 2
- inflight_wr_count: 1 (moderate load)

#### Trace: 30e43339
```
URMA write: useNumaAffinity:1, src:1, dst:2, jetty id:1039, urma_inflight_wr_count:1
```
- Source NUMA: 1, Dest NUMA: 2
- inflight_wr_count: 1 (moderate load)

#### Trace: 0082e75d
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1093, urma_inflight_wr_count:10
```
- Source NUMA: 1, Dest NUMA: 1 (same NUMA)
- inflight_wr_count: 10 (HIGH - potential bottleneck)

#### Trace: 278d4f06
```
URMA write: useNumaAffinity:1, src:2, dst:2, jetty id:1097, urma_inflight_wr_count:1
```
- Source NUMA: 2, Dest NUMA: 2 (same NUMA)
- inflight_wr_count: 1 (low load)

## Key Findings

### 1. Client Request Framework Latency
- Range: 662us - 3668us
- High variability indicates network or processing variance

### 2. Eviction Impact
Trace 278d4f06 shows eviction activity with 1226 items in eviction list, taking ~4ms for master query. This adds latency to the overall request.

### 3. URMA Connection Reuse
Trace 0082e75d shows `urma_inflight_wr_count:10` indicating the URMA connection is heavily loaded, which may cause queuing delays.

### 4. NUMA Affinity
All URMA writes use useNumaAffinity:1, leveraging NUMA-aware placement for optimal performance.

## Recommendations
1. Monitor `urma_inflight_wr_count` threshold - values > 10 may indicate congestion
2. Eviction manager processing on 192.168.219.66 takes ~4ms - consider optimization
3. Master query times vary (0.3ms - 6.8ms) - investigate metadata service latency
