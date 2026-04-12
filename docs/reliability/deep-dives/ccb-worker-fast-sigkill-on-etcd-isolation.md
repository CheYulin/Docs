---
name: CCB：Worker 被动缩容快速自杀行为评审
overview: >
  评审 worker 在检测到 etcd hash ring 中自身被写入 del_node_info / 被移出 ring 后
  立即 raise(SIGKILL) 的行为是否合理；包含当前机制的代码证据、存在的问题、风险矩阵与可选改造方向。
---

# CCB：Worker 被动缩容快速自杀行为评审

## 1. 背景与触发路径（代码证据）

### 1.1 触发条件

当 Worker B 认定 Worker A 已故障（lease 到期 → TIMEOUT → FAILED，共 `node_dead_timeout_s - node_timeout_s` 秒），B 会向 etcd ring 写入 `del_node_info[A]`。

A 自身的 etcd watch 线程收到 ring 更新事件后，在 **同一个 EtcdUtil 线程循环迭代**内完成以下两步：

**第一步**：`UpdateRing` → `UpdateLocalState` → `ChangeStateTo(FAIL)`
```cpp
// hash_ring.cpp:1180
if (ContainsKey(ringInfo_.del_node_info(), workerAddr_)) {
    ChangeStateTo(FAIL, "There is a running scale down task on this node.");
    return;
}
```

**第二步**（同一迭代，无 sleep）：`RemoveWorkers` 检查 `state_ == FAIL` → `raise(SIGKILL)`
```cpp
// hash_ring.cpp:1435
if (state_ == FAIL || (voluntaryScaleDownDone_ && !allWorkersVoluntaryScaleDown_)) {
    rc = RemoveWorker(workerAddr_, workers);  // → NeedToTryRemoveWorker → raise(SIGKILL)
}
```

```cpp
// hash_ring.cpp:1404
(void)raise(SIGKILL);   // 被动缩容路径，注释明确说是故意的
```

**FAIL 是终态，不可逆：**
```cpp
// hash_ring.cpp:1141
if (state_ == FAIL) {
    LOG(ERROR) << "Skip convert hash ring local state from FAIL to X because FAIL state is the terminate state.";
    return false;
}
```

前提条件：`EnableAutoDelDeadNode()` = `enableDistributedMaster_ && FLAGS_auto_del_dead_node`

---

### 1.2 时间轴（以当前测试配置 node_timeout=2s, node_dead_timeout=3s 为例）

```
t=0        A 续约失败，keepAliveTimeoutTimer 开始

t=0~1.8s   静默期（< GetLeaseExpiredMs = 1.8s），仅置 keepAliveTimeout_=true

t=1.8s     开始向 peer 询问 etcd 可用性，每次 sleep(5s)

t=1.8s     etcd lease TTL(2s) 到期 → B 收到 A 的 etcd DELETE 事件
           → B: A.SetTimedOut()（路由隔离立即生效，CheckConnection 返回 K_MASTER_TIMEOUT）

t=2.8s     B: DemoteTimedOutNode: (3-2)=1s 后 A.SetFailed()
           → B: HandleFailedNode → StartClearWorkerMeta
           → B: GetFailedWorkers 包含 A
           → B: HashRing::RemoveWorkers({A}) → CAS 写 del_node_info[A] 到 etcd

           【临界点到达：A 被动缩容开始】

t≈2.8s+ε  A 的 watch 线程收到 ring 更新 → UpdateLocalState → state_=FAIL
           同一循环：RemoveWorkers → raise(SIGKILL)

t≈6.8s     A 的 keep-alive 路径：第 2 轮 peer 确认 etcd OK
           keepAliveTimer ≈ 6.8s > node_dead_timeout_s(3s) → 也会 raise(SIGKILL)
           （通常 ring 路径更快到达）

重启后：   B 看到 A 的"restart" PUT → IfNeedTriggerReconciliation
           → ClearWorkerMeta + NodeRestartEvent（重新初始化内存/路由）
```

默认配置（node_timeout=60s, node_dead_timeout=300s）下同样路径，时间放大为：
- B 隔离 A（TIMEOUT）：**0s**（etcd DELETE 到达即刻）
- B 将 A 判死（FAILED）：**240s** 后
- A 自杀窗口：**~300s**（via keepAliveTimer 路径）或 **~315s**（via deathTimer 兜底）

