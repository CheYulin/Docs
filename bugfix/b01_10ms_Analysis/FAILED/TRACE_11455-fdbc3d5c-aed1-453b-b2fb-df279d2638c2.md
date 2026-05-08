# Trace: 11455-fdbc3d5c-aed1-453b-b2fb-df279d2638c2

## 指标汇总

| 指标 | 值 |
|------|-----|
| QueryMeta (worker1->meta) | 11 ms |
| ProcessGetObjectRequest | 11 ms |
| URMA Wait (最大) | N/A |
| 节点 | 192.168.210.230, 192.168.42.102 |
| 错误 | Failed |

## 全量日志

```
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19410:2026-05-07T05:50:53.797760 | I | worker_oc_service_get_impl.cpp:130 | 192.168.210.230 | 11:282 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  [Get] Receive, clientId: fc309c5f-eb6e-4d55-8bf7-1d6ebaaa5769, serverApiReadCost: 0.004ms, inflightRemoteGet: 0
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19411:2026-05-07T05:50:53.797777 | I | worker_oc_service_get_impl.cpp:165 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  [Get] Receive, clientId: fc309c5f-eb6e-4d55-8bf7-1d6ebaaa5769, objects: kv_test_4_3_87630039884340_0, threadPool: idle(4),total(8),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19412:2026-05-07T05:50:53.797794 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  Query metadata from master: 192.168.42.102:31402, objects: kv_test_4_3_87630039884340_0, request id: b457dde7-ebee-4cd3-b5b2-400150e9bf0a, remainingTime:14ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19489:2026-05-07T05:50:53.808889 | E | rpc_util.h:115 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  [RPC Retry]: code: [RPC unavailable], msg: [[RPC_RECV_TIMEOUT] Rpc service for client c6c7505f-59a6-4224:11:281316601364816:0 has not responded within the allowed time. Detail: code: [Try again], msg: [Thread ID 281428919844064 Try again. The queue is empty within allowed time: 11 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19492:traceId      : fdbc3d5c-aed1-453b-b2fb-df279d2638c2]. RPC Retry detail: [ RPC unavailable * 1 ] with 0 times in 12 ms.]
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19493:2026-05-07T05:50:53.808898 | E | worker_oc_service_get_impl.cpp:1535 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  Query metadata from master[192.168.42.102:31402]: code: [RPC unavailable], msg: [[RPC_RECV_TIMEOUT] Rpc service for client c6c7505f-59a6-4224:11:281316601364816:0 has not responded within the allowed time. Detail: code: [Try again], msg: [Thread ID 281428919844064 Try again. The queue is empty within allowed time: 11 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19496:traceId      : fdbc3d5c-aed1-453b-b2fb-df279d2638c2]. RPC Retry detail: [ RPC unavailable * 1 ] with 0 times in 12 ms.], elapsed 11.105 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19497:2026-05-07T05:50:53.808906 | E | worker_oc_service_get_impl.cpp:764 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  Query from master failed : code: [RPC unavailable], msg: [[RPC_RECV_TIMEOUT] Rpc service for client c6c7505f-59a6-4224:11:281316601364816:0 has not responded within the allowed time. Detail: code: [Try again], msg: [Thread ID 281428919844064 Try again. The queue is empty within allowed time: 11 ms
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19500:traceId      : fdbc3d5c-aed1-453b-b2fb-df279d2638c2]. RPC Retry detail: [ RPC unavailable * 1 ] with 0 times in 12 ms.]
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19501:2026-05-07T05:50:53.808916 | I | worker_request_manager.cpp:388 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  Can't find object kv_test_4_3_87630039884340_0, clientId fc309c5f-eb6e-4d55-8bf7-1d6ebaaa5769
worker_192.168.210.230/datasystem_worker.INFO.20260507055215_290.log.gz:19502:2026-05-07T05:50:53.808942 | I | worker_oc_service_get_impl.cpp:194 | 192.168.210.230 | 11:186 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  [Get] Done, clientId: fc309c5f-eb6e-4d55-8bf7-1d6ebaaa5769, objects: 1, transferPath: UB, totalCost: exceed 3ms: {Worker to master rpc QueryMeta: 11 ms; ProcessGetObjectRequest: 11 ms; }
worker_192.168.42.102/datasystem_worker.INFO.20260507055149_098.log.gz:30270:2026-05-07T05:50:28.443173 | I | master_oc_service_impl.cpp:261 | 192.168.42.102 | 11:284 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  Processing QueryMetaReq, requestId: b457dde7-ebee-4cd3-b5b2-400150e9bf0a
worker_192.168.42.102/datasystem_worker.INFO.20260507055149_098.log.gz:30271:2026-05-07T05:50:28.443192 | I | master_oc_service_impl.cpp:270 | 192.168.42.102 | 11:284 | fdbc3d5c-aed1-453b-b2fb-df279d2638c2 | jingpai |  QueryMeta on master 192.168.210.230:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
```
