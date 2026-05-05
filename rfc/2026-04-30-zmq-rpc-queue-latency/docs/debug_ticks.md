# ZMQ RPC：Tick / Metrics 核对说明

本文仅描述 **当前代码** 中真实存在的符号；**不包含**历史上讨论过但未合入的调试 API。

权威定义与公式见 **[design.md](design.md)** 与源码 **`src/datasystem/common/rpc/zmq/zmq_constants.h`**。

---

## 1. Tick 名（`MetaPb.ticks[].tick_name`）

**Wall（`ts` = 墙钟）**

- `CLIENT_ENQUEUE`, `CLIENT_TO_STUB`, `CLIENT_RECV`
- `SERVER_RECV`, `SERVER_DEQUEUE`, `SERVER_EXEC_END`, `SERVER_SEND`

**合成（`ts` = 时长 ns）**

- `SERVER_EXEC_NS` — 由 **`RecordServerLatencyMetrics`** 追加
- `SERVER_RPC_WINDOW_NS` — 同上

**不存在于当前常量的名字**（勿在文档中当作已打点）：`CLIENT_SEND`、`CLIENT_STUB_SEND`、`CLIENT_DEQUEUE`、`TICK_SERVER_ZMQ_SEND` 等。

---

## 2. 核心函数（均在 `zmq_constants.h`）

| 函数 | 作用 |
|------|------|
| `RecordTick(MetaPb&, const char*)` | 追加 wall tick |
| `MetaHasNamedTick` | 判断是否已有某 `tick_name` |
| `RecordServerLatencyMetrics` | Server 侧 3 个 span + reply + 合成 [8][9] |
| `RecordRpcLatencyMetrics` | Client 侧 queuing + e2e + network 残差 |
| `RecordLatencyMetric` | `deltaNs` → `NsToUs` → `GetHistogram(id).Observe` |

---

## 3. 日志里如何核对

1. **抓一条 RPC 响应 `MetaPb`**（或客户端 merge 后的最终 `ticks`）。
2. 按时间顺序列出 **`tick_name` + `ts`**；注意 **`SERVER_EXEC_NS` / `SERVER_RPC_WINDOW_NS` 的 `ts` 是时长**。
3. 用 **[README.md](README.md)** 中的 **Span 表** 手算是否落在合理范围。
4. **PerfPoint**（如 `ZMQ_NETWORK_TRANSFER_*`）与 **`zmq_rpc_network_latency`** 公式不同，不可混为一谈。

---

## 4. 常见误判

| 现象 | 说明 |
|------|------|
| 期望有 `CLIENT_ZMQ_SEND` | 架构上不在 **MetaPb** 打该点；无对应 Histogram |
| `zmq_rpc_network_latency` 与 ping 不符 | 设计为 **残差**（混合 client 钟与 server 窗口），见 `zmq_constants.h` 注释 |
| `SERVER_EXEC_NS` "含排队" | 当前实现为 **`EXEC_END − RECV`**，不是 **`EXEC_END − DEQUEUE`** |
