# Client 锁范围治理 — 客户交流摘要

面向**非实现细节读者**：说明改了哪些锁、锁在保护什么、改完后临界区内是否仍包含易阻塞操作，以及**读写数据面**与**其它路径**的先后关系。实现细节与 Review 要点见同目录 `LOCK_SCOPE_CHANGES_REVIEW.md`。

---

## 1. 结论（可先读）

| 主题 | 结论 |
|------|------|
| 目标 | 在**不放宽数据一致性语义**的前提下，缩短 client 侧若干重锁的持有时间，降低并发下长尾与死锁风险。 |
| 阻塞类操作是否仍在锁内 | **mmap、与 worker 的全局引用 RPC、服务发现 SelectWorker、内核 epoll_ctl（写方向）** 等已从对应管理锁的临界区**移出**；锁内主要保留**表项更新、快照、二次校验、短回填**。 |
| 语义 | 成功路径与「锁内做完 RPC」等价；失败路径通过**回滚**与 **dec 后清理 0 引用**收紧短暂不一致窗口。 |

---

## 2. 按「读写数据面优先」梳理

### 2.1 读路径（对象数据 / 共享内存视图）

**典型含义**：从 worker 拉取对象或 SHM 描述后，client 要把 **worker 侧 fd** 转成进程内 **mmap 指针**，供后续读/写用户缓冲区。

**锁 `MmapManager::mutex_`（`shared_timed_mutex`）的目的**：保护 **mmap 表**（哪些 fd 已映射、指针缓存）与「分类/回填」逻辑的一致性。

**改完后保护范围**：

- **Phase 1（持锁）**：只扫描请求里的 `units`，区分「已在表中」与「待收 fd」，收集列表；**不**调用 `GetClientFd`、**不**执行 `mmap`。
- **Phase 2（不持 `mutex_`）**：`GetClientFd`（RPC/收 fd）+ `MmapAndStoreFd`（`mmap` 与表写入由 mmap 表实现自身约定保证并发安全）。
- **Phase 3（短持锁）**：对刚完成的单元从表取指针，写回 `unit->pointer`。

代码骨架：

```50:110:src/datasystem/client/mmap_manager.cpp
Status MmapManager::LookupUnitsAndMmapFds(const std::string &tenantId, std::vector<std::shared_ptr<ShmUnitInfo>> &units)
{
    // Phase 1: under manager mutex — classify units and collect worker fds to receive (no RPC/mmap here).
    {
        std::lock_guard<std::shared_timed_mutex> lck(mutex_);
        // ... build toRecvFds, mmapSizes, toRecvFdInUnitIdx ...
    }

    // Phase 2: lock-free w.r.t. manager mutex — RPC + mmap (table entries use their own internal locking).
    if (!toRecvFds.empty()) {
        if (!enableEmbeddedClient_) {
            RETURN_IF_NOT_OK(clientWorker_->GetClientFd(toRecvFds, clientFds, tenantId));
            for (size_t i = 0; i < clientFds.size(); i++) {
                RETURN_IF_NOT_OK(mmapTable_->MmapAndStoreFd(clientFds[i], toRecvFds[i], mmapSizes[i], tenantId));
            }
        } else {
            // embedded path ...
        }
    }

    // Phase 3: fill pointers for units that just completed mmap (short manager lock)
    {
        std::lock_guard<std::shared_timed_mutex> lck(mutex_);
        for (auto &idx : toRecvFdInUnitIdx) {
            // LookupFdPointer -> unit->pointer
        }
    }
    return Status::OK();
}
```

**从哪个接口「走进来」**（概念栈，便于和客户对齐）：

1. 业务侧：对象 **Get / 打开带 SHM 的 Buffer** 等（具体 API 因场景为 Object / Stream 等而异）。
2. 共享内存视图：`ClientBaseImpl::GetShmInfo` 在需要时调用 `mmapManager_->LookupUnitsAndMmapFd`（内部走 `LookupUnitsAndMmapFds`）。
3. 再往下：`GetClientFd` → worker 侧配合；ZMQ/其它 RPC 通道发送请求时，会走到下文 **§3.1** 的发送路径。

---

### 2.2 写路径（与「全局引用」相关的数据面）

**典型含义**：对象在 client 进程内的 **全局引用计数** 与 worker 侧一致；**Increase / Decrease** 会触发与 worker 的 RPC。

**锁 `globalRefMutex_` 的目的**：保护 **TBB `globalRefCount_`** 的插入、加减与遍历，避免并发破坏表结构或丢失更新。

**改完后保护范围**：

- **共享锁内**：只做本地表更新，并收集「从 0→1 需通知 worker」或「从 1→0 需通知 worker」的 id 列表。
- **锁外**：调用 `GIncreaseWorkerRef` / `GDecreaseWorkerRef`（内部为到 worker 的 RPC）。
- **独占锁（短）**：RPC 部分失败时 **回滚**本地计数；Decrease 后在引用已为 0 时 **擦除表项**，避免残留。

**Increase 示例**：

```2229:2262:src/datasystem/client/object_cache/object_client_impl.cpp
    {
        std::map<std::string, GlobalRefInfo> accessorTable;
        std::shared_lock<std::shared_timed_mutex> lck(globalRefMutex_);
        // ... update globalRefCount_, collect firstIncIds ...
    }

    RETURN_OK_IF_TRUE(firstIncIds.empty());

    auto rc = workerApi_[LOCAL_WORKER]->GIncreaseWorkerRef(firstIncIds, failedObjectKeys);
    if (!failedObjectKeys.empty()) {
        std::unique_lock<std::shared_timed_mutex> ulock(globalRefMutex_);
        GIncreaseRefRollback(failedObjectKeys, objWithTenantToDelta);
    }

    return objectKeys.size() > failedObjectKeys.size() ? Status::OK() : rc;
```

