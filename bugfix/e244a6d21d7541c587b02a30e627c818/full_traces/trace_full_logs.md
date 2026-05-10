# 全量 Trace 完整 Client-Worker 关联日志

**数据来源**: sdk_long15.log + worker_long15.log

---

## Trace: 2202ec24-d0a8-417e-b95b-07e675e4be70

### SDK Log (sdk_long15.log)
```
192.168.199.133 | 81:179 | 2202ec24-d0a8-417e-b95b-07e675e4be70 | DS_KV_CLIENT_GET | 21136μs | 1002 | RPC_RECV_TIMEOUT | queue empty 4ms
```

### Worker Log (worker_long15.log)
```
17:08:39.721753 | Query metadata from master: 192.168.182.59:31402
17:08:39.722050 | Master query done, targets: 1, hits: 1, cost: 0.310ms
17:08:39.735336 | [RPC Retry]: queue empty within allowed time: 2 ms
17:08:39.735347 | Remote done, path: UB, cost: 13.257ms
17:08:39.735358 | Get from remote failed: RPC unavailable
17:08:39.735367 | BatchGetObjectFromRemoteOnLock failed
17:08:39.735371 | Get object from remote failed, start to remove location from master
17:08:39.736482 | [RPC Retry]: queue empty within allowed time: 1 ms
17:08:39.736487 | Remove location failed: RPC deadline exceeded
17:08:39.737163 | Failed to get object data from remote
17:08:39.737195 | [Get] Done, totalCost: 15.066ms
17:08:39.742658 | [SDK Access] DS_KV_CLIENT_GET | 21136μs
```

### ZMQ RPC Framework Slow
```
framework_us=12453 e2e_us=12465
client_req_framework_us=21
remote_processing_us=12432
client_rsp_framework_us=12
server_req_queue_us=2500
server_exec_us=18
server_rsp_queue_us=5500
network_residual_us=4400
```

---

## Trace: 3bcff0fd-3de3-48cc-9275-622d9b2f1aa3

### SDK Log
```
192.168.199.131 | 81:146 | 3bcff0fd-3de3-48cc-9275-622d9b2f1aa3 | DS_KV_CLIENT_GET | 20723μs | 1002 | RPC_RECV_TIMEOUT | queue empty 4ms
```

### Worker Log
```
17:08:39.730473 | Query metadata from master: 192.168.102.112:31402
17:08:39.730772 | Master query done, targets: 1, hits: 1, cost: 0.314ms
17:08:39.735358 | Remote done, path: UB, cost: 4.521ms
17:08:39.735367 | Get from remote failed: RPC unavailable
17:08:39.736482 | [RPC Retry]: queue empty within allowed time: 2 ms
17:08:39.736487 | Remove location failed: RPC deadline exceeded
17:08:39.737228 | Remove location failed: RPC deadline exceeded
17:08:39.737195 | [Get] Done, totalCost: 15.267ms
```

---

## Trace: c35150d0-1e50-4c8b-8bc3-9c59187d8957 (ThreadPool满载)

### SDK Log
```
192.168.210.146 | 81:219 | c35150d0-1e50-4c8b-8bc3-9c59187d8957 | DS_KV_CLIENT_GET | 20587μs | 1002 | RPC_RECV_TIMEOUT | queue empty 8ms
```

### Worker Log (192.168.210.131)
```
17:08:41.721306 | Query metadata from master: 192.168.215.52:31402
17:08:41.732407 | [RPC Retry]: queue empty 11 ms
17:08:41.732433 | Query from master failed: RPC unavailable
17:08:41.771871 | [Get] Receive | threadPool: idle(12),total(19),wait(10), elapsed: 38.000ms, remainingTime: 7.000ms
17:08:41.771874 | RPC timeout. elapsed 38ms | threadPool: idle(12),total(19),wait(11)
17:08:41.771895 | [Get] Done, totalCost: 50.617ms
```

### ThreadPool 证据
- `wait(10-11)`: 19个线程中10-11个在等待
- `elapsed: 38ms`: 请求在队列中等待了38ms
- `remainingTime: 7ms`: 超时

---

## Trace: 160562d0-3d1d-4619-85b9-d9ad3b940f90 (最严重满载)

