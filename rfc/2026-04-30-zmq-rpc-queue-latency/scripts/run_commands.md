## ST 验证脚本说明

本目录是 **ZMQ RPC queue latency ST（gtest）** 在远端 `xqyun-32c32g` 上 **rsync → bazel build → bazel test → 本地 parse** 的**唯一推荐入口**，避免各会话各写一套 ssh/bazel 命令导致 **third-party 缓存不一致** 或 **并行度不一致**。

> **OS 层 Profiling**：见 [README.md](./README.md)（perf / strace / tcp / 统一解析），推荐入口 `build_profiling_pipeline.sh`。

### 脚本一览

| 脚本 | 作用 |
|------|------|
| `repl_remote_common.inc.sh` | **仅被 source**：统一 `LOCAL_DS`、`REMOTE`、`REMOTE_DS`、`DS_OPENSOURCE_DIR_REMOTE`、`BAZEL_JOBS`、bazel target、日志路径（不要单独执行） |
| `repl_pipeline.sh` | **推荐一键**：按顺序调用下面三步 + `parse_repl_log.py`；可加 **`--kv-metrics-ut`**：在远端 `bazel build` 之后、长耗时的 REPL `bazel test` 之前跑一次 **`MetricsTest.kv_metric_urma_id_layout_test`** |
| `rsync_datasystem.sh` | 将本地 `yuanrong-datasystem` 同步到远端 `REMOTE_DS`（`--delete`，排除项见 `${AGENT_WORKBENCH_ROOT}/scripts/build/remote_build_run_datasystem.rsyncignore`） |
| `bazel_build.sh` | 远端 `bazel build`：`//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl`，`--config=perf --config=release` |
| `bazel_run.sh` | 默认：远端 **`bazel test`**（`ds_cc_test`），`--test_env=ZMQ_RPC_QUEUE_LATENCY_SEC=<秒>`（位置参数默认 5），stdout/stderr 重定向 **`REMOTE_REPL_LOG_PATH`** 后 **`scp` 回本机** `results/zmq_rpc_queue_latency_repl.log`。盯屏：**`./bazel_run.sh --tee [秒]`**。 |
| `build_profiling_pipeline.sh` | **推荐入口**：rsync → `build.sh -b bazel -r -p on -t build` → tcp_profile → syscall_profile → perf_profile → repl_pipeline → parse；`--skip-*` 可跳步骤 |
| `run_profiling_pipeline.sh` | 纯 profiling（复用已有 build）：tcp + strace + perf + repl + parse |
| `perf_profile.sh` | `perf stat -a`（1s 间隔 hw counters）+ `perf record -F 99 -a -g`（系统级火焰图采样） |
| `tcp_profile.sh` | 采样 `/proc/net/snmp`、`/proc/net/netstat`、`ss -ti`（TCP 重传、RTT、socket 缓冲） |
| `syscall_profile.sh` | `strace -c` 系统调用时间与次数分布（**需要远端 `dnf install -y strace`**） |
| `parse_profiling.py` | 统一解析 tcp / strace / perf stat / perf record / REPL JSON metrics，输出结构化摘要 |
| `bazel_run_kv_metric_urma_layout_ut.sh` | 远端 **仅 UT**：**`//tests/ut/common/metrics:metrics_test`** + **`--test_filter=MetricsTest.kv_metric_urma_id_layout_test`**，`--define=enable_urma=false`（依赖已 `rsync`/build）；**`repl_pipeline.sh --kv-metrics-ut`** 会调用 |
| `parse_repl_log.py` | 从上述 log 中提取 metrics_summary / queue-flow histogram（**本地运行**） |

### 推荐用法（人机与 Agent 对齐）

```bash
cd yuanrong-datasystem-agent-workbench/rfc/2026-04-30-zmq-rpc-queue-latency/scripts

# 一键：sync + build + run + parse（默认跑 5s）
./repl_pipeline.sh

# 改并行度（与 remote CMake 文档一致：用大缓存目录，避免 cold rebuild）
BAZEL_JOBS=16 ./repl_pipeline.sh 10

# 仅改代码后重跑 binary（仍建议保留同一条 DS_OPENSOURCE_DIR 链路）
./repl_pipeline.sh --skip-sync 10

# 需要盯 RPC 日志流：加 --tee（经 ssh \| tee）；默认不写满屏而是远端文件 + scp
./repl_pipeline.sh --tee --skip-sync 10

# build 后、长 REPL `bazel test` 前先跑 KV metrics tail 布局 UT（几秒级）
./repl_pipeline.sh --kv-metrics-ut --skip-sync 10

# 分步（与一键脚本完全一致的环境变量）
./rsync_datasystem.sh && ./bazel_build.sh && ./bazel_run_kv_metric_urma_layout_ut.sh && ./bazel_run.sh 10
./parse_repl_log.py ../results/zmq_rpc_queue_latency_repl.log
```

### 环境变量覆盖（可选）

