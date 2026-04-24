# 重构 Scripts 和远端工作空间

**目标**：重构 `yuanrong-datasystem-agent-workbench/scripts/` 和远端工作空间布局，分离 Cursor 日间工作流和 hermes agent 夜间工作流，建立多节点可配置的远端执行框架，目标新节点 30 分钟内可跑起来。

**背景约束**：
- hermes agent 无法访问 gitcode，只能访问 GitHub
- `yuanrong-datasystem` 在 gitcode（hermes 不可达）
- `yuanrong-datasystem-agent-workbench` 在 GitHub（hermes 可达）
- 目录已改名：`vibe-coding-files` → `yuanrong-datasystem-agent-workbench`

---

## 一、整体工作空间布局

```
/home/t14s/workspace/git-repos/
├── yuanrong-datasystem/                  ← 核心：只构建这个，所有产物基于此
├── yuanrong-datasystem-agent-workbench/   ← agent workbench（GitHub）：scripts、plans、docs
├── vibe-coding-files/                    ← 旧 workbench：待归档
├── machine-config/
├── results/
└── umdk/
```

### Cursor 工作区配置

| 文件 | 用途 | 处理 |
|------|------|------|
| `datasystem-dev.code-workspace` | 引用 `vibe-coding-files` + `yuanrong-datasystem` | **保留**（符合日常使用） |
| `observability-dev.code-workspace` | 引用了不需要的 `tech-research`、`vibe-observability-artifacts` | **归档** |

---

## 二、远端目录布局（xqyun-32c32g）

### xqyun-32c32g 上的两个逻辑独立工作空间

```
~/workspace/git-repos/           ← Cursor 日间工作空间（现有）
├── yuanrong-datasystem/            ← gitcode 仓库（Cursor 可 push）
│   └── build/                      ← Cursor 用 CMake/Bazel 构建产物
└── yuanrong-datasystem-agent-workbench/  ← GitHub 仓库（原 vibe-coding-files）

~/agent/hermes-workspace/       ← hermes agent 夜间工作空间（新建）
├── yuanrong-datasystem/            ← Cursor rsync 过来的同一份代码（只读 baseline）
│   └── build/                      ← hermes 独立构建产物
└── yuanrong-datasystem-agent-workbench/  ← hermes 从 GitHub 直接 clone（可写）
```

**为什么这样分离**：
- hermes 无法访问 gitcode，datasystem 必须由 Cursor rsync 推送
- hermes 可以直接 clone/push `yuanrong-datasystem-agent-workbench`（GitHub），无需经过 Cursor
- 两边共享 `~/.cache/yuanrong-datasystem-third-party` 第三方缓存，节省磁盘和构建时间

---

## 二、最终目录结构

### `yuanrong-datasystem-agent-workbench/scripts/`

