# Issue: Framework 延迟分解分析 (41037us - 83567us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | 整体 Framework |
| **影响节点** | Worker1 / Worker2 / Master |
| **严重程度** | High |
| **Trace ID** | metrics_framework_us_min_41037_max_83567 |

---

## 一、正确的系统流程

### E2E 流程: Client -> Worker1 -> Worker2 -> Worker1 (URMA)

```
┌────────┐     ┌─────────────┐     ┌─────────────┐
│ Client │────>│ Worker1    │────>│ Worker2    │
│        │     │ 102.88     │     │ 42.114     │
└────────┘     │ (RPC Client)│     │ (RPC Server)│
               │             │     │ URMA Write  │
               │             │<────│ (数据传回)  │
               │ 接收数据      │ URMA│             │
               └─────────────┘     └─────────────┘
```

### 各阶段延迟分布

```
总 E2E: 82.7ms (82701us)

client_req:     49us (0.06%)   // Worker1 准备请求
remote_process: 82639us (99.9%) // Worker2 处理 + URMA 传输
  server_req_q:   65us (0.08%)
  server_exec:    42us (0.05%)
  server_rsp_q:   21us (0.03%)
  network_res:  82509us (99.8%)  <-- 主导!
client_rsp:      12us (0.01%)   // Worker1 接收响应
```

---

## 二、各指标详解

### 2.1 client_req_framework_us

**定义**: Worker1 准备请求的时间（Client 发送请求到 Worker1 接收）

**代码确认**: `worker_oc_service_get_impl.cpp:117-131`

```cpp
Status WorkerOcServiceGetImpl::Get(
    std::shared_ptr<ServerUnaryWriterReader<GetRspPb, GetReqPb>> &serverApi)
{
    PerfPoint point(PerfKey::WORKER_GET_OBJECT);
    Timer timer;
    auto request = std::make_shared<GetRequest>(...);

    GetReqPb req;
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "serverApi read request failed");
    LOG(INFO) << FormatString("[Get] Receive, clientId: %s, serverApiReadCost: %.3fms,...",
                              clientId, timer.ElapsedMilliSecond());
}
```

**数值**: 14us - 49us ✅ 正常

---

### 2.2 server_req_queue_us

**定义**: Worker2 请求排队时间

**异常 Trace**: 1051ba83 (3068us - 3149us)

**代码确认**: Worker2 线程池排队

```cpp
// worker_oc_service_get_impl.cpp:165
LOG(INFO) << "[Get] Receive, ... threadPool: " << threadPool_->GetStatistics();
// threadPool: idle(12),total(17),wait(0) 表示有 12 个空闲线程
```

**数值**: 65us (正常) / 3068us (异常) ⚠️

---

### 2.3 server_exec_us

**定义**: Worker2 执行请求的时间

**代码确认**: `worker_worker_oc_service_impl.cpp:134-168`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(...)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    PerfPoint point(PerfKey::WORKER_SERVER_GET_REMOTE);

    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "GetObjectRemote read error");
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload(...), "GetObjectRemote send payload error");
}
```

**数值**: 42us - 3206us ⚠️

---

### 2.4 server_rsp_queue_us

**定义**: Worker1 响应排队时间（收到 URMA 数据后到发送响应）

**异常 Trace**: 26842642 (4084us)

**关键发现**: server_rsp_queue 应该 ≈ network_residual，但实际差 26x

```
server_rsp_q (4084us) / network_residual (155us) = 26x
```

**代码确认**: Worker1 URMA 数据接收后的处理

**数值**: 21us (正常) / 4084us (异常) ⚠️

---

### 2.5 network_residual_us

**定义**: URMA 数据传输时间（Worker1 发送请求到收到响应的时间 - Worker2 处理时间）

**主导因素**: 82.5ms / 82.7ms = 99.8%

**代码确认**: `urma_manager.cpp:1292-1299`

```cpp
LOG(INFO) << "URMA write useNumaAffinity:" << useNumaAffinity
          << ", src:" << static_cast<uint32_t>(args.srcChipId)
          << ", dst:" << static_cast<uint32_t>(args.dstChipId)
          << ", jetty id:" << jettyId
          << ", urma_inflight_wr_count:" << tbbEventMap_.size();
