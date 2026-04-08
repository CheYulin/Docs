# 阶段 2：业务宽锁 — Object client、mmap、ref、切换、DecreaseShmRef、CommFactory

## 目标

- 消除或缩短 **`shutdownMux_`、`globalRefMutex_`、`switchNodeMutex_`** 以及 **`MmapManager::mutex_`** 内的 RPC / 阻塞等待。
- 降低 bthread 场景下 **假死与尾延迟**。

## 工作事项（建议按子 MR 拆分）

| 子项 | 位置 / 要点 |
|------|----------------|
| 2a ShutDown | `object_client_impl.cpp`：`shutdownMux_` 内快照 `workerApi_`，**锁外** `Disconnect`。**已落地**。 |
| 2b shutdownMux_ shared 全路径 | `Create`/`Put`/`Seal`/`Publish`/`MultiCreate`/`MultiPublish`/`Set(buffer)`/`GIncreaseRef` 等：缩短持锁跨度或「状态检查锁内、RPC 锁外」。 |
| 2c MmapManager | `mmap_manager.cpp`：三段式 — 锁内收集 fd → 锁外 `GetClientFd`+`MmapAndStoreFd` → 锁内回写表。 |
| 2d globalRef | `GIncreaseRef`/`GDecreaseRef`：锁内维护本地表与快照，**锁外** `GIncreaseWorkerRef`/`GDecreaseWorkerRef`，失败 **短锁回滚**。 |
| 2e Rediscover | `RediscoverLocalWorker`：`SelectWorker` **锁外**，锁内二次校验 `currentNode_`/`ipAddress_` 再 `ReconnectLocalWorkerAt`。**已落地**。 |
| 2f DecreaseShmRef | `client_worker_remote_api.cpp`：拆分 `shutdownMtx`/`mtx_` 与队列等待、减少锁内长路径。 |
| 2g CommFactory（暂缓） | 异构路径当前客户未用，**代码不改**；实现草案见 [comm_factory_lock_rpc_remediation_deferred.md](./comm_factory_lock_rpc_remediation_deferred.md)。 |

每个子 MR 完成后：**跑 KV 门禁 + collect 对比**，避免一次性大 diff 难以定位回归。

## 依赖

- 阶段 0 基线；阶段 1 若已合入，对比对象可为「阶段 1 后 run」。
- 设计原则：总 plan §3「快照 + 解锁 + RPC + 短锁回写」。

## 风险

- 解锁窗口内状态漂移：需版本戳或二次检查，避免重复 RPC 或错误 ref 计数。
- 并发 shutdown 与在途请求：需与 `clientStateManager_` 状态机一致。

## 本阶段验收

| 类型 | 标准 |
|------|------|
| 正确性 | Object/KV 相关 st 测试 + 手工关注的 shutdown/ref/mmap 场景无回归；**KV brpc 参考用例通过**。 |
| 性能 | 针对所改子项，**绝对 µs** 或你们定义的 **p95/p99** 较对应基线 **有下降**（同拓扑）；不能只报 QPS 比例而无绝对值。 |
| KV | **`validate_brpc_kv_executor.sh` 或等价 ctest 全绿**（硬性）。 |
