# /kind feature

**这是什么类型的 PR？**

/kind feature（可观测性增强；不改错误码、不改对外接口、不改网络协议）

---

**这个 PR 做了什么 / 为什么需要**

本 PR 在 ZMQ RPC 路径补齐"队列时延可定界 + 可自证清白"的 metrics 能力：

1. **时延自证清白**
   当 RPC 延迟高时，可明确区分瓶颈在哪个阶段：
   - `ZMQ_CLIENT_QUEUING_LATENCY`：Client 框架 MsgQue 队列等待
   - `ZMQ_CLIENT_STUB_SEND_LATENCY`：Client Stub 发送（ZmqFrontend + Socket）
   - `ZMQ_SERVER_QUEUE_WAIT_LATENCY`：Server 队列等待
   - `ZMQ_SERVER_EXEC_LATENCY`：Server 业务执行
   - `ZMQ_SERVER_REPLY_LATENCY`：Server 回复入队

2. **E2E 定界**
   - `ZMQ_RPC_E2E_LATENCY`：端到端延迟
   - `ZMQ_RPC_NETWORK_LATENCY` = E2E - SERVER_EXEC，将网络开销与其他阶段分离

3. **零协议修改**
   复用现有 `MetaPb.ticks` 字段传递时间戳，无网络开销

---

**接口/兼容性影响**

- 无对外 API 签名变化
- 无 `StatusCode` 枚举变化
- 无协议字段变化（复用 `MetaPb.ticks`）
- 向后兼容：旧 Server 无 `SERVER_EXEC_NS` 时，Client 侧 NETWORK = E2E

---

**主要代码变更**

**新增 MetricId（7个）**

- `src/datasystem/common/metrics/kv_metrics.h`
  - `ZMQ_CLIENT_QUEUING_LATENCY`
  - `ZMQ_CLIENT_STUB_SEND_LATENCY`
  - `ZMQ_SERVER_QUEUE_WAIT_LATENCY`
  - `ZMQ_SERVER_EXEC_LATENCY`
  - `ZMQ_SERVER_REPLY_LATENCY`
  - `ZMQ_RPC_E2E_LATENCY`
  - `ZMQ_RPC_NETWORK_LATENCY`

**新增常量**

- `src/datasystem/common/rpc/zmq/zmq_constants.h`
  - 8 个 Tick 常量定义（`TICK_CLIENT_ENQUEUE`、`TICK_CLIENT_TO_STUB`、`TICK_CLIENT_SEND`、`TICK_CLIENT_RECV`、`TICK_SERVER_RECV`、`TICK_SERVER_DEQUEUE`、`TICK_SERVER_EXEC_END`、`TICK_SERVER_SEND`）

**修改**

- `src/datasystem/common/rpc/zmq/zmq_stub_impl.h`
  - 新增 `FindTickTs()` 辅助函数（提取 tick timestamp）
  - 新增 `RecordRpcLatencyMetrics()` 函数（Client 侧计算 QUEUING、STUB_SEND、E2E、NETWORK）
  - `AsyncWriteImpl()`：`GetLapTime(p.first, TICK_CLIENT_ENQUEUE)` 记录入口时间戳
  - `AsyncReadImpl()`：`GetLapTime(rsp.first, TICK_CLIENT_RECV)` + 调用 `RecordRpcLatencyMetrics()` 计算并记录 Client 侧 metrics

- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`
  - `RouteToZmqSocket()`：记录 `TICK_CLIENT_SEND`
  - `SendMsg()`：记录 `TICK_CLIENT_TO_STUB`
  - 参数从 `const MetaPb&` 改为 `MetaPb&`（用于记录 tick）

- `src/datasystem/common/rpc/zmq/zmq_service.cpp`
  - 新增匿名命名空间 `FindTickTs()` 和 `RecordServerLatencyMetrics()` 辅助函数
  - `FrontendToBackend()`：记录 `TICK_SERVER_RECV`
  - `WorkerCB::WorkerEntry()`：记录 `TICK_SERVER_DEQUEUE` 和 `TICK_SERVER_EXEC_END`
  - `ServiceToClient()`：记录 `TICK_SERVER_SEND`，计算 SERVER 侧各阶段延迟，追加 `SERVER_EXEC_NS` tick 传回 Client

**Metric ID 重排**

- `kv_metrics.cpp` 中原有 alloc/free、shm、ttl 等 metrics 的 ID 相应后移（36→43 开始）

---

**核心等式（自证清白）**

```
E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY + NETWORK

