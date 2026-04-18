# KV Client 故障处理 PlantUML 配图

与 [`../../05-reliability-design.md`](../../05-reliability-design.md) 和 [`../../01-architecture-and-paths.md`](../../01-architecture-and-paths.md) 对照阅读。

| 文件 | 说明 |
|------|------|
| [kv_client_triage_doc_map.puml](kv_client_triage_doc_map.puml) | 故障处理文档的逻辑分层（历史图，保留作参考） |
| [fault_handling_ub_plane_and_tcp.puml](fault_handling_ub_plane_and_tcp.puml) | UB 多平面 / 单平面、~128ms / ~133ms 与短超时 |
| [fault_handling_sdk_etcd_failover.puml](fault_handling_sdk_etcd_failover.puml) | SDK ~2s 切流、etcd 隔离 ~3s 量级 |
| [fault_handling_data_reliability.puml](fault_handling_data_reliability.puml) | 异步持久化、分片迁移与预加载 |
| [fault_handling_etcd_degradation.puml](fault_handling_etcd_degradation.puml) | etcd 单节点 / 续租失败 / 全挂降级 |

**读写主路径时序**：[`../../../flows/sequences/kv-client/`](../../../flows/sequences/kv-client/)
