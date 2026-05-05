# RFC: metrics_summary 多分片与测试导出 API

## Status

**In-Progress**（与 `yuanrong-datasystem` MR 对齐；合入后可改为 **Done**）

## 背景

运行时 `datasystem::metrics::LogSummary()` 会在单行 JSON（`metrics_summary`）超过 **`MAX_METRICS_LOG_BYTES`** 时拆成多段，每段自带 **`cycle` / `part_index` / `part_count`**。原先仅暴露在测试里的 **`DumpSummaryForTest()`** 等价于 **`BuildSummary(...).front()`**，多段场景下只看到第一段，容易引发误判。

## 目标

1. 为测试与分析提供与生产一致的 **完整多分片快照**：新增 **`metrics::DumpSummariesForTest(intervalMs)`** → `std::vector<std::string>`，逐元素即一条与 `LOG(INFO)` 对齐的摘要行。
2. **不改动** **`DumpSummaryForTest()`** 的历史语义：**仍仅返回第一段**字符串（空则为 `""`），避免搅动大量 UT 语义。
3. 需要 **`nlohmann::json` 合并视图**的用例（如 ZMQ 队列延迟 REPL）：在调用方对每个 **原始 part 字符串** `LOG(INFO)` 打印后，`parse` 并合并 **`metrics`** 数组，再把顶层 **`part_index` / `part_count`** 置为 **1** 表示已是逻辑上的“单对象”快照。

## 代码落点（`yuanrong-datasystem`）

| 区域 | 文件 | 变更摘要 |
|------|------|-----------|
| 公共 metrics | `src/datasystem/common/metrics/metrics.{h,cpp}` | **`DumpSummariesForTest`**；**`DumpSummaryForTest`** 保持 `summaries.front()` |
| Metrics UT | `tests/ut/common/metrics/metrics_test.cpp` | **`dump_summaries_contains_all_parts_when_split`**（大 payload，`DumpSummariesForTest`） |
| ZMQ UT/ST | `tests/ut/common/rpc/zmq_metrics_test.cpp`、`tests/st/common/rpc/zmq/zmq_rpc_queue_latency_repl.cpp` | **`DumpSummaryJson`** 基于 **`DumpSummariesForTest`** 合并 |

## PR 正文

拷贝或微调 [pr-description.md](./pr-description.md) 提交到代码托管 MR。

## 关联

- 多分片规则与上限：`metrics.cpp` 中 **`MAX_METRICS_LOG_BYTES`**、`BuildSummary`、`RenderJsonSummary`。
- ZMQ RFC：[2026-04-30-zmq-rpc-queue-latency/](../2026-04-30-zmq-rpc-queue-latency/README.md)