```
scripts/
├── README.md

├── config/                           ← 【新增】节点配置
│   └── nodes.yaml                    ← 所有远端节点的统一配置（替代硬编码）

├── lib/                              ← 【已有，增强】
│   ├── datasystem_root.sh           ← 已有，保留
│   ├── vibe_coding_root.sh          ← 已有，保留
│   ├── datasystem_root.py           ← 已有，保留
│   ├── remote_defaults.sh            ← 【新增】DEFAULT_REMOTE_HOST, resolve_remote_path(), ssh_remote()
│   ├── rsync_excludes.sh            ← 【新增】RSYNC_EXCLUDE_ARRAY，替代 6 个脚本的内联定义
│   ├── build_backend.sh              ← 【新增】build_cmd(), run_cmd(), binary_path() 抽象 cmake/bazel
│   ├── timing.sh                     ← 【新增】run_timed(), print_timing_report(), banner()
│   ├── cmake_test_env.sh            ← 【新增】extract_ld_library_path()，替代 4 个脚本的内联 Python
│   ├── common.sh                    ← 【新增】stamp_utc(), log_info()
│   └── load_nodes.sh                ← 【新增】YAML 读取库，node_* 函数

├── build/                               ← 【拆分构建脚本】
│   ├── build_bazel.sh                    ← 【新增】纯 Bazel 构建入口
│   ├── build_cmake.sh                    ← 【新增】纯 CMake 构建入口
│   ├── build_remote.sh                   ← 【改造】用 nodes.yaml；修复路径 bug
│   ├── build_remote.rsyncignore
│   ├── bootstrap_brpc_st_compat.sh      ← 保留（独立工具）
│   └── list_client_third_party_deps.sh   ← 保留（独立工具）

├── deployment/                          ← 【新增】etcd + data worker 部署
│   ├── etcd/
│   │   ├── start_etcd.sh                 ← 【新增】启动单节点 etcd
│   │   ├── start_etcd_cluster.sh          ← 【新增】启动 3 节点 etcd 集群
│   │   └── stop_etcd.sh                  ← 【新增】停止 etcd
│   ├── data_worker/
│   │   ├── start_worker.sh               ← 【新增】启动 data worker
│   │   ├── stop_worker.sh                ← 【新增】停止 data worker
│   │   └── worker_config.yaml            ← 【新增】worker 配置模板
│   └── health_check.sh                   ← 【新增】检查 etcd + worker 健康状态

├── development/
│   ├── git/
│   │   └── generate_commit_message.sh   ← 保留（独立工具）
│   ├── index/
│   │   └── refresh_urma_index_db.py    ← 保留（独立工具）
│   ├── lib/                             ← 已在上级列出
│   ├── sync/
│   │   ├── sync_to_xqyun.sh             ← 【改造】用 nodes.yaml
│   │   ├── sync_to_xqyun.rsyncignore
│   │   └── sync_hermes_workspace.sh    ← 【新增】仅同步 datasystem 到 hermes 工作空间
│   └── node/
│       ├── bootstrap_new_node.sh         ← 【新增】新节点 30 分钟自动化
│       └── switch_node.sh               ← 【新增】快速切换默认节点

├── testing/verify/                      ← 【按层级拆分运行脚本】
│   ├── smoke/                           ← 【新增】smoke 测试（< 5 min）
│   │   ├── run_smoke_bazel.sh           ← 【新增】Bazel 模式 smoke
│   │   ├── run_smoke_cmake.sh           ← 【新增】CMake 模式 smoke
│   │   └── run_smoke_remote.sh           ← 【新增】远端 smoke
│   ├── ut/                              ← 【新增】UT 回归（< 30 min）
│   │   ├── run_ut_bazel.sh              ← 【新增】Bazel 模式 UT
│   │   ├── run_ut_cmake.sh              ← 【新增】CMake 模式 UT
│   │   └── run_ut_remote.sh             ← 【新增】远端 UT
│   ├── st/                              ← 【新增】ST 集成测试（< 60 min）
│   │   ├── run_st_bazel.sh              ← 【新增】Bazel 模式 ST
│   │   ├── run_st_cmake.sh              ← 【新增】CMake 模式 ST
│   │   ├── run_st_remote.sh             ← 【新增】远端 ST
│   │   └── run_st_zmq_metrics.sh        ← 【新增】ZMQ metrics ST（来自 run_zmq_rpc_metrics_remote.sh）
│   └── e2e/                             ← 【新增】复杂用例（> 60 min）
│       ├── run_e2e_kv_executor.sh        ← 【新增】KV executor E2E（来自 validate_kv_executor.sh）
│       ├── run_e2e_urma_tcp.sh          ← 【新增】URMA/TCP E2E
│       ├── run_shm_leak_metrics.sh        ← 【新增】ShM leak metrics（来自 run_shm_leak_metrics_remote.sh）
│       └── run_zmq_fault_e2e.sh          ← 【新增】ZMQ fault E2E（来自 verify_zmq_metrics_fault.sh）
│
│   ← 原有单文件仍保留的（过渡期）：
│   ├── validate_kv_executor.sh           ← 保留（未来拆入 e2e/）
│   ├── validate_brpc_kv_executor.sh      ← 保留
│   ├── validate_urma_tcp_observability_logs.sh  ← 保留
│   ├── summarize_observability_log.sh    ← 保留（独立工具）
│   ├── verify_zmq_metrics_fault.sh       ← 保留（未来拆入 e2e/）
│   ├── verify_zmq_fault_injection_logs.sh ← 保留
│   ├── run_shm_leak_metrics_remote.sh    ← 【归档】功能拆入 e2e/run_shm_leak_metrics.sh
│   ├── run_zmq_metrics_ut_regression_remote.sh  ← 【归档】功能拆入 ut/run_ut_remote.sh
│   ├── run_zmq_rpc_metrics_remote.sh    ← 【归档】功能拆入 st/run_st_zmq_metrics.sh
│   ├── run_zmq_metrics_fault_e2e_remote.sh  ← 【归档】功能拆入 e2e/run_zmq_fault_e2e.sh
│   ├── run_kv_rw_metrics_remote_capture.sh   ← 【归档】无其他脚本调用
│   └── run_zmq_metrics_bazel.sh          ← 【归档】被 ut/run_ut_bazel.sh 覆盖

├── analysis/perf/                     ← 【保留，部分用 lib 改造】
│   ├── run_kv_concurrent_lock_perf.sh    ← 保留（用 timing.sh 改造）
│   ├── collect_client_lock_baseline.sh    ← 保留（用 timing.sh 改造）
│   ├── compare_client_lock_baseline.sh    ← 保留（修复 line 27 缺 `"` bug）
│   ├── perf_record_kv_lock_io.sh          ← 保留（用 cmake_test_env.sh 改造）
│   ├── trace_kv_lock_io.sh               ← 保留（用 cmake_test_env.sh 改造）
│   ├── trace_kv_lock_io_bpftrace.sh      ← 保留（用 cmake_test_env.sh 改造）
│   ├── run_kv_lock_ebpf_workflow.sh      ← 保留
│   ├── analyze_kv_lock_bpftrace.py        ← 保留
│   ├── analyze_strace_lock_io.py          ← 保留
│   ├── kv_executor_perf_analysis.py       ← 保留（用 datasystem_root.py 改造）
│   ├── zmq_rpc_perf_nightly.sh           ← 保留（用 remote_defaults.sh + timing.sh 改造）
│   ├── zmq_rpc_perf_report.md            ← 保留（模板）
│   └── bpftrace/
│       ├── env_for_symbols.sh
│       ├── kv_lock_io_stacks.bt
│       ├── RUN_SYMBOLS.txt
│       └── symbolize_bpftrace_stacks.py

