# ZMQ RPC + 业务逻辑 专项分析

## 一、ZMQ RPC 指标定义

### 1.1 指标体系

根据 `zmq_constants.h:172-188` 代码：

| 指标 | 计算公式 | 说明 |
|------|----------|------|
| `client_req_framework_us` | clientSendTs - clientStartTs | **RPC Client 发送请求时间** |
| `client_rsp_framework_us` | clientEndTs - clientRecvTs | **RPC Client 接收响应等待时间** |
| `server_req_queue_us` | serverExecStartTs - serverRecvTs | **RPC Server 请求排队时间** |
| `server_exec_us` | serverExecEndTs - serverExecStartTs | **RPC Server 业务执行时间** |
| `server_rsp_queue_us` | serverSendTs - serverExecEndTs | **RPC Server 响应排队时间** |
| `network_residual_us` | remoteProcessingNs - serverProcessingNs | **网络传输时间** |

### 1.2 时序图

```
Client Side                          Server Side
    |                                     |
    |------ clientStartTs ----->|         |
    |                           |         |
    |      [业务处理]            |         |
    |                           |         |
    |<----- clientSendTs -------| serverRecvTs
    |                           |         |
    |                           | [server_req_queue]  <-- server_req_queue_us
    |                           |         |
    |                           |<-- serverExecStartTs
    |                           |         |
    |                           | [server_exec]  <-- server_exec_us
    |                           |         |
    |                           | serverExecEndTs --->
    |                           |         |
    |                           | [server_rsp_queue] <-- server_rsp_queue_us
    |                           |         |
    |<----- clientRecvTs ------- | serverSendTs
    |                           |
    |      [业务处理]            |
    |                           |
    |<----- clientEndTs --------|         |
```

### 1.3 Tick 定义

**文件**: `zmq_constants.h:150-170`

```cpp
for (int i = 0; i < meta.latency_ticks_size(); i++) {
    const auto &tick = meta.latency_ticks(i);
    const std::string &name = tick.tick_name();
    if (name == TICK_CLIENT_START) {
        clientStartTs = tick.ts();
    } else if (name == TICK_CLIENT_SEND) {
        clientSendTs = tick.ts();
    } else if (name == TICK_CLIENT_RECV) {
        clientRecvTs = tick.ts();
    } else if (name == TICK_CLIENT_END) {
        clientEndTs = tick.ts();
    } else if (name == TICK_SERVER_RECV) {
        serverRecvTs = tick.ts();
    } else if (name == TICK_SERVER_EXEC_START) {
        serverExecStartTs = tick.ts();
    } else if (name == TICK_SERVER_EXEC_END) {
        serverExecEndTs = tick.ts();
    } else if (name == TICK_SERVER_SEND) {
        serverSendTs = tick.ts();
    }
}
```

---

## 二、RPC Client 请求分析 (client_req_framework)

### 2.1 Trace 0c3d819d

```
ZMQ_RPC_FRAMEWORK_SLOW:
  client_req_framework_us=49   // ✅ 正常 (< 100us)
```

**代码位置**: `worker_oc_service_get_impl.cpp:117-131`

```cpp
Status WorkerOcServiceGetImpl::Get(
    std::shared_ptr<ServerUnaryWriterReader<GetRspPb, GetReqPb>> &serverApi)
{
    PerfPoint point(PerfKey::WORKER_GET_OBJECT);
    Timer timer;
    auto request = std::make_shared<GetRequest>(AccessRecorderKey::DS_POSIX_GET);

    GetReqPb req;
    // clientStartTs -> clientSendTs 的时间
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "...");
}
```

**结论**: Client 请求准备正常，49us < 100us 阈值。

---

## 三、RPC Server 请求排队分析 (server_req_queue)

### 3.1 Trace 1051ba83 - 异常案例

```
ZMQ_RPC_FRAMEWORK_SLOW:
  server_req_queue_us=3068   // ⚠️ 异常! (正常 < 100us)
  server_exec_us=1790
```

**问题**: Worker2 请求排队 3068us，远超正常值。

### 3.2 代码分析

**文件**: `worker_worker_oc_service_impl.cpp:134-168`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(
    std::shared_ptr<::datasystem::ServerUnaryWriterReader<GetObjectRemoteRspPb, GetObjectRemoteReqPb>> serverApi)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    PerfPoint point(PerfKey::WORKER_SERVER_GET_REMOTE);

    GetObjectRemoteReqPb req;
    PerfPoint pointImpl(PerfKey::WORKER_SERVER_GET_REMOTE_READ);
    // serverRecvTs 记录点
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "GetObjectRemote read error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_IMPL);

    // serverExecStartTs 记录点 - 这里开始执行业务
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));

    // serverExecEndTs 记录点 - 业务执行结束
    // serverSendTs 记录点 - 发送响应
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
}
```

### 3.3 根因分析

| 可能原因 | 检查点 |
|----------|--------|
| 线程池饱和 | ThreadPool idle=0, total=17 |
| 锁竞争 | 全局锁等待 |
| CPU 调度 | 进程被换出 |

---

## 四、RPC Server 业务执行分析 (server_exec)

### 4.1 Trace 0c3d819d

```
ZMQ_RPC_FRAMEWORK_SLOW:
  server_exec_us=42    // ✅ 正常
