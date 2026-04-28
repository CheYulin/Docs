## ST 验证脚本说明

本目录包含四个脚本/工具，支持将本地代码 rsync 到远端机器后执行 bazel build + run，日志自动保存到 `results/` 目录。日志解析脚本在本地运行，无需 SSH。

### 脚本一览

| 脚本 | 作用 |
|------|------|
| `rsync_datasystem.sh` | 将本地 yuanrong-datasystem 同步到远端 `/root/workspace/git-repos/yuanrong-datasystem`（`--delete` 同步） |
| `bazel_build.sh` | 在远端 bazel build 两个 target：<br>· `//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_test`<br>· `//tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl` |
| `bazel_run.sh` | 在远端 bazel run，日志保存到 `results/` |
| `parse_repl_log.py` | 从 `results/zmq_rpc_queue_latency_repl.log` 中提取关键 metrics 并美化输出（本地运行，无需 SSH） |

### 使用流程

```bash
# 1. 同步代码（首次，或本地代码有变更后）
./rsync_datasystem.sh

# 2. 构建（两个 target 一起构建）
./bazel_build.sh

# 3. 运行
./bazel_run.sh              # 默认：先跑 repl(5s)，再跑 test
./bazel_run.sh repl         # 只跑 repl，默认 5 秒
./bazel_run.sh repl 10      # 只跑 repl，10 秒
./bazel_run.sh test         # 只跑 test

# 4. 解析日志（本地运行，无需 SSH）
./parse_repl_log.py ../results/zmq_rpc_queue_latency_repl.log
```

### 目录结构

```
rfc/2026-04-zmq-rpc-queue-latency/
├── scripts/
│   ├── rsync_datasystem.sh   # 同步代码到远端
│   ├── bazel_build.sh        # 构建两个 target
│   ├── bazel_run.sh          # 运行并保存日志
│   ├── parse_repl_log.py     # 解析 repl 日志（本地运行）
│   └── run_commands.md        # 本文件
├── results/                   # bazel_run.sh 自动创建，日志输出目录
│   ├── zmq_rpc_queue_latency_repl.log
│   └── zmq_rpc_queue_latency_test.log
└── .gitignore                # 忽略 results/ 和 *.log
```

### 远端信息

- **远端机器**: `root@xqyun-32c32g`
- **远端代码路径**: `/root/workspace/git-repos/yuanrong-datasystem`
- **third-party 缓存**: `/root/.cache/yuanrong-datasystem-third-party`（bazel build 复用，避免重复编译 protobuf 等依赖）

### repl 独立可执行文件

`zmq_rpc_queue_latency_repl` 是一个独立的可执行 binary（非 gtest），功能：

1. 在本进程内启动 ZMQ TCP server + client
2. 运行指定时长（默认 5 秒）的 RPC 循环
3. 调用 `DumpSummaryJson()` 输出 metrics 汇总

支持参数：

```bash
--duration=N        # 运行 N 秒（默认 5）
--logtostderr=1     # 日志输出（bazel_run.sh 自动传入）
```

### BUILD.bazel 修改记录

已在 `//tests/st/common/rpc/zmq/BUILD.bazel` 中做以下修改：

**1. `zmq_rpc_queue_latency_test`（ds_cc_test）**
```python
# 新增 deps 解决 undefined reference
"//src/datasystem/common/flags:ds_flags",
# 移除 st_common（避免引入 worker/object_cache 深层依赖）
```

**2. 新增 `zmq_rpc_queue_latency_repl`（cc_binary）**
```python
cc_binary(
    name = "zmq_rpc_queue_latency_repl",
    srcs = ["zmq_rpc_queue_latency_repl.cpp", "zmq_test.h"],
    deps = [
        "//src/datasystem/common/flags:ds_flags",
        "//src/datasystem/common/inject:common_inject",
        "//src/datasystem/common/log:common_log",
        "//src/datasystem/common/metrics:common_metrics",
        "//src/datasystem/common/rpc:rpc_channel",
        "//src/datasystem/common/rpc:rpc_server",
        "//src/datasystem/common/rpc:rpc_unary_client_impl",
        "//src/datasystem/common/rpc/zmq:zmq_common",
        "//src/datasystem/common/rpc/zmq:zmq_context",
        "//src/datasystem/common/rpc/zmq:zmq_service",
        "//src/datasystem/common/util:status_helper",
        "//src/datasystem/protos:zmq_test_zmq_cc_proto",
        "@nlohmann_json//:json",
    ],
)
```

### 已知问题

#### 已解决：ZMQ Queue-Flow Latency Metrics 缺失

通过修复 4 个 tick 记录问题（CLIENT_SEND、SERVER_SEND、SERVER_EXEC_END 及 e2e 计算逻辑），queue-flow metrics 现已正常输出：

```
zmq_client_queuing_latency     count=1550,  avg=217us
zmq_server_queue_wait_latency  count=1550,  avg=281us   ← 之前 MISSING
zmq_server_exec_latency        count=1550,  avg=227us   ← 之前 MISSING
zmq_server_reply_latency       count=1550,  avg=3us     ← 之前 MISSING
zmq_rpc_e2e_latency           count=1550,  avg=2585us
zmq_rpc_network_latency        count=1550,  avg=2077us
```

完整根因和修复记录见 `../docs/issue-rfc.md`。

### 注意事项

- rsync 会跳过 `build/`、`output/`、`.git/`、`.cache/` 等目录（由 `remote_build_run_datasystem.rsyncignore` 定义）。
- 构建目标带有 `tags = ["manual"]`，bazel 不会自动包含在 `//...` 全量构建中，必须用完整 target 路径。
- 如需修改并行度，可设置环境变量 `BAZEL_JOBS`：`BAZEL_JOBS=16 ./bazel_build.sh`。