├── lint/
│   └── check_cpp_line_width.sh            ← 保留（独立工具）

├── documentation/                        ← 【保留】
│   ├── excel/
│   │   └── build_kv_sdk_fema_workbook.py
│   └── observable/kv-client-excel/

├── results/                              ← 【保留，运行产物归档】
│   └── zmq_rpc_perf_20260412_081402/
│       └── scenarios.tsv

├── runtime/                              ← 符号链接 → ../analysis/perf 和 ../testing/verify
├── lib -> development/lib               ← 符号链接
└── verify -> testing/verify            ← 符号链接
```

### `yuanrong-datasystem/scripts/` — 官方构建链，不动

```
scripts/
├── build_common.sh
├── build_bazel.sh
├── build_cmake.sh
├── build_thirdparty.sh
├── package_go_sdk.sh
├── modules/llt_util.sh
├── ai_context/                 ← 【归档】无引用
├── generate-cmake-prebuilt.sh  ← 【归档】无引用
├── distribute_run_ut.sh         ← 【归档】无引用
└── stream_cache/parse_sc_metrics.py  ← 【归档】无引用
```

---

## 三、节点配置（nodes.yaml）

```yaml
# 注意：hermes agent 无法访问 gitcode，只能访问 GitHub
# ds = yuanrong-datasystem (gitcode, hermes 不可达)
# agent-workbench = yuanrong-datasystem-agent-workbench (GitHub, hermes 可达)

default: xqyun-32c32g

nodes:
  xqyun-32c32g:
    ssh_host: xqyun-32c32g
    ssh_user: root
    workspace_root: ~/workspace/git-repos
    hermes_workspace_root: ~/agent/hermes-workspace
    thirdparty_cache: ~/.cache/yuanrong-datasystem-third-party
    pkg_manager: dnf
    description: "主开发节点（Cursor 日间用）"

  centos9-new:
    ssh_host: <NEW_HOST_IP_OR_FQDN>
    ssh_user: root
    workspace_root: ~/workspace/git-repos
    hermes_workspace_root: ~/agent/hermes-workspace
    thirdparty_cache: ~/.cache/yuanrong-datasystem-third-party
    pkg_manager: dnf
    description: "新 CentOS9 节点（hermes 夜间用）"
