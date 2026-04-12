# KV Client FEMA 与可靠性分析（入口）

本组文档由 [`plans/kv_client_triage/cases.md`](../../plans/kv_client_triage/cases.md) **拆分迁移**而来，在 `docs/reliability/` 下以 **`00-` 前缀**标明「客户侧 FEMA / 故障模式 / 读写路径 / 粗算 SLI」主线，便于与 [`failure-modes.md`](failure-modes.md)、[`invariants.md`](invariants.md) 交叉维护。  
目录总索引与阅读路径见 [`README.md`](README.md)。

## 与 `plans/kv_client_triage/` 的对照

| 主题 | `plans/` 长篇（源码/Playbook 锚点） | 本文档组（结构化清单） |
|------|-------------------------------------|------------------------|
| 故障处理与数据可靠性 | [`FAULT_HANDLING_AND_DATA_RELIABILITY.md`](../../plans/kv_client_triage/FAULT_HANDLING_AND_DATA_RELIABILITY.md) | [00-kv-client-fema-read-paths-reliability.md](00-kv-client-fema-read-paths-reliability.md) **§可靠性设计** |
| 客户视角一表 | [`KV_CLIENT_CUSTOMER_ALLINONE.md`](../../plans/kv_client_triage/KV_CLIENT_CUSTOMER_ALLINONE.md) | 业务流程 / 故障模式编号与之一致 |
| Triage Playbook | [`KV_CLIENT_TRIAGE_PLAYBOOK.md`](../../plans/kv_client_triage/KV_CLIENT_TRIAGE_PLAYBOOK.md) | [operations/](operations/) 运维长文 |

## KV SDK × FEMA × 定位定界（Excel / 预览稿）

面向 **Init / MCreate / MSet / MGet** 的故障模式行表、检测与恢复（含 **URMA+Trace 关联**）、报错码下钻与傻瓜步骤：

- **使用步骤（推荐先读）**：[workspace/reliability/kv-sdk-fema-使用步骤.md](../../workspace/reliability/kv-sdk-fema-使用步骤.md)  
- 预览与流程图：[workspace/reliability/kv-sdk-fema-reliability-observability.md](../../workspace/reliability/kv-sdk-fema-reliability-observability.md)  
- 生成 Excel：`./ops docs.kv_fema_workbook` → `workspace/reliability/kv_sdk_fema_analysis.xlsx`  
- 与 [`docs/observable/kv-client/`](../observable/kv-client/README.md) 联动使用。

## 分册列表（按阅读顺序）

| 文档 | 内容 |
|------|------|
| [00-kv-client-fema-scenarios-failure-modes.md](00-kv-client-fema-scenarios-failure-modes.md) | 业务架构与术语、业务流程 1～11、故障模式 1～53 |
| [00-kv-client-fema-read-paths-reliability.md](00-kv-client-fema-read-paths-reliability.md) | 关键读写路径（步骤 1～6）、通信/整体可靠性表；**PlantUML 链接见下** |
| [00-kv-client-fema-timing-and-sli.md](00-kv-client-fema-timing-and-sli.md) | 毫秒/秒级时间指标、2/N 粗算与监控桶 |
| [00-kv-client-fema-dryrun-remote-read.md](00-kv-client-fema-dryrun-remote-read.md) | DryRun 模板与 UB 端口样例、举一反三速查 |
| [00-kv-client-visible-status-codes.md](00-kv-client-visible-status-codes.md) | **Client 可见 `StatusCode` 全表**、与 FEMA 的启发式对应、**跑测时日志审视与 `results/` 记录模板** |

> 运维部署与扩缩容摘要已归档：[`archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md`](archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md)。当前请优先使用 [operations/](operations/)。

## PlantUML 配图位置

| 类型 | 目录 |
|------|------|
| **读写时序 / 拓扑 / E2E / 部署交互** | [`docs/flows/sequences/kv-client/`](../flows/sequences/kv-client/) |
| **定位定界总图与分图（客户：先错误码+手册）** | [`docs/observable/kv-client/puml/README-总图与分图.md`](../observable/kv-client/puml/README-总图与分图.md) |
| **故障处理与 triage 文档地图** | [`docs/reliability/diagrams/kv-client/`](diagrams/kv-client/) |

## 高可信度外部入口

- **openYuanrong 官方**（安装、部署、开发接口示意）：[`00-reference-openyuanrong-official.md`](00-reference-openyuanrong-official.md)
- **官方案例与接口用途**（后续索引用）：[`../feature-tree/openyuanrong-official-case-examples-index.md`](../feature-tree/openyuanrong-official-case-examples-index.md)

## 修订说明

- 拆分后 `plans/kv_client_triage/cases.md` 保留**短引导**，正文以本目录 `00-*.md` 为准同步更新。
