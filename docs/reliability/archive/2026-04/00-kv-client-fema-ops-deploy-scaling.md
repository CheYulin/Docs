# KV Client FEMA：运维部署与扩缩容操作失败（摘要）

> 归档时间：2026-04。  
> 归档原因：该摘要内容已被 `operations/` 下操作手册覆盖，不再作为主线必读。  
> 当前推荐入口：[`../../operations/kv-client-ops-deploy-scaling-failure-triage.md`](../../operations/kv-client-ops-deploy-scaling-failure-triage.md) 与 [`../../README.md`](../../README.md)。

---

## 冷启动与运行中变更（与业务流程编号对齐）

**冷启动场景（业务流程 1–3 及本机无 Worker 的 2/5/6）**：**业务进程集成 SDK** 与 **KVC Worker** 同时纳入发布编排；**`KVClient::Init` 失败** 或 **建链 / 首心跳** 失败时，往往 **还没有** `DS_KV_CLIENT_*` access 行，需看 **客户端进程日志**。**本机无 Worker** 时 `Init` 必须连 **远端 Worker**（静态地址或 **服务发现**），对 **网络策略、`connectTimeoutMs`** 更敏感，易与「配错 localhost」混淆。

**运行中变更场景（业务流程 7–10）**：业务实例或 **KVC Worker** 扩缩容及 **发布窗口** 内，写失败、**32** 持续、**31**、**25**、或与 **etcd 维护** 重叠的成功率/P99 异常。

**与可靠性方案的关系**：控制面依赖 **etcd** 与 **HashRing/元数据迁移**；**etcd 全挂或长期不可写** 时，方案明确 **扩缩容与故障隔离受阻**，数据面在缓存语义下可能仍部分可用（见 [`FAULT_HANDLING_AND_DATA_RELIABILITY.md`](../../../../plans/kv_client_triage/FAULT_HANDLING_AND_DATA_RELIABILITY.md) **第四节** 控制面降级与扩缩容预期）。冷启动期若 **服务发现依赖 etcd**，控制面未就绪也会导致 **选点失败**。

---

## 推荐排查顺序（摘要）

- **若 Init 即失败** -> [../../operations/kv-client-ops-deploy-scaling-failure-triage.md](../../operations/kv-client-ops-deploy-scaling-failure-triage.md) 的「0. 部署冷启动」
- **若运行期异常** -> 先读该文「排查前置」（监控 + access log + 应用日志 + etcd 大盘），再按「2. 运行中变更」步骤；与 [`KV_CLIENT_TRIAGE_PLAYBOOK.md`](../../../../plans/kv_client_triage/KV_CLIENT_TRIAGE_PLAYBOOK.md) 的 §4.2 / §10 合并使用

---

## 相关运维长文（`docs/reliability/operations/`）

| 文档 | 说明 |
|------|------|
| [../../operations/kv-client-ops-deploy-scaling-failure-triage.md](../../operations/kv-client-ops-deploy-scaling-failure-triage.md) | 排查前置 L0-L5；部署冷启动；运行中变更 |
| [../../operations/kv-client-worker-resource-log-triage.md](../../operations/kv-client-worker-resource-log-triage.md) | `resource.log` 与官方日志附录对照 |
| [../../operations/kv-client-scaling-scale-down-client-paths.md](../../operations/kv-client-scaling-scale-down-client-paths.md) | 31/32 客户端可见性与重试 |
| [../../operations/kv-client-rpc-unavailable-triggers.md](../../operations/kv-client-rpc-unavailable-triggers.md) | 1002 与 URMA 码分层 |