```

**为什么用 YAML 而非 bash**：
- 结构化、层次清晰，人和机器都易读
- 不需要 shell 关联数组的坑（`declare -A` 不可导出、子shell中不可用）
- 可被 Python/Go 等任何语言直接复用
- 支持注释，方便记录每个节点的用途

**`load_nodes.sh` 提供的函数**：`node_default`、`node_ssh_host`、`node_ssh_user`、`node_workspace_root`、`node_hermes_workspace_root`、`node_thirdparty_cache`、`node_pkg_manager`。

---

## 四、脚本映射表

### 新增文件（24 个）

| 文件 | 用途 |
|------|------|
| `config/nodes.yaml` | 节点配置 |
| `lib/load_nodes.sh` | YAML 读取库 |
| `lib/remote_defaults.sh` | SSH/rsync 默认值 |
| `lib/rsync_excludes.sh` | 统一 rsync exclude 数组 |
| `lib/build_backend.sh` | cmake/bazel 命令抽象 |
| `lib/timing.sh` | 计时函数 |
| `lib/cmake_test_env.sh` | CMake test env 解析 |
| `lib/common.sh` | 通用工具函数 |
| `build/build_bazel.sh` | 纯 Bazel 构建入口 |
| `build/build_cmake.sh` | 纯 CMake 构建入口 |
| `deployment/etcd/start_etcd.sh` | 启动单节点 etcd |
| `deployment/etcd/start_etcd_cluster.sh` | 启动 3 节点 etcd 集群 |
| `deployment/etcd/stop_etcd.sh` | 停止 etcd |
| `deployment/data_worker/start_worker.sh` | 启动 data worker |
| `deployment/data_worker/stop_worker.sh` | 停止 data worker |
| `deployment/data_worker/worker_config.yaml` | worker 配置模板 |
| `deployment/health_check.sh` | 检查 etcd + worker 健康状态 |
| `development/sync/sync_hermes_workspace.sh` | hermes 同步脚本 |
| `development/node/bootstrap_new_node.sh` | 新节点 bootstrap |
| `development/node/switch_node.sh` | 节点切换 |
| `testing/verify/smoke/run_smoke_bazel.sh` | Bazel smoke |
| `testing/verify/smoke/run_smoke_cmake.sh` | CMake smoke |
| `testing/verify/smoke/run_smoke_remote.sh` | 远端 smoke |
| `testing/verify/ut/run_ut_bazel.sh` | Bazel UT |
| `testing/verify/ut/run_ut_cmake.sh` | CMake UT |
| `testing/verify/ut/run_ut_remote.sh` | 远端 UT |
| `testing/verify/st/run_st_bazel.sh` | Bazel ST |
| `testing/verify/st/run_st_cmake.sh` | CMake ST |
| `testing/verify/st/run_st_remote.sh` | 远端 ST |
| `testing/verify/st/run_st_zmq_metrics.sh` | ZMQ metrics ST |
| `testing/verify/e2e/run_e2e_kv_executor.sh` | KV executor E2E |
| `testing/verify/e2e/run_e2e_urma_tcp.sh` | URMA/TCP E2E |
| `testing/verify/e2e/run_shm_leak_metrics.sh` | ShM leak metrics |
| `testing/verify/e2e/run_zmq_fault_e2e.sh` | ZMQ fault E2E |

### 保留并改造（21 个）

| 文件 | 改造内容 |
|------|---------|
| `build/build_remote.sh` | 用 nodes.yaml；拆分自 `remote_build_run_datasystem.sh` |
| `development/sync/sync_to_xqyun.sh` | 用 nodes.yaml |
| `testing/verify/validate_kv_executor.sh` | 保留 |
| `testing/verify/validate_brpc_kv_executor.sh` | 保留 |
| `testing/verify/validate_urma_tcp_observability_logs.sh` | 保留 |
| `testing/verify/summarize_observability_log.sh` | 保留（独立工具） |
| `testing/verify/verify_zmq_metrics_fault.sh` | 保留（未来拆入 e2e/） |
| `testing/verify/verify_zmq_fault_injection_logs.sh` | 保留 |
| `analysis/perf/compare_client_lock_baseline.sh` | 修复 line 27 缺 `"` bug |
| `analysis/perf/zmq_rpc_perf_nightly.sh` | 用 remote_defaults.sh + timing.sh |
| `analysis/perf/run_kv_concurrent_lock_perf.sh` | 用 timing.sh |
| `analysis/perf/collect_client_lock_baseline.sh` | 用 timing.sh |
| `analysis/perf/trace_kv_lock_io.sh` | 用 cmake_test_env.sh |
| `analysis/perf/trace_kv_lock_io_bpftrace.sh` | 用 cmake_test_env.sh |
| `analysis/perf/perf_record_kv_lock_io.sh` | 用 cmake_test_env.sh |
| `analysis/perf/kv_executor_perf_analysis.py` | 用 datasystem_root.py，消除重复路径遍历 |
| `analysis/perf/run_kv_lock_ebpf_workflow.sh` | 保留 |
| `analysis/perf/analyze_kv_lock_bpftrace.py` | 保留 |
| `analysis/perf/analyze_strace_lock_io.py` | 保留 |
| `build/bootstrap_brpc_st_compat.sh` | 保留（独立工具） |
| `build/list_client_third_party_deps.sh` | 保留（独立工具） |
| `development/git/generate_commit_message.sh` | 保留（独立工具） |
| `development/index/refresh_urma_index_db.py` | 保留（独立工具） |
| `lint/check_cpp_line_width.sh` | 保留（独立工具） |

### 归档删除（8 个）

| 文件 | 归档原因 |
|------|---------|
| `testing/verify/run_zmq_metrics_bazel.sh` | 被 `ut/run_ut_bazel.sh` 覆盖；无 rsync 会导致远端漂移 |
| `testing/verify/run_zmq_metrics_fault_e2e_remote.sh` | 被 `e2e/run_zmq_fault_e2e.sh` 覆盖 |
| `testing/verify/run_kv_rw_metrics_remote_capture.sh` | 无任何脚本调用 |
| `testing/verify/run_shm_leak_metrics_remote.sh` | 功能拆入 `e2e/run_shm_leak_metrics.sh` |
| `testing/verify/run_zmq_metrics_ut_regression_remote.sh` | 功能拆入 `ut/run_ut_remote.sh` |
| `testing/verify/run_zmq_rpc_metrics_remote.sh` | 功能拆入 `st/run_st_zmq_metrics.sh` |
| `yuanrong-datasystem/scripts/ai_context/generate_repo_index.py` | 无任何引用 |
| `yuanrong-datasystem/scripts/ai_context/validate_module_metadata.py` | 无任何引用 |
| `yuanrong-datasystem/scripts/generate-cmake-prebuilt.sh` | 无任何引用 |
| `yuanrong-datasystem/scripts/distribute_run_ut.sh` | 无任何引用 |
| `yuanrong-datasystem/scripts/stream_cache/parse_sc_metrics.py` | 无任何引用 |

