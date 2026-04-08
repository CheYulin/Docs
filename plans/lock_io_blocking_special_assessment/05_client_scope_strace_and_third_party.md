# Client 专项范围：strace + 静态追踪（三方库）

## 1. 范围声明（与客户口径一致）

- **在范围内**：`src/datasystem/client/**` 中的业务锁与阻塞路径；以及 **client 目标在链接与调用上必然进入** 的本仓代码（典型为 `common_etcd_client`、`ZMQ/exclusive_conn` 相关 common 代码）。
- **不在范围内**：`worker/`、`master/` 进程内逻辑；专项结论与整改优先级**不以** worker/master 源码为准。
- **动态证据**：对 **承载 client 代码的进程** 做 strace（见下文方法 A），不把 worker 子进程的 syscall 自动等同为 “SDK client 行为”，除非明确按 PID 归因。
- **三方库**：只分析 **从 client 调用图可达** 的路径（gRPC、protobuf、ZMQ、OpenSSL 等，见 §3）。**本专项不包含 brpc / `.third_party/brpc_st_compat`**。

### 1.1 核心分析目标：client **依赖且实际调用** 的三方 —— **lock + IO**

本专项在三方侧**不是**泛读整个 `grpc-src` / `zeromq-src`，而是两层收敛后再看 **锁与 IO/阻塞是否叠在一起**：

1. **依赖（链接事实）**  
   以 `libdatasystem.so` 的 `NEEDED` / `ldd` 为准（`scripts/build/list_client_third_party_deps.sh --target lib`）。**只分析确实被 client 共享库链进来的依赖**；未出现在该列表中的库，默认不纳入本专项。

2. **调用（可达性）**  
   从 `src/datasystem/client` 经本仓封装（如 `common/kvstore/etcd/*`、`common/rpc/zmq/*`）向下，追到 **client 路径上会触发的第三方 API**（例如 gRPC 同步/异步调用、ZMQ send/recv、TLS 读写）。**未从该调用图触达的第三方内部子系统**不优先通读。

3. **lock + IO 形态（审阅判据）**  
   在「依赖 ∩ 调用」交集内，重点找：
   - **IO / 可阻塞 syscall 路径**：网络读写、`poll`/`epoll_wait`、文件 `fwrite`/`fflush`、磁盘类读写等；
   - **与互斥量/临界区同路径**：在 **持有 mutex / spinlock / 全局日志锁** 等的情况下进入上述 IO/等待，或 **回调在第三方锁内** 调回可能阻塞的逻辑。  
   **本仓可控点**主要是：**业务锁是否包裹** 进入这些第三方调用；第三方内部锁通常只能通过 **调用时机、配置、版本** 规避，而非大面积改 vendor。

运行时方法（strace / bpftrace）用于验证：在 **client 进程** 内，这些 syscall 是否与 **用户态栈上的本仓+三方帧** 同时出现，以支撑上述静态判断。

---

## 2. 方法 A：strace（运行时，client 侧）

### 2.1 对象进程

- 典型：`build/tests/st/ds_st_kv_cache`（或你们实际链接 `libdatasystem.so` 的 client 侧单测/示例）。
- 脚本：`scripts/perf/trace_kv_lock_io.sh`（需已按 `ds_st_kv_cache` 的 `RPATH`/`LD_LIBRARY_PATH` 配好运行环境）。

### 2.2 与 worker 子进程的关系

- 若测试 **fork/exec** 出 worker/etcd 等子进程，`strace -f` 会混入子进程 syscall；这些 **不属于** “纯 client SDK 线程模型” 的结论来源。
- **建议**：
  - 对比 **`strace -p <主测试进程 PID>`**（不跟子进程）与 **`strace -f`** 的差异，定性哪些统计来自主进程；
  - 或构造 **不拉起 worker** 的用例（例如仅 etcd/router 路径、mock transport），使 strace 归因更清晰；
  - 锁与 IO 的 **叠加形态**（`futex`/`epoll_wait`/`poll` 与读写并存）仍可作为 client 二进制内的环境事实，但 **因果解释** 应回指 client + 其直接调用的库，而非 master 实现细节。

### 2.3 输出解读（与专项一致）

- 汇总：`scripts/perf/analyze_strace_lock_io.py` 生成的 `trace_*_report.md`。
- 用途：证明 “业务锁若跨越阻塞 syscall 路径，存在放大条件”，**不**替代源码临界区审计。

---

## 3. 方法 B：静态 —— 从 client 调用图追到三方/外部库（先用 ldd 收敛范围）

