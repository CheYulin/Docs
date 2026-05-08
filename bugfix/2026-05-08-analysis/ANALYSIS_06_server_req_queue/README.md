# Analysis Report: metrics_server_req_queue_us (min: 585us, max: 3149us)

## Category: Server Request Queue Latency
This category highlights traces where requests spend significant time in the server queue before processing.

## Trace Files Analyzed
- 1051ba83-7426-457c-928e-fb2b89969728
- 19056d9b-11ba-427b-8825-e9993df1c40a
- 3ec5259c-b781-45cd-863a-82094d8d5543
- 66f01f6c-8962-4a24-832a-5e199f08e18c
- 836d814b-8aa6-43fd-a70c-c1a1c5d75c62
- b5087fb5-2808-4c53-a3d3-11e1e3fb8dd3
- c47aad6c-f325-4ebd-b898-17234605e7f0
- e75f3612-9ec8-4128-9964-7dc3b7912ed4
- e940d2dc-acad-4be6-b68b-2b1488b6cb1c

## Server Request Queue Summary

| Trace ID | server_req_queue_us | e2e_us |占比 | Dominant Factor |
|----------|-------------------|--------|-----|-----------------|
| 1051ba83 | 3068 | 5254 | 58.4% | server_req_queue |
| 3ec5259c | 3025 | 5108 | 59.2% | server_req_queue |
| 66f01f6c | 2932 | 4942 | 59.3% | server_req_queue |

## Detailed Trace Analysis

### Trace: 1051ba83 (server_req_queue: 3068us)

**Flow:**
```
Client -> Worker 192.168.42.114 -> Worker 192.168.219.66
Object: kv_test_24_6_118992864875120_0
```

**Framework Timing:**
```
framework_us=3463
client_req_framework_us=21
remote_processing_us=5220
  server_req_queue_us=3068 (55.5%) <-- HIGH
  server_exec_us=1790
  server_rsp_queue_us=146
  network_residual_us=215
client_rsp_framework_us=12
```

**Thread Pool Status:**
```
threadPool: idle(12), total(17), wait(0)
```
Note: Some threads idle, but requests still queued - indicates thread affinity or scheduling issues.

**Master Query:**
```
Query metadata from master: 192.168.215.24:31402
Master query cost: 0.364ms
```

### Trace: 3ec5259c (server_req_queue: 3025us)

**Flow:**
```
Client -> Worker 192.168.42.114 -> Worker 192.168.219.66
Object: kv_test_24_6_118992864875120_0
```

**Framework Timing:**
```
framework_us=3465
client_req_framework_us=19
remote_processing_us=5108
  server_req_queue_us=3025 (59.2%) <-- HIGH
  server_exec_us=1658
  server_rsp_queue_us=148
  network_residual_us=276
client_rsp_framework_us=13
```

**Thread Pool Status:**
```
threadPool: idle(12), total(17), wait(0)
```

## Root Cause Analysis

### Why High server_req_queue?

1. **Thread Pool Saturation**
   - Despite 12 idle threads, requests queue
   - Possible cause: Thread affinity to specific CPU cores
   - Check: `threadPool: idle(X), total(Y), wait(Z)` - Z=0 means no queued requests visible

2. **Work Distribution Imbalance**
   - Multiple traces show same pattern: high req_queue on 192.168.42.114
   - Indicates this worker may be handling disproportionate load

3. **Cross-Worker Coordination Delay**
   - Some requests wait for responses from other workers before processing next

## Request Flow Pattern

For trace 1051ba83:

```
14:33:41.466222 - Worker 192.168.42.114 receives request
14:33:41.466583 - Master query initiated
14:33:41.471914 - ZMQ_RPC_FRAMEWORK_SLOW logged
                  (server_req_queue=3068us)
14:33:41.471966 - Request processing completes
```

**Timeline:**
- T+0us: Request received
- T+3068us: Request starts processing (after queue)
- T+3068+1790=4858us: Processing complete
- T+3068+1790+146=5004us: Response queued

## Comparison: High vs Low Queue Latency

| Trace | server_req_queue | server_exec | network_residual | Pattern |
|-------|-----------------|-------------|-----------------|---------|
| 1051ba83 | 3068us | 1790us | 215us | Queue-bound |
| 0d34feb8 | 109us | 3654us | 3218us | Exec+Network bound |

## Worker Distribution

Traces in this category primarily involve:
- Worker 192.168.42.114 (source)
- Worker 192.168.219.66 (target)

Both workers show high queue latency, suggesting system-level contention.

## Recommendations

1. **Investigate Thread Affinity**
   - Check if threads are pinned to specific cores
   - Consider relaxing affinity for better scheduling

2. **Load Balancing Review**
   - Worker 192.168.42.114 appears in multiple high-queue traces
   - Review request distribution algorithm

3. **Queue Monitoring**
   - Add alerts when server_req_queue exceeds threshold (e.g., >1000us)
   - Track queue depth over time

4. **Worker Scaling**
   - Consider adding more worker threads on 192.168.42.114
   - Or offload some work to other workers