归档路径：`yuanrong-datasystem-agent-workbench/archive/deprecated/`（远端脚本）和 `yuanrong-datasystem/scripts/archive/ds-scripts-deprecated/`（ds scripts）。

---

## 五、实施步骤

### 第零阶段：工作区清理（前提）

**步骤：**
0. 归档 `vibe-coding-files/observability-dev.code-workspace`（引用了不需要的 tech-research 和 vibe-observability-artifacts）
0. 确认 `datasystem-dev.code-workspace` 为 Cursor 的主工作区配置

**验证：**
```bash
# 确认 observability-dev.code-workspace 存在（待归档）
ls vibe-coding-files/observability-dev.code-workspace
# 确认 vibe-coding-files 待归档
ls vibe-coding-files/
```

---

### 第一阶段：Bug 修复

**步骤：**
1. 修复 `compare_client_lock_baseline.sh:27`：补上缺失的闭合 `"`
2. 修复 `remote_build_run_datasystem.sh:444`：`scripts/verify/` → `scripts/testing/verify/`

**验证：**
```bash
bash -n scripts/analysis/perf/compare_client_lock_baseline.sh && echo "OK"
grep 'testing/verify/validate_kv_executor' scripts/build/remote_build_run_datasystem.sh
```

---

### 第二阶段：归档清理

**步骤：**
3. 将 5 个冗余远端脚本移动到 `archive/deprecated/`
4. 将 5 个无引用的 `yuanrong-datasystem/scripts/` 文件移动到 `archive/ds-scripts-deprecated/`

**验证：**
```bash
for f in scripts/testing/verify/run_zmq_metrics_bazel.sh \
         scripts/testing/verify/run_zmq_metrics_fault_e2e_remote.sh \
         scripts/testing/verify/run_kv_rw_metrics_remote_capture.sh \
         scripts/testing/verify/run_shm_leak_metrics_remote.sh \
         scripts/testing/verify/run_zmq_metrics_ut_regression_remote.sh \
         scripts/testing/verify/run_zmq_rpc_metrics_remote.sh; do
  ls "$f" 2>&1 | grep -q "No such" || echo "NOT ARCHIVED: $f"
done
ls yuanrong-datasystem/scripts/archive/ds-scripts-deprecated/ai_context/
```

---

### 第三阶段：新建共享 lib

**步骤：**
5. 新建 `lib/remote_defaults.sh`（含 `DEFAULT_REMOTE_HOST`、`resolve_remote_path()`、`ssh_remote()`）
6. 新建 `lib/rsync_excludes.sh`（含 `RSYNC_EXCLUDE_ARRAY`）
7. 新建 `lib/build_backend.sh`（含 `build_cmd()`、`run_cmd()`、`binary_path()`）
8. 新建 `lib/timing.sh`（含 `run_timed()`、`print_timing_report()`、`banner()`）
9. 新建 `lib/cmake_test_env.sh`（含 `extract_ld_library_path()`）
10. 新建 `lib/common.sh`（含 `stamp_utc()`、`log_info()`）
11. 改造 `kv_executor_perf_analysis.py`：用 `datasystem_root.py`

**验证（每新建一个 lib 后）：**
```bash
bash -n scripts/lib/<lib> && echo "SYNTAX OK: $lib"
source scripts/lib/<lib> && echo "SOURCE OK: $lib"
declare -f <函数名> > /dev/null && echo "FUNC OK: <函数名>"
```

---

### 第四阶段：拆分构建脚本（build/ 目录）

**步骤：**
12. 新建 `build/build_bazel.sh`：纯 Bazel 构建入口，调用 `bazel build //...`
13. 新建 `build/build_cmake.sh`：纯 CMake 构建入口，调用 `build.sh -b cmake`
14. 将 `remote_build_run_datasystem.sh` 改名为 `build/build_remote.sh`，用 `nodes.yaml` + `load_nodes.sh`

**验证：**
```bash
bash scripts/build/build_bazel.sh --help
bash scripts/build/build_cmake.sh --help
bash scripts/build/build_remote.sh --help
bash scripts/build/build_remote.sh -n  # dry-run，应输出 plan
```

---

### 第五阶段：拆分运行脚本（testing/verify/ 目录）

**步骤：**
15. 新建 `testing/verify/smoke/`：smoke 测试（< 5 min）
    - `run_smoke_bazel.sh`、`run_smoke_cmake.sh`、`run_smoke_remote.sh`