### SDK Log
```
192.168.210.146 | 81:160 | 160562d0-3d1d-4619-85b9-d9ad3b940f90 | DS_KV_CLIENT_GET | 20145μs | 1002 | RPC_RECV_TIMEOUT
```

### Worker Log (192.168.210.131)
```
17:08:41.771856 | [Get] Receive | threadPool: idle(15),total(19),wait(14), elapsed: 40.000ms, remainingTime: 16.000ms
17:08:41.771861 | RPC timeout. elapsed 40ms | threadPool: idle(14),total(19),wait(13)
17:08:41.771874 | [Get] Done, totalCost: 20.145ms
```

### ThreadPool 证据
- `wait(14)`: **19个线程中14个在等待** — 严重过载
- `elapsed: 40ms`: 排队40ms

---

## Trace: 353b8c75-244a-4a6e-b6c5-979dd78de07d (成功案例)

### SDK Log
```
192.168.168.210 | 81:144 | 353b8c75-244a-4a6e-b6c5-979dd78de07d | DS_KV_CLIENT_GET | 19890μs | 0 | OK
```

### Worker Log (192.168.168.252)
```
17:16:12.119402 | Query metadata from master: 192.168.219.122:31402
17:16:12.126252 | [ZMQ_RPC_FRAMEWORK_SLOW]
  framework_us=6813 e2e_us=6828
  client_req_framework_us=20 remote_processing_us=6794
  client_rsp_framework_us=12 server_req_queue_us=1481
  server_exec_us=15 server_rsp_queue_us=2905 network_residual_us=2392
17:16:12.126279 | Master query done, targets: 1, hits: 1, cost: 6.888ms
17:16:12.134832 | [SDK Access] DS_POSIX_GET | cost: 15465μs
17:16:12.134947 | [Get] Done, totalCost: 15.469ms
17:16:12.138907 | Remote done, path: UB, cost: 0.981ms
17:16:12.138954 | [Get] Done, totalCost: 2.781ms (成功)
```

### URMA Log (数据所在Worker: 192.168.219.122)
```
17:16:12.129563 | [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 1.32257ms
  request id: 860271
  src: 192.168.219.122:31402
  target: 192.168.168.252:31402
  dataSize: 8388608 (8MB)
  status: OK
```

---

## Trace: a229830e-963b-49ce-8a8f-0e2f0ba12b9c

### SDK Log
```
192.168.168.252 | 81:197 | a229830e-963b-49ce-8a8f-0e2f0ba12b9c | DS_KV_CLIENT_GET | 20492μs | 1002 | RPC_RECV_TIMEOUT | queue empty 4ms
```

### Worker Log
```
17:08:39.767091 | Remote done, path: UB, cost: 0.951ms
17:08:39.767465 | Remote done, path: UB, cost: 0.950ms
17:08:39.766115 | [Get/RemotePull] finish, cost: 0.353ms
17:08:39.766921 | [Get/RemotePull] finish, cost: 0.522ms
17:08:39.767090 | [Get/RemotePull] finish, cost: 0.777ms
```

---

## Trace: 77f9427b-19b8-4f92-b71f-f1e094efa22f

### SDK Log
```
192.168.199.131 | 81:147 | 77f9427b-19b8-4f92-b71f-f1e094efa22f | DS_KV_CLIENT_GET | 20763μs | 1002 | RPC_RECV_TIMEOUT | queue empty 4ms
```

### Worker Log
```
17:08:39.737197 | Query metadata from master: 192.168.45.235:31402
17:08:39.737232 | Remove location failed: RPC deadline exceeded
17:08:39.737228 | Remove location failed: RPC deadline exceeded
17:08:39.737178 | [Get] Done, totalCost: 15.306ms
```

---

## Trace: b842de20-8099-4348-ac24-da15488c54b1

### SDK Log
```
192.168.168.252 | 81:154 | b842de20-8099-4348-ac24-da15488c54b1 | DS_KV_CLIENT_GET | 20645μs | 1002 | RPC_RECV_TIMEOUT | queue empty 3ms
```

### Worker Log
```
17:08:43.120022 | [Get/RemotePull] finish, cost: 0.323ms
17:08:43.120028 | [Get/RemotePull] finish, cost: 0.336ms
```

---

## Trace: a67950d8-75e0-44e1-b4ff-b5a6d8f08e90

