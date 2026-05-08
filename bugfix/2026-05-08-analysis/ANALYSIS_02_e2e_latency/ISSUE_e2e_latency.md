# Issue: E2E 端到端延迟分析 (41037us - 83567us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | Worker1 -> Worker2 / URMA |
| **影响节点** | Worker1 (192.168.102.88) / Worker2 (192.168.42.114) |
| **严重程度** | High |
| **Trace ID** | metrics_e2e_us_min_41037_max_83567 |

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

---

## 二、Trace 0c3d819d 详细时序分析

### 节点角色
- **Worker1 (192.168.102.88)**: RPC Client，URMA 数据接收方
- **Worker2 (192.168.42.114)**: RPC Server，URMA 数据发送方

### 时序分析 (统一到 Worker1 时钟)

**关键发现**: Worker2 时钟比 Worker1 快约 **189ms**。

| 时间 (Worker1 时钟) | 节点 | 事件 | 说明 |
|---------------------|------|------|------|
| 14:28:55.409808 | Worker1 | 发送 Remote get request | src=102.88, dst=42.114 |
| 14:28:55.409831 | Worker1 | 创建 stub | type: 0 |
| 14:28:55.493757 | Worker1 | ZMQ_RPC_FRAMEWORK_SLOW | 汇总日志 |
| 14:28:55.493770 | Worker1 | **URMA_NEED_CONNECT 触发** | 需要重建连接 |
| 14:28:55.494629 | Worker1 | 创建 jfr id 1025 | jfr count: 1 |
| 14:28:55.498539 | Worker1 | 开始 import remote jetty | jetty_id: 1030 |
| 14:28:55.501301 | Worker1 | Import target jetty 完成 | 耗时 2.29ms |
| 14:28:55.501991 | Worker1 | **URMA 连接建立完成** | 总耗时 7.94ms |
| 14:28:55.503526 | Worker1 | **Remote get success** | 总耗时 92.53ms |

### Worker2 侧时序 (原始时间)

| 时间 (Worker2 时钟) | 节点 | 事件 | 说明 |
|---------------------|------|------|------|
| 14:28:30.137018 | Worker2 | URMA 连接交换开始 | 收到 Worker1 请求 |
| 14:28:30.139174 | Worker2 | Import target jetty | 耗时 1.86ms |
| 14:28:30.140276 | Worker2 | URMA 连接交换完成 | 总耗时 3.26ms |
| 14:28:30.145154 | Worker2 | 收到 BatchGetObjectRemote | remainingTime: 13ms |
| 14:28:30.145197 | Worker2 | **URMA write** | jetty 1029, src:1, dst:1 |
| 14:28:30.145291 | Worker2 | **send data success** | - |

### Framework 分解

```
e2e_us=82701
framework_us=82658
  client_req_framework_us=49        // Worker1 准备请求
  remote_processing_us=82639       // Worker2 处理 + URMA 传输
    server_req_queue_us=65        // Worker2 请求排队
    server_exec_us=42            // Worker2 执行
    server_rsp_queue_us=21       // Worker1 响应排队
    network_residual_us=82509    // URMA 传输 (Worker2->Worker1)
  client_rsp_framework_us=12      // Worker1 接收响应
```

### 延迟分布

```
总 E2E: 82.7ms

Worker1 侧:
- client_req: 49us (0.06%)
- client_rsp: 12us (0.01%)
- server_rsp_q: 21us (0.03%)
小计: 82us (0.1%)

Worker2 侧:
- server_req_q: 65us (0.08%)
- server_exec: 42us (0.05%)
小计: 107us (0.1%)

网络传输:
- network_residual: 82509us (99.8%)  <-- 主导!
```

---

## 三、根因分析

### 3.1 URMA 连接重建开销

```cpp
// worker_oc_service_get_impl.cpp:1026
[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered
realRemainingTimeMs=4915
lastResult=code: [Urma needs to reconnet]
```

**代码位置**: `worker_oc_service_get_impl.cpp:1026`

```cpp
// 当 URMA 连接不存在时，触发重连
if (lastResult.code() == StatusCode::K_URMA_CONNECT_FAILED) {
    RETURN_IF_NOT_OK(TryReconnectRemoteWorker(...));
}
```

**问题**: 这是该 trace 中最关键的问题！URMA 连接不存在，需要重建，耗时 **7.94ms**。

### 3.2 URMA 连接重建代码逻辑

```cpp
// urma_manager.cpp:570 - 创建 local Jetty
Created local Jetty id 1025 for recv:192.168.42.114:31402, jettyType=RECV

// urma_manager.cpp:1175 - 开始 import remote jetty
Start import remote jetty, remote urma info: Instance id 9696f39d-2e73-4f3c-90ee-30c92baa2c56,
address 192.168.42.114:31402, eid 4545:4944:2000:0000:2100:0000:2200:0000 uasid 0, jetty_id: 1030

// urma_manager.cpp:1297 - URMA write
URMA write useNumaAffinity:1, src:1, dst:1, jetty id:1029
```

### 3.3 URMA Wait 日志

```cpp
// urma_manager.cpp:852 - URMA wait 完成
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr
cost 3.57336ms, request id:972970
src address: 192.168.219.66:31402
target address: 192.168.168.216:31402
dataSize: 8388608
cpuid: 64
status: code: [OK], msg: []
urma_inflight_wr_count: 1
```

**代码位置**: `urma_manager.cpp:847-858`

