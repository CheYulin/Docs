# RFC

本目录存放 **特性开发任务**（RFC / 设计文档 / 验证手册 / PR 文案）的工作区。与 `docs/` 的区别：

| 目录 | 角色 |
|------|------|
| `docs/` | 面向读者的稳定文档（架构、可靠性、可观测、运维手册） |
| `rfc/` | 面向开发的实施任务：问题分析、方案、验证、issue/PR 文案 |
| `plans/` | 更细粒度的开发阶段 todo/进度（短周期、高频迭代） |

> **后续计划**：`plans/` 与 `rfc/` 将合并成统一的特性开发工作区。当前先保留两者共存。

---

## 状态

每个 RFC 顶层 `README.md` 必须带 **Status** 字段：

- **Draft**：方案草稿，尚未实施
- **In-Progress**：方案确认，部分代码已提交
- **Done**：代码已并入 datasystem 主干，文档作为历史参考
- **Archived**：已被更新方案取代

---

## 当前 RFC

按创建日期倒序排列（最新在上）：

| 日期 | RFC | Status | 落地位置（datasystem） |
|------|-----|--------|-----------------------|
| 2026-05-05 | [2026-05-05-metrics-summary-multi-part-test-support/](2026-05-05-metrics-summary-multi-part-test-support/README.md) | **In-Progress** | **`DumpSummariesForTest`**（全 part）+ **`DumpSummaryForTest` 保持首段**；Z **`DumpSummaryJson` 多分片合并**；见 [README](2026-05-05-metrics-summary-multi-part-test-support/README.md)、[pr-description.md](2026-05-05-metrics-summary-multi-part-test-support/pr-description.md) |
| 2026-05-03 | [2026-05-03-metrics-p99-histogram/](2026-05-03-metrics-p99-histogram/README.md) | **Draft** | **Histogram P99**（20 固定桶，`common/metrics` + `metrics_test`）；见 [implementation-plan](2026-05-03-metrics-p99-histogram/implementation-plan.md) |
| 2026-05-02 | [2026-05-02-urma-jfs-depth-write-retry/](2026-05-02-urma-jfs-depth-write-retry/README.md) | **In-Progress** | **URMA write**：gflags `urma_send_jfs_depth` / `urma_write_spin_retry_sleep_us`；`urma_resource.cpp` send JFS depth；`UrmaWriteImpl` **`URMA_EAGAIN`** 退避 + **`worker_urma_write_spin_latency`**；详见 [issue-rfc](2026-05-02-urma-jfs-depth-write-retry/issue-rfc.md) |
| 2026-04-30 | [2026-04-30-zmq-rpc-queue-latency/](2026-04-30-zmq-rpc-queue-latency/README.md) | **Draft** | `common/metrics/kv_metrics.{h,cpp}`：新增 7 个 Histogram metric（`ZMQ_CLIENT_QUEUING_LATENCY`、`ZMQ_CLIENT_STUB_SEND_LATENCY`、`ZMQ_SERVER_QUEUE_WAIT_LATENCY`、`ZMQ_SERVER_EXEC_LATENCY`、`ZMQ_SERVER_REPLY_LATENCY`、`ZMQ_RPC_E2E_LATENCY`、`ZMQ_RPC_NETWORK_LATENCY`）；`zmq_constants.h`：新增 8 个 Tick 常量 |
| 2026-04-29 | [2026-04-29-worker-ub-throughput-load-metric/](2026-04-29-worker-ub-throughput-load-metric/README.md) | **Draft** | **切流 + C↔W 连接均衡**：[issue-rfc](2026-04-29-worker-ub-throughput-load-metric/issue-rfc.md) / [design](2026-04-29-worker-ub-throughput-load-metric/design.md)；**A** Po2+连接数、[validation-po2](2026-04-29-worker-ub-throughput-load-metric/validation-po2-client-count.md)；**B** Po2+UB 字节；`CONTEXT.md` |
| 2026-04-27 | [2026-04-27-worker-get-metrics-breakdown/](2026-04-27-worker-get-metrics-breakdown/README.md) | **Draft** | **性能定位/定界**：[issue-rfc](2026-04-27-worker-get-metrics-breakdown/issue-rfc.md) / [modification_plan](2026-04-27-worker-get-metrics-breakdown/modification_plan.md) / [design](2026-04-27-worker-get-metrics-breakdown/design.md)；`kv_metrics` 增量 + Get 分段；验收：Bazel `metrics_test` + 日志 + [`grep_get_breakdown`](../scripts/metrics/grep_get_latency_breakdown.sh) |
| 2026-04-19 | [2026-04-19-shm-leak-observability/](2026-04-19-shm-leak-observability/README.md) | **In-Progress**（MR [#635](https://gitcode.com/openeuler/yuanrong-datasystem/merge_requests/635) 评审中） | 新增 18 条 metric（10 worker + 6 master + 2 client）合并为单 commit `3bbcc55a` / 单 PR：覆盖 Allocator alloc/free 对账、`memoryRefTable_` size/bytes、ShmUnit 生命周期、master TTL 链路（fire/success/failed/retry/pending）、client async release 滞后；针对 [2026-04-19 worker shm OOM](../bugfix/2026-04-19-worker-shm-oom-问题定位.md) |
| 2026-04-18 | [2026-04-18-kvclient-urma-tcp-observability/](2026-04-18-kvclient-urma-tcp-observability/README.md) | **Done** | `include/datasystem/utils/status.h`：`K_URMA_WAIT_TIMEOUT=1010`、`K_URMA_CONNECT_FAILED=1009`；`urma_manager.cpp` 新增 WARNING/ERROR 日志；Trace 上下文扩展 |
| 2026-04-18 | [2026-04-18-zmq-rpc-metrics/](2026-04-18-zmq-rpc-metrics/README.md) | **Done** | `common/metrics/kv_metrics.{h,cpp}`：`ZMQ_SEND_IO_LATENCY`、`ZMQ_RECEIVE_IO_LATENCY`、`ZMQ_LAST_ERROR_NUMBER`、`ZMQ_NETWORK_ERROR_TOTAL`、`ZMQ_SEND/RECEIVE_FAILURE_TOTAL`、`ZMQ_EVENT_DISCONNECT_TOTAL`、`ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL`、`ZMQ_GATEWAY_RECREATE_TOTAL` 等 |

---

### 散文件（非目录）

| 文件 | 日期 | 说明 |
|------|------|------|
| ~~`yuanrong-datasystem-metrics-p99-design.md`~~ / ~~`yuanrong-datasystem-metrics-p99.patch`~~ | — | **已删除**：其中 **Histogram P99（metrics）** 已迁入 [2026-05-03-metrics-p99-histogram/](2026-05-03-metrics-p99-histogram/README.md)；原稿中 ZMQ/tick/ns→µs 等内容与 [2026-04-30-zmq-rpc-queue-latency/](2026-04-30-zmq-rpc-queue-latency/README.md) 等相关 RFC 另线跟踪 |
| ~~`p99_histogram_verification.md`~~ | — | **已删除**：与 [2026-05-03-metrics-p99-histogram/verification.md](2026-05-03-metrics-p99-histogram/verification.md) 重复；以 RFC 目录内版本为准（§2 patch 路径已更新） |
| [2026-04-urma-jfs-cqe-error9-walkthrough.md](2026-04-urma-jfs-cqe-error9-walkthrough.md) | 2026-04-27 | urma-jfs-cqe-error9 排查走读笔记 |

---

## 新 RFC 约定

- 目录命名：`YYYY-MM-DD-<slug>/`（日期 + 短英文 slug，kebab-case）
- 必备文件：`README.md`（含 Status + 目标 + 代码落点摘要）
- 可选文件：`design.md`、`env-validation.md`、`test-walkthrough.md`、`results.md`、`issue-rfc.md`、`pr-description.md`
