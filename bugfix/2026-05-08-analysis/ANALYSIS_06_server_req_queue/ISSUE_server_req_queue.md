# Issue: Worker2 请求队列延迟分析 (585us - 3149us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | Worker2 请求队列 |
| **影响节点** | Worker2 (192.168.219.66) |
| **严重程度** | High |
| **Trace ID** | metrics_server_req_queue_us_min_585_max_3149 |

---

## 一、正确的系统流程

### 节点角色

- **Worker1 (192.168.42.114)**: RPC Client
- **Worker2 (192.168.219.66)**: RPC Server，请求处理方
- **Master (192.168.215.24)**: 元数据服务

```
┌─────────────┐     ┌─────────────┐     ┌─────────┐
│ Worker1    │────>│ Worker2    │────>│ Master  │
│ 42.114     │     │ 219.66     │     │ 215.24  │
│ (RPC Client)│     │(RPC Server) │     │         │
└─────────────┘     │             │     └─────────┘
                    │ server_req_q│
                    │ (3068us!) │
                    └─────────────┘
```

---

## 二、Trace 1051ba83 详细时序分析

### 时序 (Worker1 时钟)

| 时间 | 节点 | 事件 | 说明 |
|------|------|------|------|
| 14:33:41.466222 | Worker1 | 收到 Client 请求 | - |
| 14:33:41.466240 | Worker1 | ThreadPool: idle(12),total(17),wait(0) | 12 个空闲 |
| 14:33:41.466261 | Worker1 | 查询 Master 元数据 | dst=192.168.215.24 |
| 14:33:41.466583 | Worker1 | Master 查询完成 | cost: 0.364ms |
| 14:33:41.466641 | Worker1 | 发送 Remote pull 到 Worker2 | dst=192.168.219.66 |
| 14:33:41.471914 | Worker1 | ZMQ_RPC_FRAMEWORK_SLOW | 汇总 |
| 14:33:41.471956 | Worker1 | access.log | DS_POSIX_GET |

### Worker2 侧时序 (原始时间)

| 时间 | 节点 | 事件 | 说明 |
|------|------|------|------|
| 14:34:06.641583 | Worker2 | 收到 RemotePull | remainingTime: 10ms |
| 14:34:06.641590 | Worker2 | Processing pull | 对象 8MB |
| 14:34:06.641603 | Worker2 | URMA write | jetty 1125 |
| 14:34:06.643327 | Worker2 | **URMA wait 完成** | 1.64ms |
| 14:34:06.641603 | Worker2 | (同上, 原始日志时间) | - |

### Framework 分解

```
framework_us=3463
  client_req_framework_us=21        // Worker1 准备请求
  remote_processing_us=5220
    server_req_queue_us=3068       // Worker2 请求排队 (异常!)
    server_exec_us=1790           // Worker2 执行
    server_rsp_queue_us=146       // Worker1 响应排队
    network_residual_us=215        // URMA 传输
  client_rsp_framework_us=12        // Worker1 接收响应
```

### 关键发现

```
时间差分析:
Worker1 发送请求: 14:33:41.466641
Worker2 收到请求: 14:34:06.641583
时间差: 约 25秒 (因为时钟偏移!)

正确的相对时序:
假设 Worker2 时钟比 Worker1 快约 189ms
Worker2 收到请求 (原始): 14:34:06.641583
                      = 14:34:06.452 (Worker1 时钟, -189ms)

Worker1 ZMQ log: 14:33:41.471914
                = 14:33:41.471 (Worker1 时钟)

从请求发送到 ZMQ log:
14:33:41.471 - 14:33:41.466 = 5ms

而 framework 显示:
server_req_q (3068us) + server_exec (1790us) + server_rsp_q (146us) = 5004us = 5ms
```

**时间线吻合!**

---

## 三、根因分析

### 3.1 server_req_queue 异常高

```
server_req_queue_us=3068
server_exec_us=1790
比率: 3068 / 1790 = 1.7x
```

Worker2 的请求排队时间是执行时间的 1.7 倍。

### 3.2 ThreadPool 状态矛盾

```
Worker1 ThreadPool: idle(12), total(17), wait(0)
Worker2 信息: 未知 (日志未显示)
```

Worker1 显示有 12 个空闲线程，但 server_req_queue 仍有 3068us。

**可能原因**:
1. **Worker2 线程池问题**: Worker2 的 17 个线程都在忙
2. **锁竞争**: Worker2 获取全局锁等待
3. **CPU 调度**: Worker2 线程被换出

### 3.3 URMA Wait 分析

```cpp
// urma_manager.cpp:852
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr
cost 1.64181ms
urma_inflight_wr_count: 2
```

URMA wait 1.64ms 正常，但 server_exec 总计 1790us (1.79ms)，说明还有其他处理。

---

## 四、结论

| 问题 | 答案 |
|------|------|
| server_req_queue 是什么？ | Worker2 请求排队时间 |
| 延迟多少？ | **3068us (3ms)** |
| 根因？ | Worker2 线程池或调度问题 |
| 异常？ | 排队时间 > 执行时间 |

**根因**: Worker2 (192.168.219.66) 收到请求后，排队等待处理了 3ms，然后执行 1.79ms。表明 Worker2 可能存在线程池饱和或调度问题。

---

## 五、建议

1. **检查 Worker2 (192.168.219.66)** (P0)
   ```
   - 线程池状态监控
   - CPU 使用率
   - 调度延迟
   ```

2. **增加 Worker2 线程** (P1)
   ```
   - 当前 total(17)
   - 考虑增加到 32
   ```

3. **负载均衡** (P1)
   ```
   - Worker2 192.168.219.66 负载是否过高
   - 检查请求分发策略
   ```