### 3.0 先做依赖收敛（避免无效三方扫描）

优先用 `ldd`/`readelf -d` 看真实链接关系，再映射到 `build/_deps/*-src`：

- `bash scripts/build/list_client_third_party_deps.sh --build-dir build --target lib`
- 该命令会输出 `libdatasystem.so` 的 `NEEDED`/`ldd`，并提示对应源码目录。

本次实测 `libdatasystem.so` 可见的 client 侧三方主集合：

- gRPC：`libgrpc++.so`、`libgrpc.so`、`libgpr.so`
- protobuf：`libprotobuf.so`
- ZMQ：`libzmq.so`
- TLS/加密：`libssl.so`、`libcrypto.so`
- 通用依赖：`libabseil_dll.so`、`libz.so`、`libds-spdlog.so`、`libtbb.so`、`libsecurec.so`

对应源码根目录（`build/_deps`）：

- `grpc-src`、`protobuf-src`、`zeromq-src`、`openssl-src`
- `absl-src`、`zlib-src`、`spdlog-src`、`tbb-src`、`securec-src`

### 3.1 链接层事实（`src/datasystem/client/CMakeLists.txt`）

`datasystem` / `datasystem_static` 显式依赖中包含与阻塞语义相关的项：

- `protobuf::libprotobuf`
- `gRPC::grpc++`
- `common_etcd_client`（etcd 访问封装，内部使用 gRPC）
- 以及经 common 进入的 **ZMQ** 传输（见下 3.2）

### 3.2 本仓源码：client 直接进入的“库侧”入口

按 **文件名级** 展开的清单见 **`07_client_third_party_call_sites.md`**（与下表一致并补全 protobuf/TBB/securec 等）。

| 入口（client） | 进入的本仓路径（审阅锁+阻塞） |
|----------------|--------------------------------|
| `service_discovery.cpp`、`router_client.cpp` | `common/kvstore/etcd/etcd_store.cpp`、`grpc_session.cpp`、`etcd_watch.cpp`、`etcd_keep_alive.cpp`、`etcd_health.cpp`、`etcd_elector.cpp` |
| `client_worker_common_api.cpp` | `common/rpc/zmq/exclusive_conn_mgr.h` 及其实现所依赖的 ZMQ/socket 封装 |
| `stream_cache/client_worker_api.cpp` | `common/rpc/plugin_generator/zmq_rpc_generator.h` 及生成桩背后的 ZMQ 发送路径 |

审阅时关注：**互斥锁/读写锁是否跨越** `SendRpc`、`Commit`、`stream` 读写、`zmq_*` 等可能阻塞的调用。

### 3.3 外部三方：在「依赖 ∩ 调用」内查 **lock + IO**

本仓 `grpc_session.cpp` 等对 `grpc::` 的调用是 **进入 gRPC 的入口**；在 `build/_deps/grpc-src` 中只沿 **这些入口可达** 的实现向下读，检索 **持锁 + 网络读写 / epoll / 条件等待** 等组合（对齐 §1.1）。

- **gRPC**：例如 channel/completion 线程、`CompletionQueue::Next`、secure endpoint 读写路径；对照 client 是否 **在持业务锁时** 调用 `SendRpc`、同步 `Complete` 等。
- **libzmq**（`zeromq-src`）：`zmq_send`/`zmq_recv`、engine 线程与 socket 锁；对照本仓 `exclusive_conn_mgr` / 生成桩路径是否在 **持锁段** 内调用。
- **OpenSSL**（`openssl-src`）：经 gRPC TLS 等进入；关注握手与 `SSL_read`/`SSL_write` 与内部锁的搭配（通常与 **连接建立 / 加密读写** 同路径）。
- **protobuf**：多数为 CPU 序列化，**lock+IO 优先级低**；仅在 **持锁** 下做大消息拷贝或与 **日志写盘** 绑定时再细看。
- **spdlog / TBB / securec 等**：仅在 **client 调用栈或 ldd 证明** 会在热点路径上进入时，按同样 **lock+IO** 判据抽查；避免无调用关系的全库审计。

## 4. 与 `01`～`04` 的关系

- `01`～`04` 中凡涉及 **worker/master** 的条目，在 **client 专项** 下视为 **出范围**，以本文档为准划分边界。
- **brpc / bthread 参考测试**不在本工作范围内；文档与默认 trace filter 均不覆盖该路径。

---

## 5. 推荐阅读顺序（client 专项）

