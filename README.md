# yuanrong-datasystem-agent-workbench

> Agent / vibe-coding workbench paired with **Open Yuanrong DataSystem** (`yuanrong-datasystem`):
> scripts, verification flows, RFCs, plans, observability docs, and Cursor Agent Skills.
> Source code lives in the sibling `yuanrong-datasystem` repo; this repo is where agents
> **plan, run, verify, and document**.

> 本仓的历史目录名仍为 `vibe-coding-files/`，文档与脚本中的相对路径不受影响；GitHub 上的仓名建议改为 `yuanrong-datasystem-agent-workbench`（或短名 `ds-agent-workbench`）。

与 **`yuanrong-datasystem`（Open Yuanrong DataSystem）** 配套的开发载体仓库：业务**源码**在同级仓库 **`yuanrong-datasystem`**；本仓承载脚本、文档、计划、RFC、验证产物与 Agent 工作流。

## 本仓对 Agent 的角色定位

在本仓库与配对 datasystem 上工作时，Agent 应同时具备下列视角（可按任务侧重）：

| 视角 | 职责要点 |
|------|-----------|
| **架构师** | 模块边界、依赖方向、扩展点与风险；改动是否破坏分层与可运维性。 |
| **设计师与技术专家** | 接口语义、错误码与契约、日志/可观测性含义；能指到具体文件与行为。 |
| **Code Review** | 变更合理性、并发与资源生命周期、与现有模式一致；指出遗漏与替代方案。 |
| **用户 / 易用性** | SDK 与 CLI 的心智模型、错误信息是否可行动、文档与示例是否对齐真实行为。 |
| **测试与验证** | 功能用例、ST/门禁、性能基线与对比；知道「如何证明改对了、没拖慢」。 |

详细操作清单与文档地图见 [`AGENTS.md`](AGENTS.md)、[`docs/agent/README.md`](docs/agent/README.md)。

## 脚本与 Skill 约定

- **可执行脚本**：**统一放在仓库根目录 [`scripts/`](scripts/README.md)** 下，按用途分子目录（如 `build/`、`perf/`、`verify/`、`index/`）；新增脚本优先放此处，并在 [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md) 或对应 `README` 中登记。  
  - 历史或专题脚本可能仍位于 `docs/**/scripts/`、`workspace/**/scripts/` 等，**新增长脚本建议迁到 `scripts/`** 或包一层 `scripts/` 下的薄封装。  
- **重复出现的操作流程**（同一套命令、检查项、评审维度多次使用）：建议在 Cursor 中**沉淀为 Agent Skill**（可参考 Cursor 的 *create skill* 指引），便于跨会话一致执行；本仓已有示例： [`.cursor/skills/feature-tree-to-docs/SKILL.md`](.cursor/skills/feature-tree-to-docs/SKILL.md)。

## Excel 与 PPT

- **Excel**：定位定界手册、观测矩阵、特性树等以表格交付时，优先用 **脚本生成 `.xlsx`**（可维护、可复现）。现有示例：[`docs/observable/workbook/README.md`](docs/observable/workbook/README.md)（含生成命令 `./ops docs.kv_observability_xlsx`）、[`workspace/reliability/scripts/build_openyuanrong_fault_library_xlsx.py`](workspace/reliability/scripts/build_openyuanrong_fault_library_xlsx.py)。**新增表格生成器建议落在 `scripts/` 子目录**（例如 `scripts/documentation/`），并在文档中写明输入输出与依赖（如 `openpyxl`）。  
- **PPT**：本仓以 **Markdown 素材 + 结构提纲** 为主。需要自动化时可在 `scripts/` 增加导出步骤（如 pandoc / python-pptx），并在 `docs/agent` 中登记。

## 快速开始

| 角色 | 第一步 |
|------|--------|
| 人 / Agent | 阅读 [`AGENTS.md`](AGENTS.md) 与 [`docs/agent/README.md`](docs/agent/README.md) |
| **亲自逐步验收** | [`docs/verification/手动验证确认指南.md`](docs/verification/手动验证确认指南.md) |
| **产物目录 / 第三方缓存 / 可复现工作流** | [`docs/verification/构建产物目录与可复现工作流.md`](docs/verification/构建产物目录与可复现工作流.md) |
| 验证与构建命令速查 | [`docs/verification/cmake-non-bazel.md`](docs/verification/cmake-non-bazel.md) |
| 分工总览 | [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](plans/agent开发载体_vibe与yuanrong分工.plan.md) |

## 目录

- **`scripts/`** — 可执行工具（KV executor、锁、brpc、URMA 索引、bpftrace 等），见 [`scripts/README.md`](scripts/README.md)  
- **`docs/`** — 架构、流程、可靠性、验证步骤、**Agent 开发指引**、可观测性 / Excel / PPT 素材  
- **`plans/`** — 计划与复盘文稿  
- **`.cursor/skills/`** — 与本仓协作相关的 Cursor Agent Skills（可选）  
- **`datasystem-dev.code-workspace`** — Cursor/VS Code 多根工作区（本仓 + `../yuanrong-datasystem`）

## 环境

将本仓库与 `yuanrong-datasystem` 放在**同一父目录**下克隆（例如 `git-repos/`），或设置 `DATASYSTEM_ROOT` 指向 datasystem 根目录。
