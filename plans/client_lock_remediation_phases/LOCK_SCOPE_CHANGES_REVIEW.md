# Client 锁范围改动 — 同事 Review 摘要

本文说明 **当前锁范围治理** 在 client 侧的主要代码改动、影响面与风险点，便于 Code Review。验收步骤见：

- `/home/t14s/workspace/git-repos/yuanrong-datasystem/plans/client_lock_remediation_phases/MANUAL_ACCEPTANCE_BEFORE_AFTER.md`
- `/home/t14s/workspace/git-repos/yuanrong-datasystem/plans/client_lock_remediation_phases/ACCEPTANCE_CHECKLIST.md`

---

## 1. 目标（一句话）

在 **不放宽数据一致性语义** 的前提下，缩短 **持 `globalRefMutex_` / `MmapManager::mutex_` 等重锁** 期间的路径，避免在锁内执行 **RPC、阻塞 I/O、mmap** 等易触发长尾延迟或 bthread/线程调度问题的操作。

---

## 2. 涉及文件（主干）

| 路径 | 角色 |
|------|------|
| `src/datasystem/client/mmap_manager.cpp` | `LookupUnitsAndMmapFds` 三段式：分类 → 锁外 RPC+mmap → 回填指针 |
| `src/datasystem/client/object_cache/object_client_impl.cpp` | `GIncreaseRef` / `GDecreaseRef` 锁外 worker RPC；失败回滚；dec 后清理 0 引用条目 |
| `src/datasystem/client/object_cache/object_client_impl.h` | 回滚 / 辅助函数声明（如 `RemoveZeroGlobalRefAfterDecrease` 等） |
| `tests/st/client/kv_cache/kv_client_executor_runtime_e2e_test.cpp` | 并发批量 perf 用例（MCreate/MSet/MGet/Exist） |
| `tests/ut/client/mmap_manager_test.cpp` | mmap 路径 UT（stub `GetClientFd` 等） |

**明确未纳入本 MR 的项**：异构 `CommFactory` 持锁内 RPC 等已 **暂缓**，见 `plans/client_lock_remediation_phases/comm_factory_lock_rpc_remediation_deferred.md`（若存在）。

---

## 3. 代码怎么改的（逻辑 + 短代码）

### 3.1 `MmapManager::LookupUnitsAndMmapFds` — 三段式

**改法**：  
- **Phase 1**（持 `mutex_`）：只扫 `units`，区分「已在 mmap 表」与「待收 fd」，收集 `toRecvFds` / `mmapSizes` / `toRecvFdInUnitIdx`。**不做** `GetClientFd`、**不做** `mmap`。  
- **Phase 2**（**不持** `mutex_`）：`GetClientFd` + `mmapTable_->MmapAndStoreFd`（依赖 mmap 表内部自身的并发安全）。  
- **Phase 3**（再持 `mutex_`）：对刚 mmap 的 unit 从表取指针写回 `unit->pointer`。

```50:112:src/datasystem/client/mmap_manager.cpp
Status MmapManager::LookupUnitsAndMmapFds(const std::string &tenantId, std::vector<std::shared_ptr<ShmUnitInfo>> &units)
{
    // ...
    // Phase 1: under manager mutex — classify units and collect worker fds to receive (no RPC/mmap here).
    {
        std::lock_guard<std::shared_timed_mutex> lck(mutex_);
        // ... build toRecvFds, mmapSizes, toRecvFdInUnitIdx ...
    }

    // Phase 2: lock-free w.r.t. manager mutex — RPC + mmap
    if (!toRecvFds.empty()) {
        if (!enableEmbeddedClient_) {
            RETURN_IF_NOT_OK(clientWorker_->GetClientFd(toRecvFds, clientFds, tenantId));
            for (size_t i = 0; i < clientFds.size(); i++) {
                RETURN_IF_NOT_OK(mmapTable_->MmapAndStoreFd(clientFds[i], toRecvFds[i], mmapSizes[i], tenantId));
            }
        } else {
            // embedded: MmapAndStoreFd without real client fd
        }
    }

    // Phase 3: fill pointers (short manager lock)
    {
        std::lock_guard<std::shared_timed_mutex> lck(mutex_);
        for (auto &idx : toRecvFdInUnitIdx) {
            // LookupFdPointer -> unit->pointer
        }
    }
    return Status::OK();
}
```

**影响**：MCreate / Get 等走 mmap 的链路中，**持 `MmapManager::mutex_` 的时间显著缩短**；长尾更多落在 Phase 2，与其它线程争用 manager 锁的概率下降。

---

### 3.2 `GIncreaseRef` — 先改表，再 RPC；失败回滚

**改法**：  
- 在 **`globalRefMutex_` 共享锁**下完成 TBB `globalRefCount_` 的更新，并收集「从 0→1」的 `firstIncIds`。  
- **释放锁后**调用 `GIncreaseWorkerRef(firstIncIds, ...)`。  
- 若 RPC 返回部分失败：再取 **`unique_lock`**，按 **`objWithTenantToDelta`** 做 `GIncreaseRefRollback`。

```2226:2262:src/datasystem/client/object_cache/object_client_impl.cpp
    {
        std::shared_lock<std::shared_timed_mutex> lck(globalRefMutex_);
        // ... update globalRefCount_, fill firstIncIds, objWithTenantToDelta ...
    }

    RETURN_OK_IF_TRUE(firstIncIds.empty());

    auto rc = workerApi_[LOCAL_WORKER]->GIncreaseWorkerRef(firstIncIds, failedObjectKeys);
    if (!failedObjectKeys.empty()) {
        std::unique_lock<std::shared_timed_mutex> ulock(globalRefMutex_);
        GIncreaseRefRollback(failedObjectKeys, objWithTenantToDelta);
    }

    return objectKeys.size() > failedObjectKeys.size() ? Status::OK() : rc;
```

