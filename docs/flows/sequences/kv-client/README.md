# KV Client 序列图与拓扑（PlantUML）

与 [`docs/reliability/01-architecture-and-paths.md`](../../../reliability/01-architecture-and-paths.md) 中「关键读写路径」及 [`docs/observable/02-call-chain-and-syscalls.md`](../../../observable/02-call-chain-and-syscalls.md) 调用链一致。使用 [PlantUML](https://plantuml.com/) 渲染。

| 文件 | 说明 |
|------|------|
| [kv_client_read_path_normal_sequence.puml](kv_client_read_path_normal_sequence.puml) | **正常**读写路径步骤 1～6：Client→W1 本机 TCP→W2/W3→URMA→TCP resp→SHM |
| [kv_client_read_path_switch_worker_sequence.puml](kv_client_read_path_switch_worker_sequence.puml) | **切流**后路径：Client→W2 跨机首跳 |
| [kv_client_topology_case1_normal.puml](kv_client_topology_case1_normal.puml) | Case1：本地命中 / 本机 / 跨节点 |
| [kv_client_topology_case2_remote_switch.puml](kv_client_topology_case2_remote_switch.puml) | Case2：切流后拓扑 |
| [kv_client_e2e_flow.puml](kv_client_e2e_flow.puml) | KVClient→ObjectClientImpl 活动图；参数说明见原 [`plans/kv_client_triage/diagrams/README.md`](../../../../plans/kv_client_triage/diagrams/README.md) |
| [kv_client_deploy_interaction.puml](kv_client_deploy_interaction.puml) | 业务/SDK、Worker、etcd 控制面 |
| [scaling_scale_down_sequences.puml](scaling_scale_down_sequences.puml) | K_SCALING / K_SCALE_DOWN 时序（与 operations 长文一致） |

**故障处理类配图**（UB/etcd/SDK 等）见 [`../../reliability/diagrams/`](../../reliability/diagrams/)。

**故障现象 / 责任边界 / 数据系统内模块**（与上表时序图对照）：[`../../observable/kv-场景-故障分类与责任边界.md`](../../observable/kv-场景-故障分类与责任边界.md)。
