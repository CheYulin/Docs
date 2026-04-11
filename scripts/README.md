# 开发脚本（操作 `yuanrong-datasystem`）

本目录脚本的**权威位置**在 **`vibe-coding-files`**。**`yuanrong-datasystem`** 的 `scripts/` 仅保留与官方构建链强绑定的内容（如 `build_thirdparty.sh`）；说明见该仓库内 `scripts/README.md`。

**约定**：新增可执行脚本（构建、验证、perf、索引、**生成 xlsx 等**）优先放在本目录下合适子目录；若在 `docs/**/scripts` 等处新增脚本，建议后续迁到 `scripts/` 或在此增加薄封装，并在 [`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md) 登记。专题表格生成可逐步归集到 **`excel/`**（目录可按需创建）。

## 目录结构（按用途）

| 子目录 | 用途 |
|--------|------|
| [**`build/`**](build/) | 编译构建辅助：第三方 / brpc ST 兼容引导、client 依赖清单 |
| [**`index/`**](index/) | 代码索引（IDE）：URMA/UB 等宏补全用的 `compile_commands` 派生 |
| [**`perf/`**](perf/) | 性能分析：executor perf、锁竞争 ST、bpftrace/strace/perf、基线采集与对比 |
| [**`verify/`**](verify/) | 特性验证 / 门禁：KV executor、brpc 参考用例与覆盖率流程 |
| [**`git/`**](git/) | 本仓 Git 辅助：根据变更**生成提交说明草稿**（无 LLM） |
| **`lib/`** | 共享：`datasystem_root`、`vibe_coding_root`（解析 `$DS` 与本仓根） |

**Agent 速查表**（何时用哪个脚本）：[`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md)。

## 能力一览

在 **已配置 CMake 的 datasystem `build/`** 前提下：

- **门禁**：`verify/validate_kv_executor.sh`（`--skip-build` 推荐日常）、`verify/validate_brpc_kv_executor.sh`  
- **锁 / 并发 perf**：`perf/run_kv_concurrent_lock_perf.sh`  
- **Executor perf 分析**：`perf/kv_executor_perf_analysis.py`  
- **基线**：`perf/collect_client_lock_baseline.sh`、`perf/compare_client_lock_baseline.sh`  
- **bpftrace / strace / perf**：`perf/run_kv_lock_ebpf_workflow.sh`、`perf/trace_kv_lock_io_bpftrace.sh`、`perf/trace_kv_lock_io.sh`、`perf/perf_record_kv_lock_io.sh`、`perf/analyze_*.py`、`perf/bpftrace/`  
- **索引**：`index/refresh_urma_index_db.py`  
- **构建辅助**：`build/list_client_third_party_deps.sh`、`build/bootstrap_brpc_st_compat.sh`  
- **提交说明草稿**：`git/generate_commit_message.sh`（默认已暂存或未暂存工作区；`--all` 相对 HEAD；`-c` 复制到剪贴板；`-o FILE` 写入文件）

**构建、examples、全量 CTest** 仍使用 **datasystem 根目录的 `build.sh`**（见 [`docs/verification/cmake-non-bazel.md`](../docs/verification/cmake-non-bazel.md)）。

## Datasystem 根目录

Shell：在脚本中设 `SCRIPT_DIR` 后 `source "${SCRIPT_DIR}/../lib/datasystem_root.sh"`（`SCRIPT_DIR` 为**当前脚本所在目录**，如 `.../scripts/verify`）。Python：`lib/datasystem_root.py`（`scripts_root_from_here` / `resolve_datasystem_root`）。

解析顺序：`DATASYSTEM_ROOT` / `YUANRONG_DATASYSTEM_ROOT` → 与 `vibe-coding-files` 同级的 `../yuanrong-datasystem` 等（见 `lib/datasystem_root.sh`）。

## vibe-coding-files 根目录（产物路径）

Shell：在已 `source datasystem_root.sh` 的同会话中 `source "${SCRIPT_DIR}/../lib/vibe_coding_root.sh"`。设置 **`VIBE_CODING_ROOT`**。  
**bpftrace / strace / perf 原始输出** 默认写入 **`workspace/observability/`** 下对应子目录。

## 链式调用

- 同目录：`"${SCRIPT_DIR}/sibling.sh"`  
- 跨目录：`"${SCRIPT_DIR}/../build/bootstrap_brpc_st_compat.sh"` 等  

保证执行的是本仓库内的版本。

## 详细说明

- [`docs/verification/cmake-non-bazel.md`](../docs/verification/cmake-non-bazel.md)  
- [`docs/agent/scripts-map.md`](../docs/agent/scripts-map.md)  
- [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](../plans/agent开发载体_vibe与yuanrong分工.plan.md)  
- [`docs/agent/README.md`](../docs/agent/README.md)  
