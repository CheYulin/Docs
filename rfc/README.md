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

| RFC | Status | 落地位置（datasystem） |
|-----|--------|-----------------------|
| [2026-04-kvclient-urma-tcp-observability/](2026-04-kvclient-urma-tcp-observability/README.md) | **Done** | `include/datasystem/utils/status.h`：`K_URMA_WAIT_TIMEOUT=1010`、`K_URMA_CONNECT_FAILED=1009`；`urma_manager.cpp` 新增 WARNING/ERROR 日志；Trace 上下文扩展 |
| [2026-04-zmq-rpc-metrics/](2026-04-zmq-rpc-metrics/README.md) | **Done** | `common/metrics/kv_metrics.{h,cpp}`：`ZMQ_SEND_IO_LATENCY`、`ZMQ_RECEIVE_IO_LATENCY`、`ZMQ_LAST_ERROR_NUMBER`、`ZMQ_NETWORK_ERROR_TOTAL`、`ZMQ_SEND/RECEIVE_FAILURE_TOTAL`、`ZMQ_EVENT_DISCONNECT_TOTAL`、`ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL`、`ZMQ_GATEWAY_RECREATE_TOTAL` 等 |

---

## 新 RFC 约定

- 目录命名：`YYYY-MM-<slug>/`（短英文 slug，kebab-case）
- 必备文件：`README.md`（含 Status + 目标 + 代码落点摘要）
- 可选文件：`design.md`、`env-validation.md`、`test-walkthrough.md`、`results.md`、`issue-rfc.md`、`pr-description.md`
