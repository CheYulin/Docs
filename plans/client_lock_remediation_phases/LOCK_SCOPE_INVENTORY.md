# Client 侧锁范围清单（用于「持锁内无耗时 / 无 RPC / 少 syscall」核对）

本文档归纳 `src/datasystem/client` 及直接相关的 Object/ZMQ 路径上**主要互斥量/读写锁**各自保护的**数据域**，并标出当前代码里**持锁仍可能发生的耗时操作**（**RPC**、**阻塞 syscall**、**futex/条件变量等跨执行流等待**）。  
目标：后续改动的验收口径是 **临界区内只做短逻辑 + 内存数据结构访问**；需要网络/内核/长时间等待的步骤应在**快照后解锁**再执行（与总 plan「快照 → 解锁 → RPC → 短锁回写」一致）。

---

## 图例

| 标记 | 含义 |
|------|------|
| ✓ | 当前实现下，该锁的典型临界区以内存操作为主（仍可能有 `LOG`，见阶段 3） |
| ⚠ | 存在 **RPC**、**mmap/recvmsg 等 syscall**、或 **futex/长时间等待** 仍可能发生在持锁期间（需治理） |
| ◁ | 已做过局部缩短临界区（如 ZMQ `SetPollOut` 外移、`ShutDown` 锁外 `Disconnect`） |

---

## 1. Object client 核心（`object_cache/object_client_impl.*`）

| 锁名 | 保护的数据 / 不变量 | 典型持锁范围 | 耗时 / 交互风险 |
|------|---------------------|--------------|-----------------|
| **`shutdownMux_`**（`shared_timed_mutex`） | 关闭流程与正常 API 并发；析构/ShutDown 与业务路径互斥 | 几乎所有对外 API 以 **`std::shared_lock`** 贯穿整个函数体（如 `Create`、`MultiCreate`、`Get`、`Put`…） | ⚠ **整段 RPC**（`workerApi_->Create` / `Get` / …）与 **`mmapManager_->LookupUnitsAndMmapFd`（内部含 RPC+syscall）** 均发生在 **`shutdownMux_` 共享锁仍持有** 期间。任意尝试获取 **`unique_lock`（ShutDown）** 的请求会**阻塞到所有共享锁释放**，故尾延迟与 bthread 占用会被放大。 |
| **`globalRefMutex_`**（`shared_timed_mutex`） | `globalRefCount_`（TBB）一致性 | `GIncreaseRef` / `GDecreaseRef` 等对 ref 表的遍历与 accessor 更新 | ⚠ 在 **`std::shared_lock` 整个函数作用域未提前释放** 的情况下，`GIncreaseWorkerRef` / `GDecreaseWorkerRef`（**RPC**）会在**仍持有 `globalRefMutex_` 读锁**时执行；与需要 **`unique_lock`** 写 ref 表的路径竞争时，写者可能被长时间阻塞。 |
| **`switchNodeMutex_`**（`std::mutex`） | 切换本地/远端 worker、`ipAddress_`、`currentNode_` 等 | `TrySwitchWorker`、`RediscoverLocalWorker`（二次临界区）、`ReconnectLocalWorkerAt` 等 | ⚠ `ReconnectLocalWorkerAt` 内含 **`ReconnectWorker`（RPC）**、**`PrepairForDecreaseShmRef` 等**，当前在 **`RediscoverLocalWorker` 末段仍持 `switchNodeMutex_`** 调用（避免与其它切换交错）。属**有意串行**，但属于「锁内 RPC」，对「锁内无 RPC」的严格口径仍不达标。 |
| **`perfMutex_`** | perf 线程与退出同步 | `perfThread_` 启停 | ✓ 一般无 RPC |

---

## 2. Mmap（`client/mmap_manager.cpp`）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`MmapManager::mutex_`** | `mmapTable_` 与待接收 fd 列表推导 | **`LookupUnitsAndMmapFds` 从进入函数到返回前整段持 `lock_guard`** | ⚠ 在同一把锁内顺序执行：**`clientWorker_->GetClientFd`（典型含 RPC + SCM/recvmsg 等 syscall）** 与 **`mmapTable_->MmapAndStoreFd`（mmap 等）**。这是阶段 2c「三段式：锁内收集 → 锁外 GetClientFd/mmap → 锁内回写」的**首要改造点**。 |
| 同上（读锁） | 只读查询 | `LookupMmappedFile` 使用 `shared_lock` | ✓ 仅表查询（注意内部是否打日志） |

