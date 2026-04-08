# [RFC]：Client 侧锁范围收缩 — 持锁内避免 RPC / 重 syscall / 长时间跨线程等待

## 背景与目标描述

在 brpc / bthread 等 M:N 调度场景下，**互斥锁临界区若覆盖 RPC、mmap/recvmsg 等阻塞 syscall、或 futex/条件变量长时间等待**，会放大尾延迟、占用 worker 线程，并与 **ShutDown、写锁升级** 等路径叠加，形成阻塞链。

本 RFC 的目标是：

- **明确各锁保护的数据不变量**，将临界区收敛为 **短内存逻辑**（快照 / 校验 / 表项占位 / 少量回写）。
- **网络与重内核交互**（RPC、收 fd、mmap、设备初始化等）在 **解锁后**执行，再 **短锁提交状态**（与总 plan「快照 → 解锁 → RPC → 短锁回写」一致）。
- **不放宽正确性**：并发下表项、引用计数、关断序仍满足现有语义。
- **可验收**：有关键 ST / 门禁脚本与（可选）基线对比，避免回归。

仓库内另有**展开版**清单（可与本 RFC 同步维护）：`plans/client_lock_remediation_phases/LOCK_SCOPE_INVENTORY.md`。**提 issue 时以本节为准即可**，不依赖该文件是否存在。

### 锁域与风险对照（浓缩）

**图例**

| 标记 | 含义 |
|------|------|
| ✓ | 典型临界区以短内存逻辑为主（仍可能有 LOG，属阶段 3 优化） |
| ⚠ | 持锁期间仍可能含 RPC、重 syscall、futex/长等待等，需治理或已标为例外 |
| ◁ | 已局部缩短临界区（如 ZMQ `SetPollOut` 外移、`ShutDown` 锁外 `Disconnect`、Rediscover 锁外 `SelectWorker`） |

**按模块（锁名 → 保护什么 → 主要风险）**

| 区域 | 锁 | 保护数据 / 不变量 | 风险 |
|------|-----|-------------------|------|
| `object_client_impl` | `shutdownMux_` | 关断与正常 API 并发 | ⚠ 历史上整段 RPC、`mmapManager_->Lookup…` 与 `shared_lock` 同窗口；独占 `ShutDown` 需等全部共享锁释放。 |
| 同上 | `globalRefMutex_` | TBB `globalRefCount_` | ⚠ 若读锁贯穿整段 RPC，与要写 ref 的路径竞争；**2d 目标**：锁内只更新表，RPC 锁外。 |
| 同上 | `switchNodeMutex_` | worker 切换、`ipAddress_`、`currentNode_` | ⚠ `ReconnectLocalWorkerAt` 等可能含 RPC；**有意串行**时可与「锁内无 RPC」严格口径冲突，需显式说明或继续拆锁外串行。 |
| `mmap_manager` | `MmapManager::mutex_` | `mmapTable_` 与待收 fd 推导 | ⚠ 原可同锁串 `GetClientFd` 与 `mmap`；**2c 三段式**：锁内收集 → 锁外 GetClientFd+mmap → 短锁回写。 |
| `comm_factory` | `CommFactory::mutex_` | `commTable_`、创建/销毁 | ⚠ 读锁贯穿查找/占位；写锁或创建路径上 **Send/RecvRootInfo、Init/WarmUp** 等；**2g**：锁内占位，锁外 RPC+设备，短锁改状态。 |
| `client_worker_remote_api` | `mtx_` + 传入 `shutdownMux_` | `DecreaseShmRef` 队列与关闭协调 | ⚠ `mtx_` 下等待 + `shutdownMux_` 上 `FutexWait` 叠加窗口；**2f** 收紧顺序或移出等待。 |
| `worker_common_api` | `recvClientFdState_.mutex` 等 | fd 收包状态机 | 需与 `GetClientFd` 全路径对照；锁内 recvmsg → ⚠。 |
| `listen_worker` | `switchWorkerHandleMutex_` 等 | 切换句柄 | ◁ 部分 LOG 已外移；回调体仍须避免长阻塞。 |
| `router` / `discovery` | `eventMutex_`、`workerHostPortMutext_` 等 | 路由表、worker 列表 | ✓ `SelectWorker` 侧无 RPC；`ObtainWorkers` 中 etcd 在**锁外**写回结果。 |
| `stream_cache` | `flushMutex_`、`recvFdsMutex_` 等 | flush/收 fd | 持锁 flush 或跨 RPC → ⚠，需单独审计。 |
| `zmq_stub_conn` | `mux_` / `outMux_` | 连接池、出站队列 | ◁ **`SetPollOut`（epoll_ctl）已移出 `outMux_`**。 |
| 其它 | `gKvExecutorMutex`、`ClientMemoryRefTable::mutex_`、各 mmap 表锁 | 注册表、本地 ref、表级一致性 | 临界区应极短；表锁内**禁止**再调上层 `GetClientFd`。 |

