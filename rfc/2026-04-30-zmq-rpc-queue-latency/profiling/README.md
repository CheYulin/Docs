# OS-Level Profiling — 快速上手

本目录提供 ZMQ RPC 队列时延的 OS 层可观测工具链，帮助回答：

- **应用层慢在哪里？** → REPL 6 Histogram（`zmq_server_queue_wait_latency` 等）
- **CPU 时间花在哪里？** → `perf stat` 硬件计数器
- **哪个函数最热？** → `perf record` + 火焰图
- **系统 syscall 分布？** → `strace -c`
- **TCP 层有无异常？** → `/proc/net/snmp` + `ss -ti`

---

## 快速开始

### 首次完整运行（build + 全套 profiling）

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem-agent-workbench/rfc/2026-04-30-zmq-rpc-queue-latency/profiling
bash build_profiling_pipeline.sh
```

结果落入 `results/profiling_YYYYMMDD_HHMMSS/`，包含：

- `perf_stat_report.txt` — CPU cycles / instructions / cache-miss / IPC
- `perf_record_report.txt` — top 函数调用（过滤后）
- `flamegraph.svg` — 火焰图（如 graphviz 已安装）
- `tcp_profile_report.txt` — TCP retransmits / RTT / socket buffers
- `syscall_profile_report.txt` — syscall 次数与耗时
- `zmq_rpc_queue_latency_repl.log` — REPL 应用层 6 Histogram
- `parse_summary.txt` — 统一解析摘要

### 开发迭代（跳过 build，复用已有构建）

```bash
bash build_profiling_pipeline.sh --skip-build
```

### 只跑某一层

```bash
bash perf_profile.sh 15       # 15s perf 采样
bash tcp_profile.sh 10       # 10s TCP 采样
bash repl_pipeline.sh 10      # 10s REPL 测试
```

---

## 工具缺失检查

远端 `xqyun-32c32g` 可能缺少部分工具。一次性安装：

```bash
ssh root@xqyun-32c32g 'dnf install -y strace bpfcc-tools bpftrace graphviz'
```

| 工具 | 用途 | 安装 |
|------|------|------|
| `perf` | CPU 计数器 + 采样 | 系统自带（需 kernel-debuginfo） |
| `strace` | 系统调用统计 | `dnf install -y strace` |
| `bpftrace` / `bcc` | 高级 eBPF 工具 | `dnf install -y bpfcc-tools bpftrace` |
| `flamegraph.pl` | 火焰图生成 | 下载 Brendan Gregg 脚本 |

---

## 构建配置：最优选项

**必须用 profiling 专用 build：**

```bash
bash build.sh -b bazel -r -p on -t build -j 16
```

| Flag | 效果 |
|------|------|
| `-b bazel` | Bazel 构建，比 CMake 快 |
| `-r` | `--config=release` → `-O2 -DNDEBUG -g3` |
| `-p on` | `--config=perf` → `-DENABLE_PERF`（热路径 `RecordTick` 生效） |
| `-t build` | 编译所有 ST（含 `zmq_rpc_queue_latency_repl`） |
| `-j 16` | 并行度（建议 16–32） |

**等价 Bazel 命令：**

```bash
bazel build //tests/st/common/rpc/zmq:zmq_rpc_queue_latency_repl \
  --config=perf --config=release --jobs=16
