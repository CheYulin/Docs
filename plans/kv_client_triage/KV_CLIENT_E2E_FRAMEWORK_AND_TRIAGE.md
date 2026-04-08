# KVC 客户视角 E2E：目标、框架与故障排查

本文把**架构师建议**落实为可执行的文档结构，并与本目录已有材料（自导 playbook、cases、可观测性设计、PlantUML）**对齐**。写作立场：**站在客户视角**——在各类故障下**客户侧会出现什么现象**、**是否影响收入相关 SLA**，以及**如何定界、恢复、协同**。

**客户视角 All-in-One 主文**：[KV_CLIENT_CUSTOMER_ALLINONE.md](./KV_CLIENT_CUSTOMER_ALLINONE.md)。**多角色对齐与测试/横切**：[KV_CLIENT_CUSTOMER_ALLINONE_ROLES.md](./KV_CLIENT_CUSTOMER_ALLINONE_ROLES.md)。

---

## 1. 总目标


| 维度          | 说明                                                                                  |
| ----------- | ----------------------------------------------------------------------------------- |
| **定界与恢复**   | 避免 KVC 相关 **E2E 问题**无法**定界、定位、恢复**；业务侧与华为侧均有**可操作的手段**。                             |
| **客户视角**    | 从客户业务出发：在 **XX 故障**下，客户侧**有什么问题、表现是什么**（成功率、TP99、E2E 失败等）；**不**以「仅内部组件正常」替代客户可感知结果。 |
| **收入与 SLA** | 分析需区分：精排类（常等价 **E2E 失败**）与召排类（常体现 **TP99/长尾**）等，见 [cases.md](./cases.md) 业务架构说明。    |


---

## 2. 围绕目标要做的事（六项）与本目录文档映射


| 事项                        | 含义                 | 本目录中如何体现 / 待补全                                                                                                                                                                                                 |
| ------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **数据系统在故障下如何处理（可靠性行为）**   | 降级、重试、切流、TCP 回退等   | [cases.md](./cases.md) 可靠性设计；[KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md](./KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md) **报告三**（故障模式↔机制）与报告二可恢复性                                                                     |
| **异常时有什么报错信息**            | 日志、告警、可查询字段        | [KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md)（Status、`ds_client_access_*.log` 格式）；Worker / 监控平台侧需与产品对齐清单                                                                                      |
| **需要客户代码做什么**             | Init 顺序、超时、重试、降级策略 | playbook 与 cases 中「客户端未就绪」等；**建议单独维护「客户集成 checklist」**（可收敛到客户交付文档）                                                                                                                                             |
| **需要客户运维做什么**             | 拉日志、扩容、网络侧配合       | [cases.md](./cases.md) DryRun 样例步骤；运维 Runbook 可外链                                                                                                                                                              |
| **出问题后如何定位定界**            | 分层排障               | **本文「4. 故障现象 → 故障分类 → 故障排查」**；[KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md) 全流程；**边界/故障定义/URMA·OS 指标**：[KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md](./KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md) |
| **对周边组件的要求（URMA、uRPC 等）** | 能力、版本、超时语义是否满足     | [REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md)；短超时 vs UB 检测窗口等 **Gap 单列**                                                                                      |


---

## 3. E2E 设计指导（三项要求）


| 要求          | 自检问题                                                                              |
| ----------- | --------------------------------------------------------------------------------- |
| **与客户对齐**   | 现象口径（成功率/P99/E2E）、排障步骤、**错误码/日志字段**是否经客户确认可落地？                                    |
| **代码与设计一致** | `Status`、access log、`GetRsp` 行为是否与文档一致（例如 Get 路径 **NOT_FOUND→access 记 0**）？       |
| **测试覆盖**    | 关键故障场景（切流、跨节点、UB/TCP、短超时）是否有自动化或固定 DryRun？见 [cases.md](./cases.md) 与 DryRun 样例扩展。 |


---

## 4. 故障现象 → 故障分类 → 故障排查（层层手段）

### 4.1 故障现象（客户可观测）

优先从**客户已有或应建设**的观测面记录，避免只描述内部组件：


| 现象大类        | 典型表现                         | 与业务线关系（示例）                     |
| ----------- | ---------------------------- | ------------------------------ |
| **成功率下降**   | KV Get/Set 失败率升、负载均衡器侧业务失败率升 | 精排更易 E2E 失败；召排可能仍「成功」但子路径失败    |
| **时延劣化**    | TP99、Prefill 时延、端到端时延        | 召排常先看 TP99；UB 降 lane 等可能「只伤长尾」 |
| **间歇 / 突发** | 与扩缩容、网络闪断、切流窗口对齐             | 结合运维事件时间线                      |


更全场景见 [cases.md](./cases.md) 业务流程、故障模式与 DryRun 表。

### 4.2 故障分类（需有「手段」支撑）

分类应能通过 **多层证据** 收敛，而不是单一猜测：