**验收一句话（严格口径）**  
若某把锁的临界区内出现 `stub_->` / `mmap` / `recvmsg` / `epoll_ctl`（未外移）/ `FutexWait` / `condition_variable::wait` 等，则不符合「持锁只做短逻辑」；应在对应阶段项（见下「分阶段」与清单 §11）立项改掉。

**与分阶段 plan 的对应（剩余工作指针）**

| 阶段 | 要点 |
|------|------|
| 阶段 1 | ZMQ `outMux_` 等已部分 ◁；Provider 日志等见阶段 3。 |
| 阶段 2 | **2b** `shutdownMux_`；**2c** `MmapManager`；**2d** `globalRefMutex_`；**2e** Rediscover；**2f** `DecreaseShmRef`+futex；**2g** `CommFactory`。 |
| 阶段 3 | 锁内 LOG、MemoryCopy+线程池、TLS→显式 context 等。 |

## 建议的方案（分阶段，可拆 MR）

1. **Object client 宽锁（`shutdownMux_`）**  
   - 将 **`shared_lock` 生命周期**与 **`workerApi_` RPC、`mmapManager_` 查找+mmap** 解耦：仅保留关断序所需的 **短临界区**（如必要快照、标志位），RPC/mmap 在锁外。

2. **全局引用与 RPC（`globalRefMutex_`）**  
   - `GIncreaseRef` / `GDecreaseRef`：**读锁内**完成 ref 表更新后 **尽早释放**，再调用 `GIncreaseWorkerRef` / `GDecreaseWorkerRef`（RPC）；避免 **读锁横跨整段 RPC**。

3. **MmapManager（`mutex_`）— 三段式**  
   - `LookupUnitsAndMmapFds`：**锁内**收集 key/元数据 → **锁外** `GetClientFd` + `MmapAndStoreFd` → **锁内**回写表。消除 **单把锁贯穿 RPC+mmap**。

4. **CommFactory（`mutex_`）**  
   - **锁内**仅登记/占位；**锁外** `SendRootInfo` / `RecvRootInfo` 与 HCCL 初始化/预热；**短锁**更新 comm 状态。评估 `DestroyComm` 等路径是否在共享锁下触发重 ShutDown。

5. **DecreaseShmRef（`mtx_` + 传入 `shutdownMux_`）**  
   - 避免 **futex/队列等待** 与 **`shutdownMux_` 共享锁**长时间重叠；将 **FutexWait** 移出关闭大锁窗口或收紧持锁顺序（见 `phase_02` 2f）。

6. **切换路径（`switchNodeMutex_`）**  
   - 已部分落地（如 `SelectWorker` 锁外）；若需 **锁内 `ReconnectLocalWorkerAt`（RPC）** 做串行化，在文档中 **显式标注例外** 或继续评估 **锁外串行令牌** 等替代方案。

7. **阶段 3（非本 RFC 主体，可并行）**  
   - 业务锁附近的 **LOG**、MemoryCopy、TLS/context 优化见 `phase_03_logs_memory_tls.md`。

## 涉及到的对外 API

### 变更项

- **默认无**：以内部实现与持锁范围调整为主；若未来为观测性增加可选回调/统计，另开 RFC。

### 不变项

- **对外 C++ API 签名与语义**保持不变（Object / Stream / KV 等客户可见接口不因「仅缩锁」而变更行为契约）。

### 周边影响

- **ShutDown / 切换 / mmap / 异构 comm** 等路径的时序与竞态需逐条用例覆盖；性能上期望 **P99 尾延迟与 bthread 占用**改善，须用 **绝对时延或基线脚本**说明（见验收清单）。

## 测试验证

1. **功能与回归**  
   - 相关 ST（Object / client / mmap / comm 等按改动触及模块选择）。  
   - KV + brpc 门禁（若适用）：`bash scripts/verify/validate_brpc_kv_executor.sh` 或等价 `ctest -R KVClientBrpcBthreadReferenceTest`（见 `README.md` 与 `brpc_bthread_reference_test_guide.md`）。

2. **基线（可选但推荐）**  
   - `scripts/perf/collect_client_lock_baseline.sh`、`scripts/perf/compare_client_lock_baseline.sh`。

3. **人工核对**  
   - 合入前对照本 RFC「锁域与风险对照（浓缩）」与（若仓库内存在）`LOCK_SCOPE_INVENTORY.md` 展开版，更新 ✓ / ⚠ / ◁ 状态，避免「改了一处、清单仍写旧状态」。

## 期望的反馈时间

- 建议反馈周期：**7 天**。  
- 重点收集：各锁 **最小不变量**是否认可、**串行化例外**（如 `switchNodeMutex_` 内 RPC）是否接受、**验收门槛**（必须跑哪些测试 / 是否强制基线）。
