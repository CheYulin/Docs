# Agent Decision Tree

按意图快速路由到最相关的文档，避免全量阅读。

## 按意图路由

| 意图 | 先读 | 再验证 / 补充 |
|------|------|----------------|
| 跑 ST 测试 | [`scripts-map.md`](scripts-map.md) §2.1 | [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md) |
| 特性验证 / 门禁（KV executor、brpc、锁） | [`scripts-map.md`](scripts-map.md) §2.2 | [`手动验证确认指南.md`](../verification/手动验证确认指南.md) |
| 性能基线采集与对比 | [`scripts-map.md`](scripts-map.md) §2.3 | `results/` 目录下最近 run |
| bpftrace / strace 采集 | [`scripts-map.md`](scripts-map.md) §2.3 + `workspace/README.md` | `scripts/analysis/perf/` |
| 新增脚本 | [`scripts/README.md`](../../scripts/README.md) | [maintenance.md](maintenance.md) — 同步更新索引 |
| 写或更新验证步骤 | [`手动验证确认指南.md`](../verification/手动验证确认指南.md) | [`构建产物目录与可复现工作流.md`](../verification/构建产物目录与可复现工作流.md) |
| 了解构建产物 / 第三方缓存 | [`构建产物目录与可复现工作流.md`](../verification/构建产物目录与可复现工作流.md) | `output/` / `build/` 目录 |
| 查看可靠性 / FEMA / 故障模式 | [`reliability/README.md`](../reliability/README.md) | [`reliability/06-playbook.md`](../reliability/06-playbook.md) |
| 查看 Client StatusCode | [`reliability/03-status-codes.md`](../reliability/03-status-codes.md) | `results/` 抽样模板 |
| 查看产品特性树 | [`openyuanrong-data-system-feature-tree.md`](../feature-tree/openyuanrong-data-system-feature-tree.md) | `workspace/reliability/feature_tree.txt` |
| 可观测与定位定界 | [`observable/README.md`](../observable/README.md) | [`observable/04-triage-handbook.md`](../observable/04-triage-handbook.md) |
| 生成 Excel / 可观测工作簿 | [`observable/workbook/README.md`](../observable/workbook/README.md) | `./ops docs.kv_observability_xlsx` |
| 技术调研（brpc、bpftrace 等） | [`tech-research/README.md`](../../tech-research/README.md) | 对应子目录 |
| 刷新 URMA IDE 索引 | [`scripts-map.md`](scripts-map.md) §2.4 | `scripts/development/` |
| 了解双仓分工 | [`agent开发载体_vibe与yuanrong分工.plan.md`](../../plans/agent开发载体_vibe与yuanrong分工.plan.md) | [`README.md`](../../README.md) |

## 按角色路由

| 角色 | 首选文档 |
|------|----------|
| 架构师 | [`docs/architecture/`](../architecture/) + [`agent开发载体_vibe与yuanrong分工.plan.md`](../../plans/agent开发载体_vibe与yuanrong分工.plan.md) |
| Code Review | [`reliability/03-status-codes.md`](../reliability/03-status-codes.md) + [`reliability/04-fault-tree.md`](../reliability/04-fault-tree.md) |
| 测试与验证 | [`手动验证确认指南.md`](../verification/手动验证确认指南.md) + [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md) |
| 用户 / SDK 易用性 | [`用户手册.md`](../../用户手册.md) + [`feature-tree.md`](../feature-tree/openyuanrong-data-system-feature-tree.md) |

## 修改后必须检查

完成任何修改后，参考 [`maintenance.md`](maintenance.md) 确认索引与文档已同步。
