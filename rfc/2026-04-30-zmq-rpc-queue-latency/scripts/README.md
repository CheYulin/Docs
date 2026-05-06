# ST Run Scripts — Quick Reference

> **OS-level profiling** (perf / strace / tcp / parse) → see [profiling/README.md](../profiling/README.md)

本目录是 **ZMQ RPC queue latency ST (gtest)** 的推荐入口。

---

## 推荐用法

```bash
cd yuanrong-datasystem-agent-workbench/rfc/2026-04-30-zmq-rpc-queue-latency/scripts

# 一键：sync + build + run + parse（默认 5s）
./repl_pipeline.sh

# 改并行度 / 时长
BAZEL_JOBS=16 ./repl_pipeline.sh 10

# 仅重跑 binary（跳过 sync + build）
./repl_pipeline.sh --skip-sync --skip-build 10

# KV enum/desc sanity before long REPL
./repl_pipeline.sh --kv-metrics-ut --skip-sync 10

# 盯屏看 RPC 日志流
./repl_pipeline.sh --tee --skip-sync 10
```

---

## 脚本说明

| 脚本 | 作用 |
|------|------|
| `repl_pipeline.sh` | **推荐入口**：rsync → bazel build → bazel test → parse |
| `rsync_datasystem.sh` | 同步本地 `yuanrong-datasystem` → 远端 |
| `bazel_build.sh` | `bazel build //tests/st/... --config=perf --config=release` |
| `bazel_run.sh` | `bazel test`，stdout/stderr 先写远端文件再 scp 回本机 |
| `bazel_run_kv_metric_urma_layout_ut.sh` | KV metrics tail 布局 UT（`--kv-metrics-ut` 时调用） |
| `parse_repl_log.py` | 解析 REPL gtest 输出，提取 6 Histogram metrics |

---

## 构建配置

| 场景 | 命令 |
|------|------|
| **Profiling（推荐）** | `bash build.sh -b bazel -r -p on -t build -j 16` |
| **Debug** | `bash build.sh -b bazel -d -t build -j 16` |
| **Release 发布** | `bash build.sh -b bazel -r -t build -j 16` |

`-p on` → `--config=perf` → `-DENABLE_PERF`（`RecordTick` 热路径生效）。
