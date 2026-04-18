# etcd 故障隔离与恢复

> 整合原 `worker-etcd-fault-isolation-recovery-final-analysis.md` 与 `ccb-worker-fast-sigkill-on-etcd-isolation.md` 两篇。前半讲"隔离如何完成、Path 1 / Path 2 恢复链"；后半讲"被动缩容 SIGKILL 的风险评审与缓解"。

## 对应代码

| 代码位置 | 关键函数 | 说明 |
|---------|---------|------|
| `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp` | `HandleNodeRemoveEvent` / `DemoteTimedOutNode` / `CheckConnection` / `ProcessNetworkRecovery` | etcd DELETE 事件处理与状态机 |
| `src/datasystem/common/kvstore/etcd/etcd_store.cpp` | `LaunchKeepAliveThreads` / `HandleKeepAliveFailed` / `AutoCreate` | A 侧 keep-alive 主循环与 SIGKILL 触发 |
| `src/datasystem/worker/hash_ring/hash_ring.cpp` | `UpdateLocalState` / `RemoveWorkers` / `NeedToTryRemoveWorker` / `RecoverMigrationTask` / `InitRing` | hash ring watch 与被动缩容路径 |
| `src/datasystem/worker/hash_ring/hash_ring_task_executor.cpp` | `SubmitScaleDownTaskRecoverFromEtcd` | 异步恢复任务 |
| `src/datasystem/worker/object_cache/oc_metadata_manager.cpp` | `ProcessWorkerTimeout` / `ProcessPrimaryCopyByWorkerTimeout` / `ProcessWorkerNetworkRecovery` | 元数据切主与 delta 推送 |
| `src/datasystem/worker/object_cache/oc_notify_worker_manager.cpp` | `NotifyOpToWorker` | 重放 `PRIMARY_COPY_INVALID` / `CACHE_INVALID` / `DELETE` |
| `src/datasystem/common/util/gflag/common_gflag_define.cpp` | `node_timeout_s` / `node_dead_timeout_s` / `passive_scale_down_ring_recheck_delay_ms` / `auto_del_dead_node` | 关键参数 |

---

## 1. 核心结论速查

| 结论 | 依据 |
|------|------|
| **故障隔离（停止向 A 发请求 + 路由切换）在 `t = node_timeout_s` 完成**，与 `node_dead_timeout_s` 无关 | `CheckConnection` 在 `IsTimedOut()` 时就拦截；`ProcessPrimaryCopyByWorkerTimeout` 在 TIMEOUT 阶段触发 |
| **`node_dead_timeout_s` 只控制 TIMEOUT → FAILED 的等待窗口**，不影响隔离速度 | `DemoteTimedOutNode`：经过 `dead_timeout - node_timeout` 秒后才变 FAILED |
| 当前测试配置（timeout=2s, dead=3s）下 **Path 1（轻量重连）实际走不到** | Path 1 窗口 = 1s，A 重试间隔 = 5s，窗口 < 重试间隔 |
| **调大 `node_dead_timeout_s` 到 ≥ 10s（推荐 30s）即可打通 Path 1**，零代码改动 | A 有足够重试机会，B 尚未写 `del_node_info`，轻量恢复路径可达 |
| Path 1 成功后 **A 不重启**，B 推送增量元数据，秒级恢复 | `ProcessWorkerNetworkRecovery(isOffline=false)` → `AsyncPushMetaToWorker` + `AsyncNotifyOpToWorker` |

---

## 2. 两个参数的职责划分

```text
node_timeout_s      →  etcd lease TTL
                       lease 到期 → etcd DELETE → B 收到事件 → 【隔离生效】

node_dead_timeout_s →  从 lease 到期起，等多久把 A 判死
                       超过该时间 → TIMEOUT → FAILED → del_node_info → 【A 自杀】
```

**关键公式**：

```text
TIMEOUT → FAILED 等待时间   = node_dead_timeout_s - node_timeout_s
Path 1（轻量重连）可用窗口   = TIMEOUT → FAILED 等待时间
```

| 配置 | 隔离生效时间 | Path 1 窗口 | A 重试间隔 | Path 1 可达？ |
|---|---|---|---|---|
| timeout=2s, dead=3s（当前测试） | **2s** | **1s** | 5s | **不可达** |
| timeout=2s, dead=10s | **2s** | 8s | 5s | 可达（约 1 次机会）|
| timeout=2s, dead=30s（推荐）| **2s** | **28s** | 5s | **可靠**（约 5 次机会）|

---

## 3. 快速隔离链路（代码证据）