```

### 4.2 代码分析

**文件**: `worker_worker_oc_service_impl.cpp:170-182`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(
    GetObjectRemoteReqPb &req, GetObjectRemoteRspPb &rsp,
    std::vector<RpcMessage> &payload)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    // 1. 验证 AK/SK
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(akSkManager_->VerifySignatureAndTimestamp(req), "AK/SK failed.");

    // 2. 记录日志
    LOG(INFO) << "Processing pull object[" << req.object_key() << "] ...";

    // 3. 执行业务处理
    std::vector<uint64_t> eventKeys;
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));
    return Status::OK();
}
```

### 4.3 GetObjectRemoteHandler

**文件**: `worker_worker_oc_service_impl.cpp` (约 400-600 行)

主要流程:
1. 查询本地 ObjectKV
2. 从共享内存读取数据
3. 准备 URMA 写操作
4. 返回响应

---

## 五、RPC Server 响应排队分析 (server_rsp_queue)

### 5.1 Trace 26842642 - 异常案例

```
ZMQ_RPC_FRAMEWORK_SLOW:
  server_rsp_queue_us=4084    // ⚠️ 异常! (正常 < 100us)
  network_residual_us=155
  比率: 4084 / 155 = 26x     // 严重异常!
```

**问题**: server_rsp_queue (4084us) 应该是 network_residual (155us) 的正常比例，但实际差 26 倍！

### 5.2 代码分析

**文件**: `zmq_constants.h:183`

```cpp
uint64_t serverRspQueueNs = (serverSendTs > serverExecEndTs) ? (serverSendTs - serverExecEndTs) : 0U;
```

这表示从业务执行完成到发送响应的时间。

### 5.3 根因分析

| 可能原因 | 说明 |
|----------|------|
| ZMQ 背压 | Socket send buffer 满了 |
| 网络拥塞 | 出方向带宽不足 |
| 调度延迟 | 线程被换出 |

---

## 六、网络传输分析 (network_residual)

### 6.1 Trace 0c3d819d - 异常案例

```
ZMQ_RPC_FRAMEWORK_SLOW:
  network_residual_us=82509    // ❌ 严重异常! (正常 < 10ms)
```

**占比**: 82509 / 82701 = 99.8%

### 6.2 计算公式

**文件**: `zmq_constants.h:185-188`

```cpp
uint64_t networkResidualNs = 0U;
if (remoteProcessingNs > 0 && serverProcessingNs > 0) {
    // network_residual = 客户端观察的远程处理时间 - 服务端处理时间
    networkResidualNs = (remoteProcessingNs > serverProcessingNs)
                        ? (remoteProcessingNs - serverProcessingNs) : 0U;
}
```

即: `network_residual = remoteProcessing - serverProcessing`

### 6.3 根因分析

```
remoteProcessingNs = clientRecvTs - clientSendTs  // 客户端观察的总时间
serverProcessingNs = serverSendTs - serverRecvTs  // 服务端处理总时间
networkResidual    = remoteProcessing - serverProcessing  // 剩下的就是网络传输
```

**主要瓶颈**:
1. **URMA 连接重建**: 7.94ms
2. **RDMA 传输**: ~74ms

---

## 七、总结

### 7.1 各指标正常范围

| 指标 | 正常值 | 异常阈值 |
|------|--------|----------|
| client_req_framework | < 100us | > 500us |
| client_rsp_framework | < 100us | > 500us |
| server_req_queue | < 100us | > 1000us |
| server_exec | < 1000us | > 5000us |
| server_rsp_queue | ≈ network | > 2x network |
| network_residual | < 10ms | > 20ms |

### 7.2 异常案例汇总

| Trace | 异常指标 | 数值 | 根因 |
|-------|----------|------|------|
| 0c3d819d | network_residual | 82509us | URMA 连接重建 |
| 1051ba83 | server_req_queue | 3068us | Worker2 线程池饱和 |
| 26842642 | server_rsp_queue | 4084us | Worker1 响应发送瓶颈 |

---

## 附录 A：代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/common/rpc/zmq/zmq_constants.h` | ZMQ RPC 指标定义 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker1 Get 请求处理 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker2 RPC Server 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理 |
