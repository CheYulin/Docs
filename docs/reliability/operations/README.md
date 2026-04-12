# Reliability Playbooks (KV Client)

本目录是值班与排障场景的可执行手册入口，优先回答“现在该看什么日志、做什么动作、如何定界责任域”。

| 文档 | 说明 |
|------|------|
| [kv-client-ops-deploy-scaling-failure-triage.md](kv-client-ops-deploy-scaling-failure-triage.md) | 部署/扩缩容失败：L0-L5、冷启动、运行中变更 |
| [kv-client-worker-resource-log-triage.md](kv-client-worker-resource-log-triage.md) | `resource.log` 结构、采集开关、与官方日志附录对照 |
| [kv-client-scaling-scale-down-client-paths.md](kv-client-scaling-scale-down-client-paths.md) | 31/32 客户端可见性、重试语义与误判规避 |
| [kv-client-rpc-unavailable-triggers.md](kv-client-rpc-unavailable-triggers.md) | 1002 的触发分层与 URMA/传输层区分 |

**PlantUML**：[`scaling_scale_down_sequences.puml`](../../flows/sequences/kv-client/scaling_scale_down_sequences.puml)

关联总索引：[`../README.md`](../README.md)。
