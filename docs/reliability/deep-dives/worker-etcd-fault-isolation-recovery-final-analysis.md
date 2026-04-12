---
name: Worker etcd 故障隔离与自愈机制完整分析
overview: >
  分析 worker etcd 续约故障时的完整处理链路：
  ① 快速隔离（路由阻断 + 元数据切换）的时机与参数关系；
  ② 两条恢复路径（Path 1 轻量重连 vs Path 2 重启）的代码证据与差异；
  ③ Path 1 的 gap 评估及参数调优建议。
  结论：node_dead_timeout_s 与隔离速度无关，调大后可打通 Path 1，零代码改动解决闪断误杀问题。
created: 2026-04-12
related: ccb-worker-fast-sigkill-on-etcd-isolation.md
---

# Worker etcd 故障隔离与自愈机制完整分析

## 1. 核心结论速查

| 结论 | 依据 |
|------|------|
| **故障隔离（停止向 A 发请求 + 路由切换）在 t=node_timeout_s 完成**，与 node_dead_timeout_s 无关 | `CheckConnection` 在 `IsTimedOut()` 时就拦截；`ProcessPrimaryCopyByWorkerTimeout` 在 TIMEOUT 阶段触发 |
| **node_dead_timeout_s 只控制 TIMEOUT→FAILED 的等待窗口**，不影响隔离速度 | `DemoteTimedOutNode`：经过 `dead_timeout - node_timeout` 秒后才变 FAILED |
| 当前配置（timeout=2s, dead=3s）下 **Path 1（轻量重连）实际走不到** | Path 1 窗口=1s，A 重试间隔=5s，窗口小于重试间隔 |
| **调大 node_dead_timeout_s 到 ≥ 10s（推荐 30s）即可打通 Path 1**，零代码改动 | A 有足够重试机会，B 尚未写 del_node_info，轻量恢复路径可达 |
| Path 1 成功后 **A 不重启**，B 推送增量元数据，秒级恢复 | `ProcessWorkerNetworkRecovery(isOffline=false)` → `AsyncPushMetaToWorker` + `AsyncNotifyOpToWorker` |

---

## 2. 两个参数的职责划分

```
node_timeout_s      →  etcd lease TTL
                       lease 到期 → etcd DELETE → B 收到事件 → 【隔离生效】

node_dead_timeout_s →  从 lease 到期起，等多久把 A 判死
                       超过该时间 → TIMEOUT→FAILED → del_node_info → 【A 自杀】
```

**关键公式**：

```
TIMEOUT→FAILED 等待时间 = node_dead_timeout_s - node_timeout_s

Path 1（轻量重连）可用窗口 = TIMEOUT→FAILED 等待时间
                           = node_dead_timeout_s - node_timeout_s
```

| 配置 | 隔离生效时间 | Path 1 窗口 | A 重试间隔 | Path 1 可达？ |
|---|---|---|---|---|
| timeout=2s, dead=3s（当前）| **2s** | **1s** | 5s | **不可达** |
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

**`IsTimedOut()` 和 `IsFailed()` 都会拦截，TIMEOUT 状态（t=2s）已经足够，不需要等 FAILED。**

### 3.2 元数据路由立刻切换（t = node_timeout_s，同步触发）

`HandleNodeRemoveEvent` 同时发出 `NodeTimeoutEvent(changePrimary=true, removeMeta=false)`：

```cpp
// etcd_cluster_manager.cpp:591
NodeTimeoutEvent::GetInstance().NotifyAll(workerAddr, true, false, false);
```

OCMetadataManager 订阅者收到后调用 `ProcessWorkerTimeout`：

```cpp
// oc_metadata_manager.cpp:3738
if (changePrimaryCopy) {
    ProcessPrimaryCopyByWorkerTimeout(workerAddr);  // ← t=2s 就执行
}
```

`ProcessPrimaryCopyByWorkerTimeout` 遍历所有以 A 为 primary 的对象，重选 primary 为备副本 C，
并通过 `AsyncChangePrimaryCopy` 通知 C"你现在是这些对象的 primary"。

**结论：t=2s 时，A 上所有对象已切到 C 为 primary，客户端读写成功。**

### 3.3 FAILED 阶段的补充动作（t = node_dead_timeout_s）

```cpp
// etcd_cluster_manager.cpp:83-92
bool EtcdClusterManager::ClusterNode::DemoteTimedOutNode()
{
    // 从 TIMEOUT 起经过 (dead_timeout - node_timeout) 秒才变 FAILED
    if (state_ == NodeState::TIMEOUT && FLAGS_node_dead_timeout_s > FLAGS_node_timeout_s
        && timeoutStamp_.ElapsedSecond() > (FLAGS_node_dead_timeout_s - FLAGS_node_timeout_s)) {
        state_ = NodeState::FAILED;
        return true;
    }
    return false;
}
```

FAILED 后触发 `HandleFailedNode` → `NodeTimeoutEvent(removeMeta=true)` + `StartClearWorkerMeta`，
清理 A 的残留元数据，写 `del_node_info`，A 自杀。

### 3.4 时序总结

