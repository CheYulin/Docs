# ZMQ RPC Server 响应排队分析 (server_rsp_queue)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 |
| **影响组件** | RPC Server 响应队列 |
| **Trace ID** | metrics_server_rsp_queue_us_min_4084_max_8810 |
| **异常 Trace** | 26842642 (4084us) |

---

## 一、指标定义

### server_rsp_queue

**计算公式** (zmq_constants.h:183):
```cpp
uint64_t serverRspQueueNs = (serverSendTs > serverExecEndTs)
                           ? (serverSendTs - serverExecEndTs) : 0U;
```

**含义**: 从 RPC Server 业务执行完成到发送响应的时间。

### 时序位置

```
Server Side
    |
    |<---- serverExecEndTs  业务执行完成
    |         |
    |         | [server_rsp_queue] <-- server_rsp_queue_us
    |         |
    |<---- serverSendTs  发送响应
    |
    v
Client Side
    |<---- clientRecvTs  收到响应
```

---

## 二、异常 Trace 26842642 分析

### 2.1 日志

```
// Worker1 侧
14:37:05.329992 | [Get] Receive | clientId: 14f73fc3...
14:37:05.330008 | ThreadPool: idle(13),total(18),wait(0)
14:37:05.330024 | Query metadata from master
14:37:05.330289 | Master query done | cost: 0.271ms
14:37:05.330305 | [Get] Remote pull | dst=192.168.219.66:31402
14:37:05.334930 | ZMQ_RPC_FRAMEWORK_SLOW | server_rsp_queue_us=4084

// Worker2 侧
14:37:04.959685 | [Get/RemotePull] Receive | remainingTime: 13ms
14:37:04.959692 | Processing pull object
14:37:04.959704 | URMA write | jetty 1129
```

### 2.2 Framework 数据

```
framework_us=4287
  client_req_framework_us=20
  remote_processing_us=4577
    server_req_queue_us=17          // ✅ 正常
    server_exec_us=320             // ✅ 正常
    server_rsp_queue_us=4084       // ⚠️ 异常!
    network_residual_us=155         // ✅ 正常
```

### 2.3 关键发现

```
server_req_q (17us) + server_exec (320us) = 337us  // Worker2 处理很快
server_rsp_q (4084us) >> network_residual (155us)  // 严重异常!
比率: 4084 / 155 = 26x
```

**问题**: server_rsp_queue 应该是响应发送时间，正常应该接近 network_residual。但这里差 26 倍！

---

## 三、代码分析

### 3.1 server_rsp_queue 测量点

**文件**: `zmq_constants.h:183`

```cpp
// server_rsp_queue = serverSendTs - serverExecEndTs
uint64_t serverRspQueueNs = (serverSendTs > serverExecEndTs)
                            ? (serverSendTs - serverExecEndTs) : 0U;
```

### 3.2 Worker2 响应发送

**文件**: `worker_worker_oc_service_impl.cpp:149-167`

```cpp
pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_WRITE);
// serverExecEndTs 记录点 (上面这行之前)

// serverSendTs 记录点 - 发送响应 header
RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_SENDPAYLOAD);

// 发送 payload
if (rsp.data_source() == DataTransferSource::DATA_ALREADY_TRANSFERRED ...) {
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload({}, ...), ...);
}
```

### 3.3 问题分析

server_rsp_queue 异常大说明：
1. Worker2 执行完成后，等待发送响应等了 4084us
2. 但 Worker2 执行只需 320us

**可能原因**:
- ZMQ socket buffer 满
- 网络出方向拥塞
- 线程调度延迟

---

## 四、根因分析

### 4.1 时间线矛盾

```
Worker2 时间线 (原始):
14:37:04.959685  收到请求
14:37:04.959692  开始处理
14:37:04.959704  URMA write 完成
               (serverExecEndTs 应该在这里)

从 14:37:04.959704 到 14:37:05.334930 (Worker1 收到日志):
时间差 = 375.226ms

但 framework 显示:
server_rsp_q = 4084us (4ms)
network_res = 155us

server_rsp_q + network_res = 4.2ms
这与 375ms 不符，说明有时钟偏移
```

### 4.2 正常比例验证

**正常情况**: server_rsp_queue ≈ network_residual

```
因为:
- server_rsp_queue 是 Server 发送响应的时间
- network_residual 是 Client 收到响应的时间
- 两者应该接近
```

**异常情况**: server_rsp_queue >> network_residual

```
server_rsp_q (4084us) / network_res (155us) = 26x
```

**结论**: Worker2 发送响应存在瓶颈！

---

## 五、结论

| 项目 | 结果 |
|------|------|
| server_rsp_queue | 4084us (异常) |
| 正常范围 | < 100us |
| 根因 | Worker2 响应发送瓶颈 |

**根因**: Worker2 (192.168.219.66) 业务执行完成后，发送响应等了 4ms。可能原因:
1. ZMQ socket send buffer 满
2. 网络出方向带宽不足
3. 线程调度延迟

---

## 附录 A：全量日志

