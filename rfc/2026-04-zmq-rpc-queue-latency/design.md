# Design: ZMQ RPC 队列时延可观测

## 1. 背景与目标

### 1.1 问题

当前 RPC 框架的延迟只能看到端到端（E2E）时间，无法定位瓶颈在哪个阶段：

```
E2E 延迟高 = Client 框架慢？ Client Socket 慢？ 网络慢？ Server 队列慢？ Server 执行慢？ Server 回复慢？
```

### 1.2 目标

通过在 `MetaPb.ticks` 中记录关键时间点，在 Client 侧计算各阶段延迟，实现：

1. **自证清白**：任何一个阶段的延迟都可以被独立识别
2. **最小代价**：不新增 proto 字段，不修改网络协议
3. **进程内计算**：所有 Metric 在进程内完成统计

---

## 2. 时间线与 Tick 定义

### 2.1 完整路径时间线

```
                    CLIENT                                 SERVER
                       │                                     │
                       │          REQUEST PATH               │
                       ▼                                     ▼
               ┌───────────────────────────────────────────────────────────────┐
               │                                                                   │
   CLIENT_ENQUEUE ────┬──── CLIENT_TO_STUB ────┬──── CLIENT_SEND              │
       │              │         │              │         │                      │
       │   CLIENT     │         │   CLIENT     │         │   SERVER               │
       │  QUEUING     │         │ STUB_SEND   │         │  QUEUE_WAIT           │
       │              │         │              │         │        │                │
       │◄────────────┼─────────┼─────────────┼─────────┼────────┼────────────────►│
       │              │         │              │         │        │                 │
       │              │         │              │         │        │                 │
       │              │         │              │         │ SERVER_RECV           │
       │              │         │              │         │◄────────┼────────────────►│
       │              │         │              │         │        │                 │
       │              │         │              │         │        │                 │
   ────┴─────────────┴─────────┴──────────────┴─────────┴────────┴─────────────────┴────────►
   CLIENT_ENQUEUE   CLIENT_TO_STUB CLIENT_SEND  SERVER_RECV SERVER_DEQUEUE SERVER_EXEC_END SERVER_SEND CLIENT_RECV
```

### 2.2 Tick 定义（8个）

| Tick 名称 | 记录位置 | 进程 | 用途 |
|-----------|---------|------|------|
| `CLIENT_ENQUEUE` | `mQue->SendMsg()` 之前 | Client | 入口时间戳 |
| `CLIENT_TO_STUB` | `RouteToZmqSocket()` 之前 | Client | 即将进入 ZmqFrontend |
| `CLIENT_SEND` | `RouteToZmqSocket()` 末尾，SendAllFrames 之后 | Client | Socket 发送完成 |
| `CLIENT_RECV` | `AsyncReadImpl()` 收到响应后 | Client | Client 收到响应 |
| `SERVER_RECV` | `ClientToService()` ParseMsgFrames 之后 | Server | Socket 接收完成 |
| `SERVER_DEQUEUE` | `RouteToRegBackend()` lambda 执行前 | Server | Server 队列出队 |
| `SERVER_EXEC_END` | `WorkerEntryImpl()` SendStatus 之前 | Server | Server 业务处理完成 |
| `SERVER_SEND` | `ServiceToClient()` replyQueue->Put 之前 | Server | Server 回复已入队 |

### 2.3 常量定义

**文件**: `src/datasystem/common/rpc/zmq/zmq_constants.h`

```cpp
namespace datasystem {

// ==================== RPC Tracing Ticks ====================
inline constexpr const char* TICK_CLIENT_ENQUEUE = "CLIENT_ENQUEUE";
inline constexpr const char* TICK_CLIENT_TO_STUB = "CLIENT_TO_STUB";
inline constexpr const char* TICK_CLIENT_SEND = "CLIENT_SEND";
inline constexpr const char* TICK_CLIENT_RECV = "CLIENT_RECV";
inline constexpr const char* TICK_SERVER_RECV = "SERVER_RECV";
inline constexpr const char* TICK_SERVER_DEQUEUE = "SERVER_DEQUEUE";
inline constexpr const char* TICK_SERVER_EXEC_END = "SERVER_EXEC_END";
inline constexpr const char* TICK_SERVER_SEND = "SERVER_SEND";

}  // namespace datasystem
```

---

## 3. Metric 定义

### 3.1 Metric 清单

**文件**: `src/datasystem/common/metrics/kv_metrics.h`