| 层次                    | 手段                                                           | 用途                                                |
| --------------------- | ------------------------------------------------------------ | ------------------------------------------------- |
| **L1 业务与网关**          | 负载均衡器 / 监控平台上业务成功率、时延、实例维度                                   | 缩小到**哪类业务请求处理实例**、哪条链路                            |
| **L2 SDK 返回**         | 单次 API 调用返回的 **`Status`**（`StatusCode` 见 `status.h`）、业务日志里打的同一结果 | 应用线程上**即时**可见；区分未就绪、RPC、URMA、未找到等                               |
| **L3 客户端 access log** | `ds_client_access_*.log` 中 **`DS_KV_CLIENT_*`** 行：第一列 **code**、耗时、`timeout`、（若配置）**trace_id** | **同一请求**在落盘上的记录；用于按 handle 聚合、事后 grep、与监控时间对齐 |
| **L4 Worker 运行日志**   | **`datasystem_worker` 运行日志**（如 `*.INFO.log`）、**access / requestout** 等；行内 **trace_id**（与客户端一致时） | 在**已锁定节点**上看 ERROR/WARN；**跨机 / 多 Worker** 时需在集群侧用 **同一 Trace** 关联多条日志（入口 Worker、远端拉数据/Meta 等），避免只盯单机 |
| **L5 基础设施**           | URMA、TCP、交换机、etcd、主机                                         | 错误码无法区分时下沉到本层；见 cases 故障模式表                       |

**L2 与 L3 是什么关系**：对**同一次**同步 API 调用，SDK 写 access 行时通常以**当次** `Status::GetCode()` 等为来源，因此 **L2 的码与 L3 行内 `code` 在绝大多数路径上应一致**；**`trace_id`** 若在该请求上下文中生成/透传，也应与 Worker 侧同一请求的日志字段对齐，便于 **L2/L3/L4 串联**。差异需注意：[KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md) 第 3 节 — **Get 路径 `K_NOT_FOUND` 在 access 里可能被记为 `0`（OK）**，此时 **L2 业务若只看 access 第一列会误判为「无错误」**，必须以 **`Status` 对象**或 **`respMsg`** 为准。异步、批量、或 `last_rc` 与顶层 Status 不一致的路径，以 Playbook 与实现为准。


**故障分类表（与排障手段绑定）** — 示例维度，可随项目扩展：


| 分类         | 子类示例               | 主要证据来源                                                                                                     |
| ---------- | ------------------ | ---------------------------------------------------------------------------------------------------------- |
| 客户端生命周期    | 未 Init、ShutDown 竞态 | L2 `K_NOT_READY`、L3 同行应一致（除未落盘）                                                                                        |
| 连接与心跳      | Worker 重启、切流       | L2 `K_CLIENT_WORKER_DISCONNECT`、L3；L4 Worker 运行日志与 Trace 跨节点关联                                                                         |
| RPC / 网络   | 超时、断连              | L2 `1001/1002`、L3 耗时 vs timeout、L5                                                                         |
| UB / URMA  | 写失败、建链             | L2 `K_URMA_`*、L4 Worker 运行日志中的 URMA/错误串、L5 端口                                                                             |
| 元数据 vs 数据面 | 两阶段失败难区分           | L4 多节点运行日志 + **Trace** 串联 + [REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md) 改进项 |
| 数据与容量      | 未找到、恢复中            | L2 `K_NOT_FOUND` / 恢复码、L3（注意 NOT_FOUND→0）、L4                                                                                  |


### 4.3 故障排查（推荐顺序）

1. **确认现象与范围**：全局 vs 某批实例、精排 vs 召排、是否与发布/网络窗口重叠。
2. **L1 缩小 blast radius**：哪条业务路径、哪个区域。
3. **L2 与 L3**：对同一次调用核对 **Status** 与 **access 行**（code、耗时、timeout、trace_id）；发现不一致时先查 **NOT_FOUND→access 0** 等文档化例外。
4. **L4**：锁定 **入口 Worker `IP:Port`** 后查其 **运行日志**；若涉及跨节点读/写，在日志平台用 **同一 trace_id**（或业务 Trace）在 **多 Worker / Master** 上关联，再对照 `DS_POSIX_*` / requestout 等（**加固：响应中带异常节点信息** 见 REMOTE 文档）。
5. **L5**：若码不足以区分 TCP vs UB，上基础设施指标与抓包。

详细步骤与 grep 示例见 [KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md)。**处理边界、故障定义、URMA/OS 指标分解、客户配合与无法定界时操作**见 [KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md](./KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md)。

---

## 5. 与现有文档的关系


| 文档                                                                                             | 角色                                      |
| ---------------------------------------------------------------------------------------------- | --------------------------------------- |
| 本文                                                                                             | **E2E 目标 + 六项事项 + 现象/分类/排查框架 + 设计三项要求** |
| [KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md)                                 | 实操：错误码、access log、陷阱、mermaid            |
| [cases.md](./cases.md)                                                                         | 业务场景、故障清单、可靠性、DryRun 样例                 |
| [KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md](./KV_CLIENT_CLIENT_PERSPECTIVE_REPORTS.md)           | P99/成功率、部署可恢复性、cases **故障模式↔处理机制**（报告三） |
| [REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md) | 元数据 vs 数据面、UB、短超时语义与 Gap                |
| [diagrams/README.md](./diagrams/README.md)                                                     | 拓扑与 E2E 流程图 + 参数说明                      |


---

## 6. 修订记录

- 初版：纳入架构师六项与 E2E 设计三项要求；补充故障**现象—分类—排查**与客户视角目标，并与本目录其它文档交叉引用。
- 修订：**L4** 明确为 **Worker 运行日志**与 **Trace 跨集群关联**；补充 **L2（SDK 返回）与 L3（access log）** 对同请求通常一致及 **NOT_FOUND→0** 等例外说明。