```
// ========== Trace 26842642 ==========

// ========== Worker1 (192.168.45.216) 侧 ==========

14:37:05.329992 | I | worker_oc_service_get_impl.cpp:130 | 192.168.45.216 | 11:295 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get] Receive, clientId: 14f73fc3-3930-47ab-b1fc-df5186bdaabc, serverApiReadCost: 0.004ms, inflightRemoteGet: 2

14:37:05.330008 | I | worker_oc_service_get_impl.cpp:165 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get] Receive, clientId: 14f73fc3-3930-47ab-b1fc-df5186bdaabc, objects: kv_test_24_12_119171191401630_0, threadPool: idle(13),total(18),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms

14:37:05.330024 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | Query metadata from master: 192.168.215.24:31402, objects: kv_test_24_12_119171191401630_0, request id: 9ea58071-b885-47f3-9a55-eb6309a95a1e, remainingTime:14ms

14:37:05.330289 | I | worker_oc_service_get_impl.cpp:780 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get] Master query done, targets: 1, hits: 1, cost: 0.271ms

14:37:05.330305 | I | worker_oc_service_batch_get_impl.cpp:607 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get] Remote pull, count: 1, path: UB, src=192.168.45.216:31402, dst=192.168.219.66:31402

14:37:05.334930 | I | zmq_constants.h:204 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=26842642-b48b-4a41-9a6d-3a5a2daf62e8 framework_us=4287 e2e_us=4608 client_req_framework_us=20 remote_processing_us=4577 client_rsp_framework_us=10 server_req_queue_us=17 server_exec_us=320 server_rsp_queue_us=4084 network_residual_us=155

14:37:05.334986 | I | worker_oc_service_get_impl.cpp:194 | 192.168.45.216 | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get] Done, clientId: 14f73fc3-3930-47ab-b1fc-df5186bdaabc, objects: 1, transferPath: UB, totalCost: exceed 3ms: {ProcessGetObjectRequest: 4 ms; }

14:37:05.334978 | I | access_recorder.cpp:182 | kvc-jingpai-worker-55b94f576c-2dbrt | 11:412 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai |0 | DS_POSIX_GET | 4991 | 8388608 | {Object_key:kv_test_24_12_119171191401630_0,count:1,sub_timeout:0} |

// ========== Worker2 (192.168.219.66) 侧 ==========

14:37:04.959685 | I | worker_worker_oc_service_impl.cpp:693 | 192.168.219.66 | 11:394 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | [Get/RemotePull] Receive, count: 1, remainingTime: 13ms, src=192.168.45.216:31402, dst=192.168.219.66:31402

14:37:04.959692 | I | worker_worker_oc_service_impl.cpp:196 | 192.168.219.66 | 11:394 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | Processing pull object[kv_test_24_12_119171191401630_0] offset[0] size[8388608], src=192.168.45.216:31402, dst=192.168.219.66:31402

14:37:04.959704 | I | urma_manager.cpp:1297 | 192.168.219.66 | 11:394 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | URMA write useNumaAffinity:1, src:2, dst:1, jetty id:1129, urma_inflight_wr_count:1

// ========== Master (192.168.215.24) 侧 ==========

14:37:05.012498 | I | master_oc_service_impl.cpp:261 | 192.168.215.24 | 11:285 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | Processing QueryMetaReq, requestId: 9ea58071-b885-47f3-9a55-eb6309a95a1e

14:37:05.012510 | I | master_oc_service_impl.cpp:270 | 192.168.215.24 | 11:285 | 26842642-b48b-4a41-9a6d-3a5a2daf62e8 | jingpai | QueryMeta on master 192.168.45.216:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
```

---

## 附录 B：相关代码

**文件**: `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp`
**位置**: 第 134-168 行

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(
    std::shared_ptr<::datasystem::ServerUnaryWriterReader<GetObjectRemoteRspPb, GetObjectRemoteReqPb>> serverApi)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    PerfPoint point(PerfKey::WORKER_SERVER_GET_REMOTE);
    GetObjectRemoteReqPb req;
    GetObjectRemoteRspPb rsp;
    std::vector<RpcMessage> payload;
    PerfPoint pointImpl(PerfKey::WORKER_SERVER_GET_REMOTE_READ);

    // serverRecvTs 记录点
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "GetObjectRemote read error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_IMPL);
    INJECT_POINT("worker.GetObjectRemote.afterRead");
    RETURN_IF_NOT_OK(CheckConnectionStable(req));

    // serverExecStartTs 记录点 - 业务执行开始
    RETURN_IF_NOT_OK_EXCEPT(GetObjectRemote(req, rsp, payload), StatusCode::K_OC_REMOTE_GET_NOT_ENOUGH);

    // serverExecEndTs 记录点 - 业务执行结束
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_WRITE);

    // serverSendTs 记录点 - 发送响应 header
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_SENDPAYLOAD);

    // 发送 payload (DATA_ALREADY_TRANSFERRED 模式)
    if (rsp.data_source() == DataTransferSource::DATA_ALREADY_TRANSFERRED ...) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload({}, ...), ...);
    } else if (rsp.data_source() == DataTransferSource::DATA_IN_PAYLOAD) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload(payload, ...), ...);
    }

    pointImpl.Record();
    return Status::OK();
}
```
