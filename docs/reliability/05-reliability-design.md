# 05 · 可靠性设计方案与不变量

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp` | `HandleNodeRemoveEvent` / `CheckConnection` / `DemoteTimedOutNode` |
| `src/datasystem/worker/hash_ring/hash_ring.cpp` | hash ring 与 del_node_info 处理 |
| `src/datasystem/worker/object_cache/oc_metadata_manager.cpp` | `ProcessWorkerTimeout` / `ProcessPrimaryCopyByWorkerTimeout` / `ProcessWorkerNetworkRecovery` |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | `HealthCheck` → 31 |
| `src/datasystem/client/listen_worker.cpp` | Client 心跳超时 → 23 |
| `src/datasystem/common/util/rpc_util.h` | `RetryOnError` 重试间隔 `1, 5, 50, 200, 1000, 5000` ms |

故障处理配图：[diagrams/kv-client/](diagrams/kv-client/)

---

## 1. 通信故障处理方案

| 故障大类 | 链路 / 子类 | 场景简述 | 故障处理机制 | 业务影响（示例） |
|----------|-------------|----------|--------------|------------------|
| 通信链路故障 | TCP 链路 | TCP 单口故障（端口切换约 100ms） | 请求超时内 RPC 重试；客户 `timeout=20ms` 时约 1~2 次超时重试机会；TCP 重试间隔 `1, 5, 50, 200, …5000 ms`；最小 RPC 时间预算 2ms，剩余时间不足则读写退出 | 切换窗口内读写报错（约 1/n 元数据失败等）；成功率、P99 劣化；切换完成后恢复 |
| 通信链路故障 | TCP 链路 | TCP 网络抖动 | 自动失败重试后成功；时延增加 RPC 重试时间（约 0.2ms）+ 等待重试（约 1~6ms） | 时延劣化 |
| 通信链路故障 | TCP 链路 | TCP 两口故障、交换机等 | TCP 超时失败；端口恢复后业务恢复 | 故障期失败；恢复后正常 |
| UB 链路故障 | UB | 单 UB 平面故障 | 故障检测后未恢复前可走 TCP 回退；未检测到时随用户超时（如 20ms）报错，硬件侧感知约 128ms | 非 Jetty 类：约 133ms 内检测与平面切换；切换瞬间请求可能失败；切换后带宽可能减半；平面恢复后 URMA 可自愈 |
| UB 链路故障 | Jetty 不可用 | 拥塞、闪断、双 UB 平面故障等 | 过程中异常可 20ms 超时报错；Jetty 不可用则重连；无可用 Jetty 时可切 TCP（例：大 payload 时延与 TCP 相当）；平面恢复后回切 | 短时超时、建链；TCP 降级时延上升 |

---

## 2. 整体可靠性方案

| 故障大类 | 细化分类 | 故障处理机制 | 业务影响（示例） |
|----------|----------|--------------|------------------|
| 系统亚健康（高负载） | CPU、UB、HCCS、内存带宽占用高 | （依部署与调优） | （依业务） |
| 系统资源故障 | 内存故障 | 进程 Crash，组件故障隔离 | SDK 同组件切流；KVC Worker Crash 隔离，影响同 Worker 上组件 |
| 组件、节点故障 | KVC SDK 故障 | 自动清理 SDK 引用共享内存 | 不影响其他业务实例；SHM 资源释放 |
| 组件、节点故障 | KVC Worker 故障 | etcd 心跳超时（约 2s）→ 隔离与元数据重分布；SDK 心跳检测切流（约 2s），恢复后回切 | 检测隔离窗口内读写失败；切流后恢复；时延可能增加（如 UB 约 1ms）；二级存储足够时可恢复数据，否则丢弃；大规模恢复耗时与带宽相关 |
| 组件、节点故障 | 异步持久化与恢复 | 分片迁移后预加载 | 恢复过程中访问可能失败；恢复完成后数据可访问性依容量与策略 |
| 第三方组件故障 | etcd 集群故障 | KVC 降级；数据面读写删除通常不受影响；与 etcd 重连直至恢复 | 服务发现、扩缩容、故障隔离等能力依赖 etcd 恢复 |
| 二级存储故障 | 持久化 / 加载失败 | 当前策略有限 | 可靠性风险；可用性可能仍维持；恢复后持久化功能可恢复 |

---

## 3. 故障检测与隔离的时间分解

对应代码：`etcd_cluster_manager.cpp::HandleNodeRemoveEvent` / `DemoteTimedOutNode` / `CheckConnection`；`oc_metadata_manager.cpp::ProcessPrimaryCopyByWorkerTimeout`。

```text
node_timeout_s      →  etcd lease TTL
                       lease 到期 → etcd DELETE → 其它 Worker 收到事件 → 【隔离生效】