16. 新建 `testing/verify/ut/`：UT 回归（< 30 min）
    - `run_ut_bazel.sh`、`run_ut_cmake.sh`、`run_ut_remote.sh`
17. 新建 `testing/verify/st/`：ST 集成测试（< 60 min）
    - `run_st_bazel.sh`、`run_st_cmake.sh`、`run_st_remote.sh`、`run_st_zmq_metrics.sh`
18. 新建 `testing/verify/e2e/`：复杂用例（> 60 min）
    - `run_e2e_kv_executor.sh`、`run_e2e_urma_tcp.sh`、`run_shm_leak_metrics.sh`、`run_zmq_fault_e2e.sh`

**验证：**
```bash
# 每个新脚本语法检查
for f in scripts/testing/verify/smoke/*.sh \
         scripts/testing/verify/ut/*.sh \
         scripts/testing/verify/st/*.sh \
         scripts/testing/verify/e2e/*.sh; do
  bash -n "$f" && echo "OK: $f" || echo "FAIL: $f"
done

# 每个新脚本 dry-run
for f in scripts/testing/verify/smoke/*.sh \
         scripts/testing/verify/ut/*.sh \
         scripts/testing/verify/st/*.sh \
         scripts/testing/verify/e2e/*.sh; do
  bash "$f" --help > /dev/null 2>&1 && echo "HELP OK: $f"
done
```

---

### 第六阶段：新建 deployment 目录（etcd + data worker）

**步骤：**
19. 新建 `deployment/etcd/start_etcd.sh`：启动单节点 etcd
20. 新建 `deployment/etcd/start_etcd_cluster.sh`：启动 3 节点 etcd 集群
21. 新建 `deployment/etcd/stop_etcd.sh`：停止 etcd
22. 新建 `deployment/data_worker/start_worker.sh`：启动 data worker
23. 新建 `deployment/data_worker/stop_worker.sh`：停止 data worker
24. 新建 `deployment/data_worker/worker_config.yaml`：worker 配置模板
25. 新建 `deployment/health_check.sh`：检查 etcd + worker 健康状态

**验证：**
```bash
bash scripts/deployment/etcd/start_etcd.sh --help
bash scripts/deployment/etcd/start_etcd_cluster.sh --help
bash scripts/deployment/etcd/stop_etcd.sh --help
bash scripts/deployment/data_worker/start_worker.sh --help
bash scripts/deployment/data_worker/stop_worker.sh --help
bash scripts/deployment/health_check.sh --help

# YAML 格式验证
python3 -c "import yaml; yaml.safe_load(open('scripts/deployment/data_worker/worker_config.yaml'))"
echo $?
```

---

### 第七阶段：新建节点管理和同步脚本

**步骤：**
26. 新建 `config/nodes.yaml`
27. 新建 `lib/load_nodes.sh`
28. 新建 `development/sync/sync_hermes_workspace.sh`
29. 新建 `development/node/bootstrap_new_node.sh`
30. 新建 `development/node/switch_node.sh`

**验证：**
```bash
python3 -c "import yaml; yaml.safe_load(open('scripts/config/nodes.yaml')); print('YAML OK')"
source scripts/lib/load_nodes.sh
node_default
node_workspace_root xqyun-32c32g
bash scripts/development/sync/sync_hermes_workspace.sh --help
bash scripts/development/node/bootstrap_new_node.sh --help
bash scripts/development/node/switch_node.sh --help
```

---

### 第八阶段：改造现有远端脚本使用新 lib

**步骤：**
31. 改造 `development/sync/sync_to_xqyun.sh`：用 `nodes.yaml` + `load_nodes.sh`
32. 改造 `build/build_remote.sh`：用 `nodes.yaml` + `load_nodes.sh`；同时修复上述 bug
33. 改造 `analysis/perf/zmq_rpc_perf_nightly.sh`：用 `remote_defaults.sh` + `timing.sh`
34. 改造 4 个 trace/perf 脚本：用 `cmake_test_env.sh`
35. 改造 `analysis/perf/run_kv_concurrent_lock_perf.sh`、`collect_client_lock_baseline.sh`：用 `timing.sh`

**验证：**
```bash
# 硬编码检查
grep -r 'xqyun-32c32g' scripts/development/sync/sync_to_xqyun.sh \
  scripts/build/build_remote.sh && echo "STILL HARDCODED"
# 应无输出

# dry-run 验证
bash scripts/development/sync/sync_to_xqyun.sh -n | grep REMOTE_BASE
bash scripts/build/build_remote.sh -n | grep REMOTE
```

---

### 第九阶段：文档更新

**步骤：**
36. 更新 `.cursor/rules/remote-dev-host.mdc`
37. 更新 `scripts/README.md`：反映新增的 `config/`、`deployment/`、`testing/verify/{smoke,ut,st,e2e}/` 结构
38. 更新 `AGENTS.md`
39. 更新 `docs/agent/scripts-map.md`

