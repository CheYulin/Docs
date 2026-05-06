# RFC: ZMQ RPC 队列时延可观测（自证清白 + 定界）

- **Status**: **In-Progress**（ENABLE_PERF 与 Tick 的记录方式以 `zmq_constants.h` 为准）
- **Started**: 2026-04
- **Depended on**: PR #584（轻量 metrics 框架）
- **Related PR**: PR #706（ENABLE_PERF=false 仍可打点时延相关 Tick）

---

## 落地位置（datasystem）

**队列分段延迟**用到的 Histogram 仅在下面 **6** 个 `KvMetricId` 上出现（导出名字见 `kv_metrics.cpp`，单位 **µs**，采样时长经 **`NsToUs`**）。  
打点入口：**`RecordLatencyMetric`** / **`RecordRpcLatencyMetrics`** / **`RecordServerLatencyMetrics`**（**`src/datasystem/common/rpc/zmq/zmq_constants.h`**）。

| `KvMetricId` | 导出名字 | Observer 进程 | `Observe(...)` 条件（节选） |
|--------------|----------|-----------------|----------------------------|
| `ZMQ_CLIENT_QUEUING_LATENCY` | `zmq_client_queuing_latency` | Client | `CLIENT_TO_STUB` 与 `CLIENT_ENQUEUE` 均存在且 `stub > enqueue` |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | `zmq_server_queue_wait_latency` | Server | `dequeue > recv` |
| `ZMQ_SERVER_EXEC_LATENCY` | `zmq_server_exec_latency` | Server | `exec_end > dequeue` |
| `ZMQ_SERVER_REPLY_LATENCY` | `zmq_server_reply_latency` | Server | **`exec_end > 0`** 且 `send > exec_end` |
| `ZMQ_RPC_E2E_LATENCY` | `zmq_rpc_e2e_latency` | Client | `recv > enqueue` |
| `ZMQ_RPC_NETWORK_LATENCY` | `zmq_rpc_network_latency` | Client | **`networkResidualNs > 0`**（见下文） |

本目录**不文档化** **`ZMQ_CLIENT_STUB_SEND_LATENCY`**（`kv_metrics` 中已无此项）。  
另有 **`zmq_rpc_serialize_latency` / `zmq_rpc_deserialize_latency`**（`kv_metrics.{h,cpp}`）与本 RFC **队列分段**无关，亦不纳入下表公式。

---

## Tick 编号与语义（对齐 [timing_points_current.puml](timing_points_current.puml)）

**Wall tick**：`TickPb.ts()` 为 `high_resolution_clock` 时间点。  
**合成 tick**：`ts` 存 **时长(ns)**：`SERVER_EXEC_NS`、`SERVER_RPC_WINDOW_NS`。

| # | `tick_name` | 域 | 记录点（概要） |
|---|-------------|-----|----------------|
| [1] | `CLIENT_ENQUEUE` | Client | `zmq_stub_impl.h` **AsyncWriteImpl**；`zmq_unary_client_impl.h` **SendAll** |
| [2] | `CLIENT_TO_STUB` | Client | `zmq_stub_conn.cpp` **Outbound** 首行；Unary **SendConnMsg** 可补打 |
| [3] | `SERVER_RECV` | Server | `zmq_service.cpp` **FrontendToBackend** |
| [4] | `SERVER_DEQUEUE` | Server | `WorkerEntry`，**ReceiveMsg** 之后 |
| [5] | `SERVER_EXEC_END` | Server | **WorkerEntry** 尾部；Unary **Write**/**SendAll** 可更早打（guarded） |
| [6] | `SERVER_SEND` | Server | **ServiceToClient** 或 `routingFn_`（`replyQueue_->Put` 前） |
| [7] | `CLIENT_RECV` | Client | **AsyncReadImpl** / Unary **ReadImpl** |
| [8] | `SERVER_EXEC_NS` | 合成 | **RecordServerLatencyMetrics**：`ts := [5]−[3]`（墙钟差写入 `tick.ts`） |
| [9] | `SERVER_RPC_WINDOW_NS` | 合成 | **`ts := [6]−[3]`** |

**空缺**：Socket 层 **`zmq_msg_send`/`zmq_msg_recv` 完成** 不打 **独立的 MetaPb TICK**；STUB 后到网卡段 **无单独 Histogram**。

---

## Span 与 Histogram 计算（记号：`Ts(X)` = 名为 X 的 **wall** tick 的 `ts`）

**Server 上（同一时钟域）：**

| Span | 公式 | Histogram |
|------|------|-----------|
| Client stub 出站排队 | `Ts(CLIENT_TO_STUB) − Ts(CLIENT_ENQUEUE)` | `zmq_client_queuing_latency` |
| Server worker 队列等待 | `Ts(SERVER_DEQUEUE) − Ts(SERVER_RECV)` | `zmq_server_queue_wait_latency` |
| Server 业务 | `Ts(SERVER_EXEC_END) − Ts(SERVER_DEQUEUE)` | `zmq_server_exec_latency` |
| Server reply 前置 | `Ts(SERVER_SEND) − Ts(SERVER_EXEC_END)` | `zmq_server_reply_latency`（需 **`Ts(SERVER_EXEC_END)>0`**） |

**Client 上：`e2e_ns`**

- `e2e_ns = Ts(CLIENT_RECV) − Ts(CLIENT_ENQUEUE)` → `zmq_rpc_e2e_latency`

**残差 Network（源码 `RecordRpcLatencyMetrics`）：**

记 `client_framework_ns = max(0, Ts(CLIENT_TO_STUB) − Ts(CLIENT_ENQUEUE))`；  
`srvWin`：**若存在** `SERVER_RPC_WINDOW_NS` **合成 tick**则用其 **`ts`**；否则若 **`Ts(SERVER_SEND) > Ts(SERVER_RECV)`** 用 **`Ts(SERVER_SEND)−Ts(SERVER_RECV)`**。  
当 **`e2e_ns>0` 且 `srvWin>0` 且 `client_framework_ns<e2e_ns`**：

- `after = e2e_ns − client_framework_ns`
- `networkResidualNs = (after > srvWin) ? (after − srvWin) : 0`

仅 **`networkResidualNs > 0`** 时记入 **`zmq_rpc_network_latency`**。  
这是对 **caller 时间与 server 嵌入窗口** 做的代数余量，**不是精确物理 RTT**（见 **`zmq_constants.h`** 注释）。

---

## 本目录文件

| 文件 | 说明 |
|------|------|
| [timing_points_current.puml](timing_points_current.puml) | 当前实现生命周期 |
| [references/timing_points.puml](references/timing_points.puml) | 早期图，命名部分过时 |
| [design.md](design.md) | 设计与实现摘录 |
| [debug_ticks.md](debug_ticks.md) | 核对 `MetaPb.ticks` 的注意点 |
| [issue-rfc.md](issue-rfc.md)、[pr-description.md](pr-description.md)、[pr-description-incremental.md](pr-description-incremental.md) | **历史**；度量以本节 + **design.md** + **源码**为准 |
| [profiling/](../profiling/README.md) | OS 层可观测工具链（perf / strace / tcp / 统一解析） |
