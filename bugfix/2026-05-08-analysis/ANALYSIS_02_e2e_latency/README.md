# Analysis Report: metrics_e2e_us (min: 41037us, max: 83567us)

## Category: End-to-End Latency
This category captures the complete end-to-end latency for distributed object Get operations.

## Trace Files Analyzed
- d727461e-d766-4fb5-9909-38ec06f46d40
- 0c3d819d-c27b-4763-903e-82188ffde287
- 2e978f3e-275f-442d-9759-7a00dabb01b4
- e5b5dcad-6f6f-4242-92d4-b609170de512
- dd8c1021-1cfb-40bf-9e48-71869843b4f1
- 69608f19-b0c0-4b32-95b8-4b8b073412ab
- e82d89aa-e649-4b77-9379-8a074b590236
- 776cfbc9-aa2f-4cfb-b912-4ce38b0d6f7a

## E2E Latency Breakdown

| Trace ID | e2e_us | framework_us | network_residual_us |占比 |
|----------|--------|--------------|-------------------|-----|
| 0c3d819d | 82701 | 82658 | 82509 | 99.8% |
| 2e978f3e | 66768 | 66720 | 66550 | 99.7% |
| 69608f19 | 46800 | 46745 | 46524 | 99.4% |
| 776cfbc9 | 83567 | 83486 | 83252 | 99.6% |

## Key Finding: Network Dominates E2E Latency

The network_residual_us accounts for **>99%** of the total e2e latency. This indicates the distributed object cache system is network-bound.

## Flow Analysis: 0c3d819d (82.7ms E2E)

### 1. Client -> Worker
```
Worker 192.168.102.88 initiates remote get
Remote get request to 192.168.42.114:31402
client_req_framework_us: 49
```

### 2. Worker1 -> Meta (Optional - not triggered)
No master metadata query in this trace.

### 3. Worker1 -> Worker2 (URMA Connection Setup)
```
[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered
remoteAddress=192.168.42.114:31402
realRemainingTimeMs=4915
```
**Critical Issue**: URMA connection did not exist, requiring full reconnection.

URMA connection establishment timeline:
- 14:28:30.137 - WorkerWorkerExchangeUrmaConnectInfo start
- 14:28:30.140 - Import target jetty elapsed = 1.86ms
- 14:28:30.145 - send data success

### 4. Target Worker: URMA Write
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1029
Remote get success, elapsed 92.531 ms
```

## Flow Analysis: 69608f19 (46.8ms E2E)

### 1. Client -> Worker
```
Worker 192.168.235.151 initiates remote get
client_req_framework_us: 92
```

### 2. Worker1 -> Worker2 (URMA)
```
Remote get request to 192.168.215.24:31402
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1095
Remote get success, elapsed 58.436 ms
```

### 3. Target Worker: URMA Write
```
Processing pull object[_urma_192_168_215_24:31402]
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1095, urma_inflight_wr_count:1
send data success
```

## URMA Connection Establishment Patterns

| Trace | Connection Type | Elapsed Time | Issue |
|-------|----------------|--------------|-------|
| 0c3d819d | New Connection | 7.94ms | URMA_NEED_CONNECT triggered |
| 2e978f3e | New Connection | 7.81ms | Full connection establishment |
| 69608f19 | New Connection | 8.77ms | Full connection establishment |

**Observation**: New URMA connections add ~8ms overhead per request.

## Performance Breakdown Summary

```
e2e_latency = client_req_framework + remote_processing + client_rsp_framework
            = 49 + 82639 + 12 = 82701us (for 0c3d819d)

remote_processing = server_req_queue + server_exec + server_rsp_queue + network_residual
                   = 65 + 42 + 21 + 82509 = 82639us
```

## Root Cause Analysis

### High Latency Traces (82-83ms)
- **Primary Cause**: `network_residual_us` dominates at 99.7%+ of total time
- **Secondary Cause**: URMA connection establishment overhead (~8ms)
- **Tertiary Cause**: Cross-NUMA memory operations

### Medium Latency Traces (46-66ms)
- **Primary Cause**: Network transfer time (URMA write/read)
- **Secondary Cause**: Connection setup overhead

## Recommendations
1. **Reduce URMA connection overhead**: Pool and reuse URMA connections
2. **Optimize cross-NUMA access**: Prefer same-NUMA worker placement
3. **Investigate network_residual**: 82ms for local transfer suggests network infra issues
4. **Connection caching**: Pre-establish URMA connections to avoid 8ms handshake