1. 本文档 `05`（范围 + 方法 A/B/C）
2. `02_hotspot_inventory.md`（client + client 可达 common）
3. `04_evidence_based_analysis.md`（client + etcd + 运行时证据）
4. `01`、`03`（工作量以 client 裁剪版为准）

---

## 6. 方法 C：bpftrace（推荐，用调用栈定位“谁在触发阻塞 syscall”）

**可复制操作指南（含 sudo/非 sudo、可选符号化）见：`08_ebpf_bpftrace_operator_runbook.md`。**

`strace` 只看到 syscall；`bpftrace` 给出用户态栈，用于把 **futex / epoll / read / write** 等与 **client + 三方帧** 对齐，支撑 §1.1 的 **lock + IO** 归因（需符号化后效果最好）。

执行方式（需要 root）：

- **安全**：不要用仓库内明文文件保存 sudo 密码，也不要在脚本里 `sudo -S` 读密码；仓库根目录的 `passwd` 已列入 `.gitignore`，仍建议删除该文件并视情况修改本机密码。开发机可用 `visudo` 配置**仅限** `bpftrace` 的窄 NOPASSWD。

仓库根目录下（路径不必写全，脚本用自身路径算 `ROOT_DIR`）：

```bash
cd /path/to/yuanrong-datasystem
sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh --build-dir build --out-dir workspace/observability/bpftrace
```

若不在仓库根目录，可对**脚本本身**用绝对路径（`--build-dir` 仍相对于 `ROOT_DIR` 解析，一般用默认即可）：

```bash
sudo bash /path/to/yuanrong-datasystem/scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --out-dir /path/to/yuanrong-datasystem/workspace/observability/bpftrace
```

输出：

- `workspace/observability/bpftrace/trace_*_stacks.txt`（与终端 `tee` 同步；gtest 在 `bpftrace -c` 子进程里跑，常需 **1～2 分钟以上** 才有汇总栈）
- **样例解读**：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_132806_report.md`（对应一次实跑；当前裸地址栈为主，需按报告第 3 节改进符号化后再做三方归因）

说明：

- 当前 `bpftrace` 脚本按 `comm == "ds_st_kv_cache"` 过滤，只聚焦 client 测试二进制。
- 栈里若出现 `grpc`/`zmq`/`openssl`/`protobuf` 等符号，即可判定该三方在 client 路径上“实际触发”了相应阻塞 syscall。
- 若环境是 WSL2，eBPF/BTF 可能受限；建议在原生 Linux 复现同样命令。

### 6.1 用户态栈「符号做全」（脚本与命令）

仓库内步骤汇总见 **`scripts/perf/bpftrace/RUN_SYMBOLS.txt`**。你本地可按下面执行：

1. **调试构建 + frame pointer**（CMake 一行见 `RUN_SYMBOLS.txt`）。
2. **带符号解析器跑 bpftrace**（`llvm-symbolizer` 需在 PATH；用 `-E` 保留环境）：

```bash
cd /path/to/yuanrong-datasystem
BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh --out-dir workspace/observability/bpftrace
```

若目标是优先覆盖 `common_etcd_client(grpc)` 路径，建议改为：

```bash
cd /path/to/yuanrong-datasystem
BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --out-dir workspace/observability/bpftrace \
  --filter 'KVClientEtcdDfxTest.LEVEL1_TestEtcdRestart:KVClientEtcdDfxTest.TestEtcdCommitFailed:KVClientEtcdDfxKeepAliveTest.LEVEL1_TestEtcdKeepAlive:KVClientEtcdDfxTestAdjustNodeTimeout.TestSetHealthProbe:KVClientEtcdDfxTestAdjustNodeTimeout.TestRestartDuringEtcdCrash'
```

说明：该过滤器优先触发 etcd 异常恢复、keepalive、txn commit retry 等链路，更容易在栈里看到 grpc/gpr 相关符号。

3. **后处理**（进程退出后补符号）：在测试**运行中**另开终端保存 maps，再跑：

```bash
pgrep -nx ds_st_kv_cache | xargs -I{} cat /proc/{}/maps > /tmp/ds_maps.txt
python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \
  --maps /tmp/ds_maps.txt \
  workspace/observability/bpftrace/trace_XXXX_stacks.txt \
  -o workspace/observability/bpftrace/trace_XXXX_stacks.sym.txt
```

4. **备用**：dwarf 栈更稳时可用 `bash scripts/perf/perf_record_kv_lock_io.sh`，再 `perf report`（见 `RUN_SYMBOLS.txt`）。