---

## 2. 当前行为引发的两个核心问题

### 问题 1：内存缓存数据丢失

A 被 SIGKILL 时，其内存中的缓存数据（元数据路由 cache、内存 KV 数据）**无条件丢失**，没有任何 graceful flush 机会。

B 端的数据恢复（`RecoverMetaAndDataOfFaultWorker`）是**异步**启动的：
```cpp
// hash_ring_task_executor.cpp:407
scaleThreadPool_->Execute([this, currRing, traceId]() {
    ClearDataWithoutMeta(currRing, ranges);
    RecoverMetaAndDataOfFaultWorker(currRing, removeNode, allSubstitueUuidList);
    // ... CAS 写 etcd 移除 del_node_info（异步完成）
});
```

**时序竞争**：B 写 `del_node_info` 后，A 几乎立刻被杀（同一 EtcdUtil 循环迭代内），而 B 的数据恢复是异步线程池任务。A 被杀时 B 的恢复大概率尚未完成。

系统的设计假设是：**元数据已持久化到 etcd/rocksdb**，可从持久层重建。这对"所有未持久化的内存 cache"是一个风险敞口。

### 问题 2：重启后需要全量重新初始化

A 重启后必须走完整的 Reconciliation 流程：
1. 写 `"timestamp;restart"` 到 etcd cluster table
2. B 看到 ADD 事件（restart 状态）→ `IfNeedTriggerReconciliation` → `ClearWorkerMeta(A)` + `NodeRestartEvent`
3. A 重新 `InitKeepAlive` → `InitRing`（InitRing 遇到 `del_node_info[A]` 仍存在时，还会 sleep(1s) 轮询等待缩容完成）

```cpp
// hash_ring.cpp:239
if (oldRing.del_node_info().find(workerAddr_) != oldRing.del_node_info().end()) {
    LOG(INFO) << "The scale down of this node is being executed, retry...";
    sleep(1s); return K_TRY_AGAIN;  // 阻塞重启入环
}
```

重建成本包括：重新加载所有 hash range 的元数据路由、client 重连、副本同步等。

---

## 3. 风险矩阵

| # | 风险场景 | 严重度 | 概率（当前配置） | 是否有兜底 |
|---|---------|--------|----------------|-----------|
| R1 | A 短暂网络抖动（< node_dead_timeout_s），B 已写 del_node_info，A 网络恢复后仍被杀 | 高（缓存丢失 + 重启开销） | **高**（node_dead_timeout=3s 窗口极小） | 有：`passive_scale_down_ring_recheck_delay_ms`（默认关） |
| R2 | etcd 自身短暂不可达（非 A 故障），B 误判 A 死亡并写 del_node_info | 高（误杀正常节点） | 中（依赖 peer 探测机制，需 ≥3 次确认） | 有：3 次确认机制（networkFailedConfirmMinTimes=3） |
| R3 | A 被杀时 B 的数据恢复尚未完成，del_node_info 仍在 etcd，A 重启入环阻塞 | 中（重启慢） | **高**（异步竞争） | 有：`InitRing` 的 sleep+retry，等待 del_node_info 清除 |
| R4 | A 被杀时，A 的内存中有未持久化的"脏"元数据 | 高（数据一致性） | 依赖持久化策略 | 无（依赖系统假设：所有元数据持久化到 etcd） |
| R5 | B 误写 del_node_info 后自身也故障，del_node_info 长期悬挂，阻塞 A 重新入环 | 中（可用性长时中断） | 低 | 有：`HashRingHealthCheck` 周期性巡检修复 |
| R6 | `passive_scale_down_ring_recheck_delay_ms=0`（默认），无任何二次确认直接杀进程 | 中（误杀概率不可控） | 当前默认配置下存在 | 有：该 flag 非零时会 re-read etcd 环并可撤销 |

---

## 4. 当前缓解手段（已在仓库落地）

