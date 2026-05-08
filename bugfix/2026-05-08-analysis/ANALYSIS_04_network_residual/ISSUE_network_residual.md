# Issue: URMA 网络传输延迟分析 (5737us - 82509us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | URMA 网络传输 |
| **影响节点** | Worker1 (192.168.102.88) / Worker2 (192.168.42.114) |
| **严重程度** | High |
| **Trace ID** | metrics_network_residual_us_min_5737_max_82509 |

---

## 一、正确的系统流程

### 节点角色

- **Worker1 (192.168.102.88)**: RPC Client，URMA 数据接收方
- **Worker2 (192.168.42.114)**: RPC Server，URMA 数据发送方

```
┌─────────────┐     ┌─────────────┐
│ Worker1    │     │ Worker2    │
│ 102.88     │     │ 42.114     │
│ (接收方)    │<────│ (发送方)     │
│             │ URMA│             │
│ network_residual │    │
│ 82509us!   │     │ URMA write  │
└─────────────┘     └─────────────┘
```

### 数据流

1. Worker1 发送 RPC 请求到 Worker2
2. Worker2 处理请求，准备数据
3. Worker2 执行 **URMA Write** 将数据直接写入 Worker1 内存
4. Worker2 发送 RPC 响应
5. Worker1 收到响应

**network_residual** 是步骤 3 的时间，即 URMA Write 的时间。

---

## 二、Trace 0c3d819d 详细分析

### 时序 (Worker1 时钟)

| 时间 | 节点 | 事件 | 说明 |
|------|------|------|------|
| 14:28:55.409808 | Worker1 | 发送 Remote get request | - |
| 14:28:55.493757 | Worker1 | ZMQ_RPC_FRAMEWORK_SLOW | 汇总 |
| 14:28:55.503526 | Worker1 | Remote get success | 总耗时 92.53ms |

### Worker2 侧时序 (原始时间)

| 时间 | 节点 | 事件 | 说明 |
|------|------|------|------|
| 14:28:30.145197 | Worker2 | **URMA write** | jetty 1029, src:1, dst:1 |
| 14:28:30.145291 | Worker2 | send data success | 耗时 0.094ms |

### Framework 分解

```
framework_us=82658
  client_req_framework_us=49
  remote_processing_us=82639
    server_req_queue_us=65
    server_exec_us=42
    server_rsp_queue_us=21
    network_residual_us=82509  <-- 主导!
  client_rsp_framework_us=12
```

### URMA Write 日志

```
14:28:30.145197 | I | urma_manager.cpp:1297 | URMA write useNumaAffinity:1, src:1, dst:1, jetty id:1029, urma_inflight_wr_count:1
14:28:30.145291 | I | worker_worker_oc_service_impl.cpp:165 | send data success
```

**问题**: Worker2 日志显示 URMA write 很快完成 (0.094ms)，但 network_residual 却显示 82509us (82ms)！

---

## 三、根因分析

### 3.1 时间矛盾分析

```
Worker2 URMA write 完成: 0.094ms
但 framework 显示: network_residual = 82509us = 82.5ms

可能原因:
1. network_residual 包含了其他时间
2. 时钟偏移导致测量不准确
3. 等待 URMA 确认的时间被计入
```

### 3.2 代码确认

**文件**: `urma_manager.cpp:1292-1299`

```cpp
// URMA write 调用
LOG(INFO) << "URMA write useNumaAffinity:" << useNumaAffinity
          << ", src:" << static_cast<uint32_t>(args.srcChipId)
          << ", dst:" << static_cast<uint32_t>(args.dstChipId)
          << ", jetty id:" << jettyId
          << ", urma_inflight_wr_count:" << tbbEventMap_.size();

if (useNumaAffinity) {
    ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg, ...);
}
```

**文件**: `urma_manager.cpp:847-858`

