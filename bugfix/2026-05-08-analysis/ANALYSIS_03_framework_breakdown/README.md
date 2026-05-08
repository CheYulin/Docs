# Analysis Report: metrics_framework_us (min: 40972us, max: 83486us)

## Category: Framework Latency Breakdown
This category provides detailed framework timing breakdowns for each trace.

## Trace Files Analyzed
- d727461e-d766-4fb5-9909-38ec06f46d40
- 0c3d819d-c27b-4763-903e-82188ffde287
- 2e978f3e-275f-442d-9759-7a00dabb01b4
- e5b5dcad-6f6f-4242-92d4-b609170de512
- dd8c1021-1cfb-40bf-9e48-71869843b4f1
- 69608f19-b0c0-4b32-95b8-4b8b073412ab
- e82d89aa-e649-4b77-9379-8a074b590236
- 776cfbc9-aa2f-4cfb-b912-4ce38b0d6f7a

## Framework Timing Breakdown

| Trace ID | framework_us | client_req | remote_proc | client_rsp | req_q | exec | rsp_q | network |
|----------|-------------|------------|-------------|------------|-------|------|-------|---------|
| 0c3d819d | 82658 | 49 | 82639 | 12 | 65 | 42 | 21 | 82509 |
| 2e978f3e | 66720 | 50 | 66701 | 16 | 84 | 47 | 18 | 66550 |
| 69608f19 | 46745 | 92 | 46695 | 12 | 97 | 54 | 18 | 46524 |
| 776cfbc9 | 83486 | 53 | 83405 | 16 | 90 | 58 | 24 | 83252 |

## Timing Breakdown Analysis

### 1. client_req_framework_us
Time for client to prepare and send request.
- Range: 49-92us
- All traces show healthy client-side latency (<100us)

### 2. client_rsp_framework_us
Time for client to receive and process response.
- Range: 12-16us
- Excellent client response handling

### 3. server_req_queue_us
Time request spends in server queue before processing.
- Range: 65-97us
- Acceptable queue latency

### 4. server_exec_us
Actual server-side execution time.
- Range: 42-58us
- Efficient execution

### 5. server_rsp_queue_us
Time response spends in server outbound queue.
- Range: 18-24us
- Healthy response queue latency

### 6. network_residual_us (DOMINANT)
Time spent in network transfer - **accounts for 99%+ of total latency**.
- Range: 46524-83252us (46-83ms)
- **This is the primary performance bottleneck**

## Per-Trace Analysis

### Trace: 0c3d819d (framework: 82658us)
```
client_req_framework_us=49
remote_processing_us=82639
  server_req_queue_us=65
  server_exec_us=42
  server_rsp_queue_us=21
  network_residual_us=82509 (99.8%)
client_rsp_framework_us=12
```
**Observation**: network_residual dominates at 99.8%

### Trace: 2e978f3e (framework: 66720us)
```
client_req_framework_us=50
remote_processing_us=66701
  server_req_queue_us=84
  server_exec_us=47
  server_rsp_queue_us=18
  network_residual_us=66550 (99.7%)
client_rsp_framework_us=16
```
**Observation**: network_residual dominates at 99.7%

### Trace: 69608f19 (framework: 46745us)
```
client_req_framework_us=92
remote_processing_us=46695
  server_req_queue_us=97
  server_exec_us=54
  server_rsp_queue_us=18
  network_residual_us=46524 (99.5%)
client_rsp_framework_us=12
```
**Observation**: network_residual dominates at 99.5%

### Trace: 776cfbc9 (framework: 83486us)
```
client_req_framework_us=53
remote_processing_us=83405
  server_req_queue_us=90
  server_exec_us=58
  server_rsp_queue_us=24
  network_residual_us=83252 (99.7%)
client_rsp_framework_us=16
```
**Observation**: Highest latency, network_residual at 99.7%

## Conclusion

The framework breakdown confirms:
1. All server-side processing (queue + exec) is <200us combined
2. Network transfer dominates at 99%+ of total time
3. Client framework overhead is negligible (<100us)
4. **Focus optimization efforts on network layer**

## Recommendations
1. Profile network_residual at the RDMA/URMA level
2. Check for packet loss, retransmissions
3. Verify MTU settings and network path
4. Consider larger batch sizes to amortize network overhead
