# Scripts

yuanrong-datasystem-agent-workbench 脚本库。按职责分为以下目录：

## 目录结构

```
scripts/
  lib/                         # 共享 bash 库（source 使用）
  │   ├── load_nodes.sh         # 解析 config/nodes.yaml，提供 node_* 查询函数
  │   ├── remote_defaults.sh    # 远端 SSH/rsync/rsync_excludes 抽象
  │   ├── rsync_excludes.sh    # 统一 rsync 排除参数
  │   ├── build_backend.sh      # CMake / Bazel 构建命令抽象
  │   ├── timing.sh            # run_timed / banner / print_timing_report
  │   ├── cmake_test_env.sh     # 从 CMake test desc 提取 LD_LIBRARY_PATH
  │   └── common.sh             # log_info / stamp_utc / require_var / cmd_exists
  │
  config/
  │   └── nodes.yaml            # 节点统一配置

  build/
  │   ├── build_bazel.sh        # 本地 Bazel 构建入口
  │   ├── build_cmake.sh        # 本地 CMake 构建入口
  │   └── remote_build_run_datasystem.sh  # 远端构建 + 测试 + 验证完整流程

  deployment/
  │   ├── health_check.sh       # etcd + data worker 健康检查
  │   └── etcd/
  │       ├── start_etcd.sh            # 单节点 etcd
  │       ├── start_etcd_cluster.sh    # 3 节点 etcd 集群
  │       └── stop_etcd.sh             # 停止 etcd
  │   └── data_worker/
  │       ├── start_worker.sh           # 启动 data worker
  │       ├── stop_worker.sh           # 停止 data worker
  │       └── worker_config.yaml       # worker 配置模板

  development/
  │   ├── sync/
  │   │   ├── sync_to_xqyun.sh       # 同步本地 repos 到远端（Cursor 日间用）
  │   │   └── sync_hermes_workspace.sh # 同步 datasystem 到 hermes 工作区（夜间用）
  │   ├── node/
  │   │   ├── bootstrap_new_node.sh    # 新 CentOS9 节点初始化（< 30 分钟）
  │   │   └── switch_node.sh          # 切换默认远端节点
  │   ├── code-index/
  │   │   └── refresh_urma_index_db.py # URMA/UB macro 索引数据库刷新
  │   └── lib/                        # 共享库（同上 lib/，二选一使用）

  testing/verify/
  │   ├── smoke/                      # 冒烟测试（< 5 分钟）
  │   │   ├── run_smoke.py           # Python 冒烟入口
  │   │   ├── run_smoke_bazel.sh
  │   │   ├── run_smoke_cmake.sh
  │   │   └── run_smoke_remote.sh
  │   ├── ut/                        # 单元测试（< 30 分钟）
  │   │   ├── run_ut_bazel.sh
  │   │   ├── run_ut_cmake.sh
  │   │   └── run_ut_remote.sh
  │   ├── st/                        # 集成测试（< 60 分钟）
  │   │   ├── run_st_bazel.sh
  │   │   ├── run_st_cmake.sh
  │   │   ├── run_st_remote.sh
  │   │   └── run_st_zmq_metrics.sh
  │   ├── validate_kv_executor.sh           # KV executor 验证
  │   ├── validate_urma_tcp_observability_logs.sh  # URMA/TCP 日志验证
  │   ├── verify_zmq_metrics_fault.sh       # ZMQ 指标 fault 验证
  │   └── verify_zmq_fault_injection_logs.sh # ZMQ fault injection 日志验证

  analysis/perf/               # 性能分析工具（bpftrace/strace/perf）
  ├── perf_record_kv_lock_io.sh
  ├── trace_kv_lock_io.sh
  ├── collect_client_lock_baseline.sh
  ├── compare_client_lock_baseline.sh
  └── bpftrace/               # BPFTrace 脚本

  lint/
  └── check_cpp_line_width.sh # C++ 行宽检查（Cursor rule 调用）

  archive/                     # 归档文件（不再维护）
  ├── validate_brpc_kv_executor.sh.archived
  └── summarize_observability_log.sh.orphaned
```

## 快速开始

### 1. 配置节点

编辑 `config/nodes.yaml`，添加/修改节点信息。查看当前节点：

```bash
SCRIPT_DIR="$(pwd)/scripts/development/lib" bash -c \
  'source scripts/development/lib/load_nodes.sh && echo "默认节点: $(node_default)"'
```

### 2. 切换默认节点

```bash
bash scripts/development/node/switch_node.sh centos9-new
```

### 3. 初始化新节点（< 30 分钟）

```bash
bash scripts/development/node/bootstrap_new_node.sh --node centos9-new
```

### 4. 本地构建（Cursor 日间）

```bash
# Bazel
bash scripts/build/build_bazel.sh

# CMake
bash scripts/build/build_cmake.sh
```

### 5. 远端构建 + 测试

```bash
bash scripts/build/remote_build_run_datasystem.sh \
  --remote xqyun-32c32g \
  --hetero on \
  --perf on
```

### 6. 分层测试

```bash
# 冒烟（< 5 分钟）
bash scripts/testing/verify/smoke/run_smoke_bazel.sh

# UT（< 30 分钟）
bash scripts/testing/verify/ut/run_ut_bazel.sh

# ST（< 60 分钟）
bash scripts/testing/verify/st/run_st_bazel.sh
```

### 7. hermes 同步（夜间）

hermes agent 在执行任务前调用此脚本获取最新的 datasystem 代码：

```bash
bash scripts/development/sync/sync_hermes_workspace.sh --node centos9-new
```

## 工作空间分离

- **Cursor（白天）**：直接操作 `~/workspace/git-repos`（本地或 SSHFS）
- **hermes（夜间）**：操作 `~/agent/hermes-workspace/yuanrong-datasystem`，通过 `sync_hermes_workspace.sh` 同步
- 两者共享 `~/.cache/yuanrong-datasystem-third-party`（第三方依赖缓存）

## 归档文件

废弃脚本已移至 `archive/`，不再维护。
