# KV 锁内系统调用风险精炼版（评审一页）

## 1. 范围

- KV 入口：`KVClient::*`（`src/datasystem/client/kv_cache/kv_client.cpp`）
- 重点三方链路：`zmq`、`spdlog`、`grpc/etcd`
- 本文主判断口径：**锁持有期间发生（或稳定映射到）系统调用**

## 2. 核心结论

1. 主风险是“**锁内 syscall/等待**”导致临界区放大，而非单纯日志开销。  
2. 当前优先治理应聚焦可直接闭环的主证据链：ZMQ、mmap/FD、memcopy 线程池等待。  
3. `grpc` 已确认链路触发，但函数级“锁+syscall”证据仍需补充采样闭环（`perf dwarf`）。

## 3. 主清单（仅锁内 syscall 口径）

| Case | 锁范围 | 关键文件 | syscall | 风险级别 | 建议 |
|---|---|---|---|---|---|
| A | `RouteToUnixSocket`（`ReadLock + WriteLock`） | `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | `epoll_ctl` | P0 | `SetPollOut` 移锁外；锁内只做入队与状态位 |
| C | `LookupUnitsAndMmapFds`（全局 `shared_timed_mutex`） | `src/datasystem/client/mmap_manager.cpp` | `recvmsg/sendmsg`, `mmap/madvise/close`（调用链） | P0 | 两/三段锁：锁内收集，锁外 RPC+映射，锁内回写 |
| H-2 | `ThreadPool::Submit/DoThreadWork` | `src/datasystem/common/util/thread_pool.*` | futex/condvar 等等待机制 | P1（组合到P0） | 背压与阈值调优；避免业务大锁内发起并行拷贝 |

## 4. 扩展风险（非本轮主证据）

- 锁内 RPC（`ShutDown`、`GIncreaseRef/GDecreaseRef`、`RediscoverLocalWorker`）
- 锁内日志（是否落到 `write/fsync` 取决配置）
- TLS/thread_local 在 bthread 下的上下文污染

这些风险建议并行治理，但不影响本轮“锁内 syscall”主结论。

## 5. 三方覆盖状态（关键）

- **已覆盖**：`zmq`、`spdlog`、`brpc/bthread`
- **部分覆盖**：`grpc/protobuf`（链路触发已证实，函数级锁+syscall 待补证）

## 6. 立即执行顺序

1. **先做 P0**：Case A、Case C
2. **再做 P1**：Case H-2 的线程池背压与阈值调优
3. **补证 grpc**：`perf dwarf` + 现有 bpftrace 交叉

