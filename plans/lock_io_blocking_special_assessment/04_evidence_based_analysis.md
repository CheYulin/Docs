# 证据化专项分析（Client 范围：代码片段 + 运行日志 + 问题 + 解决思路）

> **范围**：与 `05_client_scope_strace_and_third_party.md` 一致——**仅** client 与 client 可达的 etcd/gRPC、ZMQ common；**不**展开 worker/master 源码证据。**本专项不涉及 brpc / bthread 参考测试链路与 `.third_party/brpc_st_compat`。**  
> **三方重点**：**仅** `libdatasystem.so` **依赖且 client 实际调用** 到的库（`ldd` + 调用图收敛），分析其中的 **lock + IO/阻塞** 形态（`05` §1.1、§3.3）。  
> **方法**：**A** `strace`（syscall 面）；**B** 静态沿调用图 + `_deps/*-src` 查持锁 IO；**C** `bpftrace` 栈归因（`05` §6 与 `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_132806_report.md`）。

## 1. 运行结果证据（已实跑，client 侧测试进程）

采集命令：

```bash
bash scripts/perf/trace_kv_lock_io.sh --build-dir build --out-dir workspace/observability/strace
```

默认 gtest filter：`KVClientExecutorRuntimeE2ETest.*`（与 `scripts/perf/trace_kv_lock_io.sh` 一致，**不含** brpc 用例）。

日志摘录（测试覆盖 + 通过）：

```text
[INFO] filter=KVClientExecutorRuntimeE2ETest.*
[==========] Running 7 tests from 1 test suite.
...
[  PASSED  ] 7 tests.
```

**归因说明**：该二进制在部分用例下可能 **fork** 子进程；syscall 汇总可能含子进程贡献。Client 专项结论应结合 **`05` §2.2** 做 PID/用例层面的区分。

syscall 统计摘录（锁/IO 叠加，历史一次全量采集形态供对照；复跑请以新生成的 `trace_*_report.md` 为准）：

```text
futex: count=150863, total_s=15021.445653
epoll_wait: count=22196, total_s=1774.479896
poll: count=15986, total_s=244.936607
read/write/sendto/recvfrom/recvmsg/sendmsg 高频
pread64/pwrite64 存在
```

结论：测试进程内锁等待与事件/网络/存储等待并存；与 **client + etcd + ZMQ + gRPC 内部** 阻塞面叠加时，若业务锁跨越这些路径，存在放大条件。

---

## 1.1 bpftrace 调用栈证据

采集输出（当前默认脚本与 strace 一致：`KVClientExecutorRuntimeE2ETest.*`）：

- 新一轮：`workspace/observability/bpftrace/trace_20260402_140947_stacks.txt`
- 新一轮解析：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_140947_report.md`
- 历史对照：`workspace/observability/bpftrace/trace_20260402_132806_stacks.txt`
- 历史解析：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_132806_report.md`

关键观察（client 侧、`comm == ds_st_kv_cache` 过滤）：

- 新一轮（`140947`）：`futex` Top 约 `954`，`rw` Top 约 `883`，`epoll/poll/net` 在 `comm` 过滤下仍较低（`epoll` 约 `1`，`poll` 约 `3`，`net` 约 `1`）。
- 历史轮次（`132806`）出现过 `@futex[]` 与 `failed to look up stack id`，说明 bpftrace 用户态栈质量会受运行时与符号条件影响。
- 两轮共同点：`epoll/poll` 与 strace 全量统计存在口径差异（`comm` 过滤、线程命名、采集窗口），需结合 strace 与静态调用图联合解释。
- 两轮都可见疑似坏帧常量（如 `0x38393132207c2020` / `0x32353032207c2020`），当前不宜直接用于函数级归因。

本轮结论：

- bpftrace 链路已跑通，可作为第三种运行时证据。
- 当前栈符号以地址为主，三方库函数级归因仍需先做符号化增强（`RelWithDebInfo/-g` + symbolizer），再将高频栈映射到 `build/_deps/{grpc,zeromq,protobuf,openssl}-src` 细读。

---

## 2. 代码证据与问题判定（本仓 client + client 可达 common）

### 2.1 Client：锁内 RPC + mmap（P0）

文件：`src/datasystem/client/mmap_manager.cpp`

```cpp
Status MmapManager::LookupUnitsAndMmapFds(...) {
    std::lock_guard<std::shared_timed_mutex> lck(mutex_);
    ...
    RETURN_IF_NOT_OK(clientWorker_->GetClientFd(toRecvFds, clientFds, tenantId));
    for (...) {
        RETURN_IF_NOT_OK(mmapTable_->MmapAndStoreFd(clientFds[i], ...));
    }
}
```

问题：在 `mutex_` 持有期间执行 `GetClientFd`（RPC/fd 传输）和 `MmapAndStoreFd`（重 IO）。