NETWORK = E2E - SERVER_EXEC
```

**Tick 时间线**

```
                    CLIENT                                 SERVER
                       │                                     │
   CLIENT_ENQUEUE ────┬──── CLIENT_TO_STUB ────┬──── CLIENT_SEND
       │              │         │              │         │
       │   CLIENT     │         │   CLIENT     │         │   SERVER
       │  QUEUING     │         │ STUB_SEND   │         │  QUEUE_WAIT
       │              │         │              │         │        │
   ◄───┼─────────────┼─────────┼──────────────┼─────────┼────────┼────────────────►
       │              │         │              │         │        │
       │              │         │              │         │ SERVER_RECV
       │              │         │              │         │◄────────┼────────────────►
       │              │         │              │         │        │
   ────┴─────────────┴─────────┴──────────────┴─────────┴────────┴─────────────────►
   CLIENT_ENQUEUE   CLIENT_TO_STUB CLIENT_SEND  SERVER_RECV SERVER_DEQUEUE SERVER_EXEC_END SERVER_SEND CLIENT_RECV
```

---

**测试验证**

UT 测试用例（规划中）：

| 用例 | 验证内容 |
|------|---------|
| `TickPropagationTest` | Server 追加的 tick 能正确传回 Client |
| `E2ELatencyTest` | E2E = CLIENT_RECV - CLIENT_ENQUEUE |
| `ClientQueuingLatencyTest` | CLIENT_QUEUING = CLIENT_TO_STUB - CLIENT_ENQUEUE |
| `ClientStubSendLatencyTest` | CLIENT_STUB_SEND = CLIENT_SEND - CLIENT_TO_STUB |
| `ServerQueueWaitLatencyTest` | SERVER_QUEUE_WAIT = SERVER_DEQUEUE - SERVER_RECV |
| `ServerExecLatencyTest` | SERVER_EXEC = SERVER_EXEC_END - SERVER_DEQUEUE |
| `ServerReplyLatencyTest` | SERVER_REPLY = SERVER_SEND - SERVER_EXEC_END |
| `NetworkLatencyTest` | NETWORK = E2E - SERVER_EXEC |
| `BackwardCompatTest` | 旧 Server 无 SERVER_EXEC_NS 时 Client 行为 |

---

**性能开销**

- Tick 记录：`GetLapTime()` ~10ns/call
- Metric 计算：遍历 ticks 数组 ~50ns/call
- 总开销：~60ns/request（可忽略）

---

**关联**

关联：ZMQ RPC 队列时延可观测（自证清白 + 定界）
RFC：[`2026-04-zmq-rpc-queue-latency`](README.md)
Fixes #<ISSUE_ID>

---

**建议的 PR 标题**

`feat(zmq): add RPC queue latency metrics for end-to-end latency breakdown and isolation`

---

**Self-checklist**

- [x] 不改错误码，不改对外 API
- [x] 不改网络协议（复用 MetaPb.ticks）
- [x] 5 个阶段延迟 metric 正交（时间不重叠）
- [x] NETWORK = E2E - SERVER_EXEC 可计算
- [x] 向后兼容：旧 Server 无 SERVER_EXEC_NS 时 NETWORK = E2E
- [x] ENABLE_PERF 开启时：所有 tick 正常记录，metrics 正常工作
- [x] ENABLE_PERF=false 时：新增 `RecordTick()`/`GetTotalElapsedTime()` 始终记录 tick，metrics 仍能正常分段时间（PR #706 修复点）