### 3.1 请求立刻停止发给 A（t = node_timeout_s）

etcd DELETE 触发 `HandleNodeRemoveEvent` → `SetTimedOut()`，此后 `CheckConnection` 拦截所有路由：

```cpp
// etcd_cluster_manager.cpp:886
if (accessor->second->IsFailed() || accessor->second->IsTimedOut()) {
    RETURN_STATUS(StatusCode::K_MASTER_TIMEOUT, "Disconnected from remote node " + nodeAddr.ToString());
}
```

**`IsTimedOut()` 和 `IsFailed()` 都会拦截**，TIMEOUT 状态（t=2s）已经足够，不需要等 FAILED。

### 3.2 元数据路由立刻切换

`HandleNodeRemoveEvent` 同时发出 `NodeTimeoutEvent(changePrimary=true, removeMeta=false)`：

```cpp
// etcd_cluster_manager.cpp:591
NodeTimeoutEvent::GetInstance().NotifyAll(workerAddr, true, false, false);
```

`OCMetadataManager` 订阅者收到后调用 `ProcessWorkerTimeout`：

```cpp
// oc_metadata_manager.cpp:3738
if (changePrimaryCopy) {
    ProcessPrimaryCopyByWorkerTimeout(workerAddr);  // ← t=2s 就执行
}
```

`ProcessPrimaryCopyByWorkerTimeout` 遍历所有以 A 为 primary 的对象，重选 primary 为备副本 C，并通过 `AsyncChangePrimaryCopy` 通知 C。

**结论：t=2s 时，A 上所有对象已切到 C 为 primary，客户端读写成功。**

### 3.3 FAILED 阶段的补充动作（t = node_dead_timeout_s）

```cpp
// etcd_cluster_manager.cpp:83-92
bool EtcdClusterManager::ClusterNode::DemoteTimedOutNode()
{
    if (state_ == NodeState::TIMEOUT && FLAGS_node_dead_timeout_s > FLAGS_node_timeout_s
        && timeoutStamp_.ElapsedSecond() > (FLAGS_node_dead_timeout_s - FLAGS_node_timeout_s)) {
        state_ = NodeState::FAILED;
        return true;
    }
    return false;
}
```

FAILED 后触发 `HandleFailedNode` → `NodeTimeoutEvent(removeMeta=true)` + `StartClearWorkerMeta`，清理 A 的残留元数据，写 `del_node_info`，A 自杀。

### 3.4 时序总结

```text
t=0s    A 的 etcd 续约失败

t=2s    etcd lease 到期 → B 收到 DELETE 事件
        ├─ SetTimedOut()
        ├─ CheckConnection → K_MASTER_TIMEOUT        ← 请求不再发给 A
        └─ ProcessPrimaryCopyByWorkerTimeout         ← 路由切到备副本 C
                                                       后续读写成功

        （以上由 node_timeout_s 控制，与 dead_timeout 无关）

t=3s    DemoteTimedOutNode 触发（dead_timeout - node_timeout = 1s 后）
        ├─ RemoveMetaByWorker（清理残留元数据）
        └─ 写 del_node_info → A 触发 SIGKILL         ← 这才是 dead_timeout 的作用域
```

---

## 4. 两条恢复路径

### 4.1 Path 1：TIMEOUT 窗口内轻量重连（A 不重启）

**触发条件**：A 在 TIMEOUT 状态期间（未变 FAILED）成功重新续约 etcd。

**A 侧**：keep-alive 失败后每 5s 重试一次 `RunKeepAliveTask`；重连成功后调 `AutoCreate`，写入 state=`"recover"`（不是 `"restart"`）：

```cpp
// etcd_store.cpp:491
if (keepAliveValue_.state == "start" || keepAliveValue_.state == "restart") {
    keepAliveValue_.state = "recover";
}
```

**B 侧**：收到 state=`"recover"` 的 PUT → `HandleNodeAdditionEvent` → A 处于 TIMEOUT → `HandleFailedNodeToActive` → `ProcessNetworkRecovery`：

```cpp
// etcd_cluster_manager.cpp:831
if (recoverNode->IsTimedOut()) {
    NodeNetworkRecoveryEvent::GetInstance().NotifyAll(nodeAddr, timestamp, false);  // isOffline=false
    hashRing_->RecoverMigrationTask(nodeAddr);
}
foundNode->SetActive();  // 清除 TIMEOUT 状态
```

`NodeNetworkRecoveryEvent(isOffline=false)` 触发 `ProcessWorkerNetworkRecovery`：

