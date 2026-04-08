# vibe-coding-files

与 **`yuanrong-datasystem` 配套的开发载体仓库**：脚本（build / perf / tests / examples / 覆盖率 / 特性验证）、结构化 **`docs/`**（含 **Agent 指引**）、**`plans/`** 分析与计划。业务**源码**在同级仓库 **yuanrong-datasystem**。

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
- **`docs/`** — 架构、流程、可靠性、验证步骤、**Agent 开发指引**  
- **`plans/`** — 计划与复盘文稿  
- **`datasystem-dev.code-workspace`** — Cursor/VS Code 多根工作区（本仓 + `../yuanrong-datasystem`）

## 环境

将本仓库与 `yuanrong-datasystem` 放在**同一父目录**下克隆（例如 `git-repos/`），或设置 `DATASYSTEM_ROOT` 指向 datasystem 根目录。