解决思路：锁内收集待处理 fd → 解锁执行 GetClientFd/mmap → 短锁回写。

---

### 2.2 Client：锁内 worker RPC（P1）

文件：`src/datasystem/client/object_cache/object_client_impl.cpp`

```cpp
Status ObjectClientImpl::GIncreaseRef(...) {
    std::shared_lock<std::shared_timed_mutex> lck(globalRefMutex_);
    ...
    auto rc = workerApi_[LOCAL_WORKER]->GIncreaseWorkerRef(firstIncIds, failedObjectKeys);
    ...
}
```

问题：`globalRefMutex_` 作用域内包含远端 RPC，持锁时长不可控。

解决思路：锁内仅计算增量与回滚 token；锁外 RPC；再短锁提交或回滚。

---

### 2.3 Common（client 经 `EtcdStore` 调用）：etcd 读锁跨 RPC/Txn（P0）

文件：`src/datasystem/common/kvstore/etcd/etcd_store.cpp`

```cpp
Status EtcdStore::Put(...) {
    std::shared_lock<std::shared_timed_mutex> lck(mutex_);
    ...
    RETURN_IF_NOT_OK(rpcSession_->SendRpc("Put::etcd_kv_Put", ...));
}

Status EtcdStore::BatchPut(...) {
    std::shared_lock<std::shared_timed_mutex> lck(mutex_);
    ...
    return txn.Commit();
}
```

问题：配置锁跨 gRPC `SendRpc`/事务提交；慢网或重试时放大共享锁持有。

解决思路：锁内仅快照表配置；锁外 `SendRpc`/`Commit`；版本校验防漂移。

---

### 2.4 静态方法 B：三方侧只查「依赖 ∩ 调用」里的 lock + IO

本仓入口：`grpc_session.cpp`、`etcd_watch.cpp` 等对 `grpc::` 的调用；`exclusive_conn_mgr` / `zmq_rpc_generator` 对 ZMQ 的封装。  
从上述入口进入 `build/_deps/grpc-src`、`zeromq-src` 等，**只跟可达路径**，检索 **持锁 + 网络/文件/epoll 类阻塞**（判据见 `05` §1.1）。

### 2.5 client 路径 thread_local 风险（新增标识）

- 已确认 client 路径大量依赖 `common/util/thread_local.*`（`reqTimeoutDuration`、`g_ContextTenantId` 等）及
  `common/rpc/zmq/exclusive_conn_mgr.cpp` 中的 `thread_local gExclusiveConnMgr`。
- 这类 TLS 在“线程复用/跨线程回调”场景下的核心风险是：**状态残留与线程绑定假设失效**，可能引发
  timeout 语义漂移、租户上下文串用、连接回收不一致。
- 风险级别建议：`reqTimeoutDuration/g_ContextTenantId` 为 **中风险**；`gExclusiveConnMgr`（线程绑定连接）为 **中高风险**。
- 详细命中点与整改建议见：`07_client_third_party_call_sites.md` §9。

---

## 3. 工作量评估（Client 专项，证据驱动）

与 `03_execution_plan_and_workload.md` 对齐：

- P0：mmap、comm_factory、etcd_store — **8~12 人日**
- P1：object_client_impl、listen_worker、ZMQ/etcd 辅助路径 — **10~16 人日**
- P2：日志与指标 — **4~8 人日**

---

## 4. 建议执行顺序

1. P0 锁边界（client mmap、comm_factory、etcd_store）。  
2. P1 引用计数与 ZMQ/etcd 周边。  
3. P2 可观测与降噪。  
4. 每阶段按 `05` 方法 A 复跑 strace 并对比趋势。

---

## 5. 锁与 IO 整改矩阵（Client 专项）

### P0

1. `client/mmap_manager.cpp::LookupUnitsAndMmapFds` — 两阶段（锁内收集 → 锁外 RPC/mmap → 短锁回写）。  
2. `client/object_cache/device/comm_factory.cpp::{CreateCommInRecv, ProcessCommCreationInSend}` — 状态机拆段 + 锁外 RPC。  
3. `common/kvstore/etcd/etcd_store.cpp::{Put, BatchPut, Get*, Delete*}` — 锁外 `SendRpc`/`Commit`。

### P1

1. `client/object_cache/object_client_impl.cpp::{GIncreaseRef, GDecreaseRef}` — 锁外 RPC，短锁提交/回滚。  
2. `client/listen_worker.cpp` — 回调锁外化。  
3. `client/client_worker_common_api.cpp` / `stream_cache/client_worker_api.cpp` + 下层 `common/rpc/zmq/*` — 避免持锁进入 ZMQ 阻塞。  
4. `common/kvstore/etcd/etcd_watch.cpp`、`etcd_keep_alive.cpp`、`grpc_session.cpp` — 核对锁与 gRPC 异步路径。

### P2

1. `client/router_client.cpp` 等锁内日志外移。  
2. 指标与 strace 回归自动化。