```cpp
// oc_metadata_manager.cpp:3791
Status OCMetadataManager::ProcessWorkerNetworkRecovery(..., bool isOffline) {
    notifyWorkerManager_->RemoveFaultWorker(workerAddr);
    if (!isOffline) {
        notifyWorkerManager_->AsyncPushMetaToWorker(workerAddr, timestamp, false);  // 推 delta
        notifyWorkerManager_->AsyncNotifyOpToWorker(workerAddr, timestamp);          // 重放积压操作
    }
}
```

`NotifyOpToWorker` 将 TIMEOUT 期间积压的 `PRIMARY_COPY_INVALID` / `CACHE_INVALID` / `DELETE` 推送给 A，A 更新本地状态，恢复正常 worker 角色。

**Path 1 效果**：A 进程全程存活，无重启；B 推 delta（非全量），秒级完成；RocksDB 不清空。

### 4.2 Path 2：超过 dead_timeout 后 A 自杀重启

**触发条件**：A 续约失败累计时间超过 `node_dead_timeout_s`，或读到 etcd ring 中自己的 `del_node_info`。

**A 侧**：`raise(SIGKILL)` 强制退出，进程重启后 state=`"restart"`。

**B 侧**：走 `isOffline=true` 的重量级路径 —— `RequestMetaFromWorker`（A 从 B 拉取全量元数据）、Reconciliation 流程、A 等待 `del_node_info` 清除才能入环（可能几十秒）。

### 4.3 对比

| 维度 | Path 1（轻量重连） | Path 2（自杀重启） |
|---|---|---|
| A 进程 | **存活，无重启** | SIGKILL 后重启 |
| etcd state | `"recover"` | `"restart"` |
| 元数据同步 | **B 推 delta** | A 拉全量 |
| RocksDB | 不动 | 清空重建 |
| 恢复耗时 | **秒级** | 分钟级 |
| 触发条件 | A 在 dead_timeout 前重连 | A 超过 dead_timeout |

---

## 5. Path 1 的 gap 评估

### 5.1 Gap 1（最关键）：当前配置下 Path 1 实际不可达

A 重试间隔硬编码 5s：

```cpp
// etcd_store.cpp:567
int RETRY_DELAY = 5;
std::this_thread::sleep_for(std::chrono::seconds(RETRY_DELAY));
```

当前 `node_dead_timeout_s=3s`，Path 1 窗口（1s）< 重试间隔（5s）。**A 第一次重试机会到来时（5s），B 已经在 t=3s 变 FAILED 并写了 `del_node_info`，Path 1 已关闭。**

**修复**：无需改代码，调大 `node_dead_timeout_s`。

### 5.2 Gap 2（设计层面）：Path 1 恢复后 A 不再是 primary

A 在 TIMEOUT 期间，B 已把 A 的 primary 切到 C。Path 1 恢复后 `NotifyOpToWorker` 把 `PRIMARY_COPY_INVALID` 推给 A，A 知道自己不再是这些对象的 primary，**但 B 不会把 primary 切回 A**。

影响：A 恢复后成为被动副本，C 持续作为 primary。频繁闪断会导致负载长期倾斜。

**当前建议**：接受此设计（安全优先），不改代码。如需改善，后续加 rebalance 特性。

### 5.3 Gap 3（边界竞争，低概率）

`RecoverMigrationTask` 只回滚 `add_node_info`，不处理 `del_node_info`：

```cpp
// hash_ring.cpp:792
void HashRing::RecoverMigrationTask(const std::string &node) {
    if (ringInfo_.add_node_info().find(node) != ringInfo_.add_node_info().end()) {
        taskExecutor_->SubmitOneScaleUpTask(...);
    }
    // del_node_info 无处理
}
```

若 B 刚写完 `del_node_info` 而 A 的恢复事件几乎同时到达，A 的 HashRing watch 会读到 `del_node_info` → `state_=FAIL` → `SIGKILL`，Path 1 被强制切换为 Path 2。发生概率极低（毫秒级竞争），调大 `dead_timeout` 后边界推远，实际影响可忽略。

---

## 6. 被动缩容 SIGKILL：机制与风险

### 6.1 触发路径（代码证据）

当 B 认定 A 已故障，B 写入 `del_node_info[A]` 后，A 自身的 etcd watch 线程在 **同一个 EtcdUtil 线程循环迭代** 内完成两步：

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