```cpp
// 在 ZMQ_RPC_DESERIALIZE_LATENCY 之后新增：

ZMQ_RPC_SERIALIZE_LATENCY,
ZMQ_RPC_DESERIALIZE_LATENCY,
// Client 侧
ZMQ_CLIENT_QUEUING_LATENCY,       // CLIENT_TO_STUB - CLIENT_ENQUEUE（MsgQue 队列等待）
ZMQ_CLIENT_STUB_SEND_LATENCY,     // CLIENT_SEND - CLIENT_TO_STUB（ZmqFrontend + Socket 发送）
// Server 侧
ZMQ_SERVER_QUEUE_WAIT_LATENCY,     // SERVER_DEQUEUE - SERVER_RECV
ZMQ_SERVER_EXEC_LATENCY,           // SERVER_EXEC_END - SERVER_DEQUEUE
ZMQ_SERVER_REPLY_LATENCY,         // SERVER_SEND - SERVER_EXEC_END
// E2E
ZMQ_RPC_E2E_LATENCY,             // CLIENT_RECV - CLIENT_ENQUEUE
ZMQ_RPC_NETWORK_LATENCY,          // E2E - SERVER_EXEC

WORKER_ALLOCATOR_ALLOC_BYTES_TOTAL,
```

**根因对照表**：

| Metric | 可能根因 |
|--------|---------|
| `CLIENT_QUEUING_LATENCY` | MsgQue (Client → Prefetcher 之间的队列) 堆积，prefetcher 处理不过来 |
| `CLIENT_STUB_SEND_LATENCY` | ZmqFrontend 线程繁忙，或 zmq_msg_send 系统调用慢 |

### 3.2 Metric 正交性

所有 5 个开销 metric 都是**正交**的（时间不重叠）：

|  | CLIENT_QUEUING | CLIENT_STUB_SEND | SERVER_QUEUE_WAIT | SERVER_EXEC | SERVER_REPLY |
|--|-----------------|------------------|------------------|-------------|--------------|
| **CLIENT_QUEUING** | - | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 |
| **CLIENT_STUB_SEND** | ✓ 不重叠 | - | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 |
| **SERVER_QUEUE_WAIT** | ✓ 不重叠 | ✓ 不重叠 | - | ✓ 不重叠 | ✓ 不重叠 |
| **SERVER_EXEC** | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 | - | ✓ 不重叠 |
| **SERVER_REPLY** | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 | ✓ 不重叠 | - |

---

## 4. 计算公式

### 4.1 Client 侧计算（AsyncReadImpl）

```cpp
// 1. 记录 CLIENT_RECV tick
GetLapTime(rsp.first, TICK_CLIENT_RECV);

// 2. 计算 E2E
uint64_t e2eNs = GetTotalTime(rsp.first);

// 3. 提取各阶段 tick
int64_t clientEnqueueTs = 0, clientSendTs = 0;
uint64_t serverExecNs = 0;
for (int i = 0; i < rsp.first.ticks_size(); i++) {
    const auto& tick = rsp.first.ticks(i);
    if (strcmp(tick.tick_name(), TICK_CLIENT_ENQUEUE) == 0) clientEnqueueTs = tick.ts();
    else if (strcmp(tick.tick_name(), TICK_CLIENT_SEND) == 0) clientSendTs = tick.ts();
    // SERVER_EXEC 时间通过 SERVER_EXEC_END - SERVER_RECV 计算
    else if (strcmp(tick.tick_name(), TICK_SERVER_EXEC_END) == 0) {
        // 需要配合 Server 侧传递的 SERVER_EXEC 时间
    }
}

// 4. 记录 Client 侧 metrics
// CLIENT_QUEUING = CLIENT_SEND - CLIENT_ENQUEUE（包含 QUEUING + STUB_SEND）
if (clientSendTs > clientEnqueueTs) {
    uint64_t clientTotalNs = clientSendTs - clientEnqueueTs;
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_CLIENT_QUEUING_LATENCY))
        .Observe(clientTotalNs);  // 这里实际是 CLIENT_QUEUING + CLIENT_STUB_SEND 的总和
}
if (e2eNs > 0) {
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_RPC_E2E_LATENCY)).Observe(e2eNs);
}
```

### 4.2 Server 侧计算（ServiceToClient）

