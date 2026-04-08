# 业务场景与故障 / 可靠性 Case 清单

**正文已拆分迁移至 `docs/reliability/` 下 `00-kv-client-fema-*.md`，请以该组文档为单一事实来源（SSOT）。**

- **入口索引**：[`docs/reliability/00-kv-client-fema-index.md`](../../docs/reliability/00-kv-client-fema-index.md)

与 [`KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md`](./KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md) 中的部署与 DryRun 表对照使用。

**系统可靠性方案**（通信/组件/数据/etcd）与 **triage 口径对齐**：见 [`FAULT_HANDLING_AND_DATA_RELIABILITY.md`](./FAULT_HANDLING_AND_DATA_RELIABILITY.md)（**「第五节」与 triage、Case 对齐说明** 与本文、REMOTE 对照）。

**配图（PlantUML）**：

- 读写时序 / 拓扑 / E2E：[`docs/flows/sequences/kv-client/`](../../docs/flows/sequences/kv-client/)
- 故障处理与文档地图：[`docs/reliability/diagrams/kv-client/`](../../docs/reliability/diagrams/kv-client/)

**客户视角**：业务流程（1～11）、故障模式（1～53）、关键读写路径（步骤 1～6）与故障检测/定界步骤的对照表与主流程（T1～T6）写在 [`KV_CLIENT_CUSTOMER_ALLINONE.md`](./KV_CLIENT_CUSTOMER_ALLINONE.md) **第一节 1.1～1.4**（可与工单中的 Case 编号同填）。

**运维部署与扩缩容**长文与分层排查：[`docs/reliability/operations/`](../../docs/reliability/operations/)。

**官方安装/部署/日志高可信度入口**：[`docs/reliability/00-reference-openyuanrong-official.md`](../../docs/reliability/00-reference-openyuanrong-official.md)。

---

## 修订记录

- 表格由原始清单整理为规范 Markdown；**主体内容**迁至 `docs/reliability/00-kv-client-fema-*.md`（本文件保留导航与交叉引用）。
