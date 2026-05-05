# /kind feature

**这是什么类型的 PR？**

/kind feature（可观测 / 开发者体验：**测试与 ST 导出**对齐生产 **`metrics_summary` 多分片**，不改变运行时摘要 JSON schema，不改动 **`DumpSummaryForTest()`** 历史语义）

---

**这个 PR 做了什么 / 为什么需要**

运行时 **`LogSummary`** 可能在一次 tick 输出 **多条** `metrics_summary` 行（`part_index`、`part_count` 递增，**同一 `cycle`**）。测试侧如果只拿 **`DumpSummaryForTest()`**，其实一直是 **`BuildSummary(...).front()`**：**多分片时会丢后续 part**。本变更补上 **`DumpSummariesForTest(intervalMs)`** 暴露完整 **`std::vector<std::string>`**，与每条 **`LOG(INFO)`** 对齐；原有 **`DumpSummaryForTest`** **保持仅为第一段**，减少对既有 UT 的差异。

顺带修复 / 补强：

- **ZMQ** 场景的 **`DumpSummaryJson`**：**不得**再对 **`DumpSummaryForTest()`** 单行做 **`json::parse`**（多分片会破坏解析）；改为 **`DumpSummariesForTest` → 遍历 → 打印原始 **`parts[i]`**（便于比对 part）→ **`parse`** 后合并 **`metrics` 数组**；合并结果顶层 **`part_index`/`part_count` 设为 1** 表示语义上的单视图。
- **UT**：新增大 payload + 多分片用例，用 **`DumpSummariesForTest`** 校验 **全体 metric name** 均出现在某一 part 中。

---

**接口影响**

| 符号 | 行为 |
|------|------|
| **`metrics::DumpSummariesForTest(int intervalMs = 10000)`** | **新增**。返回本条 tick 的全部摘要行（0..N）。 |
| **`metrics::DumpSummaryForTest(...)`** | **语义不变**。仍为 **第一段**或空字符串。 |

**无** **`KvMetricId`** 改动，**无**生产 **`Observe`/`Tick`** 行为变更。

---

**主要代码变更（`yuanrong-datasystem`）**

- `src/datasystem/common/metrics/metrics.h`：声明 **`DumpSummariesForTest`**。
- `src/datasystem/common/metrics/metrics.cpp`：**`DumpSummariesForTest`** 委托 **`BuildSummary`**；**`DumpSummaryForTest`** 仍为 **`summaries.empty() ? "" : summaries.front()`**。
- `tests/ut/common/metrics/metrics_test.cpp`：**`dump_summaries_contains_all_parts_when_split`**。
- `tests/ut/common/rpc/zmq_metrics_test.cpp`：**`DumpSummaryJson`** 合并多分片（含按需 **`#include`** **`log.h`**）。
- `tests/st/common/rpc/zmq/zmq_rpc_queue_latency_repl.cpp`：同上 **`DumpSummaryJson`**；测试中 **`LOG(INFO) << parts[i]`** 用于原始分片对齐排查。

---

**测试**

在 **`xqyun-32c32g`**（或与团队约定环境）workspace 路径下：

```bash
bazel test //tests/ut/common/metrics:metrics_test \
           //tests/ut/common/rpc:zmq_metrics_test \
           --test_output=errors
```

**任选**：`bazel test //tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl`。

---

**建议的 MR 标题**

- `feat(metrics): add DumpSummariesForTest for full metrics_summary split`

---

**Self-checklist**

- [ ] **`DumpSummariesForTest`** 与 **`LogSummary`** 条数、`part_*`、`cycle` 一致（手工或日志比对）。
- [ ] **`DumpSummaryForTest`** **仅第一段**，未静默拼接多分片。
- [ ] **`DumpSummaryJson`** 仅在 **`DumpSummariesForTest`** 上合并，多分片 **`json::parse`** 不失败。
- [ ] **`bazel test //tests/ut/common/metrics:metrics_test //tests/ut/common/rpc:zmq_metrics_test`** 通过。
- [ ] C++ **≤120 列**（若团队启用行宽脚本则跑一遍）。
- [ ] （可选）合入后将本 RFC **`README.md` Status** 更新为 **Done**。
