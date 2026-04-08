# Plans

Contents were migrated from `yuanrong-datasystem/plans/` with **directory layout preserved** (e.g. `kv_client_triage/`, `kvexec/`, `client_lock_remediation_phases/`).

**脚本位置**：可执行的验证/分析脚本在 **`vibe-coding-files/scripts/`**（子目录 **`build/`**、**`index/`**、**`perf/`**、**`verify/`**），不在 `yuanrong-datasystem`。地图见 [`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md)。分工总览见 [`agent开发载体_vibe与yuanrong分工.plan.md`](agent开发载体_vibe与yuanrong分工.plan.md)。

**与本仓库其他目录**：与 datasystem **无强绑定的第三方 / 库分析**见 **[`../tech-research/`](../tech-research/README.md)**；bpftrace/perf/strace **产物**见 **[`../workspace/observability/`](../workspace/observability/README.md)**（默认输出目录，**不**再写入 `plans/kvexec/{perf,bpftrace}`）。

New material: prefer **English filenames**, short **kebab-case** names, and organize by feature area as the feature tree matures.

## Top-level `.plan.md` in this repo

- **Active**：`urma_ub_索引脚本使用说明.plan.md`（URMA/UB 索引脚本与验证入口交叉引用）；`agent开发载体_vibe与yuanrong分工.plan.md`（vibe 与 datasystem 分工）。
- **Moved to `docs/`**（叙事、可靠性、架构决策类；索引见 [`docs/README.md`](../docs/README.md)「从 plans/ 迁入的参考稿」）：dsbench 操作计划、Remote Get / 重试链路、client–worker–master 总结、时延敏感 Get 分析、超时与缩容参数、锁内 RPC 治理总览、重启 vs 被动缩容等。