**验证：**
```bash
grep 'deployment/' scripts/README.md   # 应 > 0
grep 'smoke/' scripts/README.md        # 应 > 0
grep 'run_zmq_metrics_bazel' docs/agent/scripts-map.md  # 应无输出
```

---

### 全流程最终验证（全部完成后执行）

#### A. 脚本自身验证（本地可做）

```bash
# 1. 所有 lib 语法正确
for f in scripts/lib/*.sh; do bash -n "$f" || echo "FAIL: $f"; done

# 2. 所有活跃脚本语法正确（含新增的层级）
for f in scripts/build/*.sh scripts/development/sync/*.sh \
         scripts/testing/verify/smoke/*.sh scripts/testing/verify/ut/*.sh \
         scripts/testing/verify/st/*.sh scripts/testing/verify/e2e/*.sh \
         scripts/analysis/perf/*.sh scripts/lint/*.sh \
         scripts/deployment/etcd/*.sh scripts/deployment/*.sh; do
  bash -n "$f" || echo "FAIL: $f"
done

# 3. nodes.yaml 格式正确
python3 -c "import yaml; c=yaml.safe_load(open('scripts/config/nodes.yaml')); \
  assert 'nodes' in c; assert 'xqyun-32c32g' in c['nodes']; print('YAML OK')"

# 4. load_nodes.sh 函数完整
source scripts/lib/load_nodes.sh
for fn in node_default node_ssh_host node_ssh_user node_workspace_root \
         node_hermes_workspace_root node_thirdparty_cache node_pkg_manager; do
  declare -f "$fn" > /dev/null || echo "MISSING: $fn"
done

# 5. 远端脚本不再硬编码 host（允许 nodes.yaml 中的占位符 <...>）
grep -r 'xqyun-32c32g' scripts/build/build_remote.sh \
  scripts/development/sync/sync_to_xqyun.sh && echo "STILL HARDCODED"
# 应无输出

# 6. 归档文件确实已移除
for f in scripts/testing/verify/run_zmq_metrics_bazel.sh \
         scripts/testing/verify/run_zmq_metrics_fault_e2e_remote.sh \
         scripts/testing/verify/run_kv_rw_metrics_remote_capture.sh \
         scripts/testing/verify/run_shm_leak_metrics_remote.sh \
         scripts/testing/verify/run_zmq_metrics_ut_regression_remote.sh \
         scripts/testing/verify/run_zmq_rpc_metrics_remote.sh; do
  ls "$f" 2>&1 | grep -q "No such" || echo "NOT ARCHIVED: $f"
done

# 7. 新层级目录结构存在
ls scripts/testing/verify/smoke/  # 应列出 smoke 脚本
ls scripts/testing/verify/ut/      # 应列出 ut 脚本
ls scripts/testing/verify/st/       # 应列出 st 脚本
ls scripts/testing/verify/e2e/      # 应列出 e2e 脚本
ls scripts/deployment/etcd/         # 应列出 etcd 脚本
ls scripts/deployment/data_worker/  # 应列出 worker 脚本
```

#### B. 构建验证（远端执行，需 SSH）

**在远端 xqyun-32c32g 上执行：**

```bash
cd ~/workspace/git-repos/yuanrong-datasystem

# 1. Bazel 构建完整（清理后）
bazel clean --expunge
bazel build //... 2>&1 | tail -20
# 期望：无 ERROR，BUILD 成功完成

# 2. 检查动态库依赖完整性（无 missing）
find bazel-bin -name "*.so*" -exec ldd {} \; 2>/dev/null | grep "not found"
# 期望：无输出

# 3. CMake 构建完整
rm -rf build && bash build.sh -t build -B build -b cmake -j 16 2>&1 | tail -20
# 期望：BUILD SUCCESS 或等效成功信息

# 4. CMake 构建产物动态库依赖检查
find build -name "*.so*" -exec ldd {} \; 2>/dev/null | grep "not found"
# 期望：无输出
```

#### C. 代码索引验证（本地可做）

```bash
cd ~/workspace/git-repos/yuanrong-datasystem

# 1. CMake compile_commands.json 完整
wc -l build/compile_commands.json
# 期望：> 1000 行（每个源文件至少一条）

# 2. 关键源文件都在索引中
for f in src/datasystem/common/rpc/zmq/zmq_service.cpp \
         src/datasystem/client/kv_client.cpp \
         src/datasystem/worker/data_worker.cpp \
         src/datasystem/server/kv_server.cpp; do
  grep -q "$f" build/compile_commands.json || echo "MISSING INDEX: $f"
done

# 3. URMA/UB 宏补丁后索引仍完整
python3 ../yuanrong-datasystem-agent-workbench/scripts/development/index/refresh_urma_index_db.py
grep -c 'USE_URMA' .cursor/compile_commands.json
# 期望：> 0（URMA 宏被正确追加到每个条目）
wc -l .cursor/compile_commands.json
# 期望：与 build/compile_commands.json 行数一致
```

