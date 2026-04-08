# KVClient PlantUML 图

使用 [PlantUML](https://plantuml.com/) 渲染（IDE 插件、`plantuml` CLI 或文档站点）。

**`docs/` 镜像（导航入口）**：读写时序与拓扑见 [`docs/flows/sequences/kv-client/`](../../../docs/flows/sequences/kv-client/README.md)，故障处理配图见 [`docs/reliability/diagrams/kv-client/`](../../../docs/reliability/diagrams/kv-client/README.md)。FEMA 正文见 [`docs/reliability/00-kv-client-fema-index.md`](../../../docs/reliability/00-kv-client-fema-index.md)。本目录与 **`docs` 下副本**内容一致，任选其一渲染。

### 文档导航（本 triage 目录 Markdown 关联）

| 文件 | 说明 |
|------|------|
| [kv_client_triage_doc_map.puml](./kv_client_triage_doc_map.puml) | **plans/kv_client_triage 下各 md 的逻辑分层与指向**（与上级 [README.md](../README.md) 中 Mermaid 图一致） |

### 代码与拓扑

| 文件 | 说明 |
|------|------|
| [kv_client_e2e_flow.puml](./kv_client_e2e_flow.puml) | **KVClient→ObjectClientImpl** 一次读写主路径（活动图）；**图意图与关键参数见下文**，不在 puml 内写 legend，避免导出图片过长 |
| [kv_client_topology_case1_normal.puml](./kv_client_topology_case1_normal.puml) | **Case1**：**① 本地缓存命中**（除 Client→W1 外无 W2/W3 RPC）/ ② 本机非缓存 / ③ 跨节点 box |
| [kv_client_topology_case2_remote_switch.puml](./kv_client_topology_case2_remote_switch.puml) | **Case2**：W1' 上同样分 **① 缓存命中** / ② 本机 / ③ 跨节点；对 Client 仍一次 Get |
| [kv_client_read_path_normal_sequence.puml](./kv_client_read_path_normal_sequence.puml) | **关键读写路径（正常）**：Client→W1 本机 TCP→W2/W3 跨机→URMA→TCP resp→SHM（与 [cases.md](../cases.md)、[KV_CLIENT_CUSTOMER_ALLINONE.md](../KV_CLIENT_CUSTOMER_ALLINONE.md) **第一节 1.3** 对齐） |
| [kv_client_read_path_switch_worker_sequence.puml](./kv_client_read_path_switch_worker_sequence.puml) | **关键读写路径（切流）**：Client→W2 跨机首跳→W3/W4→URMA→SHM |

<a id="fault-handling-diagrams"></a>

### 故障处理与数据可靠性方案配图

对应 [FAULT_HANDLING_AND_DATA_RELIABILITY.md](../FAULT_HANDLING_AND_DATA_RELIABILITY.md) **「第六节」配图与叙事**。

| 文件 | 说明 |
|------|------|
| [fault_handling_ub_plane_and_tcp.puml](./fault_handling_ub_plane_and_tcp.puml) | UB 多平面 / 单平面故障、**~128ms / ~133ms** 与短超时提示 |
| [fault_handling_sdk_etcd_failover.puml](./fault_handling_sdk_etcd_failover.puml) | SDK **~2s** 心跳切流、etcd 侧隔离 **< ~3s**（图中避免 `**` 以利渲染） |
| [kv_client_deploy_interaction.puml](./kv_client_deploy_interaction.puml) | **部署与交互简图**：业务/SDK、Worker 集群、etcd 控制面 |
| [fault_handling_data_reliability.puml](./fault_handling_data_reliability.puml) | 异步持久化、分片迁移与预加载 |
| [fault_handling_etcd_degradation.puml](./fault_handling_etcd_degradation.puml) | etcd 单节点 / 续租失败 / 全挂降级 |

---

## `kv_client_e2e_flow.puml`：图意图与关键参数

以下内容原在图中 `legend` 内，现移至 README，便于读图时对照，并缩短渲染图高度。

### 图意图

- 描述从 **KVClient API** 进入 **ObjectClientImpl** 后，如何串联：**就绪检查 → 选取当前 Worker 连接 → 读或写 RPC**。
- 泳道 **|KVClient|** / **|ObjectClientImpl|** 对应源码 **`kv_client.cpp`** / **`object_client_impl.cpp`**。
- **读路径**与**写路径**在一次调用中通常只执行其一；图中两个 `partition` 并列仅为展示完整逻辑。
- **DispatchKVSync**：若配置了 KVExecutor，业务线程可将闭包投递到专用线程执行。

### 关键参数（与实现相关）

| 项 | 说明 |
|----|------|
| **ConnectOptions** | 建连、Worker 发现、**heartBeatIntervalMs**、**clientDeadTimeoutMs** 等 |
| **ClientState** | `Init` 成功为 **INITIALIZED**，否则 **IsClientReady** 返回 **K_NOT_READY** |
| **currentNode_** | 当前 **IClientWorkerApi**（本机/远端）；切流后指向远端，参见拓扑 **Case2** |
| **Get** | **subTimeoutMs**、**GetParam**（objectKeys、readParams、queryL2Cache、**ubTotalSize** 等）；UB 模式下可能先 **GetObjMetaInfo** 再分批 **Get** |
| **RPC 超时** | **requestTimeoutMs**、**reqTimeoutDuration** 与剩余预算；与 **K_RPC_DEADLINE_EXCEEDED** 相关 |
| **写路径** | **SetParam**（writeMode、ttl、cacheType）；大块可走 SHM/URMA 或 **Publish** |