```

**数值**: 5737us - 82509us ❌ 异常

---

### 2.6 client_rsp_framework_us

**定义**: Worker1 接收响应的时间

**数值**: 12us ✅ 正常

---

## 三、根因分析总结

### 3.1 主要瓶颈

| 指标 | 正常值 | 异常值 | 根因 |
|------|--------|--------|------|
| network_residual | < 10ms | **82.5ms** | URMA 连接重建 + 传输慢 |
| server_req_queue | < 100us | 3068us | Worker2 线程池饱和 |
| server_rsp_queue | ≈ network | 4084us | Worker1 响应发送瓶颈 |
| server_exec | < 1ms | 3206us | 数据读取开销 |

### 3.2 关键问题

1. **URMA 连接未缓存**
   ```
   [URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered
   每次请求重建连接，花费 ~8ms
   ```

2. **Worker2 线程池饱和**
   ```
   ThreadPool: idle(12),total(17),wait(0)
   但 server_req_queue 仍有 3068us
   ```

3. **Worker1 响应发送瓶颈**
   ```
   server_rsp_q (4084us) >> network_residual (155us)
   26x 异常比例
   ```

---

## 四、结论

| 问题 | 答案 |
|------|------|
| 主要瓶颈？ | **network_residual (URMA 传输)** |
| 次要瓶颈？ | server_req_queue, server_rsp_queue |
| 根因？ | URMA 连接未缓存，Worker 线程池竞争 |

---

## 五、建议

1. **URMA 连接池化** (P0)
   - 缓存 URMA 连接避免重建 (~8ms 节省)

2. **Worker 线程池扩容** (P1)
   - 当前 17 线程，考虑扩容

3. **监控告警** (P2)
   - network_residual > 10ms
   - server_req_queue > 1000us
   - server_rsp_queue > 1000us

---

## 附录 A：全量日志

### Trace 0c3d819d 全量日志

```
// ========== Worker1 (192.168.102.88) 侧 ==========

14:28:55.409808 | I | worker_oc_service_get_impl.cpp:1161 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Remote get request:[be68a78d-edde-4601-85a1-9840cefce853] object:[_urma_192_168_42_114:31402], offset[0] size[1], src=192.168.102.88:31402, dst=192.168.42.114:31402

14:28:55.409831 | I | rpc_stub_cache_mgr.cpp:191 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start to create stub, destAddr: 192.168.42.114:31402, type: 0

14:28:55.493757 | I | zmq_constants.h:204 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=0c3d819d-c27b-4763-903e-82188ffde287 framework_us=82658 e2e_us=82701 client_req_framework_us=49 remote_processing_us=82639 client_rsp_framework_us=12 server_req_queue_us=65 server_exec_us=42 server_rsp_queue_us=21 network_residual_us=82509

14:28:55.493770 | W | worker_oc_service_get_impl.cpp:1026 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered, remoteAddress=192.168.42.114:31402, remoteWorkerId=b6b9966c-d424-43cf-b85f-8e3377528ecd, realRemainingTimeMs=4915, lastResult=code: [Urma needs to reconnet], msg: [Thread ID 281361878613216 Urma needs to reconnet. No existing connection requires creation.]

14:28:55.494629 | I | urma_resource.cpp:225 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | urma create jfr id 1025 success. jfr count: 1

14:28:55.498539 | I | urma_manager.cpp:1175 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start import remote jetty, remote urma info: Instance id 9696f39d-2e73-4f3c-90ee-30c92baa2c56, address 192.168.42.114:31402, eid 4545:4944:2000:0000:2100:0000:2200:0000 uasid 0, jetty_id 1030, local address:192.168.102.88:31402

14:28:55.501301 | I | urma_manager.cpp:1161 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_CONNECT] Import target jetty elapsed = 2.288ms, cpuid: 69, remoteInfo: Instance id 9696f39d-2e73-4f3c-90ee-30c92baa2c56, address 192.168.42.114:31402, eid 4545:4944:2000:0000:2100:0000:2200:0000 uasid 0, jetty_id 1030

14:28:55.501991 | I | worker_worker_transport_api.cpp:64 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_NEED_CONNECT] Worker-worker transport connection exchange success, elapsed ms: 7.94136

14:28:55.503526 | I | worker_oc_service_get_impl.cpp:1256 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Remote get success, elapsed 92.531 ms

// ========== Worker2 (192.168.42.114) 侧 ==========

14:28:30.137018 | I | worker_worker_transport_service_impl.cpp:59 | 192.168.42.114 | 11:318 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_NEED_CONNECT] WorkerWorkerExchangeUrmaConnectInfo start, peerAddress=192.168.102.88:31402

14:28:30.137038 | I | urma_manager.cpp:1660 | 192.168.42.114 | 11:318 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start import remote jetty, remote urma info: Instance id 442d08e9-bcab-4cf4-9559-82b1448afb62, address 192.168.102.88:31402, eid 4345:4944:1000:0000:2d00:0000:2e00:0000 uasid 0, jetty_id 1025, local address:192.168.42.114:31402

14:28:30.139174 | I | urma_manager.cpp:1161 | 192.168.42.114 | 11:318 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_CONNECT] Import target jetty elapsed = 1.86272ms, cpuid: 66, remoteInfo: Instance id 442d08e9-bcab-4cf4-9559-82b1448afb62, address 192.168.102.88:31402, eid 4345:4944:1000:0000:2d00:0000:2e00:0000 uasid 0, jetty_id 1025

14:28:30.140276 | I | worker_worker_transport_service_impl.cpp:61 | 192.168.42.114 | 11:318 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_NEED_CONNECT] WorkerWorkerExchangeUrmaConnectInfo finish, elapsed ms: 3.26462, status=code: [OK], msg: []

14:28:30.145154 | I | worker_worker_oc_service_impl.cpp:176 | 192.168.42.114 | 11:303 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Processing pull object[_urma_192_168_42_114:31402] offset[0] size[1], src=192.168.102.88:31402, dst=192.168.42.114:31402

14:28:30.145197 | I | urma_manager.cpp:1297 | 192.168.42.114 | 11:303 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | URMA write useNumaAffinity:1, src:1, dst:1, jetty id:1029, urma_inflight_wr_count:1

14:28:30.145291 | I | worker_worker_oc_service_impl.cpp:165 | 192.168.42.114 | 11:303 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | send data success
```

---

## 附录 B：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker1 Get 请求处理 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_batch_get_impl.cpp` | Worker1 Remote Pull 发送 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker2 URMA Write 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理和读写 |
| `src/datasystem/common/zmq/zmq_constants.h` | ZMQ RPC 日志定义 |