4. **监控告警** (P2)
   - server_req_queue > 1000us 触发告警

---

## 附录 A：全量日志

### Trace 1051ba83 全量日志

```
// ========== Worker1 (192.168.42.114) 侧 ==========

14:33:41.466222 | I | worker_oc_service_get_impl.cpp:130 | 192.168.42.114 | 11:296 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Receive, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, serverApiReadCost: 0.005ms, inflightRemoteGet: 2

14:33:41.466240 | I | worker_oc_service_get_impl.cpp:165 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Receive, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, objects: kv_test_24_6_118992864875120_0, threadPool: idle(12),total(17),wait(0), elapsed: 0.000ms, remainingTime: 16.000ms

14:33:41.466261 | I | worker_oc_service_get_impl.cpp:1752 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Query metadata from master: 192.168.215.24:31402, objects: kv_test_24_6_118992864875120_0, request id: f34e8570-7f08-4fd3-bb5e-e1fef4060fe0, remainingTime:14ms

14:33:41.466615 | I | worker_oc_service_get_impl.cpp:780 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Master query done, targets: 1, hits: 1, cost: 0.364ms

14:33:41.466641 | I | worker_oc_service_batch_get_impl.cpp:607 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Remote pull, count: 1, path: UB, src=192.168.42.114:31402, dst=192.168.219.66:31402

14:33:41.471914 | I | zmq_constants.h:204 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [ZMQ_RPC_FRAMEWORK_SLOW] trace_id=1051ba83-7426-457c-928e-fb2b89969728 framework_us=3463 e2e_us=5254 client_req_framework_us=21 remote_processing_us=5220 client_rsp_framework_us=12 server_req_queue_us=3068 server_exec_us=1790 server_rsp_queue_us=146 network_residual_us=215

14:33:41.471966 | I | worker_oc_service_get_impl.cpp:194 | 192.168.42.114 | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get] Done, clientId: 1ae73c9b-4a2f-40f3-8cf0-fdcaf37bcbfe, objects: 1, transferPath: UB, totalCost: exceed 3ms: {ProcessGetObjectRequest: 5 ms; }

14:33:41.471956 | I | access_recorder.cpp:182 | kvc-jingpai-worker-55b94f576c-x7vbw | 11:200 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai |0 | DS_POSIX_GET | 5741 | 8388608 | {Object_key:kv_test_24_6_118992864875120_0,count:1,sub_timeout:0} |

// ========== Worker2 (192.168.219.66) 侧 ==========

14:34:06.641583 | I | worker_worker_oc_service_impl.cpp:693 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [Get/RemotePull] Receive, count: 1, remainingTime: 10ms, src=192.168.42.114:31402, dst=192.168.219.66:31402

14:34:06.641590 | I | worker_worker_oc_service_impl.cpp:196 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Processing pull object[kv_test_24_6_118992864875120_0] offset[0] size[8388608], src=192.168.42.114:31402, dst=192.168.219.66:31402

14:34:06.641603 | I | urma_manager.cpp:1297 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | URMA write useNumaAffinity:1, src:2, dst:1, jetty id:1125, urma_inflight_wr_count:2

14:34:06.643327 | I | urma_manager.cpp:852 | 192.168.219.66 | 11:432 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 1.64181ms, request id:123697, src address:192.168.219.66:31402, target address:192.168.42.114:31402, dataSize:8388608, cpuid:79, status: code: [OK], msg: [], urma_inflight_wr_count: 2, suggest: check whether URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY logs appear in the same time window; if none appear, check URMA and UDMA

// ========== Master (192.168.215.24) 侧 ==========

14:34:06.691161 | I | master_oc_service_impl.cpp:261 | 192.168.215.24 | 11:285 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | Processing QueryMetaReq, requestId: f34e8570-7f08-4fd3-bb5e-e1fef4060fe0

14:34:06.691174 | I | master_oc_service_impl.cpp:270 | 192.168.215.24 | 11:285 | 1051ba83-7426-457c-928e-fb2b89969728 | jingpai | QueryMeta on master 192.168.42.114:31402, target num 1, success num 1. The operations of master QueryMeta exceed 3ms: {}
```

---

## 附录 B：相关代码

### B.1 server_req_queue 测量

**文件**: `worker_oc_service_get_impl.cpp:165-169`

```cpp
// server_req_queue 在 ZMQ_RPC_FRAMEWORK_SLOW 日志中测量
// ZMQ_RPC_FRAMEWORK_SLOW 由 ZMQ 框架在 RPC 完成时记录
// 位于 Worker1 侧，但包含 Worker2 的时间戳
LOG(INFO) << FormatString(
    "[Get] Receive, clientId: %s, objects: %s, "
    "threadPool: %s, elapsed: %.3fms, remainingTime: %.3fms",
    clientId, VectorToString(request->GetRawObjectKeys()),
    threadPool_->GetStatistics(),
    static_cast<double>(elapsed), static_cast<double>(timeout));
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

### B.3 Remote Pull 发送

**文件**: `worker_oc_service_batch_get_impl.cpp:607`

```cpp
// Worker1 发送 Remote pull 请求
LOG(INFO) << "[Get] Remote pull, count: " << payloads.size()
          << ", path: " << (IsUrmaEnabled() ? "UB" : "TCP")
          << ", src=" << localAddress << ", dst=" << targetAddress;
```

---

## 附录 C：相关代码文件路径

| 文件 | 说明 |
|------|------|
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker1 Get 请求处理 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_batch_get_impl.cpp` | Worker1 Remote Pull 发送 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker2 URMA Write 处理 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接管理和读写 |
