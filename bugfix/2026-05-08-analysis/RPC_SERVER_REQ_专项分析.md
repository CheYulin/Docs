# ZMQ RPC Server 请求排队分析 (server_req_queue)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 |
| **影响组件** | RPC Server 请求队列 |
| **Trace ID** | metrics_server_req_queue_us_min_585_max_3149 |
| **异常 Trace** | 1051ba83 (3068us) |

---

## 一、指标定义

### server_req_queue

**计算公式** (zmq_constants.h:181):
```cpp
uint64_t serverReqQueueNs = (serverExecStartTs > serverRecvTs)
                           ? (serverExecStartTs - serverRecvTs) : 0U;
```

**含义**: 从 RPC Server 收到请求到开始执行业务逻辑的时间。

### 时序位置

```
Server Side
    |
    |<---- serverRecvTs  收到请求
    |         |
    |         | [server_req_queue] <-- server_req_queue_us
    |         |
    |<---- serverExecStartTs 开始执行业务
```

---

## 二、异常 Trace 1051ba83 分析

### 2.1 日志

```
// Worker1 侧
14:33:41.466222 | [Get] Receive | clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe
14:33:41.466240 | ThreadPool: idle(12),total(17),wait(0)
14:33:41.466641 | [Get] Remote pull | dst=192.168.219.66:31402
14:33:41.471914 | ZMQ_RPC_FRAMEWORK_SLOW | server_req_queue_us=3068

// Worker2 侧
14:34:06.641583 | [Get/RemotePull] Receive | remainingTime: 10ms
14:34:06.641603 | Processing pull object
```

### 2.2 Framework 数据

```
framework_us=3463
  client_req_framework_us=21
  remote_processing_us=5220
    server_req_queue_us=3068       // ⚠️ 异常!
    server_exec_us=1790
    server_rsp_queue_us=146
    network_residual_us=215
```

### 2.3 问题分析

```
server_req_queue (3068us) > server_exec (1790us)
比率: 3068 / 1790 = 1.7x

正常情况下 server_req_queue 应该 << server_exec
```

---

## 三、代码分析

### 3.1 RPC Server 接收请求

**文件**: `worker_worker_oc_service_impl.cpp:134-144`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(
    std::shared_ptr<::datasystem::ServerUnaryWriterReader<GetObjectRemoteRspPb, GetObjectRemoteReqPb>> serverApi)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    PerfPoint point(PerfKey::WORKER_SERVER_GET_REMOTE);

    GetObjectRemoteReqPb req;
    PerfPoint pointImpl(PerfKey::WORKER_SERVER_GET_REMOTE_READ);

    // serverRecvTs 记录点 - 收到请求
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "GetObjectRemote read error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_IMPL);

    // serverExecStartTs 记录点 - 开始执行业务
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));
}
```

### 3.2 业务处理

**文件**: `worker_worker_oc_service_impl.cpp:170-182`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(GetObjectRemoteReqPb &req, GetObjectRemoteRspPb &rsp,
                                                  std::vector<RpcMessage> &payload)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    // 1. AK/SK 验证
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(akSkManager_->VerifySignatureAndTimestamp(req), "AK/SK failed.");

    // 2. 日志记录
    LOG(INFO) << "Processing pull object[" << req.object_key() << "] ...";

    // 3. 业务处理
    std::vector<uint64_t> eventKeys;
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));
}
```

---

## 四、根因分析

### 4.1 ThreadPool 状态矛盾

```
Worker1: ThreadPool idle(12), total(17), wait(0)
Worker2: 未知

但 Worker2 server_req_queue = 3068us，说明有排队
```

### 4.2 可能原因

| 可能原因 | 检查点 |
|----------|--------|
| Worker2 线程池饱和 | 所有线程都在忙 |
| 全局锁竞争 | 获取锁等待 |
| CPU 调度延迟 | 进程被换出 |

### 4.3 结论

**根因**: Worker2 (192.168.219.66) 收到请求后，等待线程池调度等了 3068us。

---

