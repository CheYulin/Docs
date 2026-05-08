# Issue: Worker2 服务端执行延迟分析 (1428us - 3206us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | Worker2 服务端执行 |
| **影响节点** | Worker2 (192.168.42.114) |
| **严重程度** | Medium |
| **Trace ID** | metrics_server_exec_us_min_1428_max_3206 |

---

## 一、正确的系统流程

### 节点角色

- **Worker1 (192.168.102.88)**: RPC Client
- **Worker2 (192.168.42.114)**: RPC Server，执行方
- **Master (192.168.215.24)**: 元数据服务

```
┌─────────────┐     ┌─────────────┐     ┌─────────┐
│ Worker1    │────>│ Worker2    │────>│ Master  │
│ 102.88     │     │ 42.114     │     │ 215.24  │
│ (RPC Client)│     │(RPC Server) │     │         │
└─────────────┘     │ server_exec│     └─────────┘
                    │ (1428-3206us)│
                    └─────────────┘
```

---

## 二、Trace 分析

### Framework 分解

```
framework_us=82658
  client_req_framework_us=49        // Worker1 准备请求
  remote_processing_us=82639
    server_req_queue_us=65          // Worker2 请求排队
    server_exec_us=1428            // Worker2 执行 (异常!)
    server_rsp_queue_us=21        // Worker1 响应排队
    network_residual_us=82509      // URMA 传输
  client_rsp_framework_us=12        // Worker1 接收响应
```

### 延迟分布

```
总 E2E: 82.7ms

Worker2 侧:
- server_req_q: 65us (0.08%)
- server_exec: 1428us (1.7%)  <-- 这个 trace 较高
- 小计: 1493us (1.8%)

网络传输:
- network_residual: 82509us (99.8%)  <-- 主导!
```

---

## 三、根因分析

### 3.1 server_exec 组成

server_exec 是 Worker2 处理请求的时间，包括：
1. **读取请求**: 解析 protobuf
2. **查询本地缓存**: 检查对象是否在本地
3. **读取数据**: 从内存/磁盘读取对象数据
4. **写 URMA**: 发起 URMA 写操作

### 3.2 代码确认

**文件**: `worker_worker_oc_service_impl.cpp:134-168`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(
    std::shared_ptr<::datasystem::ServerUnaryWriterReader<GetObjectRemoteRspPb, GetObjectRemoteReqPb>> serverApi)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    PerfPoint point(PerfKey::WORKER_SERVER_GET_REMOTE);
    GetObjectRemoteReqPb req;
    GetObjectRspPb rsp;
    std::vector<RpcMessage> payload;

    PerfPoint pointImpl(PerfKey::WORKER_SERVER_GET_REMOTE_READ);
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "GetObjectRemote read error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_IMPL);

    // K_OC_REMOTE_GET_NOT_ENOUGH error happens only when URMA is used for RDMA
    RETURN_IF_NOT_OK(CheckConnectionStable(req));
    RETURN_IF_NOT_OK_EXCEPT(GetObjectRemote(req, rsp, payload), StatusCode::K_OC_REMOTE_GET_NOT_ENOUGH);
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_WRITE);
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Write(rsp), "GetObjectRemote write error");
    pointImpl.RecordAndReset(PerfKey::WORKER_SERVER_GET_REMOTE_SENDPAYLOAD);

    if (rsp.data_source() == DataTransferSource::DATA_ALREADY_TRANSFERRED
        || rsp.data_source() == DataTransferSource::DATA_DELAY_TRANSFER
        || rsp.data_source() == DataTransferSource::DATA_ALREADY_TRANSFERRED_MEMSET_META) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload({}, FLAGS_oc_worker_worker_direct_port > 0),
                                         "GetObjectRemote send payload error");
    } else if (rsp.data_source() == DataTransferSource::DATA_IN_PAYLOAD) {
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->SendAndTagPayload(payload, FLAGS_oc_worker_worker_direct_port > 0),
                                         "GetObjectRemote send payload error");
    }

    pointImpl.Record();
    return Status::OK();
}
```

### 3.3 GetObjectRemoteHandler

**文件**: `worker_worker_oc_service_impl.cpp:170-182`

```cpp
Status WorkerWorkerOCServiceImpl::GetObjectRemote(GetObjectRemoteReqPb &req, GetObjectRemoteRspPb &rsp,
                                                  std::vector<RpcMessage> &payload)
{
    METRIC_TIMER(metrics::KvMetricId::WORKER_RPC_REMOTE_GET_INBOUND_LATENCY);
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(akSkManager_->VerifySignatureAndTimestamp(req), "AK/SK failed.");
    const std::string callerAddress = GetRemoteAddressForLog(req);
    LOG(INFO) << AppendSrcDstForLog(FormatString("Processing pull object[%s] offset[%ld] size[%ld]",
                                                 req.object_key(),
                                                 req.read_offset(), req.read_size()),
                                    callerAddress, FLAGS_worker_address);
    std::vector<uint64_t> eventKeys;
    RETURN_IF_NOT_OK(GetObjectRemoteHandler(req, rsp, payload, true, eventKeys));
    return Status::OK();
}
```

---

## 四、结论

| 问题 | 答案 |
|------|------|
| server_exec 是什么？ | Worker2 执行请求的时间 |
| 延迟多少？ | **1428us - 3206us** |
| 正常值？ | 应该 < 1000us |
| 根因？ | 数据读取或 URMA 准备开销 |

**server_exec 相对较高但不是主要瓶颈**，因为 network_residual 占了 99.8%。

---

## 附录 A：全量日志

### Trace 0c3d819d Worker2 侧全量日志

```
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

## 附录 B：相关代码

### B.1 GetObjectRemoteHandler

**文件**: `worker_worker_oc_service_impl.cpp` (约 400-600 行)

```cpp
// GetObjectRemoteHandler 是实际处理请求的函数
// 1. 验证 AK/SK
// 2. 查询本地 ObjectKV
// 3. 如果命中，从共享内存读取数据
// 4. 准备 URMA 写操作
Status WorkerWorkerOCServiceImpl::GetObjectRemoteHandler(...)
{
    // ...
}
```

### B.2 URMA Write 代码

**文件**: `urma_manager.cpp:1292-1310`

```cpp
if (useNumaAffinity) {
    INJECT_POINT("UrmaManager.UrmaWriteNumaAffinity");
    ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg,
                      reinterpret_cast<urma_cb_t>(args.callback), args.useNumaAffinity, args.coalescing,
                      args.localSegCount, nullptr);
} else {
    ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg,
                      reinterpret_cast<urma_cb_t>(args.callback), args.useNumaAffinity, args.coalescing,
                      args.localSegCount, nullptr);
}
```

---

## 附录 C：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker-to-Worker RPC 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理和读写 |