---

## 3. 异构 Comm（`object_cache/device/comm_factory.cpp`）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`CommFactory::mutex_`** | `commTable_`（TBB accessor + 工厂逻辑） | `GetOrCreateComm`：**`shared_lock` 贯穿**查找/插入占位 | ⚠ 在**仍持有 `shared_lock`** 时调用 **`CreateCommInSend` / `CreateCommInRecv`**（内部再排队到 comm 线程，但**表项已在锁下创建**）；其它路径可能长时间占读锁。 |
| 同上 | 创建 HCCL root | **`CreateCommInRecv` / `ProcessCommCreationInSend` 内 `lock_guard`（写锁）** | ⚠ 写锁内 **`SendRootInfo` / `RecvRootInfo`（RPC）**、`InitCommunicator` / `WarmUpComm`（设备与驱动交互，**重 syscall**）。阶段 2g：应 **锁内仅登记/占位，锁外 RPC + 初始化，再短锁改状态**。 |
| 同上 | 遍历/删除 | `GetAllComm`、`DestroyComm`、`DelComm` | `DestroyComm` 在**共享锁**下 **`comm->ShutDown()`** — 若 ShutDown 触达驱动/RPC，标 ⚠（依 `CommWrapper` 实现而定）。 |

---

## 4. Worker 侧 API（`client_worker_remote_api.cpp` 等）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`ClientWorkerRemoteApi::mtx_`** | `decreaseRPCQ_`、`waitRespMap_`、队列槽位 | `DecreaseShmRef` 中与 `shutdownMtx` 组合使用 | ⚠ **`AddShmLockForClient`** 内 **`WaitForQueueFull` / `SharedLock`（futex 等）** 可能在 **`mtx_` 持有期间**执行；与 **`shutdownMux_` 传入的 `shared_lock` 叠加**时，其它需独占 `shutdownMux_` 的路径易被拖死。 |
| **`shutdownMux_`（传入引用）** | 与 ObjectClient 关闭协调 | `DecreaseShmRef` **整函数持 `shared_lock(shutdownMtx)`** | ⚠ **`CheckShmFutexResult`（FutexWait）** 在已释放 `mtx_` 后、**`shutdownLock` 仍持有**时执行 → **关闭互斥锁与 futex 睡眠同窗口**。 |
| 无额外 client 锁 | 纯 RPC | `DecreaseWorkerRef`、`GIncreaseWorkerRef`、各类 `stub_->` | ✓ 一般不持 ObjectClient 大锁（除非调用方已持锁）。 |

---

## 5. Worker 公共能力（`client_worker_common_api.cpp`）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`standbyWorkerMutex_`** | `standbyWorkerAddrs_` | `SaveStandbyWorker` / `GetStandbyWorkers` | ✓ 仅解析与容器更新；**`SendHeartbeat`（RPC）在锁外**，返回后再 `SaveStandbyWorker`。 |
| **`recvClientFdState_.mutex`** | fd 接收状态机 | 多段 `lock_guard` | 需与 **`GetClientFd`** 实现对照：若在锁内 **recvmsg/等待**，标 ⚠（建议单独审计该函数全路径）。 |

---

## 6. Listen worker（`listen_worker.cpp`）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`callbackMutex_` / `deletedCallbackMutex_`** | 回调表、延迟删除集合 | 注册/触发/清理回调 | ✓ 应只触达内存表；若回调体内有 RPC，属于**回调设计问题**（非锁本身）。 |
| **`switchWorkerHandleMutex_`** | `switchWorkerHandle_` 与切换相关标志 | 读锁检查句柄；异步任务内短临界区 | ◁ 已将 **`LOG(INFO)` 挪到锁外**；`switchWorkerHandle_()` 本身可能间接触发较重逻辑，需保证**实现体不阻塞过久**。 |

---

## 7. Router / 发现（`router_client.cpp`、`service_discovery.cpp`）

