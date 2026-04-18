# 文档索引

路径相对于本仓库根目录 `vibe-coding-files/`。

## 主目录

| 区域 | 用途 |
|------|------|
| [**agent/**](agent/) | **指导 Agent**：仓库分工、[`scripts-map.md`](agent/scripts-map.md)（`scripts/` 分类）、检查清单 |
| [architecture/](architecture/) | 4+1 视图与可选 ADR |
| [flows/](flows/) | 序列图与流程叙事 |
| [**reliability/**](reliability/) | **KV Client 可靠性**：架构、故障模式、StatusCode 分层、故障树、可靠性设计、运维 playbook |
| [**observable/**](observable/) | **可观测与定位定界**：调用链、故障模式库、triage 手册、metrics、外部依赖（URMA / OS / etcd / 二级存储） |
| [verification/](verification/) | **构建、测试、perf、覆盖率、examples**；[手动验证确认指南](verification/手动验证确认指南.md)；[构建产物目录与可复现工作流](verification/构建产物目录与可复现工作流.md) |
| [**用户手册.md**](用户手册.md) | **端到端上手**：环境要求、pip / 源码、`build.sh`、测试、`dscli` / ETCD / 进程与 K8s 摘要 |
| [feature-tree/](feature-tree/) | **特性树**：[openYuanrong Data System 特性树](feature-tree/openyuanrong-data-system-feature-tree.md)；官方案例索引 |

仓库根下另有：
- **[`../rfc/`](../rfc/README.md)**：特性开发 RFC（设计 / 验证 / PR 文案）
- **[`../plans/`](../plans/README.md)**：短周期开发计划（与 rfc 规划合并中）
- **[`../results/`](../results/README.md)**：本地验证输出目录
- **[`../tech-research/`](../tech-research/README.md)**：第三方与库的技术调研
- **[`../workspace/`](../workspace/README.md)**：bpftrace / perf / strace 等可复现产物

## KV Client 主线

### 可靠性（`docs/reliability/`）

| 序号 | 文档 | 主题 |
|-----|------|------|
| 01 | [01-architecture-and-paths.md](reliability/01-architecture-and-paths.md) | 架构 + 正常 / 切流读写路径 6 步 |
| 02 | [02-failure-modes-and-sli.md](reliability/02-failure-modes-and-sli.md) | 业务流程 × 故障模式 53 + 时间量级 + 2/N SLI |
| 03 | [03-status-codes.md](reliability/03-status-codes.md) | StatusCode 全表 + L0-L5 分层 |
| 04 | [04-fault-tree.md](reliability/04-fault-tree.md) | 错误码 → 根因故障树（6 大类）+ 源码证据 |
| 04a | [04a-fault-tree-by-interface.md](reliability/04a-fault-tree-by-interface.md) | Init / MCreate / MSet / MGet 接口级故障树 |
| 05 | [05-reliability-design.md](reliability/05-reliability-design.md) | 通信 / 组件 / etcd 可靠性方案 + 不变量 |
| 06 | [06-playbook.md](reliability/06-playbook.md) | 运维排障：部署 / 扩缩容、1002 三元化、31/32 可见性、`resource.log` |
| R | [references.md](reliability/references.md) | openYuanrong 官方入口、DryRun 模板 |
| D | [deep-dives/](reliability/deep-dives/) | etcd 隔离与恢复、超时与时延预算、client 锁内 RPC |

### 可观测（`docs/observable/`）

| 序号 | 文档 | 主题 |
|-----|------|------|
| 01 | [01-architecture.md](observable/01-architecture.md) | 可观测架构：应用日志 / access log / metrics / Trace |
| 02 | [02-call-chain-and-syscalls.md](observable/02-call-chain-and-syscalls.md) | Init / MCreate / MSet / MGet 调用链 + OS/URMA 接口清单 |
| 03 | [03-fault-mode-library.md](observable/03-fault-mode-library.md) | FM-001..023 故障模式库 + 日志关键字 + URMA/OS 互斥定界 |
| 04 | [04-triage-handbook.md](observable/04-triage-handbook.md) | 定位定界手册：Trace × 分支 × 责任域（研发 / 测试 / 客户）|
| 05 | [05-metrics-and-perf.md](observable/05-metrics-and-perf.md) | ZMQ / KV metrics 清单 + 性能关键路径 + 采集命令 |
| 06 | [06-dependencies/](observable/06-dependencies/README.md) | 外部依赖：URMA / OS syscall / etcd / 二级存储 |
| — | [diagrams/](observable/diagrams/) | 总图 + 分图 + 步骤图（PlantUML）|
| — | [workbook/](observable/workbook/) | Excel 工作簿 + Sheet1/2/3 Markdown 对照 |

### reliability vs observable 分工

- **reliability**：错误码 → 根因（代码证据）、故障处理方案、SLI、运维剧本
- **observable**：调用链 → 现象 → 证据 → 归因，定位定界 SOP
- 两边通过错误码与 FM 编号对齐，交叉引用不重复。

## 其它主题

| 文稿 | 路径 |
|------|------|
| dsbench 安装 / 部署 / 运行 / 观测 | [flows/narratives/dsbench-install-deploy-run-observe.md](flows/narratives/dsbench-install-deploy-run-observe.md) |
| Remote Get（UB/URMA）流程梳理 | [flows/narratives/remote-get-ub-urma-flow.md](flows/narratives/remote-get-ub-urma-flow.md) |
| RemoteGet TCP 回切、URMA 重试与 poll/jfc 时延 | [flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md](flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md) |
| Client–Worker–Master 重试与故障处理 | [flows/narratives/client-worker-master-retry-fault-handling.md](flows/narratives/client-worker-master-retry-fault-handling.md) |
| 原地重启 vs 被动缩容（设计取舍）| [architecture/decisions/restart-vs-passive-scale-down.md](architecture/decisions/restart-vs-passive-scale-down.md) |

## 代码在哪

**yuanrong-datasystem** 为同级 Git 仓库（`../yuanrong-datasystem/`）。建议打开 [`datasystem-dev.code-workspace`](../datasystem-dev.code-workspace)。

## Agent 入口

1. [`agent/README.md`](agent/README.md)
2. [`verification/cmake-non-bazel.md`](verification/cmake-non-bazel.md)
3. [`../plans/agent开发载体_vibe与yuanrong分工.plan.md`](../plans/agent开发载体_vibe与yuanrong分工.plan.md)