```
t=0s    A 的 etcd 续约失败

t=2s    etcd lease 到期 → B 收到 DELETE 事件
        ├─ SetTimedOut()
        ├─ CheckConnection → K_MASTER_TIMEOUT      ← 请求不再发给 A ✅
        └─ ProcessPrimaryCopyByWorkerTimeout       ← 路由切到备副本 C ✅
                                                     后续读写成功 ✅

        （以上由 node_timeout_s 控制，与 dead_timeout 无关）

t=3s    DemoteTimedOutNode 触发（dead_timeout - node_timeout = 1s 后）
        ├─ RemoveMetaByWorker（清理残留元数据）
        └─ 写 del_node_info → A 触发 SIGKILL        ← 这才是 dead_timeout 的作用域
```

---

## 4. 两条恢复路径

### Path 1：TIMEOUT 窗口内轻量重连（A 不重启）

**触发条件**：A 在 TIMEOUT 状态期间（未变 FAILED）成功重新续约 etcd。

**A 侧行为**：keep-alive 失败后每 5s 重试一次 `RunKeepAliveTask`；
重连成功后调 `AutoCreate`，写入 state=`"recover"`（不是 `"restart"`）：

```cpp
// etcd_store.cpp:491
if (keepAliveValue_.state == "start" || keepAliveValue_.state == "restart") {
    keepAliveValue_.state = "recover";  // 后续重连统一写 recover
}
```

**B 侧行为**：收到 state=`"recover"` 的 PUT 事件 → `HandleNodeAdditionEvent` →
A 处于 TIMEOUT 状态 → `HandleFailedNodeToActive` → `ProcessNetworkRecovery`：

```cpp
// etcd_cluster_manager.cpp:831
if (recoverNode->IsTimedOut()) {
    NodeNetworkRecoveryEvent::GetInstance().NotifyAll(nodeAddr, timestamp, false);  // isOffline=false
    hashRing_->RecoverMigrationTask(nodeAddr);  // 取消未开始的 scale-up 任务
}
// ...
foundNode->SetActive();  // 清除 TIMEOUT 状态，line 494
```

`NodeNetworkRecoveryEvent(isOffline=false)` 触发 `ProcessWorkerNetworkRecovery`：

```cpp
// oc_metadata_manager.cpp:3791
Status OCMetadataManager::ProcessWorkerNetworkRecovery(..., bool isOffline) {
    notifyWorkerManager_->RemoveFaultWorker(workerAddr);              // 从故障名单移除
    if (!isOffline) {
        notifyWorkerManager_->AsyncPushMetaToWorker(workerAddr, timestamp, false);  // 推 delta 元数据
        notifyWorkerManager_->AsyncNotifyOpToWorker(workerAddr, timestamp);          // 重放错过的操作
    }
}
```

`NotifyOpToWorker` 将 TIMEOUT 期间积压的操作（`PRIMARY_COPY_INVALID`、`CACHE_INVALID`、`DELETE`）
推送给 A，A 更新本地状态，恢复正常 worker 角色。

**Path 1 效果**：
- A 进程全程存活，无重启
- B 推送 delta（非全量），秒级完成
- RocksDB 不清空，A 继续作为备副本服务

### Path 2：超过 dead_timeout 后 A 自杀重启（重量级）

**触发条件**：A 续约失败累计时间超过 `node_dead_timeout_s`，或读到 etcd ring 中自己的 `del_node_info`。

**A 侧**：`raise(SIGKILL)` 强制退出，进程重启后 state=`"restart"`。

**B 侧**：走 `isOffline=true` 的重量级路径：
- `RequestMetaFromWorker`：A 从 B 拉取全量元数据
- Reconciliation 流程：重新初始化内存路由、client 重连、副本同步
- A 等待 `del_node_info` 清除才能入环（可能需要几十秒）

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

### Gap 1（最关键）：当前配置下 Path 1 实际不可达

A 重试间隔硬编码 5s：

```cpp
// etcd_store.cpp:567
int RETRY_DELAY = 5;
// ...
std::this_thread::sleep_for(std::chrono::seconds(RETRY_DELAY));
```

当前 `node_dead_timeout_s=3s`，Path 1 窗口（1s）< 重试间隔（5s），
**A 第一次重试机会到来时（5s），B 已经在 t=3s 变 FAILED 并写了 del_node_info，Path 1 已关闭。**

**修复**：无需改代码，调大 `node_dead_timeout_s`。

### Gap 2（设计层面）：Path 1 恢复后 A 不再是 primary

A 在 TIMEOUT 期间，B 已把 A 的 primary 切到 C（`ProcessPrimaryCopyByWorkerTimeout`）。
Path 1 恢复后 `NotifyOpToWorker` 把 `PRIMARY_COPY_INVALID` 推给 A，
A 知道自己不再是这些对象的 primary，**但 B 不会把 primary 切回 A**。

影响：A 恢复后成为被动副本，C 持续作为 primary。频繁闪断会导致**负载长期倾斜**。

**当前建议**：接受此设计（安全优先），不改代码。如需改善，后续加 rebalance 特性。

### Gap 3（边界竞争，低概率）：del_node_info 写入与 A 恢复的竞争