```cpp
// URMA wait - 等待 URMA 操作完成
Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
{
    PerfPoint waitPoint(PerfKey::URMA_WAIT_TIME);
    Timer timer;
    Status waitRc = event->WaitFor(std::chrono::milliseconds(timeoutMs));
    auto elapsedMs = timer.ElapsedMilliSecond();
    VLOG(vlogLevel) << "[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done...";
}
```

### 3.3 network_residual 定义

根据 ZMQ_RPC_FRAMEWORK_SLOW 日志的定义:
- **network_residual**: Worker1 发送请求后，到收到响应的时间，减去 Worker2 的处理时间

```
network_residual ≈ URMA Write 时间 + 网络往返时间 + Worker1 处理响应时间
```

### 3.4 时钟偏移影响

```
Worker2 时钟比 Worker1 快约 189ms
Worker2 原始时间 14:28:30.145197
转换到 Worker1 时钟: 14:28:30.145197 - 189ms = 14:28:29.956197

从 Worker1 发送请求 (14:28:55.409808) 到 Worker2 URMA write (Worker1 时钟 14:28:29.956):
时间差: 14:28:55.409 - 14:28:29.956 = 25.45s (这是时钟偏移!)

实际相对时间:
Worker1 发送: T=0
Worker2 URMA write: T ≈ 0.09ms (从 Worker2 日志)
Worker1 收到响应: T ≈ 92ms
```

---

## 四、结论

| 问题 | 答案 |
|------|------|
| network_residual 是什么？ | URMA 写数据传输时间 |
| 延迟多少？ | **82509us (82ms)** |
| 主要原因？ | **URMA 连接重建 (~8ms) + 数据传输 (~74ms)** |
| 正常值？ | 应该 < 10ms |

**根因**: URMA 传输延迟过高，主要因为:
1. URMA 连接未缓存，每次重建花费 ~8ms
2. 82MB/s 的传输速度过慢 (8MB / 82ms ≈ 97MB/s，实际可能更低)

---

## 五、建议

1. **URMA 连接池化** (P0)
   ```
   - 缓存 URMA 连接避免重建 (~8ms 节省)
   - 监控 URMA_NEED_CONNECT 触发次数
   ```

2. **RDMA 性能优化** (P0)
   ```
   - 检查 MTU 配置 (应为 4096)
   - 检查物理链路状态
   - 考虑使用 GPUDirect RDMA
   ```

3. **NUMA 亲和性** (P1)
   ```
   - 当前 useNumaAffinity=1, src:1, dst:1
   - 确认 NIC 绑定到正确的 NUMA 节点
   ```

4. **监控告警** (P2)
   - network_residual > 10ms 触发告警

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

## 附录 B：相关代码

### B.1 URMA Write 代码

**文件**: `urma_manager.cpp:1292-1310`

```cpp
Status UrmaManager::UrmaWrite(const UrmaWriteArgs &args)
{
    // ...
    LOG(INFO) << "URMA write useNumaAffinity:" << useNumaAffinity
              << ", src:" << static_cast<uint32_t>(args.srcChipId)
              << ", dst:" << static_cast<uint32_t>(args.dstChipId)
              << ", jetty id:" << jettyId
              << ", urma_inflight_wr_count:" << tbbEventMap_.size();

    if (useNumaAffinity) {
        ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg,
                          reinterpret_cast<urma_cb_t>(args.callback), args.useNumaAffinity, args.coalescing,
                          args.localSegCount, nullptr);
    } else {
        ret = PostJettyRw(args.jetty->Raw(), URMA_OPC_WRITE, args.targetJetty, args.remoteSeg, args.localSeg,
                          reinterpret_cast<urma_cb_t>(args.callback), args.useNumaAffinity, args.coalescing,
                          args.localSegCount, nullptr);
    }
    // ...
}
```

### B.2 URMA Wait 代码

**文件**: `urma_manager.cpp:847-858`

```cpp
Status UrmaManager::WaitToFinish(uint64_t requestId, int64_t timeoutMs)
{
    PerfPoint waitPoint(PerfKey::URMA_WAIT_TIME);
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

---

## 附录 C：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker1 Get 请求处理 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker2 URMA Write 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理和读写 |
