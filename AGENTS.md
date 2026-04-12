# Agent 说明

本仓库 **`vibe-coding-files`** 与 **`yuanrong-datasystem`（Open Yuanrong DataSystem）** 配对使用：前者承载**脚本 + 文档 + 计划**，后者以**源码与 `build.sh`** 为主。

## 工作角色（与本仓协作时）

- **架构师**：评估模块边界、依赖与演进是否合理。  
- **设计师 / 技术专家**：弄清接口语义、错误与可观测性细节，能引用代码证据。  
- **Code Review**：从正确性、并发、风格一致性给出可执行的评审意见。  
- **用户视角**：关注 SDK/文档/错误信息的易用性与可行动性。  
- **测试与验证**：功能验收路径、性能基线与门禁脚本（见 `docs/verification`、`scripts/verify`、`scripts/perf`）。

## 脚本与 Skill

- **新增可执行脚本**：放在仓库根目录 **`scripts/`** 合适子目录，并更新 [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md) 或对应 README。  
- **同一流程多次重复**：建议沉淀为 **Cursor Agent Skill**（本仓示例：[`.cursor/skills/feature-tree-to-docs/SKILL.md`](.cursor/skills/feature-tree-to-docs/SKILL.md)）。

## Excel / PPT

- **Excel**：表格类交付优先脚本生成；见 [`docs/observable/kv-client/README.md`](docs/observable/kv-client/README.md) 与 [`docs/observable/workbook/kv-client/README.md`](docs/observable/workbook/kv-client/README.md)，新脚本优先放 **`scripts/`**。  
- **PPT**：以 `docs/observable/*ppt*`、`ppt.md` 等 Markdown 素材为主；自动化导出可再加 `scripts/` 工具。

## 请先阅读

1. [`docs/agent/README.md`](docs/agent/README.md)  
2. [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md)（`scripts/{build,index,perf,verify}/` 何时用哪个）  
3. [`docs/verification/手动验证确认指南.md`](docs/verification/手动验证确认指南.md)（逐步验收）  
4. [`docs/verification/cmake-non-bazel.md`](docs/verification/cmake-non-bazel.md)  
5. [`docs/verification/构建产物目录与可复现工作流.md`](docs/verification/构建产物目录与可复现工作流.md)（第三方缓存与 `output`/`build` 结构）  
6. [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](plans/agent开发载体_vibe与yuanrong分工.plan.md)  
7. 根目录 [`README.md`](README.md)（角色定位、脚本/Skill/Excel/PPT 约定）

执行本仓库脚本时，若未与 `yuanrong-datasystem` 同级放置，请设置 `DATASYSTEM_ROOT`。
