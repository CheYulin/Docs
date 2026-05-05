# /kind feature（历史 PR 描述）

> **当前实现**以 **[README.md](README.md)**、**[design.md](design.md)** 为准：**6** 个 queue Histogram；**无** `TICK_CLIENT_SEND` / **无** `ZMQ_CLIENT_STUB_SEND`；**`zmq_rpc_network_latency`** 为 **残差公式**而非 `E2E − SERVER_EXEC`。

**这是什么类型的 PR？**

/kind feature（可观测性增强；不改错误码、不改对外接口、不改网络协议）

---

**这个 PR 做了什么 / 为什么需要**

本 PR 在 ZMQ RPC 路径补齐「队列时延可定界」的 metrics（**现行命名与条目见 README**）：

1. **分段 Histogram（server + client stub 排队）**  
   `zmq_client_queuing_latency`、`zmq_server_queue_wait_latency`、`zmq_server_exec_latency`、`zmq_server_reply_latency`、`zmq_rpc_e2e_latency`、`zmq_rpc_network_latency`

2. **E2E 与残差 Network**  
   E2E = `CLIENT_RECV − CLIENT_ENQUEUE`；Network 按 **`RecordRpcLatencyMetrics`** 中 **残差** 定义。

3. **零协议修改**  
   复用 `MetaPb.ticks`；追加 **`SERVER_EXEC_NS`、`SERVER_RPC_WINDOW_NS`**（合成）。

---

**接口/兼容性影响**

- 无对外 API 签名变化
- 无 `StatusCode` 枚举变化
- 无协议字段变化（复用 `MetaPb.ticks`）
- 向后兼容：`SERVER_RPC_WINDOW_NS` 缺失时 Client 可能对 **srvWin** 用 `SEND−RECV` 回退（见 `zmq_constants.h`）

---

**主要代码变更**

**队列 flow 新增 MetricId（6 个，现行）**：见 `kv_metrics.h` / `kv_metrics.cpp` 中  
`ZMQ_CLIENT_QUEUING_LATENCY` … `ZMQ_RPC_NETWORK_LATENCY`（导出 `zmq_*`）。

**Tick 常量**（节选）：`CLIENT_ENQUEUE`、`CLIENT_TO_STUB`、`CLIENT_RECV`、`SERVER_*`、`SERVER_EXEC_NS`、`SERVER_RPC_WINDOW_NS`。  
详见 **`design.md`**。

**修改**：`RecordRpcLatencyMetrics` / `RecordServerLatencyMetrics` 在 **`zmq_constants.h`**；各路径 **`RecordTick`** 见 **`timing_points_current.puml`**。

---

**测试验证**

UT 测试用例（规划中）：

| 用例 | 验证内容 |
|------|---------|
| `TickPropagationTest` | Server 追加的 tick 能正确传回 Client |
| `E2ELatencyTest` | E2E = CLIENT_RECV − CLIENT_ENQUEUE |
| `ClientQueuingLatencyTest` | CLIENT_QUEUING = CLIENT_TO_STUB − CLIENT_ENQUEUE |
| `ServerQueueWaitLatencyTest` | SERVER_QUEUE_WAIT = SERVER_DEQUEUE − SERVER_RECV |
| `ServerExecLatencyTest` | SERVER_EXEC = SERVER_EXEC_END − SERVER_DEQUEUE |
| `ServerReplyLatencyTest` | SERVER_REPLY = SERVER_SEND − SERVER_EXEC_END |
| `NetworkLatencyTest` | `zmq_rpc_network_latency` 与 **残差公式**一致（见 `RecordRpcLatencyMetrics`） |
| `BackwardCompatTest` | `SERVER_RPC_WINDOW_NS` / `SEND−RECV` 回退化 |

---

**性能开销**

- Tick 记录：`RecordTick()` ~数十 ns/次
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
- [x] 6 个 queue Histogram 语义与 **`zmq_constants.h`** 一致
- [x] **Network** 为残差，`E2E` 与各 server span **不能**在无混合假设下设为简单相加
- [x] ENABLE_PERF 开启时：所有 tick 正常记录，metrics 正常工作
- [x] ENABLE_PERF=false 时：新增 `RecordTick()`/`GetTotalElapsedTime()` 始终记录 tick，metrics 仍能正常分段时间（PR #706 修复点）