**影响**：worker 侧全局引用与 client 侧表可能出现 **短暂不一致窗口**（client 已加表、RPC 尚未成功），由失败回滚收紧；成功路径语义与「锁内 RPC」一致。

---

### 3.3 `GDecreaseRef` — 先改表，再 RPC；失败回滚；成功后清理 0 引用

**改法**：  
- 共享锁内更新 `globalRefCount_`，收集「可能从 1→0」的 `finishDecIds`。  
- 锁外 `GDecreaseWorkerRef(finishDecIds, ...)`。  
- 再 **`unique_lock`**：若 RPC 失败则 `GDecreaseRefRollback`；无论成功与否调用 `RemoveZeroGlobalRefAfterDecrease(finishDecIds)`，避免 client 表残留 `<=0` 条目。

```2340:2382:src/datasystem/client/object_cache/object_client_impl.cpp
    {
        std::shared_lock<std::shared_timed_mutex> lck(globalRefMutex_);
        // ... decrement globalRefCount_, fill finishDecIds, objWithTenantToDelta ...
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

```2415:2427:src/datasystem/client/object_cache/object_client_impl.cpp
void ObjectClientImpl::RemoveZeroGlobalRefAfterDecrease(const std::vector<std::string> &checkIds)
{
    for (const auto &objectKey : checkIds) {
        auto objWithTenant = ConstructObjKeyWithTenantId(objectKey);
        TbbGlobalRefTable::accessor accessor;
        if (!globalRefCount_.find(accessor, objWithTenant)) {
            LOG(WARNING) << "Unknown object key " << objWithTenant;
            continue;
        }
        if (accessor->second <= 0) {
            (void)globalRefCount_.erase(accessor);
        }
    }
}
```

---

### 3.4 `RediscoverLocalWorker` — 锁内快照，锁外 `SelectWorker` / 重连

**改法**：在 `switchNodeMutex_` 下只拷贝 `currentNode_` / `ipAddress_`；**锁外** `serviceDiscovery_->SelectWorker`；再短暂加锁做 **二次校验**（避免与并发 switch 打架），最后 `ReconnectLocalWorkerAt`。

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
    // ... same-node / address changed checks ...

    {
        std::lock_guard<std::mutex> lock(switchNodeMutex_);
        if (currentNode_ == LOCAL_WORKER) return false;
        if (newAddress == ipAddress_) return false;
        if (currentNode_ != nodeSnapshot || ipAddress_ != ipSnapshot) {
            return false;
        }
    }

    return ReconnectLocalWorkerAt(newAddress);
}
```

**影响**：降低 discovery / 网络调用与 **切流互斥锁** 的耦合；依赖 **双重检查** 保证与 `TrySwitchWorker` 等路径不互相踩。

---

## 4. 风险与 Review 关注点

| 风险 | 说明 | 建议 Review 动作 |
|------|------|------------------|
| **client / worker 引用短暂不一致** | `GIncreaseRef`/`GDecreaseRef` 在 RPC 前后存在窗口 | 确认 **Rollback** 与 `objWithTenantToDelta` 覆盖所有失败 key；确认 **partial success** 返回值与旧行为一致 |
| **并发下 TBB 与锁顺序** | 回滚路径 `unique_lock` + TBB accessor | 搜其它持 `globalRefMutex_` 的路径，确认 **无死锁顺序反转** |
| **Dec 后表项清理** | `RemoveZeroGlobalRefAfterDecrease` 仅在 `finishDecIds` 非空且走完 RPC 后执行 | 确认「RPC 成功但 worker 已释放、client 已为 0」时不会长期残留错误条目（与日志 WARNING 一起看） |
| **MmapManager 与 mmapTable** | Phase 2 无 manager 锁 | 确认 `ShmMmapTable`/`EmbeddedMmapTable` 对 `MmapAndStoreFd` / `FindFd` 的并发约定未被破坏 |
| **Rediscover 竞态** | 双重检查仍可能存在极端丢重连 | 关注 `currentNode_`/`ipAddress_` 变更频率；必要时加指标或日志采样 |

---

## 5. 测试与回归建议（给 Reviewer 勾选）

- UT：`tests/ut/client/mmap_manager_test.cpp`  
- ST：`build/tests/st/ds_st_kv_cache` 全量；其中 `KVClientExecutorRuntimeE2ETest` + `PerfConcurrentMCreateMSetMGetExistUnderContention` 与锁/mmap/ref 路径相关  
- 性能/基线：`scripts/perf/collect_client_lock_baseline.sh`、`scripts/perf/run_kv_concurrent_lock_perf.sh`（见验收文档）

---

## 6. 小结

- **mmap**：RPC + mmap **移出** `MmapManager::mutex_` 临界区，manager 锁只做元数据与指针回填。  
- **全局引用**：**锁内**只维护 `globalRefCount_`；**锁外**调 worker；**失败回滚** + dec 后 **清理 0 引用**。  
- **本机 worker 重发现**：**锁外** discovery，**锁内**仅快照与校验，降低持锁时间。

若 Review 中对某条路径的 **锁顺序** 或 **rollback 完整性** 有疑问，建议在 MR 里 @ 熟悉 ref 与 switch 的同学重点看 `GIncreaseRef` / `GDecreaseRef` / `RediscoverLocalWorker` 三段。
