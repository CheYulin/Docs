# Analysis Report: metrics_server_exec_us (min: 1527us, max: 3685us)

## Category: Server Execution Time
This category highlights traces with significant server-side execution time.

## Trace Files Analyzed
- 0d34feb8-95f9-420a-a3ee-549bed835437
- 1051ba83-7426-457c-928e-fb2b89969728
- 3dc4a7b3-5f6b-449b-ac5f-3e741b71dc69
- 3ec5259c-b781-45cd-863a-82094d8d5543
- 815962c5-3be3-478b-b88e-764283f70401
- 836390db-3596-467e-98f8-3d12b9a11fa4
- 858e62f6-b9e6-4bc7-8f1e-9adcdbeff217
- 97704d33-d920-4566-90d2-68ad20a58430
- ae2eadca-717d-4f0c-b4fe-96259d7edd27
- bab3cc19-3b5c-4642-a737-d731174ac6f4

## Server Execution Summary

| Trace ID | server_exec_us | e2e_us | Framework Breakdown |
|----------|---------------|--------|---------------------|
| 0d34feb8 | 3654 | 7097 | req_q:109, exec:3654, rsp_q:85 |
| 1051ba83 | 1790 | 5254 | req_q:3068, exec:1790, rsp_q:146 |
| 3ec5259c | 1658 | 5108 | req_q:3025, exec:1658, rsp_q:150 |
| 836d814b | 1628 | 5066 | req_q:2955, exec:1628, rsp_q:158 |

## Detailed Trace Analysis

### Trace: 0d34feb8 (server_exec: 3654us)

**Flow:**
```
Worker 192.168.168.216 -> Worker 192.168.219.66 (UB path)
Object: kv_test_24_14_119472993788120_0 (8MB)
```

**Framework Timing:**
```
framework_us=3442
client_req_framework_us=17
remote_processing_us=7068
  server_req_queue_us=109
  server_exec_us=3654 (51.7%)
  server_rsp_queue_us=85
  network_residual_us=3218
client_rsp_framework_us=11
```

**Key Observations:**
- server_exec (3654us) is 51.7% of framework time
- This is the **highest server_exec** in this category
- network_residual (3218us) still significant at 45%

**URMA Write:**
```
URMA write: useNumaAffinity:1, src:2, dst:1, jetty id:1122, urma_inflight_wr_count:5
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 3.57ms
```

### Trace: 1051ba83 (server_exec: 1790us)

**Flow:**
```
Worker 192.168.42.114 -> Worker 192.168.219.66 (UB path)
Object: kv_test_24_6_118992864875120_0 (8MB)
```

**Framework Timing:**
```
framework_us=3463
client_req_framework_us=21
remote_processing_us=5220
  server_req_queue_us=3068 (55.5%)
  server_exec_us=1790
  server_rsp_queue_us=146
  network_residual_us=215
client_rsp_framework_us=12
```

**Key Observations:**
- server_req_queue (3068us) dominates at 55.5%
- This indicates **queueing delay** on the server
- network_residual (215us) is minimal - local transfer

**URMA Write:**
```
URMA write: useNumaAffinity:1, src:2, dst:1, jetty id:1125, urma_inflight_wr_count:2
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 1.64ms
```

## High Server Execution Root Cause

### 1. Object Size Impact
All objects in this category are 8MB (8388608 bytes). Large objects require:
- Memory allocation
- Data copying
- Memory registration for RDMA

### 2. Eviction Manager Impact
Trace 1051ba83 shows:
```
EvictionList size before evict: 1226
EvictionList size after evict: 1218
```
Eviction processing adds latency before the actual get operation.

### 3. URMA Wait Time
The `[URMA_ELAPSED_TOTAL]` log shows wait times:
- 0d34feb8: 3.57ms wait
- 1051ba83: 1.64ms wait

This indicates URMA jfc (completion queue) polling overhead.

## Comparison: server_exec vs server_req_queue

| Scenario | server_exec | server_req_queue | Issue |
|----------|------------|-----------------|-------|
| 0d34feb8 | 3654us | 109us | Execution bottleneck |
| 1051ba83 | 1790us | 3068us | Queueing bottleneck |
| 3ec5259c | 1658us | 3025us | Queueing bottleneck |

## Recommendations
1. **For execution bottlenecks**:
   - Profile object deserialization/copying
   - Check memory allocator performance
   - Consider pre-allocation pools

2. **For queueing bottlenecks**:
   - Increase server worker thread count
   - Reduce request batch sizes
   - Investigate load balancing

3. **For URMA wait**:
   - Monitor `urma_inflight_wr_count` threshold
   - Check RDMA completion queue configuration
   - Consider interrupt vs polling mode