node_dead_timeout_s →  从 lease 到期起，等多久把 A 判死
                       超过该时间 → TIMEOUT → FAILED → 写 del_node_info → 【A 自杀】
```

**关键结论**（详细分析见 [deep-dives/etcd-isolation-and-recovery.md](deep-dives/etcd-isolation-and-recovery.md)）：

- **故障隔离（停止发请求 + 路由切换）在 `t = node_timeout_s` 完成**，与 `node_dead_timeout_s` 无关。`CheckConnection` 在 `IsTimedOut()` 时就拦截；`ProcessPrimaryCopyByWorkerTimeout` 在 TIMEOUT 阶段触发 primary 重选。
- **`node_dead_timeout_s` 只控制 TIMEOUT → FAILED 的等待窗口**，决定 Path 1（轻量重连）的可用时间。
- Path 1 窗口 = `node_dead_timeout_s - node_timeout_s`；若小于 A 的重试间隔（硬编码 5s），Path 1 走不到，只能走 Path 2（SIGKILL + 重启）。

---

## 4. 恢复路径：Path 1（轻量重连） vs Path 2（重启）

| 维度 | Path 1（轻量重连） | Path 2（自杀重启） |
|---|---|---|
| A 进程 | **存活，无重启** | SIGKILL 后重启 |
| etcd state | `"recover"` | `"restart"` |
| 元数据同步 | **B 推 delta** | A 拉全量 |
| RocksDB | 不动 | 清空重建 |
| 恢复耗时 | **秒级** | 分钟级 |
| 触发条件 | A 在 dead_timeout 前重连 | A 超过 dead_timeout 或 ring 中被写入 `del_node_info` |

参数调优建议：生产环境 `node_timeout_s=2s, node_dead_timeout_s=30s` 可打通 Path 1，零代码改动解决闪断误杀；详见 deep-dive 对应文档。

---

## 5. 客户端切流与重试

对应代码：`client/listen_worker.cpp`、`client/object_cache/client_worker_api/client_worker_remote_api.cpp`。

- **SDK 心跳超时约 2s** → 触发切流，连接新 Worker（路径见 [01 § 2.2](01-architecture-and-paths.md)）
- **`RetryOnError` 重试间隔**：`1, 5, 50, 200, 1000, 5000` ms
- **重试继续条件**：剩余时间 ≥ `minOnceRpcTimeoutMs` (50ms)；否则直接结束
- **重试集合**（`RETRY_ERROR_CODE`）：`{K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED, K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY}`
  - `MultiPublish` 额外加入 `K_SCALING`
  - `Get` 的 lambda 通过 `IsRpcTimeoutOrTryAgain` 裁剪
  - `RegisterClient` 把 `K_SERVER_FD_CLOSED` 改写为 `K_TRY_AGAIN` 后重试

---

## 6. 不变量（设计原则）

这些原则在任何故障下都应成立，变更评审与排障复盘需回扣：

### 6.1 超时与重试边界

- 超时参数必须与链路实际量级匹配，避免把可恢复抖动放大成业务失败。
- 重试应有边界与退避，避免在故障窗口形成自激流量。
- 短超时（5ms / 20ms）实际上是"快速失败策略"，不是"重试容错策略"；详见 [deep-dives/timeout-and-latency-budget.md](deep-dives/timeout-and-latency-budget.md)。

### 6.2 错误语义分层

- `K_RPC_UNAVAILABLE` (1002) 等通用码不直接等价于单一根因，必须二次下钻到传输 / URMA / 业务语义层。
- 客户端可见状态码解释以 [03-status-codes.md](03-status-codes.md) 为准。
- 证据链优先看 [04-fault-tree.md](04-fault-tree.md)。

### 6.3 可观测性完整性

- 每次故障定位至少同时具备：**应用日志、access log、关键指标** 三类证据。
- 资源与运行状态采集保持可用，避免"有告警无上下文"。
- Worker 资源观测字段以源码 `res_metrics.def` 顺序为准；运维侧读法见 [06-playbook.md § 4](06-playbook.md)。

### 6.4 变更窗口可靠性

- 扩缩容、发布、拓扑变更期间，默认按"风险窗口"执行分层巡检。
- 31 / 32 等状态必须结合请求路径和对象级状态解释，避免误告或漏告。
- 产品语义：扩缩容对用户是"元数据重定向、不中断"；31/32 **不是**业务侧 API 契约，不应让终端用户为其设计分支。

### 6.5 幂等与回滚约束

- 写路径重试必须满足业务幂等约束，否则需要应用层补偿策略。
- 可靠性改造默认提供灰度与回滚开关，先低流量验证再全量。
- 持锁 RPC / 持锁日志 flush 的治理需分阶段、可回滚；参见 [deep-dives/client-lock-rpc-logging.md](deep-dives/client-lock-rpc-logging.md)。