路径与远端账号若与默认值不同，在执行任一脚本 **前** export：

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `YUANRONG_DATASYSTEM_ROOT` | agent-workbench 同级的 `yuanrong-datasystem`，否则 `~/workspace/git-repos/yuanrong-datasystem` | 本地待 rsync 的仓库根 |
| `REMOTE_USER` | `root` | SSH 用户 |
| `REMOTE_HOST` | `xqyun-32c32g` | SSH Host（可走 `~/.ssh/config` 别名） |
| `REMOTE_DS` | `${REMOTE_REPO_BASE}/yuanrong-datasystem` | 远端 datasystem 根 |
| `REMOTE_REPO_BASE` | `/root/workspace/git-repos` | 与 `REMOTE_DS` 拼接用 |
| `DS_OPENSOURCE_DIR_REMOTE` | `/root/.cache/yuanrong-datasystem-third-party` | **远端 Bazel/third_party 持久缓存**（勿指向每次会删的 `bazel-bin`/`/tmp`） |
| `BAZEL_JOBS` | `32` | **`bazel build` / `bazel test` 共用** `--jobs` |
| `LOCAL_RESULTS_DIR` | 本 RFC 下 `results/` | **`scp`** 拉回后的日志目录（默认模式不打满屏 SSH） |
| `REMOTE_REPL_LOG_PATH` | `/tmp/zmq_rpc_queue_latency_repl_capture.log` | 远端：`bazel test` stdout/stderr 先写此文件，`bazel_run.sh` 末尾再 `scp` |
| `ZMQ_RPC_QUEUE_LATENCY_TEST_TIMEOUT` | `3600` | **`bazel test --test_timeout`**（秒）；由本机在调用 `ssh` **前** 展开传给远端脚本 |

### 日志与 `--tee`

- **默认**：无 tty 洪流，远端落盘后用 **`scp`** 回本机 `LOCAL_RESULTS_DIR`。
- **`./bazel_run.sh --tee`**：`ssh \| tee`，方便观察 / 兼容旧流程；大批量日志时可能比「远端写文件 + `scp`」更扰动链路。

### 目录结构

```
rfc/2026-04-30-zmq-rpc-queue-latency/
├── scripts/
│   ├── repl_remote_common.inc.sh
│   ├── repl_pipeline.sh
│   ├── rsync_datasystem.sh
│   ├── bazel_build.sh
│   ├── bazel_run.sh
│   ├── bazel_run_kv_metric_urma_layout_ut.sh
│   ├── parse_repl_log.py
│   └── run_commands.md        # 本文件
├── docs/
│   ├── timing_points.puml
│   └── timing_points_current.puml
├── results/
│   └── zmq_rpc_queue_latency_repl.log
└── .gitignore
```

### ST gtest：`zmq_rpc_queue_latency_repl`

1. 本进程内 ZMQ TCP server + client。
2. 负载时长：**远端 `bazel test` 传入 `--test_env=ZMQ_RPC_QUEUE_LATENCY_SEC=…`**（默认 5）；`bazel_run.sh <秒>` 把该时长作为位置参数转成 test env。
3. 结束前 **`DumpSummaryForTest`**，日志中带 **`Completed … RPCs`** 与 **`=== METRICS DUMP ===`**，供 `parse_repl_log.py` 解析。

`bazel_run.sh`：**`--test_arg=--logtostderr=1`、`--test_arg=--v=0`**（与 ST 内 `FLAGS_v = 0`、`LOG(INFO)` 一致）。

### BUILD.bazel

`//tests/st/common/rpc/zmq/BUILD.bazel` 中 **`ds_cc_test`** `zmq_rpc_queue_latency_repl` 带 `tags = ["manual"]`，需显式 target 路径构建/运行。

### 已知语义（摘录）

- **`zmq_client_queuing_latency`**：`CLIENT_TO_STUB − CLIENT_ENQUEUE`（真正 `zmq_msg_send` 仍难进同一 MetaPb 时序，见 `docs/issue-rfc.md`）。
- **`zmq_rpc_network_latency`**：残差模型，非纯 RTT；见 `docs/timing_points_current.puml`。

### 注意事项

- `bazel_run.sh` 对 **`bazel test` 传入 `--experimental_ui_max_stdouterr_bytes=-1`**，否则当一次 run 同时 **编译 + 跑 ST** 且编译输出很大时，Bazel 默认会 **截断/跳过** 测试 stdout，`parse_repl_log.py` 会拿不到 `Completed …` / `=== METRICS DUMP ===`。
- rsync 排除规则与全仓 `remote_build_run_datasystem.rsyncignore` 对齐，避免把巨大 `bazel-*` / `output` 同步上去。
- **日志如何到本机**：`bazel_run.sh` **默认**在远端 **`bazel test`** 输出重定向到 **`REMOTE_REPL_LOG_PATH`**，结束后 **`scp`** 到 `LOCAL_RESULTS_DIR`。调试用 **`--tee`** 才走 **`ssh \| tee`**。