## 附录 A：全量日志

```
// ========== Trace 1051ba83 ==========

// ========== Worker1 (192.168.42.114) 侧 ==========

14:33:41.466222 | I | worker_oc_service_get_impl.cpp:130 | 192.168.42.114 | 11:296 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Receive, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, serverApiReadCost: 0.005ms, inflightRemoteGet: 2

14:33:41.466240 | I | worker_oc_service_get_impl.cpp:165 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Receive, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, objects: kv_test_24_6_118992864875120_0, threadPool: idle(12),total(17),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms

14:33:41.466261 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Query metadata from master: 192.168.215.24:31402, objects: kv_test_24_6_118992864875120_0, request id: f34e8570-7f08-4fd3-bb5e-e1fef4060fe0, remainingTime:14ms

14:33:41.466615 | I | worker_oc_service_get_impl.cpp:780 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Master query done, targets: 1, hits: 1, cost: 0.364ms

14:33:41.466641 | I | worker_oc_service_batch_get_impl.cpp:607 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Remote pull, count: 1, path: UB, src=192.168.42.114:31402, dst=192.168.219.66:31402

14:33:41.471914 | I | zmq_constants.h:204 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=1051ba83-7426-457c-928e-fb2b89969728 framework_us=3463 e2e_us=5254 client_req_framework_us=21 remote_processing_us=5220 client_rsp_framework_us=12 server_req_queue_us=3068 server_exec_us=1790 server_rsp_queue_us=146 network_residual_us=215

14:33:41.471966 | I | worker_oc_service_get_impl.cpp:194 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Done, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, objects: 1, transferPath: UB, totalCost: exceed 3ms: {ProcessGetObjectRequest: 5 ms; }

// ========== Worker2 (192.168.219.66) 侧 ==========

14:34:06.641583 | I | worker_worker_oc_service_impl.cpp:693 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get/RemotePull] Receive, count: 1, remainingTime: 10ms, src=192.168.42.114:31402, dst=192.168.219.66:31402

14:34:06.641590 | I | worker_worker_oc_service_impl.cpp:196 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Processing pull object[kv_test_24_6_118992864875120_0] offset[0] size[8388608], src=192.168.42.114:31402, dst=192.168.219.66:31402

14:34:06.641603 | I | urma_manager.cpp:1297 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | URMA write useNumaAffinity:1, src:2, dst:1, jetty id:1125, urma_inflight_wr_count:2

14:34:06.643327 | I | urma_manager.cpp:852 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 1.64181ms, request id:123697, src address:192.168.219.66:31402, target address:192.168.42.114:31402, dataSize:8388608, cpuid:79, status: code: [OK], msg: [], urma_inflight_wr_count: 2, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window

// ========== Master (192.168.215.24) 侧 ==========

14:34:06.691161 | I | master_oc_service_impl.cpp:261 | 192.168.215.24 | 11:285 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Processing QueryMetaReq, requestId: f34e8570-7f08-4fd3-bb5e-e1fef4060fe0

14:34:06.691174 | I | master_oc_service_impl.cpp:270 | 192.168.215.24 | 11:285 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | QueryMeta on master 192.168.42.114:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
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

    // 检查连接稳定性
    RETURN_IF_NOT_OK(CheckConnectionStable(req));

    // serverExecStartTs 记录点 - 这里开始执行业务
    RETURN_IF_NOT_OK_EXCEPT(GetObjectRemote(req, rsp, payload), StatusCode::K_OC_REMOTE_GET_NOT_ENOUGH);
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_WRITE);

    // serverSendTs 记录点
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_SENDPAYLOAD);

    // 发送 payload
    if (rsp.data_source() == DataTransferSource::DATA_ALREADY_TRANSFERRED ...) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload({}, ...), "GetObjectRemote send payload error");
    } else if (rsp.data_source() == DataTransferSource::DATA_IN_PAYLOAD) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload(payload, ...), "GetObjectRemote send payload error");
    }

    pointImpl.Record();
    return Status::OK();
}
```
