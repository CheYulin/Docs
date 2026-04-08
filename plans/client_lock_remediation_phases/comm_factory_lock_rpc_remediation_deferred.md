# CommFactory：锁内 RPC 整改 — 暂缓落地，仅设计备案

## 状态

- **代码**：维持现状，**不**在本阶段合入「锁外 RPC」重构。
- **原因**：当前客户侧**暂不调用**异构 HCCL / P2P comm 创建主路径；优先保证无回归面。
- **清单位置**：`LOCK_SCOPE_INVENTORY.md` 附录 Case G / `phase_02` 子项 **2g** 仍标为待办或「可选」。

## 问题简述（与 kv_lock 报告一致）

文件：`src/datasystem/client/object_cache/device/comm_factory.cpp`

- **`CreateCommInRecv` 内层 `process` lambda**：在持有 `mutex_`（`std::lock_guard<std::shared_timed_mutex>`）期间依次执行  
  `CreateRootInfo` → **`SendRootInfo`（RPC）** → `InitCommunicator` → `WarmUpComm`（设备侧重交互）。
- **`ProcessCommCreationInSend`**：同样在 **`mutex_` 写锁**下执行 **`RecvRootInfo`（RPC）** → `InitCommunicator` → `WarmUpComm`。
- **`GetOrCreateComm`**：在 **`shared_lock(mutex_)`** 下插入 TBB 表项并触发上述异步流程入队；真正 RPC 多在 comm 线程执行，但 **Recv/Send 两条 process 路径仍曾设计为整段持工厂写锁**（与 `K_CLIENT_DEADLOCK` 重试注释同源）。

目标口径与其它 client 锁治理一致：**工厂表锁内只做元数据占位/快照；网络 RPC 与长时间初始化在锁外；必要时短锁回写 `comm` 状态。**

## 建议实现草案（未来 MR 按此拆步）

### 1. `CreateCommInRecv` 内 `process` lambda

1. **短锁 `mutex_`（写锁）**  
   - 仅校验 `comm` 与表项一致性（若需要）、读取 `clientId_` 等只读字段可放到锁外若已线程安全。  
   - 或：**零锁**调用 `comm->CreateRootInfo(rootInfo)`（若仅触达 `comm` 自身状态，且不遍历 `commTable_`）。

2. **锁外**  
   - 组装 `SendRootInfoReqPb`，调用 `clientWorkerApi_->SendRootInfo(req, rsp)`。  
   - 处理 `K_CLIENT_DEADLOCK`：保持与 `AsyncRetryWithTimeout` 的协作语义（可仍为「返回可重试错误 → 释放锁已由实现保证」）。

3. **锁外**  
   - `InitCommunicator`、`WarmUpComm`。

4. **若需更新工厂表或 comm 在表中的可见状态**  
   - **短锁**内仅写标志位 / `SetDetailStatus`，避免持锁跨越 RPC。

> 注意：`process` 跑在 comm 异步线程上，重构后需明确 **`mutex_` 与 `comm->Execute` 队列** 的锁序，避免与 `GetOrCreateComm` 的 `shared_lock` 死锁。

### 2. `ProcessCommCreationInSend`

1. **锁外**  
   - 组装 `RecvRootInfoReqPb`，`RecvRootInfo`（RPC）。  
   - `memcpy_s` 填充 `CommRootInfo`、校验长度与 `is_dead_lock()`。

2. **锁外**  
   - `InitCommunicator`、`WarmUpComm`。

3. **短锁**  
   - 仅当必须把结果写回与 `commTable_` 相关的字段时持有。

### 3. `GetOrCreateComm`（可选收紧）

- 保持 **`shared_lock` 仅覆盖** `find` / `insert` 占位与 `acc->second = comm` 赋值。  
- **不要**在持 `shared_lock` 时调用会阻塞的 `CreateCommInSend/InRecv` 同步体；当前实现为 `Execute` 入队则已满足「持锁时间短」，后续若改同步路径需再审计。

### 4. `DestroyComm` / `ShutDown`

- 单独审计：`shared_lock` 下 `comm->ShutDown()` 是否可能 RPC/驱动长等待；若会，改为快照 `shared_ptr` 后**解锁**再 `ShutDown()`，再短锁删表（与 Object client 模式一致）。

## 风险与验收（未来合入时）

- **正确性**：双端创建序、rootInfo 字节序、`K_CLIENT_DEADLOCK` 重试与表项生命周期。  
- **死锁**：`mutex_` 与 comm 内部锁、`GetOrCreateComm` 读锁与写锁升级场景。  
- **测试**：异构/P2P 相关 ST 或专用集成环境；无客户调用前可仅保留本设计与静态审查。

## 关联文档

- `plans/lock_scope_analysis/kv_lock_in_syscall_cases_report.md` 附录 A.1 Case G  
- `phase_02_object_client_wide_locks.md` 子项 **2g**  
- `LOCK_SCOPE_INVENTORY.md` §3 `CommFactory::mutex_`
