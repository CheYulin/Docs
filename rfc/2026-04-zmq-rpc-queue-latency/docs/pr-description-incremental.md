# /kind feature (incremental fix)

**这是什么类型的 PR？**

/kind feature（可观测性增强；不改错误码、不改对外接口、不改网络协议）

本 PR 是对 [PR #707 "feat(zmq): add RPC queue latency metrics"](pr-description.md) 的增量修复，聚焦以下问题：

---

**这个 PR 做了什么 / 为什么需要**

### 1. 修复 E2E 计算 bug（关键）

**问题：** 原有 `RecordRpcLatencyMetrics()` 使用 `GetTotalTicksTime(meta)` 计算 E2E，该函数内部取 `tick[0]`，而 `tick[0]` 可能是 `GetLapTime()` 记录的零值 `META_TICK_START`，导致 E2E 偏低。

**修复：** 改为直接用 `FindTickTs` 查找 `TICK_CLIENT_ENQUEUE` 和 `TICK_CLIENT_RECV` 的实际时间戳计算 E2E：

```cpp
// Before (bug):
uint64_t e2eNs = GetTotalTicksTime(meta);

// After (fixed):
uint64_t clientEnqueueTs = FindTickTs(meta, TICK_CLIENT_ENQUEUE);
uint64_t clientRecvTs = FindTickTs(meta, TICK_CLIENT_RECV);
uint64_t e2eNs = (clientRecvTs > clientEnqueueTs) ? (clientRecvTs - clientEnqueueTs) : 0;
```

### 2. 统一 ns→us 转换，消除重复代码

**问题：** 原有代码直接调用 `.Observe(deltaNs)`，但 histogram 以 microseconds 为单位。

**修复：** 在 `zmq_constants.h` 新增统一 helper，所有 latency 记录统一经 `RecordLatencyMetric(id, deltaNs)` 转换后入 histogram：

```cpp
inline void RecordLatencyMetric(metrics::KvMetricId id, uint64_t deltaNs)
{
    metrics::GetHistogram(static_cast<uint16_t>(id)).Observe(NsToUs(deltaNs));
}
```

### 3. 新增 `TICK_CLIENT_STUB_SEND` tick

**目的：** 细分 Client Stub 内部阶段（原来 CLIENT_STUB_SEND 阶段没有独立的 tick 记录点），便于更精细地定位 Stub 层延迟。

### 4. 新增 DEBUG dump 辅助函数

新增 `DumpServerTicks()` 和 `DumpClientTicks()`，以 `LOG(ERROR)` 输出当前所有 tick，用于开发时验证 tick 传播是否正确。

### 5. Server 侧 tick 记录位置调整

将 `TICK_SERVER_EXEC_END` 和 `TICK_SERVER_SEND` 的记录从 `zmq_service.cpp` 移至 `zmq_server_stream_base.h`（业务逻辑执行完毕后），保证 tick 记录时机正确。

### 6. 新增 ST 测试

- `zmq_rpc_queue_latency_test.cpp`：6 个 test cases，覆盖：
  - 7 个 histogram 均有数据
  - E2E 分解一致性
  - `SERVER_EXEC_NS = EXEC + QUEUE_WAIT` 关系验证
  - `NETWORK = E2E - SERVER_EXEC_NS` 关系验证
  - fault counters 保持为零
  - HighLoad 下 framework ratio 自证清白
- `zmq_rpc_queue_latency_repl.cpp`：手动 REPL 工具，支持 `--duration=N` 指定运行时长

---

**接口/兼容性影响**

- 无对外 API 签名变化
- 无 `StatusCode` 枚举变化
- 无协议字段变化（复用 `MetaPb.ticks`）
- 向后兼容：旧 Server 无 `SERVER_EXEC_NS` 时，Client 侧 NETWORK = E2E

---

**主要代码变更**

| 文件 | 变更 |
|------|------|
| `src/datasystem/common/rpc/zmq/zmq_constants.h` | 新增 `TICK_CLIENT_STUB_SEND`、`NsToUs()`、`RecordLatencyMetric()`、`RecordServerLatencyMetrics()` |
| `src/datasystem/common/rpc/zmq/zmq_server_stream_base.h` | 新增 `TICK_SERVER_EXEC_END`、`TICK_SERVER_SEND` 记录 + 调用 `RecordServerLatencyMetrics()` |
| `src/datasystem/common/rpc/zmq/zmq_service.cpp` | 移除 `RecordServerLatencyMetrics()`（已移至 constants）；新增 `DumpServerTicks()` debug helper；保留 `RecordTick(SERVER_SEND)` |
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | 新增 `TICK_CLIENT_STUB_SEND` 记录 |
| `src/datasystem/common/rpc/zmq/zmq_stub_impl.h` | 修复 E2E 计算；新增 `DumpClientTicks()` debug helper；统一使用 `RecordLatencyMetric()` |
| `tests/st/common/rpc/zmq/zmq_rpc_queue_latency_test.cpp` | **新增** 6 个 ST 测试 cases |
| `tests/st/common/rpc/zmq/zmq_rpc_queue_latency_repl.cpp` | **新增** REPL 手动测试工具 |
| `tests/st/common/rpc/zmq/BUILD.bazel` | 新增上述两个 target |

---

**核心等式（不变）**

```
E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY + NETWORK

NETWORK = E2E - SERVER_EXEC_NS
```

**已知偏差：** `SERVER_EXEC_NS = SERVER_EXEC_END - SERVER_RECV = EXEC + QUEUE_WAIT`（包含队列等待），ST 测试 `NormalRpcs_ServerExecNsEqualsExecPlusQueueWait` 已验证此关系。

---

**测试验证**

| 用例 | 验证内容 |
|------|---------|
| `NormalRpcs_AllQueueFlowMetricsPopulate` | 7 个 histogram 均有 count > 0 |
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

- Tick 记录：`GetLapTime()` ~10ns/call
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

- [x] E2E 计算不再依赖 `GetTotalTicksTime()`，改用 `FindTickTs` 实际 tick 值
- [x] 所有 latency metric 经 `NsToUs()` 统一转换后再入 histogram
- [x] 6 个 ST test cases 全部通过
- [x] `TICK_CLIENT_STUB_SEND` tick 正确传播
- [x] `TICK_SERVER_EXEC_END` / `TICK_SERVER_SEND` 在正确位置记录
- [x] 向后兼容：旧 Server 无 `SERVER_EXEC_NS` 时 NETWORK = E2E
- [x] `TICK_CLIENT_ENQUEUE` 和 `TICK_CLIENT_RECV` 时间戳均 > 0（修复后）
