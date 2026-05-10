# Full Trace Files Index

## Trace Files

| File | Description |
|------|-------------|
| `trace1_remote_pull_slow.txt` | Remote Pull 慢 (15ms) - TraceId: 2202ec24 |
| `trace2_threadpool_queue.txt` | Worker 线程池排队 (50ms) - TraceId: c35150d0 |
| `trace3_QueryMeta_bottleneck.txt` | QueryMeta 11ms 瓶颈 - TraceId: 1b5e3e17 |

## Quick Summary

### Trace 1: Remote Pull Slow (15ms)
- **TraceId**: `2202ec24-d0a8-417e-b95b-07e675e4be70`
- **Worker**: `192.168.199.160`
- **Issue**: Remote pull cost 13.257ms, totalCost 15.560ms
- **Bottleneck**: Worker -> Data Worker (192.168.168.252) URMA link

### Trace 2: Thread Pool Queue (50ms)
- **TraceId**: `c35150d0-1e50-4c8b-8bc3-9c59187d8957`
- **Worker**: `192.168.210.131`
- **Issue**: Thread pool full, queue waiting 38ms, totalCost 50.617ms
- **Bottleneck**: System-level capacity issue, not single request

### Trace 3: QueryMeta Bottleneck (11ms)
- **TraceId**: `1b5e3e17-9657-4148-93bd-49f78846c99e`
- **Worker**: `192.168.199.160`
- **Issue**: Worker -> Master RPC stable 11ms delay
- **Bottleneck**: Master processing or network fixed overhead