| 机制 | 代码位置 | 作用 | 当前默认值 |
|------|---------|------|-----------|
| `networkFailedConfirmMinTimes=3` | `etcd_store.cpp:568` | keep-alive 失败路径需 ≥3 次 peer 确认 etcd OK 才注入 fake DELETE | 硬编码 3 |
| `deathTimer` 兜底 | `etcd_store.cpp:611` | 防止 SIGKILL 机制本身失败，`(node_dead - node_timeout + 10)s` 后强杀 | 随 flag 计算 |
| `passive_scale_down_ring_recheck_delay_ms` | `common_gflag_define.cpp` | 自杀前 sleep N ms，再读一次 etcd 环，若环上自己是 ACTIVE 且不在 del_node_info 则**放弃自杀** | **0（关闭）** |
| `worker_incarnation` 字段 | `hash_ring.proto` | 区分同地址重入环是新实例还是旧进程 | 已有字段，未全链路使用 |
| `HashRingHealthCheck` 周期巡检 | `hash_ring_health_check.cpp` | 检测环一致性、CAS 修复悬挂状态 | 开启 |
| InitRing 等待 del_node_info 清除 | `hash_ring.cpp:239` | 重启进程发现自己在 del_node_info 里，sleep 轮询等待 | 1s 间隔 |

---

## 5. 评审问题清单（供讨论）

### Q1：快速自杀的合理性

**现有理由（代码注释）**：
> "For passive scaling down caused by a fault, we believe that the async task has processed the time configured by NODE_DEAD_TIMEOUT, but the task still fails, and there is no point in continuing to wait."
>
> `hash_ring.cpp:1390`

即：A 已经"死"了 `node_dead_timeout_s` 时间，继续运行反而有脑裂风险（zombie 节点仍响应请求但元数据路由已迁走）。

**反驳点**：
- 快速自杀的前提是"已经死了足够长"，但 A 本身不知道 B 的判死时钟—— A 只是读到了 etcd ring 的状态，这个状态可能在很短时间内（如本次 3s 配置）被写入，而 A 此时网络实际上已经恢复。
- `passive_scale_down_ring_recheck_delay_ms` 的设计本身就承认了"单次 ring 读可能有误判"，但默认关闭。

**讨论：是否应将 `passive_scale_down_ring_recheck_delay_ms` 默认开启（如 2~3s）？**

---

### Q2：内存缓存数据丢失是否可接受

**假设前提**：元数据全部持久化到 etcd/rocksdb，内存只是 cache。

**需要确认**：
- [ ] 是否存在"写到内存但尚未刷盘"的元数据状态？（write-back cache）
- [ ] SIGKILL 时的 in-flight RPC（客户端正在写的请求）如何处理？是否有幂等保证？
- [ ] B 的 `RecoverMetaAndDataOfFaultWorker` 完成之前，相关 range 的读写请求如何路由？是否有请求丢失窗口？

---

### Q3：重启开销的可接受性

A 重启后：
1. 等待 del_node_info 清除（B 的异步任务完成）
2. 重新 InitRing（CAS 入环）
3. 触发 Reconciliation（B push 元数据给 A）
4. 等待 A 进入 RUNNING 状态，client 重连

**需要确认**：
- [ ] 以上端到端重启时间的 P50/P99 是多少？（与当前 SLA 目标对齐）
- [ ] 客户端在这段时间内会看到什么错误码？持续多久？

---

### Q4：`node_timeout=2s, node_dead_timeout=3s` 配置是否合理

当前测试配置导致：
- TIMEOUT→FAILED 窗口仅 **1s**（几乎没有恢复机会）
- A 自杀最快 **~3s**（keep-alive 路径）或 **~3s 内**（ring 路径，B 在 1s 后写 del_node_info，A 立刻读到）
- 即使是短暂网络抖动（< 1s），也会触发完整的被动缩容+重启流程

**需要确认**：
- [ ] 这是测试专用配置，还是会用于生产？
- [ ] 如果是生产配置，SLA 要求的故障恢复时间（RTO）是多少？
- [ ] `node_dead_timeout - node_timeout` 差值 = 1s，是否足够让 B 完成数据迁移？

---

### Q5：`auto_del_dead_node=false` 时的行为

关闭 `auto_del_dead_node` 后：
- `RemoveWorkers` 直接 return，A **不会自杀**
- A 的 `state_ = FAIL`，ring 不再更新
- A 变成"活死人"：进程仍运行，但路由已失效，不接受任何新请求（CheckConnection 返回 K_MASTER_TIMEOUT）

