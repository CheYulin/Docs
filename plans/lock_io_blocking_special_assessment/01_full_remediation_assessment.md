# Datasystem Client 侧整改评估（专项）

> **范围**：仅评估 `src/datasystem/client` 及 client **直接调用** 的 etcd/gRPC、ZMQ 相关 common 代码。**不包含** worker/master 进程内整改项。三方侧聚焦 `**libdatasystem.so` 依赖且 client 会调到的库** 中的 **lock + IO/阻塞**（`05` §1.1）。运行时 + 静态方法见 `05_client_scope_strace_and_third_party.md`。

## 1. 结论摘要

- 主风险仍是 **锁范围与阻塞操作耦合**（锁内 RPC、锁内 mmap/IO、锁内等待）。
- 已有 strace 证据表明锁等待与 `epoll_wait`/`poll`/读写等叠加，具备阻塞放大条件；解释时应 **归因到 client 进程与 client 可达库**，见 `05` 第 2 节。
- 若不引入额外线程池，仍可通过 **锁边界治理 + 快照解锁 + 回写校验** 收敛 client 侧风险。

## 2. 动态证据（基于已跑 kv client 侧测试）

采集：`scripts/perf/trace_kv_lock_io.sh`（对象进程为链接 client 的测试二进制，详见 `05`）。

摘录统计（同前，`trace_20260402_122304_report.md`）：

- `futex` / `fcntl` 高频
- `epoll_wait` / `poll` / 网络读写与 `pread64`/`pwrite64` 并存

含义：client **进程内** 呈现锁等待与 IO/多路复用等待叠加；具体临界区需结合 client + etcd + ZMQ 封装源码。

## 3. 风险分级（仅 Client + client 可达 common）

### P0（必须优先）

1. `client/mmap_manager.cpp`：锁内 `GetClientFd + mmap`
2. `client/object_cache/device/comm_factory.cpp`：锁内 root-info RPC 与通信初始化
3. `common/kvstore/etcd/etcd_store.cpp`：共享锁跨 `SendRpc` / `txn.Commit`

### P1（高优先）

1. `client/object_cache/object_client_impl.cpp`：`GIncreaseRef` / `GDecreaseRef` 锁内 worker RPC
2. `client/listen_worker.cpp`：锁下回调与等待
3. `client/client_worker_common_api.cpp` / `stream_cache/client_worker_api.cpp`：ZMQ 路径与上层锁的配合
4. `common/kvstore/etcd/`*（除 store 外）：watch/keepalive 等与 gRPC 交互处的锁范围

### P2（优化项）

1. `client/router_client.cpp` 等路径锁内重日志与字符串构造
2. client 全链路锁内日志降噪与指标

## 4. 整改原则（不引入额外线程池前提）

1. 锁内只做内存态读写，不做 RPC/等待/重 IO。
2. **快照(锁内) → 解锁 → 回写(短锁+版本校验)**。
3. 外部回调、通知、日志锁外执行。
4. 对必须等待路径加超时与可观测。

## 5. 改造后预期收益（client 侧）

- client 相关路径上锁等待分位（p95/p99）与尾延迟风险下降。
- “持业务锁进入 etcd/gRPC/ZMQ 阻塞” 的代码路径减少。

## 6. 风险与边界

- 解锁后状态变化需版本号/epoch/CAS 保护。
- **外部 gRPC/libzmq** 内部锁行为本仓不可改，只能通过 **避免持业务锁进入这些调用** 降耦。
- strace 不能单独证明源码临界区因果；需与方法 B（静态调用图 + 必要时阅读 gRPC/ZMQ 上游源码）结合，见 `05`。

