# Trace: 12012-c642fb0d-b9ad-4f01-b385-fc2fb2dbad71

## 指标汇总

| 指标 | 值 |
|------|-----|
| QueryMeta (worker1->meta) | 5 ms |
| ProcessGetObjectRequest | 11 ms |
| URMA Wait (最大) | 0.26 ms |
| 节点 | 192.168.102.103, 192.168.168.230, 192.168.219.108 |
| 错误 | None |

## 全量日志

```
worker_192.168.102.103/datasystem_worker.INFO.20260507055454_003.log.gz:1297073:2026-05-07T05:54:41.658499 | I | worker_worker_oc_service_impl.cpp:693 | 192.168.102.103 | 11:408 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get/RemotePull] Receive, count: 1, remainingTime: 10ms, src=192.168.219.108:31402, dst=192.168.102.103:31402
worker_192.168.102.103/datasystem_worker.INFO.20260507055454_003.log.gz:1297075:2026-05-07T05:54:41.658510 | I | worker_worker_oc_service_impl.cpp:196 | 192.168.102.103 | 11:408 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  Processing pull object[kv_test_17_7_87811698213570_0] offset[0] size[8388608], src=192.168.219.108:31402, dst=192.168.102.103:31402
worker_192.168.102.103/datasystem_worker.INFO.20260507055454_003.log.gz:1297079:2026-05-07T05:54:41.658522 | I | urma_manager.cpp:1299 | 192.168.102.103 | 11:408 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  URMA write useNumaAffinity:1, src:2, dst:1, jetty id:1066, urma_inflight_wr_count:3
worker_192.168.102.103/datasystem_worker.INFO.20260507055454_003.log.gz:1297084:2026-05-07T05:54:41.658806 | I | urma_manager.cpp:852 | 192.168.102.103 | 11:408 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.26481ms, request id:270842, src address:192.168.102.103:31402, target address:192.168.219.108:31402, dataSize:8388608, cpuid:59, status: code: [OK], msg: [], urma_inflight_wr_count: 3, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
worker_192.168.168.230/datasystem_worker.INFO.20260507055452_472.log.gz:1330742:2026-05-07T05:54:41.656967 | I | master_oc_service_impl.cpp:261 | 192.168.168.230 | 11:281 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  Processing QueryMetaReq, requestId: 5807f3f3-5dfc-4f5f-b7c2-7afe1b43c9ca
worker_192.168.168.230/datasystem_worker.INFO.20260507055452_472.log.gz:1330745:2026-05-07T05:54:41.656978 | I | master_oc_service_impl.cpp:270 | 192.168.168.230 | 11:281 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  QueryMeta on master 192.168.219.108:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498431:2026-05-07T05:54:41.517891 | I | worker_oc_service_get_impl.cpp:130 | 192.168.219.108 | 11:296 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get] Receive, clientId: 13d9cecf-4184-446a-931b-c4ff99584e54, serverApiReadCost: 0.004ms, inflightRemoteGet: 3
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498432:2026-05-07T05:54:41.517913 | I | worker_oc_service_get_impl.cpp:165 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get] Receive, clientId: 13d9cecf-4184-446a-931b-c4ff99584e54, objects: kv_test_17_7_87811698213570_0, threadPool: idle(23),total(27),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498434:2026-05-07T05:54:41.517939 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  Query metadata from master: 192.168.168.230:31402, objects: kv_test_17_7_87811698213570_0, request id: 5807f3f3-5dfc-4f5f-b7c2-7afe1b43c9ca, remainingTime:14ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498630:2026-05-07T05:54:41.523329 | I | worker_oc_service_get_impl.cpp:780 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get] Master query done, targets: 1, hits: 1, cost: 5.401ms
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498632:2026-05-07T05:54:41.523341 | I | worker_oc_eviction_manager.cpp:421 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  Eviction start.
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498633:2026-05-07T05:54:41.523345 | I | worker_oc_eviction_manager.cpp:431 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  Evict is going on...
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498637:2026-05-07T05:54:41.523361 | I | worker_oc_service_batch_get_impl.cpp:607 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get] Remote pull, count: 1, path: UB, src=192.168.219.108:31402, dst=192.168.102.103:31402
worker_192.168.219.108/datasystem_worker.INFO.20260507055518_623.log.gz:498916:2026-05-07T05:54:41.529450 | I | worker_oc_service_get_impl.cpp:194 | 192.168.219.108 | 11:405 | c642fb0d-b9ad-4f01-b385-fc2fb2dbad71 | jingpai |  [Get] Done, clientId: 13d9cecf-4184-446a-931b-c4ff99584e54, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc QueryMeta: 5 ms; ProcessGetObjectRequest: 11 ms; }
```
