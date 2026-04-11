# 指导 Agent 使用本仓库

本目录说明：**何时改 `yuanrong-datasystem`，何时用 `vibe-coding-files` 的脚本与文档**，避免在错误仓库里找工具或重复造轮子。

## 0. Agent 角色（Open Yuanrong DataSystem）

在本载体仓库与配对 datasystem 上工作时，宜同时具备：**架构合理性**（边界与依赖）、**设计与语义细节**（接口与观测）、**Code Review**、**用户易用性**、**测试与性能验证**。根目录 [`README.md`](../../README.md) 有对照表；重复流程建议做成 **Cursor Skill**（见 [`.cursor/skills/feature-tree-to-docs/SKILL.md`](../../.cursor/skills/feature-tree-to-docs/SKILL.md)）。

**Excel**：可复现表格优先用脚本生成，见 [`docs/observable/kv-client-excel/README.md`](../observable/kv-client-excel/README.md)；新脚本放 [`scripts/`](../../scripts/README.md)。**PPT**：见 [`docs/observable/ppt.md`](../observable/ppt.md) 与 `docs/observable/定位定界-ppt素材-*.md`。

## 1. 仓库分工（必读）

- **`yuanrong-datasystem`**：C/C++ 等**产品源码**、`build.sh`、与 CMake 强耦合的 `scripts/build_thirdparty.sh` 等。  
- **`vibe-coding-files`**：**开发载体**——验证 KV executor、锁、brpc ST、覆盖率门禁、URMA IDE 索引、bpftrace/strace 辅助；以及 `docs/`、`plans/`。

打开 [`datasystem-dev.code-workspace`](../../datasystem-dev.code-workspace) 同时加载两个根目录。

## 2. 执行任务前的检查清单

1. **定位 datasystem 根**：若脚本找不到仓库，设置 `export DATASYSTEM_ROOT=/绝对路径/yuanrong-datasystem`。  
2. **ST 测试**：用 **`ctest --test-dir <build>`** 或本仓库 **`scripts/verify/validate_kv_executor.sh`**，不要直接执行 `ds_st_kv_cache` 二进制（缺 `LD_LIBRARY_PATH` 会失败）。  
3. **已编过 ST、避免长耗时重编**：`scripts/verify/validate_kv_executor.sh --skip-build <build>`。  
4. **需要人类读的长文档**：优先写进 `docs/` 或 `plans/`，不要在对话里只留碎片命令。

## 3. 文档地图

| 文档 | 用途 |
|------|------|
| [**`scripts-map.md`**](scripts-map.md) | **`scripts/` 分类地图**：build / index / perf / verify 何时用哪个入口 |
| [`docs/verification/手动验证确认指南.md`](../verification/手动验证确认指南.md) | **逐步验收**：每步命令、成功判据、自检清单 |
| [`docs/verification/构建产物目录与可复现工作流.md`](../verification/构建产物目录与可复现工作流.md) | 第三方缓存、`output`/`build` 目录结构、Client/Worker/whl |
| [`docs/verification/cmake-non-bazel.md`](../verification/cmake-non-bazel.md) | build、perf、coverage、executor、锁、examples 命令速查 |
| [`scripts/README.md`](../../scripts/README.md) | 脚本子目录说明、`lib/` 解析、`scripts-map` 链接 |
| [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](../../plans/agent开发载体_vibe与yuanrong分工.plan.md) | 分工与脚本总表 |
| [`docs/reliability/00-kv-client-fema-index.md`](../reliability/00-kv-client-fema-index.md) | 客户侧 FEMA / 故障模式清单 / 读写路径；运维见 [`docs/reliability/operations/`](../reliability/operations/) |
| [`docs/reliability/00-kv-client-visible-status-codes.md`](../reliability/00-kv-client-visible-status-codes.md) | 跑测时审视 **Client `StatusCode`**、grep 建议、`results/` 抽样模板 |
| [`tech-research/README.md`](../../tech-research/README.md) | 第三方库技术调研（如 brpc、bpftrace 方法论） |
| [`docs/feature-tree/openyuanrong-data-system-feature-tree.md`](../feature-tree/openyuanrong-data-system-feature-tree.md) | **产品特性树**（openYuanrong / yuanrong-datasystem 能力矩阵；表头说明 + 同目录 `.xlsx`） |
| [`workspace/README.md`](../../workspace/README.md) | bpftrace/perf/strace **默认产物根**（`workspace/observability/`） |

## 4. 修改边界

- **改业务逻辑 / CMake 目标 / 测试用例**：在 **yuanrong-datasystem**。  
- **改验证流程、加新门禁脚本、更新操作说明**：在 **vibe-coding-files**（并更新 `docs/verification` 与本目录）。