**Decrease 示例**（锁外 RPC + 锁内回滚/清理）：

```2343:2382:src/datasystem/client/object_cache/object_client_impl.cpp
    {
        std::shared_lock<std::shared_timed_mutex> lck(globalRefMutex_);
        // ... decrement globalRefCount_, collect finishDecIds ...
    }

    RETURN_OK_IF_TRUE(finishDecIds.empty());

    Status rc = workerApi_[LOCAL_WORKER]->GDecreaseWorkerRef(finishDecIds, failedObjectKeys);
    {
        std::unique_lock<std::shared_timed_mutex> ulock(globalRefMutex_);
        if (!failedObjectKeys.empty()) {
            GDecreaseRefRollback(failedObjectKeys, objWithTenantToDelta);
        }
        RemoveZeroGlobalRefAfterDecrease(finishDecIds);
    }

    return objectKeys.size() > failedObjectKeys.size() ? Status::OK() : rc;
```

**从哪个接口「走进来」**：

- 对外封装：`ObjectClient::GIncreaseRef` / `ObjectClient::GDecreaseRef` 转入 `ObjectClientImpl`（见 `object_client.cpp`）。
- 业务侧通常在 **Buffer / 对象生命周期**（打开、关闭、跨进程引用约定）中触发；KV/Object 等上层会间接依赖该语义。

---

## 3. 其它路径（放在读写之后）

### 3.1 RPC 发送：ZMQ 网关 `outMux_` 与 `epoll_ctl`

**锁的目的**：`outMux_` 保护 **每条连接上的出站消息队列** 的入队顺序与结构。

**改法**：**仅在 `outMux_` 下将消息入队**；`SetPollOut`（内部会触达 **`epoll_ctl` 等内核调用**）移到**锁外**，避免大量并发发送方长时间占着同一把锁。

```163:171:src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp
    // Enqueue under outMux_ only; SetPollOut -> epoll_ctl outside outMux_ ...
    {
        WriteLock lock(fdConn->outMux_.get());
        fdConn->outMsgQueue_->emplace_back(type, std::move(frames));
    }
    RETURN_IF_NOT_OK(fdConn->outPoller_->SetPollOut(fdConn->outHandle_));
```

**从哪个接口「走进来」**（概念栈）：

- Worker/Object 等 **stub 发送 RPC** → `ZmqFrontend::BackendToFrontend` 调度 → `RouteToUnixSocket` → 上段入队 + `SetPollOut`。
- 因此：**不仅是「对象专用接口」**，凡走该 ZMQ 前端发送路径的调用，都会受益。

### 3.2 切回本地 worker：`RediscoverLocalWorker`

**锁 `switchNodeMutex_` 的目的**：保护 **当前节点、worker 地址** 等切换相关状态。

**改法**：锁内只做 **快照**；**`SelectWorker`（服务发现，可能阻塞/耗时）在锁外**；再短暂加锁做 **双重检查**，通过后 `ReconnectLocalWorkerAt`（内部仍有重连与 RPC，不在本节展开）。

```656:701:src/datasystem/client/object_cache/object_client_impl.cpp
bool ObjectClientImpl::RediscoverLocalWorker()
{
    WorkerNode nodeSnapshot;
    HostPort ipSnapshot;
    {
        std::lock_guard<std::mutex> lock(switchNodeMutex_);
        if (currentNode_ == LOCAL_WORKER) {
            return false;
        }
        nodeSnapshot = currentNode_;
        ipSnapshot = ipAddress_;
    }

    Status rc = serviceDiscovery_->SelectWorker(workerIp, workerPort, &isSameNode);
    // ... same-node / address changed checks (abbreviated) ...

    {
        std::lock_guard<std::mutex> lock(switchNodeMutex_);
        // double-check vs concurrent switch ...
    }

    return ReconnectLocalWorkerAt(newAddress);
}
```

---

## 4. 与客户沟通时可用的「一句话地图」

1. **读 SHM / mmap**：`LookupUnitsAndMmapFds` — 锁短、**RPC+mmap 在锁外**。  
2. **全局引用**：`GIncreaseRef` / `GDecreaseRef` — **锁内只动本地表**，**worker RPC 在锁外**，失败 **回滚**，dec 后 **清 0**。  
3. **ZMQ 发送**：**队列入锁**、**epoll 注册出锁**。  
4. **切流发现**：**快照与校验在锁内**、**发现与网络在锁外**。

---

## 5. 验证与证据（内部可引用）

- ST：`ds_st_kv_cache` 中 `KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention`（并发 MCreate/MSet/MGet/Exist）。  
- 操作手册：`plans/lock_io_blocking_special_assessment/08_ebpf_bpftrace_operator_runbook.md`（含 bpftrace 与权限说明）。  
- 脚本：`scripts/perf/run_kv_lock_ebpf_workflow.sh`、`scripts/perf/analyze_kv_lock_bpftrace.py`。

---

## 6. 范围说明（避免过度承诺）

- 本批改动聚焦 **client 侧 mmap 管理锁、全局引用锁、ZMQ 出站锁、worker 重发现持锁方式**；**未**将 `CommFactory` 等其它持锁内 RPC 全部纳入同一 MR（若存在单独延期说明，以仓库内 `plans/client_lock_remediation_phases/` 文档为准）。
