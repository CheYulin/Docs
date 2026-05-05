# Design: ZMQ RPC 队列时延可观测

本文与 **`yuanrong-datasystem`** 当前实现一致，依据：

- `src/datasystem/common/rpc/zmq/zmq_constants.h`（`RecordTick`、`RecordServerLatencyMetrics`、`RecordRpcLatencyMetrics`）
- `src/datasystem/common/metrics/kv_metrics.{h,cpp}`（Histogram ID 与导出名字）

---

## 1. 目标

在 **`MetaPb.ticks`** 中记录少量时间点，在进程内计算 **6 个队列相关 Histogram**，用于：

- Client stub 出站排队
- Server 入 worker 队列等待、业务、回包前置
- 调用方 E2E
- 与 **server 嵌入式窗口** 混合运算得到的 **network 残差**（非独立 RTT 测量）

---

## 2. Tick 清单（`zmq_constants.h`）

### 2.1 Wall ticks（`ts` = `high_resolution_clock` 时刻）

| 常量 | `tick_name` | 典型记录位置 |
|------|-------------|----------------|
| `TICK_CLIENT_ENQUEUE` | `CLIENT_ENQUEUE` | `zmq_stub_impl.h` **AsyncWriteImpl**；`zmq_unary_client_impl.h` **SendAll** |
| `TICK_CLIENT_TO_STUB` | `CLIENT_TO_STUB` | `zmq_stub_conn.cpp` **ZmqStubConnMgrImpl::Outbound** 开始；Unary **SendConnMsg** 可补打 |
| `TICK_CLIENT_RECV` | `CLIENT_RECV` | `zmq_stub_impl.h` **AsyncReadImpl**；`zmq_unary_client_impl.h` **ReadImpl** |
| `TICK_SERVER_RECV` | `SERVER_RECV` | `zmq_service.cpp` **FrontendToBackend** |
| `TICK_SERVER_DEQUEUE` | `SERVER_DEQUEUE` | `zmq_service.cpp` **WorkerEntry**，**ReceiveMsg** 之后 |
| `TICK_SERVER_EXEC_END` | `SERVER_EXEC_END` | **WorkerEntry** 尾部；`zmq_server_stream_base.h` Unary **Write**/**SendAll** 可更早打 |
| `TICK_SERVER_SEND` | `SERVER_SEND` | `zmq_service.cpp` **ServiceToClient**；构造里 **routingFn\_**（`!multiDestinations_` 时在 **Put** 前） |

**故意不记录**：在 **真正的 `zmq_msg_send` 完成** 处打 **MetaPb** tick（无 `CLIENT_ZMQ_SEND` 等常量）；STUB 之后到 socket 的区间 **无单独 Histogram**。

### 2.2 合成 ticks（`ts` 字段存 **时长 ns**，非墙钟）

| 常量 | `tick_name` | 写入 |
|------|-------------|------|
| `TICK_SERVER_EXEC_NS` | `SERVER_EXEC_NS` | **`RecordServerLatencyMetrics`**：`ts := ts(SERVER_EXEC_END) − ts(SERVER_RECV)`（若 `exec_end > recv`） |
| `TICK_SERVER_RPC_WINDOW_NS` | `SERVER_RPC_WINDOW_NS` | **`RecordServerLatencyMetrics`**：`ts := ts(SERVER_SEND) − ts(SERVER_RECV)`（若 `send > recv`） |

说明：`SERVER_EXEC_NS` **从 RECV 量到 EXEC_END**，在墙钟意义上 **包含** worker 队列等待 + 业务段；命名来自历史，阅读时以公式为准。

---

## 3. Histogram 清单（queue flow 仅 6 个）

`kv_metrics.cpp` 导出名字（单位 **µs**），采样时 **`RecordLatencyMetric(id, deltaNs)`** 内部 **`Observe(NsToUs(deltaNs))`**。

| `KvMetricId` | 导出名字 | 计算（**ns** 差分后入 `RecordLatencyMetric`） |
|--------------|----------|-----------------------------------------------|
| `ZMQ_CLIENT_QUEUING_LATENCY` | `zmq_client_queuing_latency` | `TsStub − TsEnqueue`，当 `TsStub > TsEnqueue` |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | `zmq_server_queue_wait_latency` | `TsDequeue − TsRecv`，当 `TsDequeue > TsRecv` |
| `ZMQ_SERVER_EXEC_LATENCY` | `zmq_server_exec_latency` | `TsExecEnd − TsDequeue`，当 `TsExecEnd > TsDequeue` |
| `ZMQ_SERVER_REPLY_LATENCY` | `zmq_server_reply_latency` | `TsSend − TsExecEnd`，当 **`TsExecEnd > 0`** 且 `TsSend > TsExecEnd` |
| `ZMQ_RPC_E2E_LATENCY` | `zmq_rpc_e2e_latency` | `TsClientRecv − TsEnqueue`，当 `TsClientRecv > TsEnqueue` |
| `ZMQ_RPC_NETWORK_LATENCY` | `zmq_rpc_network_latency` | 见 §4.2 **残差** |

**不在本设计范围**：`ZMQ_RPC_SERIALIZE_LATENCY`、`ZMQ_RPC_DESERIALIZE_LATENCY` 等同文件其它 ZMQ 指标；**无** `ZMQ_CLIENT_STUB_SEND_LATENCY`（历史文档曾出现，已删除）。

---

## 4. 计算逻辑（与源码一致）

### 4.1 `RecordServerLatencyMetrics(MetaPb &meta)`（Server 侧）

1. 扫描 ticks，取 **最后一个** 匹配的 `TsRecv`、`TsDequeue`、`TsExecEnd`、`TsSend`（同名多次则以实现遍历顺序为准；通常每个名一条）。
2. 按 §3 表 Observe **前三项 server span** 与 **reply**。
3. 追加合成：`SERVER_EXEC_NS`、`SERVER_RPC_WINDOW_NS`（§2.2）。

### 4.2 `RecordRpcLatencyMetrics(MetaPb &meta)`（Client 侧）

扫描得到 `TsEnqueue`、`TsStub`、`TsClientRecv`；以及 **`SERVER_RPC_WINDOW_NS` 合成 tick 的 `ts`**（记为 `srvWinMeta`），可选 `TsRecv`/`TsSend` 用于回退：

- `e2eNs = TsClientRecv − TsEnqueue`（若 `>` 0）
- `clientFrameworkNs = TsStub − TsEnqueue`（若 `TsStub > TsEnqueue`）
- `serverRpcWindowNs`：若 `srvWinMeta > 0` 用它；**否则**若 `TsSend > TsRecv` 用 `TsSend − TsRecv`
- `networkResidualNs`：仅当 `e2eNs > 0`、`serverRpcWindowNs > 0`、`clientFrameworkNs < e2eNs`：  
  `after = e2eNs − clientFrameworkNs`；`networkResidualNs = (after > serverRpcWindowNs) ? (after − serverRpcWindowNs) : 0`

再按 §3 Observe **queuing、e2e、network（仅当 residual > 0）**。

**不要**将 `E2E` 写成「各 server span 与 clientFramework 的简单求和」：server 与 client **时钟不同**，**network** 为 **残差**而不是第四段「正交」socket 时间。

---

## 5. Span 汇总表（文档用语）

记 **[1]…[7]** 为 §2.1 中 wall tick 的顺序编号（与 **`timing_points_current.puml`** 一致），**`Ts(k)`** 为对应墙的 `ts`：

| Span | 公式 | Histogram |
|------|------|-----------|
| Client queuing | `Ts(2) − Ts(1)` | `zmq_client_queuing_latency` |
| Server queue wait | `Ts(4) − Ts(3)` | `zmq_server_queue_wait_latency` |
| Server exec | `Ts(5) − Ts(4)` | `zmq_server_exec_latency` |
| Server reply | `Ts(6) − Ts(5)` | `zmq_server_reply_latency`（需 **`Ts(5)>0`**） |
| E2E（client 时钟） | `Ts(7) − Ts(1)` | `zmq_rpc_e2e_latency` |
| Network residual | §4.2 | `zmq_rpc_network_latency` |

合成：**[8]** `SERVER_EXEC_NS` `= Ts(5) − Ts(3)`；**[9]** `SERVER_RPC_WINDOW_NS` `= Ts(6) − Ts(3)`（均写入 **`tick.ts` 为时长**）。

---

## 6. 定界指引（口述）

| 观测 | 可能含义 |
|------|----------|
| `zmq_client_queuing_latency` 高 | Client **MsgQue / prefetch → Outbound** 段堆积 |
| `zmq_server_queue_wait_latency` 高 | 请求已到 service 但在 **worker 队列** 等待 |
| `zmq_server_exec_latency` 高 | **业务 handler** 慢 |
| `zmq_server_reply_latency` 高 | **`SERVER_SEND` 前**路径（队列、序列化、`ServiceToClient` 等），非单独 zmq 完成点 |
| `zmq_rpc_e2e_latency` 高 | 端到端慢；再结合上表逐项拆 |
| `zmq_rpc_network_latency`（残差）大 | **仅作线索**：时钟/NTP、`srvWin` 与 client 代数差；不可替代真实 RTT 仪器 |

---

## 7. 相关文件（实现）

| 文件 | 作用 |
|------|------|
| `zmq_constants.h` | Tick 名、`RecordLatencyMetric`、`RecordServerLatencyMetrics`、`RecordRpcLatencyMetrics` |
| `zmq_stub_impl.h` | `CLIENT_ENQUEUE`、合并 client ticks、`CLIENT_RECV`、`RecordRpcLatencyMetrics` |
| `zmq_stub_conn.cpp` | `CLIENT_TO_STUB` |
| `zmq_unary_client_impl.h` | Unary 路径与 Async 对齐的 enqueue / recv / TO_STUB 补打 |
| `zmq_service.cpp` | `SERVER_RECV`、Worker ticks、`SERVER_SEND`、`routingFn_`、`ServiceToClient` |
| `zmq_server_stream_base.h` | Unary **SERVER_EXEC_END** 保护与 **enableMsgQ\_** 语义 |
| `kv_metrics.{h,cpp}` | 6 个 queue histogram 的注册与名字 |
