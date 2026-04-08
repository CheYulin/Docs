# Fault Handling and Data Reliability Plan

> 中文原标题：**故障处理及数据可靠性方案**（章节结构保留）。

# 一、通信故障处理方案：针对可恢复的链路故障，在时延约束内有限重试可用

## （一）针对UB链路故障和拥塞处理

- 针对UB链路拥塞，利用URMA多平面多路径传输能力（双IO Die 4端口），充分利用带宽；

- 针对单平面故障，利用 URMA **多平面切换**；**端到端**检测与切换整体 **~133ms（128+5ms）** 量级（与 cases 一致），并支持 **TCP 兜底**；配图见 [diagrams/fault_handling_ub_plane_and_tcp.puml](./diagrams/fault_handling_ub_plane_and_tcp.puml)；

## （二）针对IPC、RPC over TCP的故障处理

- 时延约束范围内（用户可在读写接口中配置，例如10秒）有限重试，超时返回报错;

|故障分类|已有处理逻辑|方案 & 需求|业务效果|
|---|---|---|---|
|① IPC 链路故障|• IPC访问有限重试；• UDS的IPC故障走TCP流程兜底；|• 功能已具备；|• 读写可用，保障成功率|
|② RPC 链路故障|• 自动重试，直到请求超时，返回错误码；• etcd续租失败触发被动缩容；|• 功能已具备；|• 读写可用，保障成功率|
|③ UB 链路拥塞|• 超时请求返回报错，避免不必要带宽占用；|• 【URMA】URMA支持RM+CTP模式多平面多路径传输；|• 读取负载均衡，8MB读取P99 2ms；|
|③ UB 链路故障|• 自动重试，直到请求超时，返回错误码；|• 【元戎】UB 链路全故障下，数据系统支持 **TCP 兜底**；• 【URMA】单平面故障下启用 **多平面切换**；**端到端**上，硬件侧平面故障感知约 **128ms 量级**，检测与平面切换整体 **~133ms（128+5ms）** 量级（与 [cases.md](./cases.md) 可靠性表一致）；**非**「5ms 内端到端完成」——原「5ms 内平面切换」表述易误解，已按上述分段与 [REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md) 短超时分析对齐；|• 故障识别后平面切换与兜底，保障读取成功率；|
# 二、组件故障处理方案：秒级故障隔离，SDK自动故障切流

## （一）节点或者KV Cache worker POD故障处理

- 故障切流：SDK自动故障切流，秒级保证读写访问可用；

- 故障隔离：基于etcd租约的故障检测机制，秒级快速隔离故障节点；

## （二）KVC Worker故障处理

1. 故障切流：推理实例KVC SDK通过心跳超时（2s，可调）检测KVC worker故障，自动切换到其他节点KVC Worker，保证后续读写可用；

2. 故障检测 & 隔离：KVC worker故障后与ETCD心跳超时（2s，可调），其他KVC worker感知后进行故障隔离（< 3s）；

## （三）KVC Worker故障对业务的影响

1. 故障节点影响：推理实例KVC SDK切换前请求会失败，切换后请求恢复正常；

2. 其他节点影响：故障发生到故障隔离期间任意路由到故障节点的请求会发生失败，故障节点隔离后请求恢复正常；

# 三、数据可靠性方案：数据异步持久化，自动预加载恢复

针对组件故障缓存丢失问题处理：KV Cache通过对接二级存储实现数据可靠性。

- 异步数据持久化：各worker异步写数据到各自的二级存储目录，KVC数据按照分片策略聚合写入不同文件，并周期性Compact整理；

- 自动数据加载恢复：故障隔离后，将数据分片分配到目的节点，自动预加载恢复；

## （一）对业务影响

- 未持久化数据少量丢失；故障节点数据加载完成前，读取报错；加载完成后，可正常读取；

- 支持写二级存储流量、内存控制

- 被删除数据从异步任务删除

## （二）数据自动预加载恢复

故障隔离后，系统自动将故障节点的数据分片分配至正常节点，并完成预加载，加载完成后即可恢复正常读写。

# 四、第三方组件故障处理方案：etcd集群故障时，服务降级，依赖运维恢复

针对etcd集群故障处理：

- etcd集群故障下，无KVC组件故障发生情况下，利用各KVC组件缓存的集群信息，保证已有读写可用性；过程中，扩缩容、故障隔离受影响；

- etcd集群故障恢复后，扩缩容、故障隔离功能自动恢复正常；