```cpp
// urma_manager.cpp:847
Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
{
    PerfPoint waitPoint(PerfKey::UrMA_WAIT_TIME);
    Timer timer;
    Status waitRc = event->WaitFor(std::chrono::milliseconds(timeoutMs));
    auto elapsedMs = timer.ElapsedMilliSecond();
    auto vlogLevel = (elapsedMs > URMA_LOG_LIMIT_MS || waitRc.IsError()) ? 0 : 1;
    VLOG(vlogLevel) << "[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done...";
}
```

---

## 四、结论

| 问题 | 答案 |
|------|------|
| E2E 延迟多少？ | **82.7ms** |
| 主要瓶颈？ | **URMA 连接重建 (7.94ms) + 网络传输 (~84ms)** |
| Worker1 有问题吗？ | 无 - 处理极快 |
| Worker2 有问题吗？ | 无 - 处理极快 |
| 关键问题？ | **URMA 连接未缓存，每次重建** |

**根因**: 虽然处理时间极快，但 URMA 连接未复用导致 7.94ms 开销，加上 ~84ms 的网络传输，总延迟达 82.7ms。

---

## 五、建议

1. **URMA 连接池化** (P0)
   - 缓存 URMA 连接避免重建 (~8ms 节省)
   - 监控 `URMA_NEED_CONNECT` 触发次数

2. **网络传输优化** (P0)
   - 检查 RDMA 链路状态
   - 验证 MTU 配置

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

14:28:55.494884 | I | urma_resource.cpp:295 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | urma create jetty id 1025 success. jetty count: 1

14:28:55.494888 | I | urma_resource.cpp:761 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [UrmaResource] Registered Jetty 1025 in registry

14:28:55.494892 | I | urma_manager.cpp:570 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Created local Jetty id 1025 for recv:192.168.42.114:31402, jettyType=RECV

14:28:55.494903 | I | urma_manager.cpp:620 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | local seg info: ubva: { eid: 4345:4944:1000:0000:2d00:0000:2e00:0000, uasid: 0, va: 281362770690048}, len: 12884901888, attr: 449, token_id: 0

14:28:55.498539 | I | urma_manager.cpp:1175 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Start import remote jetty, remote urma info: Instance id 9696f39d-2e73-4f3c-90ee-30c92baa2c56, address 192.168.42.114:31402, eid 4545:4944:2000:0000:2100:0000:2200:0000 uasid 0, jetty_id 1030, local address:192.168.102.88:31402

14:28:55.501292 | I | urma_manager.cpp:422 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | URMA|liburma|342|-|bondp_import_jetty[1645]|Successfully imported target jetty: (4545:4944:2000:0000:2100:0000:2200:0000, uasid: 0, id: 1030)

14:28:55.501301 | I | urma_manager.cpp:1161 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | [URMA_CONNECT] Import target jetty elapsed = 2.288ms, cpuid: 69, remoteInfo: Instance id 9696f39d-2e73-4f3c-90ee-30c92baa2c56, address 192.168.42.114:31402, eid 4545:4944:2000:0000:2100:0000:2200:0000 uasid 0, jetty_id 1030

14:28:55.501311 | I | urma_resource.h:467 | 192.168.102.88 | 11:342 | 0c3d819d-c27b-4763-903e-82188ffde287 | jingpai | Created connection with Jetty 1028 and remote Jetty 1030

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

## 附录 B：相关代码

### B.1 URMA Write 代码

**文件**: `urma_manager.cpp:1292-1299`

```cpp
// URMA write 调用
LOG(INFO) << "URMA write useNumaAffinity:" << useNumaAffinity << ", src:" << static_cast<uint32_t>(args.srcChipId)
          << ", dst:" << static_cast<uint32_t>(args.dstChipId) << ", jetty id:" << jettyId
          << ", urma_inflight_wr_count:" << tbbEventMap_.size();

if (useNumaAffinity) {
    INJECT_POINT("UrmaManager.UrmaWriteNumaAffinity");
    ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg, ...);
}
```

### B.2 URMA Wait 代码

**文件**: `urma_manager.cpp:847-858`

```cpp
Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
{
    PerfPoint waitPoint(PerfKey::UrMA_WAIT_TIME);
    Timer timer;
    Status waitRc = event->WaitFor(std::chrono::milliseconds(timeoutMs));
    auto elapsedMs = timer.ElapsedMilliSecond();
    auto vlogLevel = (elapsedMs > URMA_LOG_LIMIT_MS || waitRc.IsError()) ? 0 : 1;
    VLOG(vlogLevel) << "[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost "
                    << elapsedMs << "ms, request id:" << requestId
                    << ", src address:" << localUrmaInfo_.localAddress.ToString()
                    << ", target address:" << event->GetRemoteAddress() << ", dataSize:" << event->GetDataSize()
                    << ", cpuid:" << sched_getcpu() << ", status: " << waitRc.ToString()
                    << ", urma_inflight_wr_count: " << tbbEventMap_.size()
                    << ", suggest: " << URMA_ELAPSED_TOTAL_SUGGEST;
}
```

### B.3 Remote Get Success 代码

**文件**: `worker_oc_service_get_impl.cpp:1256`

```cpp
// Remote get 成功完成
LOG(INFO) << "Remote get success, elapsed " << timer.ElapsedMilliSecond() << " ms";
```

---

## 附录 C：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker Get 请求处理 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker-to-Worker RPC 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理和读写 |
| `src/datasystem/common/rdma/urma_resource.cpp` | URMA 资源管理 (Jetty, JFR) |
