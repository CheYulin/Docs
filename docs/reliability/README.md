# Reliability Docs Index

本目录聚焦 KV Client 可靠性文档，采用“主线必读 + 操作手册 + 专项深挖 + 参考资料 + 历史归档”的结构，避免重复阅读与信息分散。

## 1) 主线必读（core）

按这个顺序阅读即可建立全局心智模型：

1. [00-kv-client-fema-index.md](00-kv-client-fema-index.md)
2. [00-kv-client-fema-scenarios-failure-modes.md](00-kv-client-fema-scenarios-failure-modes.md)
3. [00-kv-client-fema-read-paths-reliability.md](00-kv-client-fema-read-paths-reliability.md)
4. [00-kv-client-fema-timing-and-sli.md](00-kv-client-fema-timing-and-sli.md)
5. [00-kv-client-visible-status-codes.md](00-kv-client-visible-status-codes.md)
6. [定位定界-故障树-代码证据与告警设计.md](定位定界-故障树-代码证据与告警设计.md)

## 2) 操作手册（playbooks）

值班与排障优先使用 `operations/`：

- [operations/kv-client-ops-deploy-scaling-failure-triage.md](operations/kv-client-ops-deploy-scaling-failure-triage.md)
- [operations/kv-client-rpc-unavailable-triggers.md](operations/kv-client-rpc-unavailable-triggers.md)
- [operations/kv-client-worker-resource-log-triage.md](operations/kv-client-worker-resource-log-triage.md)
- [operations/kv-client-scaling-scale-down-client-paths.md](operations/kv-client-scaling-scale-down-client-paths.md)

## 3) 专项深挖（deep-dives）

以下文档保留专题价值，不作为首次阅读必需：

- [deep-dives/README.md](deep-dives/README.md)

- [deep-dives/client-lock-in-rpc-logging-bthread-blocking.md](deep-dives/client-lock-in-rpc-logging-bthread-blocking.md)
- [deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md](deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md)
- [deep-dives/timeout-params-restart-vs-scale-down.md](deep-dives/timeout-params-restart-vs-scale-down.md)
- [deep-dives/故障码树状梳理-URMA与TCP-fd共享内存.md](deep-dives/故障码树状梳理-URMA与TCP-fd共享内存.md)
- [deep-dives/client-status-codes-evidence-chain.md](deep-dives/client-status-codes-evidence-chain.md)

## 4) 参考资料（references）

- [00-reference-openyuanrong-official.md](00-reference-openyuanrong-official.md)

## 5) 图与时序（diagrams）

- [diagrams/kv-client/README.md](diagrams/kv-client/README.md)
- 读写主路径与拓扑图在 [`../flows/sequences/kv-client/`](../flows/sequences/kv-client/)

## 6) 历史归档（archive）

`archive/` 存放历史摘要、镜像迁移文档、以及不再作为主链路的重复内容。  
当前归档：

- [archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md](archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md)

## 7) 维护约定

- 主线新增文档时，必须同时更新本索引与 `00-kv-client-fema-index.md`。
- 若文档仅是“摘要重述”且已被操作手册覆盖，优先放入 `archive/`。
- `failure-modes.md` 与 `invariants.md` 维护为“跨文档提纲页”，不重复拷贝大段细节。
