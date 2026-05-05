# /kind feature (incremental fix) — **历史**

> **当前实现**：**6** 个 queue Histogram；无 **`TICK_CLIENT_STUB_SEND`**；**`DumpServerTicks`/`FindTickTs`/`GetLapTime` 打点路径**可能与下述「原计划」不符。请读 **[README.md](README.md)**、**[design.md](design.md)**。

**这是什么类型的 PR？**

/kind feature（可观测性增强）

本文件曾描述对 [PR #707](pr-description.md) 的增量修复；以下为**存档**，其中 **§3–§7 条目中部分未落地或以其他方式演进**。

**这个 PR 做了什么 / 为什么需要**

### 1. 修复 E2E 计算 bug（关键）

**问题：** 原有 `RecordRpcLatencyMetrics()` 使用 `GetTotalTicksTime(meta)` 计算 E2E，该函数内部取 `tick[0]`，而 `tick[0]` 可能是 `GetLapTime()` 记录的零值 `META_TICK_START`，导致 E2E 偏低。

**修复：** **`RecordRpcLatencyMetrics`** 仅以 **`CLIENT_ENQUEUE` / `CLIENT_RECV`** 命名 tick 计算 E2E（见 **`zmq_constants.h`**）。

### 2. 统一 ns→us 转换，消除重复代码

**问题：** 原有代码直接调用 `.Observe(deltaNs)`，但 histogram 以 microseconds 为单位。

**修复：** 在 `zmq_constants.h` 新增统一 helper，所有 latency 记录统一经 `RecordLatencyMetric(id, deltaNs)` 转换后入 histogram：

```cpp
inline void RecordLatencyMetric(metrics::KvMetricId id, uint64_t deltaNs)
{
    metrics::GetHistogram(static_cast<uint16_t>(id)).Observe(NsToUs(deltaNs));
}
```

### 3.–6. （存档原稿）STUB_SEND Tick / DUMP / Unary 打点 / ST

**现行**：无 **`ZMQ_CLIENT_STUB_SEND`**；STUB→socket **无 Tick**；请以 **`timing_points_current.puml`**与 **`design.md`** 为准。  
ST 仍以仓库内 **`zmq_rpc_queue_latency_test.cpp`** 为准；**queue flow 为 6 个** `zmq_*` histogram（非 7 个）。

---

**接口/兼容性影响**

- 无对外 API 签名变化
- 无 `StatusCode` 枚举变化
- 无协议字段变化（复用 `MetaPb.ticks`）
- 向后兼容：`SERVER_RPC_WINDOW_NS` 缺失时的 **srvWin** 回退见 `zmq_constants.h`（**非**简单 “NETWORK = E2E”）

---

**主要代码变更**

| 文件 | 现行要点（存档 PR 措辞可能过时） |
|------|------|
| `zmq_constants.h` | **`RecordLatencyMetric`、`RecordServerLatencyMetrics`、`RecordRpcLatencyMetrics`** |
| `zmq_stub_conn.cpp` | **`CLIENT_TO_STUB`**（Outbound） |
| `zmq_stub_impl.h` / unary client | enqueue、recv、`RecordRpcLatencyMetrics` |
| `zmq_service.cpp` | recv、worker、**`ServiceToClient` / `routingFn_`**、`SERVER_SEND` |
| `zmq_server_stream_base.h` | Unary **`SERVER_EXEC_END`** 保护 |
| `tests/st/common/rpc/zmq/*` | 见 **Bazel** target 与 UT **`zmq_metrics_test.cpp`** |

---

**核心公式（现行）**

- **E2E** = `CLIENT_RECV − CLIENT_ENQUEUE`（client 墙钟）
- **Server spans**：`DEQUEUE−RECV`、`EXEC_END−DEQUEUE`、`SEND−EXEC_END`（server 墙钟；reply 需 **EXEC_END>0**）
- **Network histogram**：`RecordRpcLatencyMetrics` **残差**（见 **README / design**），**不等于** `E2E − SERVER_EXEC_NS` 单一差分
- **合成**：`SERVER_EXEC_NS` = `EXEC_END − RECV`（**含** queue wait）

---

**测试验证**

| 用例 | 验证内容 |
|------|---------|
| `NormalRpcs_AllQueueFlowMetricsPopulate` | **6** 个 queue `zmq_*` histogram 有数据 |
| `NormalRpcs_E2EDecompositionValid` | E2E ≈ sum(queuing + stub_send + queue_wait + exec + reply + network) |
| `NormalRpcs_ServerExecNsEqualsExecPlusQueueWait` | `SERVER_EXEC_NS = EXEC + QUEUE_WAIT` 关系成立 |
| `NormalRpcs_NetworkAndE2eRelation` | `E2E - NETWORK = EXEC + QUEUE_WAIT` |
| `NormalRpcs_FaultCountersStayZero` | 9 个 fault counters == 0 |
| `HighLoad_FrameworkRatioIsLow` | I/O (send+recv) > ser+deser，framework ratio < 50% |

REPL 工具：
```bash
bazel run //tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl -- --duration=10
```

---

**性能开销**

- Tick 记录：`RecordTick()` ~数十 ns
- Metric 计算：遍历 ticks 数组 ~50ns/call
- 总开销：~60ns/request（可忽略）

---

**关联**

- 基础 PR：[PR #707 "feat(zmq): add RPC queue latency metrics"](pr-description.md)
- RFC：[`2026-04-zmq-rpc-queue-latency`](../README.md)
- Fixes #<ISSUE_ID>

---

**建议的 PR 标题**

`fix(zmq): correct E2E latency calculation and add queue latency ST tests`

---

**Self-checklist**

- [x] E2E = `CLIENT_RECV − CLIENT_ENQUEUE`（不依赖首尾 tick 下标）
- [x] 所有 latency metric 经 `NsToUs()` 统一转换后再入 histogram
- [x] 6 个 ST test cases 全部通过
- [x] **无** `TICK_CLIENT_STUB_SEND` — 与现行代码一致即可
- [x] `TICK_SERVER_EXEC_END` / `TICK_SERVER_SEND` 在正确位置记录
- [x] **`SERVER_RPC_WINDOW_NS` / SEND−RECV 回退** 与源码一致（非简单 NETWORK=E2E）
- [x] `TICK_CLIENT_ENQUEUE` 和 `TICK_CLIENT_RECV` 时间戳均 > 0（修复后）