`RecoverMigrationTask` 只回滚 `add_node_info`，不处理 `del_node_info`：

```cpp
// hash_ring.cpp:792
void HashRing::RecoverMigrationTask(const std::string &node) {
    if (ringInfo_.add_node_info().find(node) != ringInfo_.add_node_info().end()) {
        taskExecutor_->SubmitOneScaleUpTask(...);  // 只处理 add_node_info
    }
    // del_node_info 无处理
}
```

若 B 刚写完 `del_node_info` 而 A 的恢复事件几乎同时到达，A 的 HashRing watch 会
读到 `del_node_info` → `state_=FAIL` → `SIGKILL`，Path 1 被强制切换为 Path 2。

**发生概率极低**（毫秒级竞争），调大 `dead_timeout` 后边界推远，实际影响可忽略。

---

## 6. 参数调优建议

### 推荐配置

```
node_timeout_s     = 2        # 不变，控制隔离速度（2s 感知故障）
node_dead_timeout_s = 30      # 从 3s 调大到 30s
```

效果对比：

```
调整前（dead=3s）：
  t=2s   B 完成隔离（路由切换）✅
  t=3s   A 被自杀（Path 1 窗口=1s，走不到）
  t=3s~  A 走 Path 2 重量级重启，耗时分钟级

调整后（dead=30s）：
  t=2s   B 完成隔离（路由切换）✅（与之前完全相同）
  t=~7s  A 的第一次重试（5s 后）：如果网络已恢复，走 Path 1 ✅
  t=30s  如果 A 始终不恢复，才变 FAILED，触发 Path 2
```

### 各参数职责总结

| 参数 | 控制内容 | 对隔离速度的影响 |
|---|---|---|
| `node_timeout_s` | etcd lease TTL，故障感知速度 | **直接决定**隔离时间 |
| `node_dead_timeout_s` | TIMEOUT→FAILED 窗口，Path 1 容忍时间 | **无影响** |
| `node_dead_timeout_s - node_timeout_s` | Path 1 可用窗口大小 | - |

**增大 `node_dead_timeout_s` 不改变隔离速度，只增加 A 自愈的时间窗口。**

---

## 7. 决策矩阵（供 CCB 讨论）

| 方案 | 描述 | 隔离速度影响 | 闪断处理 | 改动风险 |
|---|---|---|---|---|
| **A（推荐）：调大 dead_timeout** | `node_dead_timeout_s = 30s` | **无影响** | ✅ Path 1 可达 | **零风险**（纯配置）|
| B：开启 `passive_scale_down_ring_recheck_delay_ms` | A 自杀前 re-read etcd 再确认 | 无影响 | ✅ 减少误杀 | 低风险（配置变更）|
| C：改代码加 del_node_info 回滚 | `RecoverMigrationTask` 处理 del_node_info | 无影响 | ✅ 消除边界竞争 | 中风险（代码改动）|
| D：维持现状（dead=3s） | 不做任何变更 | 无影响 | ❌ Path 1 走不到 | 零风险（不变）|

**当前代码即将上线的背景下，推荐方案 A（单一配置调整），可与方案 B 组合使用。**

---

## 8. 相关代码文件索引

| 文件 | 关键函数 | 说明 |
|---|---|---|
| `etcd_cluster_manager.cpp` | `HandleNodeRemoveEvent` | etcd DELETE 处理，TIMEOUT 标记 + NodeTimeoutEvent |
| `etcd_cluster_manager.cpp` | `DemoteTimedOutNode` | TIMEOUT→FAILED 状态转换，用 dead_timeout 计时 |
| `etcd_cluster_manager.cpp` | `CheckConnection` | 路由门卫，IsTimedOut 即拦截 |
| `etcd_cluster_manager.cpp` | `ProcessNetworkRecovery` | A 恢复时的 B 侧处理，TIMEOUT/FAILED 走不同分支 |
| `etcd_store.cpp` | `LaunchKeepAliveThreads` | A 侧 keep-alive 主循环，重试逻辑，SIGKILL 触发点 |
| `etcd_store.cpp` | `AutoCreate` | A 重连后写 etcd，state 从 start/restart 改为 recover |
| `oc_metadata_manager.cpp` | `ProcessWorkerTimeout` | NodeTimeoutEvent 订阅者，changePrimary/removeMeta 两阶段处理 |
| `oc_metadata_manager.cpp` | `ProcessPrimaryCopyByWorkerTimeout` | TIMEOUT 时立即切换 primary，t=2s 完成 |
| `oc_metadata_manager.cpp` | `ProcessWorkerNetworkRecovery` | Path 1 的 B 侧元数据恢复，推 delta + replay ops |
| `oc_notify_worker_manager.cpp` | `NotifyOpToWorker` | 重放积压的 PRIMARY_COPY_INVALID/CACHE_INVALID/DELETE |
| `hash_ring.cpp` | `RecoverMigrationTask` | Path 1 时取消 add_node_info 任务，不处理 del_node_info |
| `common_gflag_define.cpp` | `node_timeout_s`, `node_dead_timeout_s` | 关键参数定义 |
