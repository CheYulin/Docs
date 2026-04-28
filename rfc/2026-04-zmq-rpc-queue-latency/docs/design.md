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

| Tick 名称 | 记录位置 | 进程 | 含义 |
|-----------|---------|------|------|
| `CLIENT_ENQUEUE` | `ZmqStubImpl.h L149`，`mQue->SendMsg()` 之前 | Client | Client 调用 stub 入口 |
| `CLIENT_TO_STUB` | `ZmqFrontend L403`，`msgQue_->Send()` 之前 | Client | 消息进入 frontend 发送队列 |
| `CLIENT_SEND` | `ZmqFrontend L124`，`SendAllFrames()` 之后 | Client | zmq_msg_send 返回，发送完成 |
| `CLIENT_RECV` | `ZmqStubImpl.h L213`，收到响应后 | Client | Client 收到完整 reply |
| `SERVER_RECV` | `ZmqService L1222`，`zmq_msg_recv` 返回后 | Server | Socket 接收完成 |
| `SERVER_DEQUEUE` | `ZmqService L755`，`WorkerEntryImpl()` 调用前 | Server | 从 worker 队列取出，开始处理 |
| `SERVER_EXEC_END` | `ZmqService L762`，`WorkerEntryImpl()` 返回后 | Server | 业务 handler 处理完成 |
| `SERVER_SEND` | `ZmqService L1030，`reply zmq_msg_send` 返回后 | Server | Server 回复发送完成 |

> **注意**：代码实际在 `WorkerEntryImpl` **返回之后**记录 `SERVER_EXEC_END`（而非之前）。这是因为 `ServiceToClient` 在 `WorkerEntryImpl` 内部被调用，`SERVER_EXEC_END` 必须在调用 `ServiceToClient` 之前记录，才能在 reply meta 中正确追加 tick。

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

// ==================== RPC Tracing Helpers ====================
inline uint64_t GetTimeSinceEpoch()
{
    return std::chrono::high_resolution_clock::now().time_since_epoch().count();
}

inline uint64_t RecordTick(MetaPb& meta, const char* tickName)
{
    auto ts = GetTimeSinceEpoch();
    TickPb tick;
    tick.set_ts(ts);
    tick.set_tick_name(tickName);
    meta.mutable_ticks()->Add(std::move(tick));
    return ts;
}

inline uint64_t GetTotalTicksTime(const MetaPb& meta)
{
    auto n = meta.ticks_size();
    if (n > 1) {
        return meta.ticks(n - 1).ts() - meta.ticks(0).ts();
    }
    return 0;
}

}  // namespace datasystem
```

---

## 3. Metric 定义

### 3.1 Metric 清单

**文件**: `src/datasystem/common/metrics/kv_metrics.h`

```cpp
// RPC Queue Flow Latency (新增 7 个 Histogram, ID 36-42)
ZMQ_CLIENT_QUEUING_LATENCY,       // CLIENT_TO_STUB - CLIENT_ENQUEUE
ZMQ_CLIENT_STUB_SEND_LATENCY,     // CLIENT_SEND - CLIENT_TO_STUB
ZMQ_SERVER_QUEUE_WAIT_LATENCY,     // SERVER_DEQUEUE - SERVER_RECV
ZMQ_SERVER_EXEC_LATENCY,           // SERVER_EXEC_END - SERVER_DEQUEUE
ZMQ_SERVER_REPLY_LATENCY,         // SERVER_SEND - SERVER_EXEC_END
ZMQ_RPC_E2E_LATENCY,               // CLIENT_RECV - CLIENT_ENQUEUE
ZMQ_RPC_NETWORK_LATENCY,           // E2E - (SERVER_EXEC + SERVER_QUEUE_WAIT)

WORKER_ALLOCATOR_ALLOC_BYTES_TOTAL,  // 原 ID 36 → 43
```

**根因对照表**：

| Metric | 含义 | 可能根因 |
|--------|------|---------|
| `CLIENT_QUEUING_LATENCY` | 消息在 client 侧入队列前的等待 | Client MsgQue 堆积，prefetcher 处理不过来 |
| `CLIENT_STUB_SEND_LATENCY` | ZmqFrontend 内部排队 + zmq_msg_send 耗时 | ZmqFrontend 线程繁忙，或 socket I/O 慢 |
| `SERVER_QUEUE_WAIT_LATENCY` | 消息在 server 侧 worker 队列中的等待 | Server 请求队列堆积 |
| `SERVER_EXEC_LATENCY` | 业务 handler 执行耗时 | 业务逻辑慢 |
| `SERVER_REPLY_LATENCY` | reply 的 zmq_msg_send 耗时 | socket buffer 满或网络抖动 |
| `RPC_E2E_LATENCY` | 端到端耗时 | - |
| `RPC_NETWORK_LATENCY` | 往返网络耗时（request 发送 + reply 接收） | 网络本身或 Server 框架慢传导 |

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

