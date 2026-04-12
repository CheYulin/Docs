# 文档索引

路径相对于本仓库根目录 `vibe-coding-files/`。

| 区域 | 用途 |
|------|------|
| [**agent/**](agent/) | **指导 Agent**：仓库分工、[`scripts-map.md`](agent/scripts-map.md)（`scripts/` 分类）、检查清单 |
| [architecture/](architecture/) | 4+1 视图与可选 ADR |
| [flows/](flows/) | 序列图与流程叙事 |
| [reliability/](reliability/) | 不变量与失败模式；**KV Client FEMA（`00-kv-client-fema-*.md`）**；[`00-kv-client-visible-status-codes.md`](reliability/00-kv-client-visible-status-codes.md)（**跑测时 Client 故障与 StatusCode**）；[deep-dives/client-status-codes-evidence-chain.md](reliability/deep-dives/client-status-codes-evidence-chain.md)；[operations/](reliability/operations/) 运维长文 |
| [verification/](verification/) | **构建、测试、perf、覆盖率、examples**；[手动验证确认指南](verification/手动验证确认指南.md)；[构建产物目录与可复现工作流](verification/构建产物目录与可复现工作流.md) |
| [**用户手册.md**](用户手册.md) | **端到端上手**：环境要求、pip/源码、`build.sh`、测试、`dscli`/ETCD/进程与 K8s 摘要；细节链官方入门 |
| [results/](../results/) | **本地验证输出目录**（命令与 `tee` 日志；除 `README.md` 外不入库，见该目录说明） |
| [feature-tree/](feature-tree/) | **特性树**：[openYuanrong Data System 特性树（Agent）](feature-tree/openyuanrong-data-system-feature-tree.md)；官方案例索引见该目录 |
| [observable/](observable/) | 定位定界总纲与专题；**KV Client 主入口**：[kv-client/README.md](observable/kv-client/README.md) · **工作簿包**：[workbook/kv-client/README.md](observable/workbook/kv-client/README.md) · **分层索引**：[kv-client/文档索引.md](observable/kv-client/文档索引.md) · **历史归档**：[archive/README.md](observable/archive/README.md) |

仓库根下另有 **[`tech-research/`](../tech-research/README.md)**（第三方与库的技术调研）与 **[`workspace/`](../workspace/README.md)**（bpftrace/perf/strace 等**可复现产物**，默认输出目录）。

### 从 `plans/` 迁入的参考稿

以下文稿已按主题落在 `docs/`，**不再**以 `plans/*.plan.md` 维护；顶层仍在 `plans/` 持续迭代的执行项见 [`plans/README.md`](../plans/README.md)。

| 文稿 | 路径 |
|------|------|
| dsbench 安装 / 部署 / 运行 / 观测 | [flows/narratives/dsbench-install-deploy-run-observe.md](flows/narratives/dsbench-install-deploy-run-observe.md) |
| Remote Get（UB/URMA）流程梳理 | [flows/narratives/remote-get-ub-urma-flow.md](flows/narratives/remote-get-ub-urma-flow.md) |
| RemoteGet TCP 回切、URMA 重试与 poll/jfc 时延（20ms） | [flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md](flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md) |
| Client–Worker–Master 重试与故障处理总结 | [flows/narratives/client-worker-master-retry-fault-handling.md](flows/narratives/client-worker-master-retry-fault-handling.md) |
| Get 时延敏感场景（5ms / 20ms）分析 | [reliability/deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md](reliability/deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md) |
| 超时参数与重启 / 缩容分歧 | [reliability/deep-dives/timeout-params-restart-vs-scale-down.md](reliability/deep-dives/timeout-params-restart-vs-scale-down.md) |
| Client 锁内日志与 RPC / bthread 阻塞风险治理（总览） | [reliability/deep-dives/client-lock-in-rpc-logging-bthread-blocking.md](reliability/deep-dives/client-lock-in-rpc-logging-bthread-blocking.md) |
| 原地重启 vs 被动缩容（设计取舍） | [architecture/decisions/restart-vs-passive-scale-down.md](architecture/decisions/restart-vs-passive-scale-down.md) |

### KV Client FEMA 与运维（由 `plans/kv_client_triage/cases.md` 拆分）

| 说明 | 路径 |
|------|------|
| **总入口（必读）** | [reliability/00-kv-client-fema-index.md](reliability/00-kv-client-fema-index.md) |
| 业务场景与故障模式表 | [reliability/00-kv-client-fema-scenarios-failure-modes.md](reliability/00-kv-client-fema-scenarios-failure-modes.md) |
| 读写路径与可靠性设计 | [reliability/00-kv-client-fema-read-paths-reliability.md](reliability/00-kv-client-fema-read-paths-reliability.md) |
| 时间指标与 2/N 粗算 | [reliability/00-kv-client-fema-timing-and-sli.md](reliability/00-kv-client-fema-timing-and-sli.md) |
| DryRun 远端读样例 | [reliability/00-kv-client-fema-dryrun-remote-read.md](reliability/00-kv-client-fema-dryrun-remote-read.md) |
| 运维部署与扩缩容（历史摘要） | [reliability/archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md](reliability/archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md) |
| 读写 PlantUML | [flows/sequences/kv-client/](flows/sequences/kv-client/) |
| 故障处理 PlantUML | [reliability/diagrams/kv-client/](reliability/diagrams/kv-client/) |
| 运维长文（L0–L5、resource.log、31/32、1002） | [reliability/operations/](reliability/operations/) |
| openYuanrong 官方（安装/部署/日志/接口示意） | [reliability/00-reference-openyuanrong-official.md](reliability/00-reference-openyuanrong-official.md) |
| 官方案例索引（后续特性树） | [feature-tree/openyuanrong-official-case-examples-index.md](feature-tree/openyuanrong-official-case-examples-index.md) |

## 代码在哪

**yuanrong-datasystem** 为同级 Git 仓库（例如 `../yuanrong-datasystem/`）。建议打开 [`datasystem-dev.code-workspace`](../datasystem-dev.code-workspace)。

## Agent 入口

1. [`agent/README.md`](agent/README.md)  
2. [`verification/cmake-non-bazel.md`](verification/cmake-non-bazel.md)  
3. [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](../plans/agent开发载体_vibe与yuanrong分工.plan.md)

## 计划文稿

内部计划与大型分析目录树：[`../plans/`](../plans/)。顶层 **执行中** 的 `.plan.md` 目前为 **`urma_ub_索引脚本使用说明.plan.md`**（URMA/UB IDE 索引脚本）与 **`agent开发载体_vibe与yuanrong分工.plan.md`**（仓库分工）；其余已沉淀文稿见上表。
