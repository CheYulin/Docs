# Analysis Report: metrics_network_residual_us (min: 40664us, max: 83252us)

## Category: Network Residual Latency
This category highlights traces where network transfer is the dominant bottleneck.

## Trace Files Analyzed
- 0c3d819d-c27b-4763-903e-82188ffde287
- 2e978f3e-275f-442d-9759-7a00dabb01b4
- 60d94932-a08e-43c5-947f-53cab3643bce
- 69608f19-b0c0-4b32-95b8-4b8b073412ab
- 776cfbc9-aa2f-4cfb-b912-4ce38b0d6f7a
- d727461e-d766-4fb5-9909-38ec06f46d40
- dd8c1021-1cfb-40bf-9e48-71869843b4f1
- e5b5dcad-6f6f-4242-92d4-b609170de512
- e82d89aa-e649-4b77-9379-8a074b590236

## Network Residual Summary

| Trace ID | network_residual_us | e2e_us |占比 |
|----------|-------------------|--------|-----|
| 0c3d819d | 82509 | 82701 | 99.8% |
| 2e978f3e | 66550 | 66768 | 99.7% |
| 69608f19 | 46524 | 46800 | 99.4% |
| 776cfbc9 | 83252 | 83567 | 99.6% |

## URMA Transfer Analysis

### Trace: 0c3d819d (network: 82509us = 82.5ms)

**URMA Connection Setup:**
```
14:28:30.137018 - WorkerWorkerExchangeUrmaConnectInfo start
14:28:30.139174 - Import target jetty elapsed = 1.86ms
14:28:30.140276 - WorkerWorkerExchangeUrmaConnectInfo finish, elapsed = 3.26ms
```

**URMA Write:**
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1029
Remote get success, elapsed 92.531 ms
```

**Key URMA Metrics:**
- Jetty ID: 1029 (RECV type)
- NUMA affinity: src:1, dst:1 (optimal same-NUMA)
- Connection: 192.168.102.88 <-> 192.168.42.114

### Trace: 2e978f3e (network: 66550us = 66.5ms)

**URMA Connection Setup:**
```
14:28:30.188019 - WorkerWorkerExchangeUrmaConnectInfo start
14:28:30.190354 - Import target jetty elapsed = 2.01ms
14:28:30.191658 - WorkerWorkerExchangeUrmaConnectInfo finish, elapsed = 3.64ms
```

**URMA Write:**
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1033
Remote get success, elapsed 76.419 ms
```

### Trace: 69608f19 (network: 46524us = 46.5ms)

**URMA Connection Setup:**
```
14:28:55.421368 - Doing URMA connect info exchange
14:28:55.423758 - Import target jetty elapsed = 2.11ms
14:28:55.424976 - WorkerWorkerExchangeUrmaConnectInfo finish, elapsed = 3.62ms
```

**URMA Write:**
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1095
Remote get success, elapsed 58.436 ms
```

## URMA Segment Import Details

All traces show similar segment import patterns:

### Source Worker (Sending)
```
Import seg [6]: 0000:0000:0001:c060:0010:0000:dfdf:0906 <- 0000:0000:0000:0060:0010:0000:dfdf:07c6
Import seg [7]: 0000:0000:0001:c060:0010:0000:dfdf:0907 <- 0000:0000:0000:0060:0010:0000:dfdf:07c7
Import seg [15]: 0000:0000:0001:c060:0010:0000:dfdf:0926 <- 0000:0000:0000:0060:0010:0000:dfdf:07e6
Import seg [16]: 0000:0000:0001:c060:0010:0000:dfdf:0927 <- 0000:0000:0000:0060:0010:0000:dfdf:07e7
```

### Target Worker (Receiving)
```
Import seg [6]: 0000:0000:0000:0060:0010:0000:dfdf:07c6 <- 0000:0000:0001:c060:0010:0000:dfdf:0906
Import seg [7]: 0000:0000:0000:0060:0010:0000:dfdf:07c7 <- 0000:0000:0001:c060:0010:0000:dfdf:0907
Import seg [15]: 0000:0000:0000:0060:0010:0000:dfdf:07e6 <- 0000:0000:0001:c060:0010:0000:dfdf:0926
Import seg [16]: 0000:0000:0000:0060:0010:0000:dfdf:07e7 <- 0000:0000:0001:c060:0010:0000:dfdf:0927
```

## Memory Region Info

### Local Segment Info
```
ubva: { eid: 4645:4944:2500:0000:2f00:0000:3000:0000, uasid: 0, va: 281367602528256}
len: 12884901888 (12GB)
attr: 449
token_id: 0
```

### Remote Segment Info
```
ubva: { eid: 4545:4944:2000:0000:2100:0000:2200:0000, uasid: 0, va: 281362233819136}
len: 12884901888 (12GB)
attr: 449
token_id: 0
```

## Key Findings

### 1. Network Dominance
network_residual_us accounts for **99.4-99.8%** of total E2E latency.

### 2. URMA Connection Overhead
- Connection establishment: ~3-4ms
- Segment import: ~2ms
- **Total connection overhead: ~7-8ms per new connection**

### 3. NUMA Affinity
All transfers use `useNumaAffinity:1` with matching src/dst NUMA nodes, which is optimal.

### 4. Memory Region Size
12GB registered memory regions are being used for RDMA transfers.

## Root Cause: Why is network_residual so high?

Possible reasons:
1. **Distance between hosts**: Cross-switch/network topology
2. **RDMA QP saturation**: Limited concurrent operations
3. **Memory registration overhead**: Each transfer requires registered memory
4. **URMA protocol overhead**: Higher-level protocol wrapping RDMA
5. **Packet size**: 8MB object size may not be optimal for RDMA

## Recommendations
1. **Pre-establish URMA connections**: Avoid 7-8ms connection overhead
2. **Tune RDMA parameters**: Check CQ size, QP depth
3. **Verify network path**: Check for cross-switch routing
4. **Consider pipeline batching**: Overlap connection setup with data transfer
5. **Profile at RDMA level**: Use perf or rdma stats to identify specific bottleneck