```cpp
// 1. 提取各阶段 tick
int64_t serverRecvTs = 0, serverDequeuTs = 0, serverExecEndTs = 0, serverSendTs = 0;
for (int i = 0; i < meta.ticks_size(); i++) {
    const auto& tick = meta.ticks(i);
    if (strcmp(tick.tick_name(), TICK_SERVER_RECV) == 0) serverRecvTs = tick.ts();
    else if (strcmp(tick.tick_name(), TICK_SERVER_DEQUEUE) == 0) serverDequeuTs = tick.ts();
    else if (strcmp(tick.tick_name(), TICK_SERVER_EXEC_END) == 0) serverExecEndTs = tick.ts();
    else if (strcmp(tick.tick_name(), TICK_SERVER_SEND) == 0) serverSendTs = tick.ts();
}

// 2. 计算并记录 SERVER 侧各阶段
if (serverDequeuTs > serverRecvTs) {
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_SERVER_QUEUE_WAIT_LATENCY))
        .Observe(serverDequeuTs - serverRecvTs);
}
if (serverExecEndTs > serverDequeuTs) {
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_SERVER_EXEC_LATENCY))
        .Observe(serverExecEndTs - serverDequeuTs);
}
if (serverSendTs > serverExecEndTs) {
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_SERVER_REPLY_LATENCY))
        .Observe(serverSendTs - serverExecEndTs);
}

// 3. 计算 SERVER_EXEC 并通过 meta.ticks 传回 Client
uint64_t serverExecNs = serverExecEndTs - serverRecvTs;
TickPb execTick;
execTick.set_ts(serverExecNs);
execTick.set_tick_name("SERVER_EXEC_NS");  // 特殊 tick，ts 字段存计算值
meta.mutable_ticks()->Add(std::move(execTick));
```

### 4.3 Client 侧计算（补充：收到响应后）

```cpp
// 在 AsyncReadImpl 中，收到响应后继续计算
// 此时 meta.ticks 包含了 Server 追加的 SERVER_EXEC_NS

uint64_t serverExecNs = 0;
for (int i = 0; i < rsp.first.ticks_size(); i++) {
    if (strcmp(rsp.first.ticks(i).tick_name(), "SERVER_EXEC_NS") == 0) {
        serverExecNs = rsp.first.ticks(i).ts();  // 直接读取计算值
        break;
    }
}

// 计算 NETWORK = E2E - SERVER_EXEC
uint64_t networkNs = (e2eNs > serverExecNs) ? (e2eNs - serverExecNs) : 0;
if (networkNs > 0) {
    metrics::GetHistogram(
        static_cast<uint16_t>(metrics::KvMetricId::ZMQ_RPC_NETWORK_LATENCY)).Observe(networkNs);
}
```

---

## 5. 核心等式（自证清白）

```
E2E = CLIENT_FRAMEWORK + CLIENT_SOCKET + NETWORK + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY

NETWORK = E2E - SERVER_EXEC
        = CLIENT_FRAMEWORK + CLIENT_SOCKET + SERVER_QUEUE_WAIT + SERVER_REPLY + (actual network)
```

### 定界决策树

```
RPC 延迟高？
      │
      ├── CLIENT_FRAMEWORK 高 → Client 侧 MsgQue 队列拥挤
      ├── CLIENT_SOCKET 高 → Client ZmqFrontend/ZmqSocket 发送慢
      │
      ├── SERVER_QUEUE_WAIT 高 → Server 侧请求队列等待
      ├── SERVER_EXEC 高 → Server 业务逻辑慢
      ├── SERVER_REPLY 高 → Server 回复入队慢
      │
      └── NETWORK 高 → 网络延迟或 Server 队列/回复延迟传导
          ├── CLIENT_FRAMEWORK + CLIENT_SOCKET 正常 → Client 端无问题
          ├── SERVER_QUEUE_WAIT + SERVER_REPLY 正常 → Server 端无问题
          └── 则问题在网络本身
```

---

## 6. 改动文件清单

| 文件 | 改动类型 | 改动量 |
|------|---------|--------|
| `zmq_constants.h` | 新增常量 | ~10行 |
| `kv_metrics.h` | 新增 MetricId | ~8行 |
| `zmq_stub_impl.cpp` | Tick + 计算 | ~40行 |
| `zmq_stub_conn.cpp` | Tick 埋点 | ~10行 |
| `zmq_service.cpp` | Tick 埋点 + 计算 | ~60行 |

---

## 7. 向后兼容性

1. **旧 Server 无 SERVER_EXEC_NS**：Client 端 network = E2E（无法分离）
2. **旧 Client 不记录 Client 侧 Tick**：Server 侧 metrics 正常计算，Client 侧 E2E 正常计算
3. **ENABLE_PERF 关闭**：所有 tick 为空，计算返回 0
