# `scripts/` 地图（指导 Agent）

优先从仓库根使用统一入口：`./ops <能力命令>`。  
仅在调试/开发脚本自身时，才直接访问 `scripts/...` 内部路径。

## 1. 总览

| 子目录 | 一句话 | 典型何时调用 |
|--------|--------|----------------|
| **`scripts/build/`** | 编译链辅助，不是替代 `build.sh` | 需要 brpc ST 兼容树、或收敛 client 第三方 `NEEDED` |
| **`scripts/development/`** | 开发阶段脚本（index/git/lib/ide） | 刷新索引、生成提交说明草稿、共享库 |
| **`scripts/testing/`** | 测试阶段脚本（verify） | 合入前跑 KV executor / brpc 参考用例 |
| **`scripts/analysis/`** | 分析阶段脚本（perf） | 对比 executor 开销、锁竞争、栈/系统调用证据 |
| **`scripts/documentation/`** | 文档阶段脚本（excel/observable） | 生成工作簿与预览页面 |

## 2. 按任务选脚本

### 2.1 「先确认能编、能跑 ST」

- 在 **`$DS`**：`bash build.sh`（见 [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md)）。  
- 不要直接执行 `build/tests/st/ds_st_kv_cache`；用 `ctest` 或 `./ops test.kv_executor`。

### 2.2 特性验证 / 门禁（无 sudo）

| 目标 | 入口 |
|------|------|
| KV executor 注入 + 源码关键字审计 | `./ops test.kv_executor`（日常加 `--skip-build`） |
| brpc/bthread 参考用例 + 可选覆盖率 HTML | `./ops test.brpc_kv_executor` |
| 锁竞争 batch 单测（看 `PERF_CONCURRENT_BATCH`） | `./ops runtime.lock_perf` |

### 2.3 性能分析（多数无 sudo；bpftrace 要 root）

| 目标 | 入口 |
|------|------|
| Executor inline vs injected 曲线 / csv | `./ops analysis.kv_executor_perf` |
| 门禁 + 可选 perf 落盘（基线目录） | `./ops analysis.collect_lock_baseline` |
| 两次 run 目录对比 | `./ops analysis.compare_lock_baseline` |
| bpftrace 工作流（打印 sudo 采集命令） | `./ops analysis.lock_ebpf_workflow` |
| strace / bpftrace / perf record 原始采集 | 调试脚本时再直接进入 `scripts/analysis/perf/` |
| 栈文本后处理 | 调试脚本时再直接进入 `scripts/analysis/perf/` |

### 2.4 代码索引（IDE）

| 目标 | 入口 |
|------|------|
| 从 `build/compile_commands.json` 生成带 URMA 宏的索引库 | `./ops analysis.refresh_urma_index` |

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