// hash_ring.cpp:1404
(void)raise(SIGKILL);   // 被动缩容路径，注释明确说是故意的
```

**FAIL 是终态，不可逆**（`hash_ring.cpp:1141`）。

前提条件：`EnableAutoDelDeadNode()` = `enableDistributedMaster_ && FLAGS_auto_del_dead_node`。

### 6.2 两个核心问题

**问题 1：内存缓存数据丢失**

A 被 SIGKILL 时，其内存中的缓存数据（元数据路由 cache、内存 KV 数据）**无条件丢失**，没有任何 graceful flush 机会。B 端的数据恢复（`RecoverMetaAndDataOfFaultWorker`）是 **异步** 启动的；A 被杀时 B 的恢复大概率尚未完成。系统设计假设是"元数据已持久化到 etcd/rocksdb"，对未持久化的内存 cache 存在风险敞口。

**问题 2：重启后需全量重新初始化**

A 重启后必须走完整的 Reconciliation 流程（写 `"timestamp;restart"` → B 发 `ClearWorkerMeta + NodeRestartEvent` → A `InitKeepAlive` + `InitRing`）。`InitRing` 遇到 `del_node_info[A]` 仍存在时还会 sleep(1s) 轮询等待缩容完成：

```cpp
// hash_ring.cpp:239
if (oldRing.del_node_info().find(workerAddr_) != oldRing.del_node_info().end()) {
    LOG(INFO) << "The scale down of this node is being executed, retry...";
    sleep(1s); return K_TRY_AGAIN;
}
```

### 6.3 风险矩阵

| # | 风险场景 | 严重度 | 概率（当前配置） | 兜底 |
|---|---|---|---|---|
| R1 | A 短暂网络抖动（< `node_dead_timeout_s`），B 已写 `del_node_info`，A 网络恢复后仍被杀 | 高 | **高**（`node_dead=3s` 窗口极小） | 有：`passive_scale_down_ring_recheck_delay_ms`（默认关） |
| R2 | etcd 自身短暂不可达（非 A 故障），B 误判 A 死亡并写 `del_node_info` | 高 | 中 | 有：3 次确认机制（`networkFailedConfirmMinTimes=3`） |
| R3 | A 被杀时 B 的数据恢复尚未完成，`del_node_info` 仍在 etcd，A 重启入环阻塞 | 中 | **高** | 有：`InitRing` 的 sleep+retry |
| R4 | A 被杀时，A 的内存中有未持久化的"脏"元数据 | 高 | 依赖持久化策略 | 无（依赖系统假设） |
| R5 | B 误写 `del_node_info` 后自身也故障，`del_node_info` 长期悬挂 | 中 | 低 | 有：`HashRingHealthCheck` |
| R6 | `passive_scale_down_ring_recheck_delay_ms=0`（默认），无二次确认直接杀进程 | 中 | 默认配置下存在 | 有：该 flag 非零时会 re-read etcd 环 |

### 6.4 当前仓库已落地的缓解手段

| 机制 | 代码位置 | 作用 | 默认值 |
|---|---|---|---|
| `networkFailedConfirmMinTimes=3` | `etcd_store.cpp:568` | keep-alive 失败路径需 ≥3 次 peer 确认 etcd OK 才注入 fake DELETE | 硬编码 3 |
| `deathTimer` 兜底 | `etcd_store.cpp:611` | 防止 SIGKILL 机制本身失败，`(node_dead - node_timeout + 10)s` 后强杀 | 随 flag 计算 |
| `passive_scale_down_ring_recheck_delay_ms` | `common_gflag_define.cpp` | 自杀前 sleep N ms，再读一次 etcd 环，若环上自己 ACTIVE 且不在 `del_node_info` 则**放弃自杀** | **0（关闭）** |
| `worker_incarnation` 字段 | `hash_ring.proto` | 区分同地址重入环是新实例还是旧进程 | 已有字段，未全链路使用 |
| `HashRingHealthCheck` 周期巡检 | `hash_ring_health_check.cpp` | 检测环一致性、CAS 修复悬挂状态 | 开启 |

---

## 7. 评审问题清单

### Q1：快速自杀的合理性

**现有理由**（`hash_ring.cpp:1390` 注释）：A 已经"死"了 `node_dead_timeout_s` 时间，继续运行反而有脑裂风险（zombie 节点仍响应请求但元数据路由已迁走）。

**反驳点**：快速自杀的前提是"已经死了足够长"，但 A 本身不知道 B 的判死时钟 —— A 只是读到了 etcd ring 的状态，这个状态可能在很短时间内（如本次 3s 配置）被写入，而 A 此时网络实际已恢复。`passive_scale_down_ring_recheck_delay_ms` 的设计本身就承认"单次 ring 读可能有误判"，但默认关闭。

**讨论**：是否应将 `passive_scale_down_ring_recheck_delay_ms` 默认开启（如 2~3s）？

### Q2：内存缓存数据丢失是否可接受

- [ ] 是否存在"写到内存但尚未刷盘"的元数据状态？（write-back cache）
- [ ] SIGKILL 时 in-flight RPC 如何处理？是否有幂等保证？
- [ ] B 的 `RecoverMetaAndDataOfFaultWorker` 完成前，相关 range 的读写请求如何路由？

### Q3：重启开销的可接受性

- [ ] 端到端重启时间 P50 / P99 是多少？
- [ ] 客户端在这段时间内会看到什么错误码？持续多久？

### Q4：`node_timeout=2s, node_dead_timeout=3s` 是否合理

- `dead - timeout = 1s`，几乎没有 Path 1 机会。
- [ ] 这是测试专用配置还是生产？SLA 要求的 RTO 是多少？

### Q5：`auto_del_dead_node=false` 时的行为

关闭后 A 不会自杀但变成"活死人"（进程仍运行，路由已失效）。是否需要"优雅降级"模式（不 SIGKILL 但主动拒绝新请求并等待管理员介入）？

---

## 8. 可选改造方向（按侵入性递增）

### 方案 A：开启 `passive_scale_down_ring_recheck_delay_ms`（低风险，配置变更）

设为 2000~3000 ms。A 在 FAIL 后 sleep 2~3s 再读一次 etcd 环，如果自己是 ACTIVE 且不在 `del_node_info` 则**撤销自杀**。

- **代价**：最坏情况下退出延迟增加 2~3s
- **收益**：消除短暂视图不一致导致的误杀
- **适用场景**：`node_dead_timeout_s` 较小的部署

### 方案 B：自杀前 flush 关键状态（中等侵入）

1. 停止接受新请求（draining 标志）
2. 等待 in-flight 请求结束（有超时）
3. 未持久化元数据 flush 到 rocksdb
4. `raise(SIGTERM)` 而非 SIGKILL

- **代价**：改造 SIGKILL 路径，引入 drain 超时机制
- **收益**：消除数据丢失风险
- **风险**：drain 期间 A 还在服务，可能有一致性窗口

### 方案 C：B 写 `del_node_info` 前等待 A 确认（高侵入）

先 RPC 通知 A "你即将被剔除"，A flush + 停服后确认，B 再写 `del_node_info`。

- **代价**：协议改造，A 可能已不可达，需要超时处理
- **收益**：完整的 graceful shutdown 语义

### 方案 D：提升 `node_dead_timeout_s`

生产建议：`node_timeout_s=2s, node_dead_timeout_s=30s`；或默认 `node_timeout_s=30~60s, node_dead_timeout_s=120~300s`，确保 `dead - timeout >= 60s`，留出数据迁移时间。

**推荐**：**方案 A + 方案 D 组合**，无需代码变更即可大幅降低误杀与数据丢失风险。

---

## 9. 决策矩阵

| 方案 | 描述 | 隔离速度影响 | 闪断处理 | 改动风险 |
|---|---|---|---|---|
| **A（推荐）：调大 `dead_timeout`** | `node_dead_timeout_s = 30s` | **无影响** | Path 1 可达 | **零风险**（纯配置）|
| B：开启 `passive_scale_down_ring_recheck_delay_ms` | A 自杀前 re-read etcd 再确认 | 无影响 | 减少误杀 | 低风险（配置变更）|
| C：改代码加 `del_node_info` 回滚 | `RecoverMigrationTask` 处理 `del_node_info` | 无影响 | 消除边界竞争 | 中风险（代码改动）|
| D：维持现状（dead=3s） | 不做任何变更 | 无影响 | Path 1 走不到 | 零风险（不变） |

---

## 10. 推荐配置（生产）

```text
node_timeout_s     = 2        # 不变，控制隔离速度（2s 感知故障）
node_dead_timeout_s = 30      # 从 3s 调大到 30s
```

效果对比：

```text
调整前（dead=3s）：
  t=2s   B 完成隔离（路由切换） ✅
  t=3s   A 被自杀（Path 1 窗口=1s，走不到）
  t=3s~  A 走 Path 2 重量级重启，耗时分钟级

调整后（dead=30s）：
  t=2s   B 完成隔离（路由切换） ✅（与之前完全相同）
  t=~7s  A 的第一次重试（5s 后）：如果网络已恢复，走 Path 1 ✅
  t=30s  如果 A 始终不恢复，才变 FAILED，触发 Path 2
```

**增大 `node_dead_timeout_s` 不改变隔离速度，只增加 A 自愈的时间窗口。**