### 4.1 Client 侧计算

**位置**: `ZmqStubImpl.h` — `RecordRpcLatencyMetrics()`

```cpp
// E2E = CLIENT_RECV - CLIENT_ENQUEUE（通过 GetTotalTicksTime）
uint64_t e2eNs = GetTotalTicksTime(meta);

// 从 reply meta 中提取各 tick
uint64_t serverExecNs = FindTickTs(meta, "SERVER_EXEC_NS");
uint64_t clientEnqueueTs = FindTickTs(meta, TICK_CLIENT_ENQUEUE);
uint64_t clientToStubTs = FindTickTs(meta, TICK_CLIENT_TO_STUB);
uint64_t clientSendTs = FindTickTs(meta, TICK_CLIENT_SEND);

// NETWORK = E2E - SERVER_EXEC_NS
uint64_t networkNs = (e2eNs > serverExecNs) ? (e2eNs - serverExecNs) : 0;

// CLIENT_QUEUING = CLIENT_TO_STUB - CLIENT_ENQUEUE
if (clientToStubTs > clientEnqueueTs) {
    metrics::GetHistogram(ZMQ_CLIENT_QUEUING_LATENCY)
        .Observe(clientToStubTs - clientEnqueueTs);
}

// CLIENT_STUB_SEND = CLIENT_SEND - CLIENT_TO_STUB
if (clientSendTs > clientToStubTs) {
    metrics::GetHistogram(ZMQ_CLIENT_STUB_SEND_LATENCY)
        .Observe(clientSendTs - clientToStubTs);
}

// E2E
if (e2eNs > 0) {
    metrics::GetHistogram(ZMQ_RPC_E2E_LATENCY).Observe(e2eNs);
}

// NETWORK
if (networkNs > 0) {
    metrics::GetHistogram(ZMQ_RPC_NETWORK_LATENCY).Observe(networkNs);
}
```

### 4.2 Server 侧计算

**位置**: `ZmqService.cpp` — `RecordServerLatencyMetrics()`

```cpp
// 提取各 tick
int64_t serverRecvTs = FindTickTs(meta, TICK_SERVER_RECV);
int64_t serverDequeuTs = FindTickTs(meta, TICK_SERVER_DEQUEUE);
int64_t serverExecEndTs = FindTickTs(meta, TICK_SERVER_EXEC_END);
int64_t serverSendTs = FindTickTs(meta, TICK_SERVER_SEND);

// SERVER_QUEUE_WAIT = SERVER_DEQUEUE - SERVER_RECV
if (serverDequeuTs > serverRecvTs) {
    metrics::GetHistogram(ZMQ_SERVER_QUEUE_WAIT_LATENCY)
        .Observe(serverDequeuTs - serverRecvTs);
}

// SERVER_EXEC = SERVER_EXEC_END - SERVER_DEQUEUE
if (serverExecEndTs > serverDequeuTs) {
    metrics::GetHistogram(ZMQ_SERVER_EXEC_LATENCY)
        .Observe(serverExecEndTs - serverDequeuTs);
}

// SERVER_REPLY = SERVER_SEND - SERVER_EXEC_END
if (serverSendTs > serverExecEndTs) {
    metrics::GetHistogram(ZMQ_SERVER_REPLY_LATENCY)
        .Observe(serverSendTs - serverExecEndTs);
}

// 计算 SERVER_EXEC_NS 并追加到 meta.ticks 传回 Client
// ★ 注意：当前实现 = SERVER_EXEC_END - SERVER_RECV（包含 QUEUE_WAIT）
//   正确应为：SERVER_EXEC_END - SERVER_DEQUEUE
uint64_t serverExecNs = (serverExecEndTs > serverRecvTs) ? (serverExecEndTs - serverRecvTs) : 0;
TickPb execTick;
execTick.set_ts(serverExecNs);
execTick.set_tick_name("SERVER_EXEC_NS");
meta.mutable_ticks()->Add(std::move(execTick));
```

**调用位置**: `ZmqService::ServiceToClient()` L1030-1031：

```cpp
RecordTick(meta, TICK_SERVER_SEND);         // L1030
RecordServerLatencyMetrics(meta);            // L1031
```

---

## 5. 核心等式（自证清白）

### 5.1 各阶段耗时组成

```
E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY + NETWORK

其中：
  NETWORK = E2E - SERVER_EXEC_NS
          = E2E - (SERVER_EXEC + SERVER_QUEUE_WAIT)      ← ★ SERVER_EXEC_NS 当前包含 QUEUE_WAIT
          = CLIENT_STUB_SEND + (actual network round-trip) + SERVER_REPLY
```

