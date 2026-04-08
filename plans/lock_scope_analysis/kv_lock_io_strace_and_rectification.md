# KV Client 读写链路锁/IO Strace分析与整改工作量评估

## 1) 本次采集范围与方法

- 采集脚本：`scripts/perf/trace_kv_lock_io.sh`
- 解析脚本：`scripts/perf/analyze_strace_lock_io.py`
- 采集命令（已实跑）：

```bash
bash scripts/perf/trace_kv_lock_io.sh \
  --build-dir build \
  --out-dir workspace/observability/strace
```

- 本轮覆盖用例（8个）：
  - `KVClientBrpcBthreadReferenceTest.BrpcSdkExecutorSmokeGoodPathBatch`
  - `KVClientExecutorRuntimeE2ETest.*`（inline/injected/reentrant/error/perf）
- 产物：
  - `workspace/observability/strace/trace_20260402_122304_report.md`
  - `workspace/observability/strace/trace_20260402_122304_summary.json`
  - 原始 `strace -ff` 分 pid 文件（同目录）

## 2) Strace关键观察（锁相关 + IO）

来自 `trace_20260402_122304_report.md`：

- 锁相关 syscall：
  - `futex`: count=150863, total_s=15021.445653
  - `fcntl`: count=2851, total_s=0.484103
  - `flock`: count=16, total_s=0.001242
- IO/等待面：
  - `epoll_wait`: count=22196, total_s=1774.479896
  - `poll`: count=15986, total_s=244.936607
  - `epoll_pwait`: count=12414, total_s=60.953083
  - `read/write/sendto/recvfrom/recvmsg/sendmsg` 在同一批次高频出现
  - `pread64/pwrite64` 存在（说明有磁盘读写路径参与）

结论（系统调用层面）：

1. 调用链显著依赖 `futex + epoll/poll`，即“锁等待 + 事件循环等待”叠加明显。  
2. 读写压测时网络收发与本地 fd/磁盘 IO 都同时存在，符合“持锁跨 RPC/等待会放大阻塞”的风险画像。  
3. 单靠日志优化无法解释或消除上述等待面，仍需按锁边界治理。

## 3) 三方库加锁点与IO判断（基于 strace 可观测性）

说明：`strace` 直接给到 syscall，不会直接告诉“具体源码行号/库函数名”。因此这里给“可证据化推断”：

- 可确认三方参与：
  - `brpc/bthread` 场景（已跑 `BrpcSdkExecutorSmokeGoodPathBatch`）下，`futex` 与 `epoll/poll` 高占比。
  - 连接样本出现多次 unix socket connect（`/tmp/.../client.sock`），与 worker/client 通道一致。
  - `pread64/pwrite64` 出现，说明底层存储链路（含三方组件）有同步IO面。
- 对“是否有 IO 操作”判断：**是**。网络IO与文件IO在同轮请求中同时出现。
- 对“加锁点是否在三方库内部”判断：**高概率是**（`futex` 大量出现且跨多进程），但仅靠 strace 不能精确到库源码函数。

建议补充验证（下一步可做）：

1. `strace -k`（内核支持时）补调用栈。  
2. 对关键进程（`datasystem_worker`, `ds_st_kv_cache`）加 `perf record -g` 交叉定位锁等待热点函数。  
3. 若要区分“自研锁”与“三方锁”，结合符号化栈再做归因。

## 4) 数据系统整改工作量识别（参考既有治理计划）

参考文档：[`docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md`](../../docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md)

### P0（必须优先，预计 1~2 周）

1. `ObjectClientImpl::ShutDown`  
   - 现状：锁内 `Disconnect`（RPC）  
   - 方案：快照 worker 列表 -> 解锁 -> RPC -> 必要回写
   - 工作量：M

2. `ObjectClientImpl::GIncreaseRef/GDecreaseRef`  
   - 现状：锁内调用 `GIncreaseWorkerRef/GDecreaseWorkerRef`  
   - 方案：锁内更新本地计数，锁外 RPC，失败回滚
   - 工作量：M

3. `MmapManager::LookupUnitsAndMmapFds`  
   - 现状：锁内 `GetClientFd` + `MmapAndStoreFd`  
   - 方案：拆分“收 fd / mmap IO”与“表更新”阶段
   - 工作量：M~L（回归较多）

4. `RediscoverLocalWorker`  
   - 现状：锁内 `SelectWorker`（etcd网络）  
   - 方案：锁内只保留状态检查，选路下沉到锁外
   - 工作量：S~M

### P1（并行推进，预计 1 周）

1. 锁内日志锁外化（`object_client_impl.cpp`、`comm_factory.cpp`、`stream_client_impl.cpp`、`listen_worker.cpp`、`router_client.cpp`）  
   - 工作量：M
2. 高频日志降采样（`LOG_EVERY_N/T`）  
   - 工作量：S

### P1 兜底（按需）

1. 对暂不可改路径做 bthread 入口隔离（切 pthread 线程池）  
   - 工作量：M
   - 风险：吞吐/时延模型改变，需要压测校准

## 5) 建议验收口径

1. 功能：现有 `KVClient` 回归全绿。  
2. 性能：关键接口 p95/p99 时延与 timeout 率不回退。  
3. 并发稳定性：长压测中不再出现“锁持有线程卡在 RPC/等待”的典型栈。  
4. 可观测性：每次改造后重复跑 `scripts/perf/trace_kv_lock_io.sh`，对比 `futex/epoll_wait/poll` 总等待时长趋势。
