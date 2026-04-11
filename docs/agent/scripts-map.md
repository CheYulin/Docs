# `scripts/` 地图（指导 Agent）

路径相对于 **`vibe-coding-files`** 仓库根。执行时建议 **`cd` 到本仓根** 或写全路径：`bash "$VIBE/scripts/<类>/<脚本>"`。

## 1. 总览

| 子目录 | 一句话 | 典型何时调用 |
|--------|--------|----------------|
| **`scripts/build/`** | 编译链辅助，不是替代 `build.sh` | 需要 brpc ST 兼容树、或收敛 client 第三方 `NEEDED` |
| **`scripts/index/`** | 只影响 IDE/clangd 索引，不参与真实编译 | URMA/UB 分支跳转差、需刷新 `.cursor/compile_commands.json` |
| **`scripts/perf/`** | 性能与 I/O 可观测性（含 bpftrace，常需 root） | 对比 executor 开销、锁竞争 batch、栈/系统调用证据 |
| **`scripts/verify/`** | 特性门禁与回归（CTest 封装） | 合入前跑 KV executor / brpc 参考用例 |
| **`scripts/lib/`** | 解析 `DATASYSTEM_ROOT` 与本仓根 | 被其它脚本 `source` / Python `import`，一般不单独跑 |
| **`scripts/git/`** | 根据当前 diff **生成 commit message 草稿**（路径启发，无 LLM） | 合入前在本仓根执行 `scripts/git/generate_commit_message.sh`；`--copy` 写入剪贴板 |

## 2. 按任务选脚本

### 2.1 「先确认能编、能跑 ST」

- 在 **`$DS`**：`bash build.sh`（见 [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md)）。  
- **不要**直接执行 `build/tests/st/ds_st_kv_cache`；用 `ctest` 或本仓 **`verify/validate_kv_executor.sh`**。

### 2.2 特性验证 / 门禁（无 sudo）

| 目标 | 入口 |
|------|------|
| KV executor 注入 + 源码关键字审计 | `scripts/verify/validate_kv_executor.sh`（日常加 `--skip-build`） |
| brpc/bthread 参考用例 + 可选覆盖率 HTML | `scripts/verify/validate_brpc_kv_executor.sh` |
| 锁竞争 batch 单测（看 `PERF_CONCURRENT_BATCH`） | `scripts/perf/run_kv_concurrent_lock_perf.sh` |

### 2.3 性能分析（多数无 sudo；bpftrace 要 root）

| 目标 | 入口 |
|------|------|
| Executor inline vs injected 曲线 / csv | `scripts/perf/kv_executor_perf_analysis.py` |
| 门禁 + 可选 perf 落盘（基线目录） | `scripts/perf/collect_client_lock_baseline.sh` |
| 两次 run 目录对比 | `scripts/perf/compare_client_lock_baseline.sh` |
| bpftrace 工作流（打印 sudo 采集命令） | `scripts/perf/run_kv_lock_ebpf_workflow.sh` |
| strace / bpftrace / perf record 原始采集 | `scripts/perf/trace_kv_lock_io.sh`、`trace_kv_lock_io_bpftrace.sh`、`perf_record_kv_lock_io.sh` |
| 栈文本后处理 | `scripts/perf/analyze_kv_lock_bpftrace.py`、`analyze_strace_lock_io.py`、`perf/bpftrace/symbolize_bpftrace_stacks.py` |

### 2.4 代码索引（IDE）

| 目标 | 入口 |
|------|------|
| 从 `build/compile_commands.json` 生成带 URMA 宏的索引库 | `python3 scripts/index/refresh_urma_index_db.py` |

### 2.5 编译构建类辅助

| 目标 | 入口 |
|------|------|
| 列出 client 测试/库真实链接的第三方 | `scripts/build/list_client_third_party_deps.sh` |
| 拉取并构建 brpc ST 兼容依赖（供 validate_brpc 使用） | `scripts/build/bootstrap_brpc_st_compat.sh` |

## 3. 环境变量（最常见）

- **`DATASYSTEM_ROOT`** / **`YUANRONG_DATASYSTEM_ROOT`**：`yuanrong-datasystem` 绝对路径（两仓不同级时必设）。  
- **`CTEST_OUTPUT_ON_FAILURE=1`**：失败时打印用例输出。  

## 4. 相关文档

| 文档 | 用途 |
|------|------|
| [`README.md`](../../scripts/README.md) | 脚本目录说明与 `lib` 约定 |
| [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md) | `build.sh`、CTest、perf、coverage 组合 |
| [`手动验证确认指南.md`](../verification/手动验证确认指南.md) | 逐步验收与记录模板 |
| [`agent开发载体_vibe与yuanrong分工.plan.md`](../../plans/agent开发载体_vibe与yuanrong分工.plan.md) | 双仓分工总表 |
