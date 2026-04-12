# 不变量与策略提纲（跨文档）

本页定义“出现任何故障时仍应成立”的原则，用于评审变更与排障复盘。  
总入口见 [README.md](README.md) 与 [00-kv-client-fema-index.md](00-kv-client-fema-index.md)。

## 1) 超时与重试边界

- 超时参数必须与链路实际量级匹配，避免把可恢复抖动放大成业务失败。
- 重试应有边界与退避，避免在故障窗口形成自激流量。
- 评估口径统一到 [00-kv-client-fema-timing-and-sli.md](00-kv-client-fema-timing-and-sli.md)。

## 2) 错误语义分层

- 1002 等通用码不直接等价于单一根因，必须二次下钻到传输/URMA/业务语义层。
- 客户端可见状态码解释以 [00-kv-client-visible-status-codes.md](00-kv-client-visible-status-codes.md) 为准。
- 证据链优先使用 [deep-dives/client-status-codes-evidence-chain.md](deep-dives/client-status-codes-evidence-chain.md)。

## 3) 可观测性完整性

- 每次故障定位至少同时具备：应用日志、access log、关键指标三类证据。
- 资源与运行状态采集保持可用，避免“有告警无上下文”。
- 资源观测与字段解释见 [operations/kv-client-worker-resource-log-triage.md](operations/kv-client-worker-resource-log-triage.md)。

## 4) 变更窗口可靠性

- 扩缩容、发布、拓扑变更期间，默认按“风险窗口”执行分层巡检。
- 31/32 等状态必须结合请求路径和对象级状态解释，避免误告或漏告。
- 执行手册见 [operations/kv-client-ops-deploy-scaling-failure-triage.md](operations/kv-client-ops-deploy-scaling-failure-triage.md) 与 [operations/kv-client-scaling-scale-down-client-paths.md](operations/kv-client-scaling-scale-down-client-paths.md)。

## 5) 幂等与回滚约束

- 写路径重试必须满足业务幂等约束，否则需要应用层补偿策略。
- 可靠性改造默认提供灰度与回滚开关，先低流量验证再全量。
- 高风险改造参考 [deep-dives/client-lock-in-rpc-logging-bthread-blocking.md](deep-dives/client-lock-in-rpc-logging-bthread-blocking.md) 中的分阶段治理和回滚原则。
