# Trace: 13763-effc82d4-ef24-4f89-86fb-1d74dbc70aba

## 指标汇总

| 指标 | 值 |
|------|-----|
| QueryMeta (worker1->meta) | N/A ms |
| ProcessGetObjectRequest | 5 ms |
| URMA Wait (最大) | 0.22 ms |
| 节点 | 192.168.219.108, 192.168.235.167, 192.168.35.39 |
| 错误 | Failed |

## 全量日志

```
worker_192.168.219.108/datasystem_worker.INFO.log:94652:2026-05-07T06:01:24.566180 | I | worker_oc_service_get_impl.cpp:130 | 192.168.219.108 | 11:295 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get] Receive, clientId: c6a40121-f74b-41ba-9818-cd537cf4847e, serverApiReadCost: 0.004ms, inflightRemoteGet: 1
worker_192.168.219.108/datasystem_worker.INFO.log:94661:2026-05-07T06:01:24.566267 | I | worker_oc_service_get_impl.cpp:165 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get] Receive, clientId: c6a40121-f74b-41ba-9818-cd537cf4847e, objects: kv_test_24_8_88294428825350_0, threadPool: idle(26),total(34),wait(3), elapsed: 0.000ms, remainingTime: 12.000ms
worker_192.168.219.108/datasystem_worker.INFO.log:94668:2026-05-07T06:01:24.566310 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  Query metadata from master: 192.168.35.39:31402, objects: kv_test_24_8_88294428825350_0, request id: f1e0f68e-7ef8-4ca4-9824-1d7a3f0dfd2b, remainingTime:10ms
worker_192.168.219.108/datasystem_worker.INFO.log:94727:2026-05-07T06:01:24.568107 | I | worker_oc_service_get_impl.cpp:780 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get] Master query done, targets: 1, hits: 1, cost: 1.817ms
worker_192.168.219.108/datasystem_worker.INFO.log:94728:2026-05-07T06:01:24.568118 | I | worker_oc_eviction_manager.cpp:421 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  Eviction start.
worker_192.168.219.108/datasystem_worker.INFO.log:94729:2026-05-07T06:01:24.568144 | I | worker_oc_service_batch_get_impl.cpp:607 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get] Remote pull, count: 1, path: UB, src=192.168.219.108:31402, dst=192.168.235.167:31402
worker_192.168.219.108/datasystem_worker.INFO.log:94735:2026-05-07T06:01:24.568181 | I | worker_oc_eviction_manager.cpp:292 | 192.168.219.108 | 11:239 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  EvictionList size before evict: 1216
worker_192.168.219.108/datasystem_worker.INFO.log:95129:2026-05-07T06:01:24.571422 | I | worker_oc_service_get_impl.cpp:194 | 192.168.219.108 | 11:406 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get] Done, clientId: c6a40121-f74b-41ba-9818-cd537cf4847e, objects: 1, transferPath: UB, totalCost: exceed 3ms: {ProcessGetObjectRequest: 5 ms; }
worker_192.168.219.108/datasystem_worker.INFO.log:95251:2026-05-07T06:01:24.573324 | I | worker_oc_eviction_manager.cpp:344 | 192.168.219.108 | 11:239 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  EvictionList size after evict:1222, failed size:1220
worker_192.168.235.167/datasystem_worker.INFO.20260507060128_590.log.gz:1467418:2026-05-07T06:01:24.833578 | I | worker_worker_oc_service_impl.cpp:693 | 192.168.235.167 | 11:424 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [Get/RemotePull] Receive, count: 1, remainingTime: 9ms, src=192.168.219.108:31402, dst=192.168.235.167:31402
worker_192.168.235.167/datasystem_worker.INFO.20260507060128_590.log.gz:1467419:2026-05-07T06:01:24.833586 | I | worker_worker_oc_service_impl.cpp:196 | 192.168.235.167 | 11:424 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  Processing pull object[kv_test_24_8_88294428825350_0] offset[0] size[8388608], src=192.168.219.108:31402, dst=192.168.235.167:31402
worker_192.168.235.167/datasystem_worker.INFO.20260507060128_590.log.gz:1467420:2026-05-07T06:01:24.833600 | I | urma_manager.cpp:1299 | 192.168.235.167 | 11:424 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  URMA write useNumaAffinity:1, src:1, dst:2, jetty id:1066, urma_inflight_wr_count:1
worker_192.168.235.167/datasystem_worker.INFO.20260507060128_590.log.gz:1467423:2026-05-07T06:01:24.833844 | I | urma_manager.cpp:852 | 192.168.235.167 | 11:424 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 0.22376ms, request id:758160, src address:192.168.235.167:31402, target address:192.168.219.108:31402, dataSize:8388608, cpuid:54, status: code: [OK], msg: [], urma_inflight_wr_count: 1, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA
worker_192.168.35.39/datasystem_worker.INFO.20260507060125_943.log.gz:1533459:2026-05-07T06:01:24.780514 | I | master_oc_service_impl.cpp:261 | 192.168.35.39 | 11:283 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  Processing QueryMetaReq, requestId: f1e0f68e-7ef8-4ca4-9824-1d7a3f0dfd2b
worker_192.168.35.39/datasystem_worker.INFO.20260507060125_943.log.gz:1533460:2026-05-07T06:01:24.780525 | I | master_oc_service_impl.cpp:270 | 192.168.35.39 | 11:283 | effc82d4-ef24-4f89-86fb-1d74dbc70aba | jingpai |  QueryMeta on master 192.168.219.108:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
```