```

---

## 脚本清单

```
profiling/
├── build_profiling_pipeline.sh   # 推荐入口：build + 全套 profiling + 解析
├── run_profiling_pipeline.sh      # 纯 profiling（复用已有 build）
├── repl_pipeline.sh              # 仅 REPL 测试（build + run + parse）
├── perf_profile.sh              # perf stat -a + perf record -a -g
├── tcp_profile.sh               # TCP 栈采样（/proc/net/snmp + ss）
├── syscall_profile.sh            # strace -c 系统调用分析
├── parse_profiling.py            # 统一解析所有输出
├── repl_remote_common.inc.sh      # 共享环境变量（不要单独执行）
└── README.md                    # 本文件
```

---

## 各工具适用场景

### 1. REPL（应用层 Histogram）

**命令：** `bash repl_pipeline.sh [duration]`

**回答：** 哪段队列慢？端到端多少？server exec 是否稳定？

```
zmq_rpc_e2e_latency        p50=██████░░░░ 800µs   p99=███████░░░ 1200µs
zmq_server_queue_wait       p50=██░░░░░░░ 200µs   p99=███░░░░░░░ 400µs
zmq_server_exec_latency     p50=████░░░░░ 500µs   p99=█████░░░░░ 800µs
zmq_rpc_network_latency     p50=███░░░░░░ 300µs   p99=████░░░░░░ 600µs  ← 代数残差
```

### 2. `perf stat -a`（硬件计数器）

**命令：** `bash perf_profile.sh [duration]`

**回答：** CPU 主要花在计算还是内存访问？IPC 正常吗？有无非预期 context-switch？

关键指标：

| 指标 | 健康值 | 警惕值 |
|------|--------|--------|
| IPC | > 1.0 | < 0.5 |
| cache-miss ratio | < 10% | > 25% |
| branches/sec | — | 突然下降 |
| context-switch/sec | < 5k | > 20k |

### 3. `perf record -a -g` + 火焰图

**命令：** `bash perf_profile.sh [duration]`（含 `perf record`）

**回答：** 最热的函数是什么？是业务逻辑还是框架开销？

上次 profiling 发现的可疑点：

- `TextFormat::Printer::PrintToString` 在每帧发送路径占 **1.32%**（日志开销）
- `pipe_write` 在 `DemoService` 占 **4.66%**（线程 IPC）
- `zmq::socket_base_t::process_commands` 占 **0.76%**（ZMQ 内部）

### 4. `strace -c`（系统调用）

**命令：** `bash syscall_profile.sh [duration]`

**回答：** 进程时间花在哪种 syscall 上？`sendmsg` / `recvmsg` / `futex` / `epoll_wait`？

> 注意：`strace -c` 会显著拖慢进程（2–10x），只用于定性判断。

### 5. TCP 栈（`/proc/net/snmp` + `ss -ti`）

**命令：** `bash tcp_profile.sh [duration]`

**回答：** 有无 TCP 重传？RTT 是否正常？socket 发送缓冲区是否积压？

关键指标：

| 指标 | 健康值 | 警惕值 |
|------|--------|--------|
| `RetransSegs` 增量 | 0 | 持续增长 |
| `AvgRTT` | < 1ms（内网） | > 5ms |
| `snd_una` 推进慢 | — | 持续落后 |

---

## 已知局限

1. **`zmq_rpc_network_latency` 是代数残差**，非物理 RTT。见 RFC docs/design.md §4.2。
2. **`perf -a` 系统级采样**包含所有进程噪音。聚焦单进程需 `bpftrace` / `cgroup` 隔离。
3. **`strace -c` 对热路径有干扰**，不用于精确延迟量化。
4. **`perf record` 火焰图**需要远端 `graphviz` 和 `flamegraph.pl`。

---

## 输出示例（parse_profiling.py 摘要）

```
=== TCP Report ===
  RetransSegs delta:    0 (clean)
  ActiveConnections:    3
  EstabRTT:             0.3ms

=== Syscall Report ===
  % time     seconds  usecs/call     calls    errors syscall
  ------  -----------  -----------  --------- --------- ------
   34.12      0.120000        1200       100       -     epoll_wait
   28.45      0.100000          500       200       -     sendmsg
   19.33      0.068000          340       200       -     recvmsg

=== REPL Summary ===
  zmq_rpc_e2e_latency       p50=  856µs  p90= 1040µs  p99= 1380µs
  zmq_server_queue_wait     p50=  210µs  p90=   380µs  p99=  560µs
  zmq_server_exec_latency   p50=  540µs  p90=   720µs  p99=  920µs
  zmq_rpc_network_latency   p50=    0µs  p90=   120µs  p99=  460µs  ← residual
```

---

## 环境变量

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `REMOTE` | `root@xqyun-32c32g` | 远端 SSH 目标 |
| `REMOTE_DS` | `/root/workspace/git-repos/yuanrong-datasystem` | 远端仓库根 |
| `DS_OPENSOURCE_DIR_REMOTE` | `/root/.cache/yuanrong-datasystem-third-party` | 第三方缓存（必须持久） |
| `BAZEL_JOBS` | `32` | 并行 build jobs |
| `DURATION` | `10` | 每个 profiling 脚本采样秒数 |
| `LOCAL_RESULTS_DIR` | `results/` | 本地结果目录 |

覆盖示例：

```bash
DURATION=20 BAZEL_JOBS=16 bash build_profiling_pipeline.sh --skip-build
```