> 由于 `SERVER_EXEC_NS` 当前实现包含 `SERVER_QUEUE_WAIT`，`NETWORK` 指标实际代表：CLIENT_STUB_SEND 之后的全部时间（request 网络传输 + server 处理 + reply 网络传输），不完全是纯网络耗时。

### 5.2 定界决策树

```
RPC 延迟高？
      │
      ├── CLIENT_QUEUING 高 → Client 侧 MsgQue 队列堆积
      ├── CLIENT_STUB_SEND 高 → ZmqFrontend 线程繁忙，或 zmq_msg_send 慢
      │
      ├── SERVER_QUEUE_WAIT 高 → Server 侧请求队列等待
      ├── SERVER_EXEC 高 → Server 业务逻辑慢
      ├── SERVER_REPLY 高 → Server reply zmq_msg_send 慢（socket buffer 满或网络抖动）
      │
      └── NETWORK 高 → 网络延迟或 Server 框架慢传导
          ├── CLIENT_STUB_SEND 正常 → Client 端无问题
          ├── SERVER_EXEC + SERVER_QUEUE_WAIT 正常 → Server 端无问题
          └── 则问题在网络本身
```

---

## 6. 向后兼容性

1. **旧 Server 无 `SERVER_EXEC_NS`**：Client 端 network = E2E（无法分离）
2. **旧 Client 不记录 Client 侧 Tick**：Server 侧 metrics 正常计算，Client 侧 E2E 正常计算
3. **所有 tick 为空**：`GetTotalTicksTime` 返回 0，所有 metric 不记录

---

## 7. 已知 Bug（PR #707 合并后仍存在）

### Bug 1: `SERVER_EXEC_NS` 定义错误

| | 设计意图 | 当前实现 |
|--|---------|---------|
| `SERVER_EXEC_NS` | `SERVER_EXEC_END - SERVER_DEQUEUE`（纯业务执行时间） | `SERVER_EXEC_END - SERVER_RECV`（包含 SERVER_QUEUE_WAIT） |

**影响**: `zmq_rpc_network_latency` 被高估了 `SERVER_QUEUE_WAIT` 的时间，不能真实反映网络耗时。

**修复方案**: 将 `zmq_service.cpp L81` 改为：
```cpp
uint64_t serverExecNs = (serverExecEndTs > serverDequeuTs) ? (serverExecEndTs - serverDequeuTs) : 0;
```

### Bug 2: `offlineRpc` 场景下 `rpc2` 的 meta 不包含 `SERVER_SEND` tick

**位置**: `zmq_service.cpp` L1040-1045（L1049-1061）

当 `offlineRpc = true` 时，会复制一份不含 `SERVER_SEND` tick 的 `meta` 通过 `rpc2` 单独发送。如果 client 侧有逻辑依赖 reply meta 中的 `SERVER_SEND`，会读不到。

**影响**: 纯数据问题，不影响当前 metrics 计算（`RecordServerLatencyMetrics` 在 move 之前调用）。

### Bug 3: `GetTotalTicksTime` 假设 tick 顺序

```cpp
inline uint64_t GetTotalTicksTime(const MetaPb& meta) {
    auto n = meta.ticks_size();
    if (n > 1) {
        return meta.ticks(n - 1).ts() - meta.ticks(0).ts();  // 假设 ticks[0] = CLIENT_ENQUEUE
    }
    return 0;
}
```

正常流程下 `ticks[0]` 是 `CLIENT_ENQUEUE`，`ticks[n-1]` 是 `CLIENT_RECV`，但如果 reply meta 中有额外追加的 tick（如 `SERVER_EXEC_NS`），边界情况下假设可能不成立。

---

## 8. 改动文件清单

| 文件 | 改动类型 |
|------|---------|
| `zmq_constants.h` | 新增 8 个 TICK 常量 + `RecordTick`/`GetTotalTicksTime`/`GetTimeSinceEpoch` |
| `kv_metrics.h` | 新增 7 个 MetricId（ZMQ_CLIENT_QUEUING_LATENCY ~ ZMQ_RPC_NETWORK_LATENCY） |
| `kv_metrics.cpp` | MetricDesc 注册（单位统一为 ns） |
| `zmq_stub_impl.h` | `RecordRpcLatencyMetrics()` 函数 + `CLIENT_ENQUEUE`/`CLIENT_RECV` 打点 |
| `zmq_stub_conn.cpp` | `CLIENT_TO_STUB`/`CLIENT_SEND` 打点（`RouteToZmqSocket`/`SendMsg`） |
| `zmq_service.cpp` | `SERVER_RECV`/`SERVER_DEQUEUE`/`SERVER_EXEC_END`/`SERVER_SEND` 打点 + `RecordServerLatencyMetrics()` |
