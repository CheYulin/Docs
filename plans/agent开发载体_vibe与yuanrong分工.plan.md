# Agent 开发载体：`vibe-coding-files` 与 `yuanrong-datasystem` 分工

## 1. 仓库职责（当前约定）

| 仓库 | 承载内容 |
|------|-----------|
| **`yuanrong-datasystem`** | 产品/库**源码**、CMake/Bazel 工程、`build.sh`、与构建强绑定的脚本（如 `scripts/build_thirdparty.sh`、`scripts/modules/`、`stream_cache/` 等）。**不**再存放 KV 验证、锁分析、brpc 引导、URMA 索引等外围自动化脚本。 |
| **`vibe-coding-files`** | **面向人与 Agent 的开发载体**：可执行脚本（build/perf/tests/examples/coverage/特性验证）、`docs/` 操作说明、`plans/` 分析与计划。脚本通过 `DATASYSTEM_ROOT` / 同级目录解析操作 **datasystem 的 `build/`、`plans/`、`example/`**。 |

多根工作区：打开本仓库下的 [`datasystem-dev.code-workspace`](../datasystem-dev.code-workspace)（`vibe-coding-files` + `../yuanrong-datasystem`）。

---

## 2. 本仓库脚本能做什么（概要）

路径均为 **`vibe-coding-files/scripts/`**，按类分子目录（见 [`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md)）：**`build/`**、**`index/`**、**`perf/`**、**`verify/`**，以及共享 **`lib/`**。

| 目的 | 入口 |
|------|------|
| **构建** | 在 **datasystem** 根目录执行 `bash build.sh`（本仓不包装 `build.sh`，避免重复维护）；见 [`docs/verification/cmake-non-bazel.md`](../docs/verification/cmake-non-bazel.md) |
| **测试（含 executor 注入 / 锁 ST）** | `verify/validate_kv_executor.sh`、`perf/run_kv_concurrent_lock_perf.sh`；`ctest` 用法见验证文档 |
| **Perf** | `perf/kv_executor_perf_analysis.py`；datasystem 侧 `build.sh -p on` |
| **覆盖率** | datasystem `build.sh -c on|html`；可选 `verify/validate_brpc_kv_executor.sh --coverage-html` |
| **Examples** | datasystem `bash build.sh -t run_example`（会先编 example，见 `build.sh -h`） |
| **特性 / 门禁验证** | `verify/validate_brpc_kv_executor.sh`、`perf/collect_client_lock_baseline.sh`、`perf/compare_client_lock_baseline.sh` |
| **锁 / I/O 观测** | `perf/run_kv_lock_ebpf_workflow.sh`、`perf/trace_kv_lock_io_bpftrace.sh`、`perf/trace_kv_lock_io.sh`、`perf/perf_record_kv_lock_io.sh`、`perf/analyze_*.py` |
| **IDE：URMA/UB 分支索引** | `index/refresh_urma_index_db.py`（见下文第 4 节） |
| **构建辅助 / 依赖** | `build/list_client_third_party_deps.sh`、`build/bootstrap_brpc_st_compat.sh` |

**亲自验收**：按 [`docs/verification/手动验证确认指南.md`](../docs/verification/手动验证确认指南.md) 逐步执行并勾选清单。

**产物路径与可复现构建**：[`docs/verification/构建产物目录与可复现工作流.md`](../docs/verification/构建产物目录与可复现工作流.md)。

**Agent 执行顺序建议**：先读 [`docs/agent/README.md`](../docs/agent/README.md) 与 [`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md)，再按 [`docs/verification/cmake-non-bazel.md`](../docs/verification/cmake-non-bazel.md) 查命令。

---

## 3. `ROOT_DIR` / `DATASYSTEM_ROOT` 解析

Shell 脚本在设置 `SCRIPT_DIR`（脚本所在目录，如 `scripts/verify`）后 `source "${SCRIPT_DIR}/../lib/datasystem_root.sh"`，得到 **`ROOT_DIR` = yuanrong-datasystem 根目录**：

1. `DATASYSTEM_ROOT` 或 `YUANRONG_DATASYSTEM_ROOT`（优先）  
2. 否则若 **`vibe-coding-files` 根**（`scripts/` 的父目录）的同级存在 **`yuanrong-datasystem`**，则指向该目录  
3. 其它回退逻辑见 `lib/datasystem_root.sh`

同类目录内链式调用使用 **`${SCRIPT_DIR}/...`**；跨类（如 verify 调 build）使用 **`${SCRIPT_DIR}/../build/...`**。

---

## 4. URMA/UB IDE 索引（不参与真实编译）

当本机未打开 `USE_URMA` / `URMA_OVER_UB` 构建时，IDE 可对 `#ifdef` 分支补全不佳。`index/refresh_urma_index_db.py` 从 `<datasystem>/build/compile_commands.json` 生成 **仅用于索引** 的 `<datasystem>/.cursor/compile_commands.json`，并追加 `-DUSE_URMA -DURMA_OVER_UB`。

```bash
python3 scripts/index/refresh_urma_index_db.py
```

可选参数：`--source`、`--output`、`--macro`（见脚本 `-h`）。**datasystem** 侧 `.vscode/settings.json` 若已指向 `.cursor/compile_commands.json`，刷新后 **Reload Window** 或重启 clangd。

索引与 **运行时 executor、perf 埋点、覆盖率、锁用例** 无关。

---

## 5. 与 datasystem `build.sh` 的关系

- **`-t`**：`off` / `build` / `run` / `run_cpp` / `run_cases` / `run_example` 等  
- **`-c`**：覆盖率  
- **`-p`**：perf 点  
- **`-m`**：用例超时  

均在 **yuanrong-datasystem** 根目录执行；本仓库文档 [`cmake-non-bazel.md`](../docs/verification/cmake-non-bazel.md) 只描述推荐组合，不复制完整 `build.sh` 手册。

---

## 6. 历史说明

- 原 `plans/urma_ub_索引脚本使用说明.plan.md` 中关于 URMA 索引、executor、perf、coverage、锁验证的条目已**合并进本计划**；旧文件名保留为**重定向**（见同目录下 `urma_ub_索引脚本使用说明.plan.md`）。

## 7. 旧文稿中的路径

`plans/` 下较早文档可能仍写「在 **yuanrong-datasystem** 根目录执行 `scripts/xxx`」。脚本已迁出后，应理解为：

- **`vibe-coding-files/scripts/<类>/xxx`**（如 `scripts/verify/validate_kv_executor.sh`），或  
- 在 datasystem 根目录时使用 **`../vibe-coding-files/scripts/<类>/xxx`**（按实际克隆路径调整）。

必要时设置 **`DATASYSTEM_ROOT`**。