#### D. 分层运行验证（远端执行）

**在远端 xqyun-32c32g 上执行：**

```bash
cd ~/workspace/git-repos/yuanrong-datasystem

# 1. smoke 测试（< 5 min）— 按 ctest label 或名称筛选
ctest --test-dir build --output-on-failure -R smoke -j 16 2>&1 | tail -20
# 期望：全部 Pass，0 Failed

# 2. UT 回归（< 30 min）— cmake/ut 或 bazel unit_test
ctest --test-dir build --output-on-failure -R "ut|UT|unit" -j 16 2>&1 | tail -20
# 期望：全部 Pass，0 Failed

# 3. ST 集成测试（< 60 min）— cmake/st 或 bazel st
ctest --test-dir build --output-on-failure -R "st|ST|integration" -j 16 2>&1 | tail -20
# 期望：全部 Pass，0 Failed

# 4. E2E 复杂用例（> 60 min）
ctest --test-dir build --output-on-failure -R "kv_executor|rpc|urma|e2e" -j 1 2>&1 | tail -30
# 期望：符合预期（有失败的用例应在 notes 中说明）
```

#### E. etcd / data worker 部署验证（远端执行）

**在远端 xqyun-32c32g 上执行：**

```bash
cd ~/workspace/git-repos/yuanrong-datasystem

# 1. etcd 单节点启动
bash yuanrong-datasystem-agent-workbench/scripts/deployment/etcd/start_etcd.sh
# 期望：etcd 进程存在
ps aux | grep etcd | grep -v grep
etcdctl endpoint health
# 期望：etcd 健康

# 2. etcd 集群启动（3 节点）
bash yuanrong-datasystem-agent-workbench/scripts/deployment/etcd/start_etcd_cluster.sh
# 期望：3 个 etcd 进程存在
etcdctl --endpoints=127.0.0.1:23790,127.0.0.1:23791,127.0.0.1:23792 endpoint health
# 期望：全部健康

# 3. data worker 启动
bash yuanrong-datasystem-agent-workbench/scripts/deployment/data_worker/start_worker.sh
# 期望：worker 进程存在
ps aux | grep data_worker | grep -v grep

# 4. 健康检查
bash yuanrong-datasystem-agent-workbench/scripts/deployment/health_check.sh
# 期望：etcd + worker 均健康

# 5. 停止验证
bash yuanrong-datasystem-agent-workbench/scripts/deployment/etcd/stop_etcd.sh
bash yuanrong-datasystem-agent-workbench/scripts/deployment/data_worker/stop_worker.sh
ps aux | grep etcd | grep -v grep  # 应无输出
ps aux | grep data_worker | grep -v grep  # 应无输出
```

#### F. whl 包验证（远端执行）

```bash
cd ~/workspace/git-repos/yuanrong-datasystem

# 1. 找到 whl 包
WHEEL=$(find build output -name "openyuanrong_datasystem-*.whl" 2>/dev/null | head -1)
echo "Wheel: $WHEEL"

# 2. 安装到 user site-packages
python3 -m pip install --user "$WHEEL" 2>&1 | tail -5
# 期望：Successfully installed

# 3. Python import 验证
python3 -c "import datasystem; print('datasystem import OK')"
# 期望：输出 OK，无 ImportError

# 4. dscli 验证
dscli --version 2>&1 | head -3
# 期望：输出版本号，无 command not found
```

---

## 六、Cursor Agent Rule 更新

改造 `.cursor/rules/remote-dev-host.mdc`：

```bash
# 远端节点统一配置在 scripts/config/nodes.yaml
# 通过 load_nodes.sh 读取，不在 rule 中硬编码任何节点信息
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${SCRIPT_DIR}/../../development/lib/load_nodes.sh"

# hermes agent 使用时：export NODE_NAME=<node_name>
REMOTE="${NODE_NAME:-$(node_default)}"
REMOTE_BASE="$(node_workspace_root "${REMOTE}")"
DS_OPENSOURCE_DIR="$(node_thirdparty_cache "${REMOTE}")"
```

hermes agent 使用时通过环境变量 `NODE_NAME=centos9-new` 切换节点。

---

## 七、hermes 同步脚本逻辑

`sync_hermes_workspace.sh` 只需同步 `yuanrong-datasystem`（gitcode，hermes 无法直接访问）。`yuanrong-datasystem-agent-workbench` 由 hermes 自己从 GitHub clone/pull，无需经过 Cursor。

| | `sync_to_xqyun.sh` (Cursor) | `sync_hermes_workspace.sh` (hermes) |
|---|---|---|
| 同步目标 | datasystem + agent-workbench | 仅 datasystem（gitcode） |
| agent-workbench | rsync | hermes 自己从 GitHub clone |
| 触发时机 | 手动 | hermes agent 每次任务前自动调用 |