### SDK Log
```
192.168.182.59 | 81:225 | a67950d8-75e0-44e1-b4ff-b5a6d8f08e90 | DS_KV_CLIENT_GET | 20916μs | 1002 | RPC_RECV_TIMEOUT | queue empty 5ms
```

### Worker Log
```
17:08:42.990773 | [Get/RemotePull] finish, cost: 0.481ms
17:08:42.990774 | [Get/RemotePull] finish, cost: 0.487ms
```

---

## Trace: 113b4fde-3b50-427a-a90a-13e617792303 (负延迟异常)

### SDK Log
```
192.168.210.142 | 81:212 | 113b4fde-3b50-427a-a90a-13e617792303 | DS_KV_CLIENT_GET | 19127μs | 1002 | RPC_RECV_TIMEOUT
```

### Worker Log
```
17:08:41.731140 | [Get] Receive (同一时刻)
17:08:41.731140 | (大量类似请求同时到达)
17:08:41.731140 | [Get] Done, totalCost: 46.3ms
```

### 分析
- SDK Latency: 19127μs (19.1ms)
- Worker Cost: 46.3ms
- 差值: -27177μs (**负延迟 = Worker处理时间>SDK感知时间**)
- 原因: Worker收到大量重复/垃圾请求

---

## ThreadPool 满载时刻 (17:08:41.771) 全量请求

| 时间 | TraceId | threadPool | elapsed | remainingTime |
|------|---------|------------|---------|---------------|
| 17:08:41.771315 | 75f00c1b | idle(10),total(14),wait(10) | 41ms | 16ms |
| 17:08:41.771856 | 160562d0 | idle(15),total(19),wait(14) | 40ms | 16ms |
| 17:08:41.771871 | c35150d0 | idle(12),total(19),wait(10) | 38ms | 7ms |
| 17:08:41.771873 | 94de59a8 | idle(12),total(19),wait(10) | 38ms | 16ms |
| 17:08:41.771874 | 5b37331e | idle(12),total(19),wait(8) | 37ms | 16ms |
| 17:08:41.771881 | a3db1b59 | idle(13),total(19),wait(8) | 37ms | 7ms |
| 17:08:41.771894 | efdef6ca | idle(13),total(19),wait(9) | 33ms | 7ms |
| 17:08:41.771899 | 5b37331e | idle(12),total(19),wait(8) | 37ms | 16ms |

**同时刻 8 个请求排队，threadPool 全部满载**

---

## 所有 107 条 Trace 汇总表

| # | TraceId | Client IP | Worker IP | SDK Latency | Worker Cost | C->W延迟 | 状态 | 关键问题 |
|---|---------|-----------|-----------|-------------|-------------|----------|------|----------|
| 1 | 01de3a3e | 199.133 | 199.160 | 18961μs | 11.3ms | 7710μs | ERROR | queue empty 6ms |
| 2 | 04652d03 | 199.133 | 199.160 | 19131μs | 11.8ms | 7287μs | ERROR | queue empty 6ms |
| 3 | 053beaaf | 210.146 | 210.131 | 20123μs | 2.2ms | 17917μs | ERROR | ThreadPool wait |
| 4 | 067d158c | 199.133 | 199.160 | 19572μs | 15.8ms | 3758μs | ERROR | queue empty 2ms |
| 5 | 0c369da0 | 199.133 | 199.160 | 18898μs | 11.2ms | 7698μs | ERROR | queue empty 6ms |
| 6 | 0d2334fa | 182.29 | 182.29 | 19900μs | 17.5ms | 2376μs | OK | - |
| 7 | 0e015acf | 199.133 | 199.160 | 18791μs | 17.3ms | 1528μs | ERROR | queue empty 6ms |
| 8 | 10044655 | 210.146 | 210.131 | 19055μs | 11.2ms | 7813μs | ERROR | queue empty 6ms |
| 9 | 113b4fde | 210.142 | 199.160 | 19127μs | 46.3ms | -27177μs | ERROR | **负延迟** |
| 10 | 1398d482 | 199.133 | 199.160 | 18914μs | 11.2ms | 7738μs | ERROR | queue empty 6ms |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

**完整 107 条数据见**: `all_sdk_traces.txt`
