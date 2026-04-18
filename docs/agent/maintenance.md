# 维护规范

本仓库的文档与脚本相互索引，修改后需同步更新相关条目，避免 drifted。

## 新增脚本

1. 脚本放在 `scripts/` 合适子目录（build / development / testing / analysis / documentation）。
2. 更新 [`scripts/README.md`](../../scripts/README.md) 中对应子目录说明。
3. 更新 [`docs/agent/scripts-map.md`](scripts-map.md) 的按任务选脚本章节。
4. 若脚本有 `./ops` 入口，确认 `ops` 路由已注册。
5. 若脚本生成产物（Excel、报告等），在脚本头部注释写明输入输出与依赖。

## 新增文档

1. 文档放在 `docs/` 下对应子目录。
2. 更新 [`docs/README.md`](../README.md) 索引。
3. 若文档涉及新的验证或操作流程，同步更新 [`docs/agent/decision-tree.md`](decision-tree.md) 路由表。
4. 若文档替换或废弃了旧文档，在旧文档头部加 `> 已迁移至 xxx.md` 并保留 30 天后删除。

## 修改验证流程

1. 修改 [`docs/verification/`](../verification/) 下任何文件后，检查 [`手动验证确认指南.md`](../verification/手动验证确认指南.md) 是否仍引用正确步骤。
2. 若命令或路径变化，同步更新 [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md)。
3. 若产物目录结构变化，同步更新 [`构建产物目录与可复现工作流.md`](../verification/构建产物目录与可复现工作流.md)。

## 新增 Cursor Rule / Skill

1. Rule 放在 `.cursor/rules/`，Skill 放在 `.cursor/skills/<name>/SKILL.md`。
2. 在 [`AGENTS.md`](../../AGENTS.md) 的"脚本与 Skill"章节登记新增条目。
3. 若 Rule 影响工作流，在 [`docs/agent/decision-tree.md`](decision-tree.md) 补充路由。

## 修改可靠性 / FEMA 文档

1. 修改 [`docs/reliability/`](../reliability/) 下任何文件后，检查 [`README.md`](../reliability/README.md) 索引中的对应条目仍完整。
2. 新增故障模式须同时更新 FEMA 索引与 StatusCode 文档（如有新增码点）。

## 定期检查

- 每次里程碑或版本发布前，确认 `docs/agent/scripts-map.md` 与 `scripts/` 实际内容一致。
- 每次 `yuanrong-datasystem` 大版本升级后，确认 `docs/verification/` 中构建命令与路径仍有效。