**讨论：是否需要一个"优雅降级"模式**（`auto_del_dead_node=false` 时，A 不 SIGKILL 但主动拒绝所有新请求并等待管理员介入）？

---

## 6. 可选改造方向（按侵入性递增）

### 方案 A：开启 `passive_scale_down_ring_recheck_delay_ms`（低风险，配置变更）

将 `passive_scale_down_ring_recheck_delay_ms` 设为 2000~3000ms。A 在 FAIL 后，sleep 2~3s 再读一次 etcd 环，如果自己是 ACTIVE 且不在 del_node_info 则**撤销自杀**。

- **代价**：最坏情况下退出延迟增加 2~3s
- **收益**：消除短暂视图不一致导致的误杀
- **适用场景**：`node_dead_timeout_s` 较小的部署

### 方案 B：自杀前 flush 关键状态（中等侵入）

在 `raise(SIGKILL)` 前改为：
1. 停止接受新请求（设一个"draining"标志）
2. 等待 in-flight 请求结束（有超时）
3. 将未持久化的元数据 flush 到 rocksdb
4. 然后 `raise(SIGTERM)` 而非 SIGKILL

- **代价**：需要改造 SIGKILL 路径，引入 drain 超时机制
- **收益**：消除数据丢失风险
- **风险**：drain 期间如果 B 认为 A 已经被杀但 A 还在服务，可能有一致性窗口

### 方案 C：B 写 del_node_info 前等待 A 确认（高侵入）

修改被动缩容协议：B 写 del_node_info 之前，先 RPC 通知 A "你即将被剔除"，A 收到后主动 flush + 停服后确认，B 再写 del_node_info。

- **代价**：协议改造，A 可能已不可达（这是触发被动缩容的原因），需要超时处理
- **收益**：完整的 graceful shutdown 语义

### 方案 D：提升 `node_dead_timeout_s` / 调整测试配置

针对测试配置（timeout=2s, dead=3s）可行性不足的问题：
- 生产建议：`node_timeout_s=30~60s`, `node_dead_timeout_s=120~300s`，确保 `dead - timeout >= 60s`，留出数据迁移时间

---

## 7. 结论与建议

| 结论 | 说明 |
|------|------|
| 快速自杀**设计意图合理** | 防止 zombie 节点在路由已迁走后继续服务，避免脑裂 |
| 当前配置（2s/3s）**有较高误杀风险** | `dead - timeout = 1s` 远小于推荐值，正常抖动即触发被动缩容 |
| `passive_scale_down_ring_recheck_delay_ms=0`（默认）**存在设计缺陷** | 该 flag 的存在本身承认了单次读可能误判，但默认关闭暴露风险 |
| 内存缓存丢失**依赖持久化假设** | 需明确所有元数据是否在 SIGKILL 前已持久化 |
| 重启恢复开销**未量化** | 需补充端到端 RTO 测试数据 |

**最小建议（无需代码变更）**：
1. 将 `passive_scale_down_ring_recheck_delay_ms` 设为非 0（建议 `node_timeout_s * 500ms`）
2. 生产部署时确保 `node_dead_timeout_s - node_timeout_s >= 60s`
3. 补充内存元数据持久化完整性测试（验证"SIGKILL 后无数据丢失"的假设）

---

## 8. 参考文档

- 超时参数与扩缩容分歧分析：[timeout-params-restart-vs-scale-down](./timeout-params-restart-vs-scale-down.md)
- 相关代码：
  - `src/datasystem/common/kvstore/etcd/etcd_store.cpp`：`LaunchKeepAliveThreads`, `HandleKeepAliveFailed`
  - `src/datasystem/worker/hash_ring/hash_ring.cpp`：`UpdateLocalState`, `RemoveWorkers`, `NeedToTryRemoveWorker`
  - `src/datasystem/worker/hash_ring/hash_ring_task_executor.cpp`：`SubmitScaleDownTaskRecoverFromEtcd`
  - `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp`：`DemoteTimedOutNodes`, `CleanupWorker`, `HandleFailedNode`
  - `src/datasystem/common/util/gflag/common_gflag_define.cpp`：`passive_scale_down_ring_recheck_delay_ms`, `node_timeout_s`, `node_dead_timeout_s`