|故障分类|已有处理逻辑|业务效果|
|---|---|---|
|单个ETCD故障|• 利用etcd集群本身的高可用不受影响|• 无影响|
|所有ETCD故障|• KVC组件降级运行，数据面读写删除操作不受到影响• KVC组件与etcd重新建链，直至ETCD故障恢复|• 故障期间，扩缩容、故障隔离功能受影响• 无单点故障时，数据读写保持可用• etcd集群恢复后，可正常扩缩容、故障隔离|
|ETCD单链路故障|• KVC Worker同etcd续租失败，触发故障隔离|• 对租约失败的节点做故障隔离|

---

## 五、与 `kv_client_triage` 分析文档的对齐与分歧

本节的 triage 材料指本目录下 [cases.md](./cases.md)、[KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md](./KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md)、[KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md](./KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md)、[REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md) 等 **客户端视角定界与可观测性** 文档，与上文 **系统方案/能力** 叙述对照。

### 5.1 一致点（可交叉引用）

| 主题 | 说明 |
|------|------|
| **链路** | UB 多平面、单平面故障下的 **TCP 兜底/回退**、RPC 在超时前有限重试，与 cases **可靠性设计**、报告三 **故障模式 ↔ 处理机制** 一致。 |
| **组件** | SDK **~2s 心跳**、**秒级**隔离/切流、切换窗口内请求可能失败，与 cases **时间指标**（2s/3s、`T_剔除`）及 **2/N 粗算** 叙述一致。 |
| **数据** | 二级存储、异步持久化、故障后 **预加载恢复**、未落盘数据可能丢失，与 cases **Worker 故障**、报告二 **可恢复性** 一致。 |
| **etcd** | 全集群 etcd 故障时 **降级**、控制面（扩缩容/隔离）受限、数据面在方案所述前提下保持可用，与 triage 中 **KVC 平台（含元数据）** 边界可兼容（仍以现网版本与配置为准）。 |

### 5.2 分歧或需统一口径处

| 条目 | 本方案表述 | triage / cases 侧表述 | 建议 |
|------|------------|------------------------|------|
| **UB 平面切换时延** | ~~「5ms 内平面切换」~~（已 **不再** 作为端到端表述；正文与上表已改） | cases：**~128ms** 硬件感知；整体 **~133ms（128+5ms）** | **+5ms** 为 cases 表中与整体窗口一同出现的 **分量**，**不等于**「用户可见 5ms 内完成全部分检测与切换」。排障以 **cases + REMOTE** 为准。 |
| **用户超时示例** | 读写接口可配，例如 **10 秒** | cases/REMOTE 常用 **20ms** 作 **短 SLA** 示例 | **不矛盾**（不同部署与产品约束）；对外文档应 **显式区分**「长超时」与「短超时」场景，避免排障时混用口径。 |
| **性能数字** | 「8MB 读取 P99 **2ms**」等 | triage **不写**该类业务效果指标，以 **可观测与定界** 为主 | 非分歧；triage 不替代 **性能/容量** 承诺文档。 |
| **可观测性与定界** | 本方案不写 **StatusCode、access log、L1–L5** | triage 强调 **同码多因**、**远端多跳**、**meta/data 难区分**、**兜底流程** | **侧重不同**：本方案描述 **能力**；triage 描述 **客户侧如何观测与升级**。二者互补，非互斥。 |

### 5.3 小结

- UB 时延口径已在本方案 **§一 表格与条目** 与 **cases** 对齐（**~128ms / ~133ms**）；勿再单独对外使用「5ms 端到端切换」类表述。
- **排障与 SLA** 以 **cases + REMOTE + SCOPE** 为准；本文件定位为 **可靠性能力/方案** 归档，**§五** 便于与 triage **索引对照**。

---

## 六、配图（PlantUML）

| 章节 | 文件 | 说明 |
|------|------|------|
| 一、通信 / UB | [diagrams/fault_handling_ub_plane_and_tcp.puml](./diagrams/fault_handling_ub_plane_and_tcp.puml) | 多平面、单平面故障、**128ms/133ms** 与短超时提示 |
| 二、组件切流 | [diagrams/fault_handling_sdk_etcd_failover.puml](./diagrams/fault_handling_sdk_etcd_failover.puml) | SDK ~2s 心跳、etcd 隔离 **< ~3s** |
| 三、数据可靠性 | [diagrams/fault_handling_data_reliability.puml](./diagrams/fault_handling_data_reliability.puml) | 异步持久化、分片迁移与预加载 |
| 四、etcd | [diagrams/fault_handling_etcd_degradation.puml](./diagrams/fault_handling_etcd_degradation.puml) | 单节点 / 续租 / 全挂降级 |

**索引**： [diagrams/README.md](./diagrams/README.md#fault-handling-diagrams)。