| 锁名 | 保护的数据 | 典型持锁范围 | 耗时 / 交互风险 |
|------|------------|--------------|-----------------|
| **`RouterClient::eventMutex_`** | `activeWorkerAddrs_`、`workerId2Addrs_` | `SelectWorker` / `GetWorkerAddrByWorkerId` 持 **`shared_lock`** 做查找 | ✓ **无 RPC**；有 **`LOG`、字符串处理**（阶段 3 可再外移日志）。etcd 回调里 **`HandleClusterEvent` / `HandleRingEvent` 持 `lock_guard` 并打 LOG**。 |
| **`ServiceDiscovery::workerHostPortMutext_`** | `activeWorkerInfo_` | **`ObtainWorkers`**：`etcdStore_->GetAll`（**gRPC**）在 **锁外**；**`lock_guard` 仅覆盖**解析结果写 `activeWorkerInfo_` | ✓ 就「持 `workerHostPortMutext_` 打 etcd」而言当前是干净的；**`SelectWorker` 仍会调用 `ObtainWorkers` → 锁外 etcd**，不属于该 mutex 临界区问题。 |

---

## 8. Stream cache（`stream_cache/*.cpp`）

| 锁名 | 保护的数据 | 备注 |
|------|------------|------|
| **`stream_client_impl::clearMutex_`** | producers/consumers 清理 | 清理路径需单独审计是否持锁调用下游 **RPC / Flush** |
| **`consumer_impl::idxMutex_`** | 消费索引 | 持锁区间若覆盖 **读流 RPC**，标 ⚠ |
| **`producer_impl::flushMutex_`** | flush 互斥 | 若 **flush 触发网络发送**，持锁 flush → ⚠ |
| **`client_base_impl::recvFdsMutex_`** | 收 fd 集合 | 与 **recvmsg** 关系需点查 |

---

## 9. ZMQ 栈（`common/rpc/zmq/zmq_stub_conn.cpp` 等）

| 锁名 | 保护的数据 | 备注 |
|------|------------|------|
| **`SockConnEntry::mux_`** | 连接项、fd 池与无效化协调 | 与 `outMux_` 锁序已文档化 |
| **`FdConn::outMux_`** | 出站消息队列 | ◁ **`SetPollOut`（epoll_ctl）已移出写锁** |
| **`IOService` / server 路径** | 出站队列 | ◁ **`Send` 内 `SetPollOut` 已移出 `outMux_`** |

---

## 10. 其它

| 锁名 | 位置 | 备注 |
|------|------|------|
| **`gKvExecutorMutex`** | `kv_cache/kv_executor.cpp` | 全局 executor 注册；临界区应极短 |
| **`ClientMemoryRefTable::mutex_`** | `client_memory_ref_table.cpp` | 本地 ref 表 |
| **各 `immap_table` / `shm_mmap_table` mutex** | `client/mmap/*.cpp` | 表级锁；避免在持锁下调用上层 **GetClientFd** |

---

## 11. 与三阶段 plan 的对应关系（剩余工作指针）

| 阶段 | 与本清单的对应 |
|------|----------------|
| **阶段 1** | ZMQ `outMux_` / `Provider::FlushLogs` ◁；**不在此清单重复** |
| **阶段 2** | **2b**：缩小 **`shutdownMux_` 共享锁**跨度（避免覆盖整段 RPC）；**2c**：**`MmapManager::mutex_`** 三段式；**2d**：**`globalRefMutex_`** 与 RPC 解耦；**2e**：`Rediscover` ◁；**2f**：**`DecreaseShmRef` + `mtx_` + futex**；**2g**：**`CommFactory::mutex_`** 与 **Send/RecvRootInfo** |
| **阶段 3** | **`RouterClient` / `HandleRingEvent` 锁内 LOG**、`ObjectClient` 热路径 **`LOG(INFO)`**、**MemoryCopy+线程池+大锁** 叠加、**TLS→显式 context** |

---

## 12. 验收用一句话

**若某把锁的临界区内出现 `stub_->` / `Heartbeat` / `SelectWorker(etcd)` / `mmap` / `recvmsg` / `epoll_ctl`（未外移）/ `FutexWait` / `condition_variable::wait`，则不符合「持锁无耗时、无 RPC、无跨线程长时间等待」的严格口径，应在上述阶段项中立项改掉。**
