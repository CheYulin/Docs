# 远端元数据失败 vs 数据面失败：现状与改进方向

客户问题：访问**远端 Worker 拉元数据失败**、与**拉数据失败**，如何感知？不希望依赖「按 TraceId 全量 grep 运行日志」。

---

## 1. 现状（基于当前客户端实现）

### 1.1 两条路径分别是什么


| 阶段          | 典型行为                                                                                                    | 代码位置（供核对）                                               |
| ----------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **元数据（预取）** | UB 模式下，非 SHM 远端路径会先 RPC `**GetObjMetaInfo`**，用于对象大小、分批（`ubTotalSize`、是否走 `GetBuffersFromWorkerBatched`） | `ObjectClientImpl::GetBuffersFromWorker`（`USE_URMA` 分支） |
| **数据面**     | 随后 `**workerApi->Get`**（`GetReqPb` / `GetRspPb`），含 TCP payload、后续 URMA 等                                | 同上函数后半段                                                 |


远端 Worker 上，元数据与对象数据在服务端也可能分属不同 RPC/阶段；客户端侧对业务暴露的往往是**一次 `Get` 的最终 `Status`**。

### 1.2 为何「只靠最终错误码」往往分不清

1. `**GetObjMetaInfo` 失败时的处理**
  若 `GetObjMetaInfo` 返回错误，当前实现仅 `**LOG(WARNING)`**，**不直接向上返回**；随后仍会调用 `**Get`**（且 `ubTotalSize` 未设置，走默认路径）。  
   因此：  
  - 若后续 `**Get` 也失败**，业务只看到 **一次失败**，无法从返回值判断根因是「元数据 RPC 已失败」还是「数据 RPC 失败」。  
  - 若 `**Get` 碰巧成功**，元数据失败被完全掩盖，仅依赖是否有人看 WARNING 日志。
2. `**GetObjMetaInfo` 与 `Get` 均未进入 KV access log 的独立阶段**
  `KVClient` 的 `DS_KV_CLIENT_GET` 只包一层 `impl_->Get`，**没有**「Meta RPC」「Data RPC」两行拆分，access log **无法按阶段聚合**。
3. **TraceId grep 全量日志不可行**
  即使有 Trace，全集群 grep 成本高；需要的是 **指标维度**、**结构化阶段字段** 或 **嵌套 Span**，而不是纯文本检索。

### 1.3 当前能间接感知的手段（弱）


| 手段                                       | 局限                                |
| ---------------------------------------- | --------------------------------- |
| WARNING 日志含 `GetObjMetaInfo failed`      | 非结构化、易被淹没、与业务监控脱节                 |
| 最终 `Status`（如 `K_RPC_DEADLINE_EXCEEDED`） | 元数据与数据共用同类码，**无法区分阶段**            |
| Worker 侧 `DS_POSIX_GET` 等                | 需关联到**同一请求**，且仍可能不暴露「客户端 Meta 预取」 |


---

## 2. 改进方向（解法分层）

下面按 **投入从小到大** 排列，可组合使用。

### 2.0 分层速览：从「少 grep」到「可观测性默认能力」

**背景**：普通排查往往只能直接利用 **本进程 SDK access log** 与 **当前直连 Worker**；路径一旦涉及 **跨机元数据 / 远端数据面**，根因节点常不在「最先 grep 的那台」，仅靠 **TraceId + 多机 grep** 则 **MTTR 长、规模化不可持续**，且 **同码多因**（如 1001）时易 **误判责任方**。

| 层级 | 侧重点 | 手段（与下文对应） |
|------|--------|-------------------|
| **短期：不改协议** | 把 grep 从「全集群」缩到「已锁定范围」 | 运维上按 [cases.md DryRun](./cases.md)：**负载均衡器 → 业务实例 → 入口 Worker IP:Port**，再带 TraceId 定点查；日志若已进 **ELK/Loki**，用 Trace 索引替代逐机 `grep` 文件。 |
| **中期：观测替代纯文本** | 不靠全量运行日志扫 Trace | **指标按阶段**（§2.1）、**结构化日志字段**（§2.2）、**Trace 子 Span**（§2.3）；与 **access log 分阶段**（§2.5）组合。 |
| **长期：语义与链路透传** | 响应侧可见「哪一跳、哪台机」 | **Status/协议阶段字段**、**Meta 失败是否继续 Get**（§2.4）；**GetRsp / ErrorInfo 带回 HostPort**、内部链路 **逐级带回 Owner**（§4）。 |

**小结**：短期缓解 **排障工序成本**；中期把问题变成 **看板与结构化检索**；长期把「远端难追踪」收进 **协议与默认遥测**，减少对 **人肉 grep** 的依赖。

### 2.1 监控指标（推荐优先）

为客户端（或 SDK 内统一出口）增加 **带标签的计数器/直方图**，例如：

- `kv_client_get_stage_total{stage="meta", result="ok|fail"}`  
- `kv_client_get_stage_total{stage="data", result="ok|fail"}`  
- 可选：`rpc="GetObjMetaInfo"|"Get"`，`worker="local|remote"`（若可安全打标）

**效果**：运维看板直接按阶段拆分成功率/失败率，**无需 grep**。  
**实现要点**：在 `GetObjMetaInfo` 与 `Get` 返回处各打一次（注意 UB 分支才走 Meta）。

### 2.2 结构化日志（替代「全量 grep TraceId」）

- 单条日志内包含固定字段：`trace_id`、`stage=meta|data`、`method`、`status_code`、`host:port`（若已有）。  
- 日志索引到 **ELK/Loki** 后，用 **stage** 过滤即可，无需全表扫。

### 2.3 分布式追踪（Trace）细化

- 为 `**GetObjMetaInfo` RPC** 与 `**Get` RPC** 各建 **子 Span**（或事件），父 Span 为业务 `KV Get`。  
- 这样在 Trace UI 里一眼可见哪一跳红，**不必**依赖 grep 所有运行日志文件。

### 2.4 协议 / Status 语义增强（最强但需版本协调）

任选其一或组合：

- **失败快速返回**：`GetObjMetaInfo` 失败时**不再**继续 `Get`，直接返回 `Status`，`msg` 标明 `stage=meta`（或新错误码子类）。  
  - 优点：业务与监控语义清晰。  
  - 注意：改变现有「降级继续 Get」的行为，需评估 UB 路径是否允许。
- **在 `Get` 响应或 `Status` 中增加可选字段**：`last_successful_stage`、`failed_stage`、`upstream_detail`（需 proto/Status 扩展）。

### 2.5 Access log 扩展（与现有 `DS_KV_CLIENT_GET` 对齐）

- 增加 `**DS_KV_CLIENT_GET_META`**（仅 UB 远端预取时写一行），或  
- 在现有 `RequestParam` 扩展 `outReq` / 专用字段，记录 `phase=meta|data`（需改 `Record` 调用点）。

便于与 **ds_client_access_*.log** 离线分析对齐，仍建议与 **2.1 指标** 同时使用。

---

## 3. 小结


| 问题                      | 现状                                                                                   |
| ----------------------- | ------------------------------------------------------------------------------------ |
| 元数据失败能否从返回值感知？          | **通常不能**；多被 WARNING 记录后继续 `Get`，最终码不区分阶段。                                            |
| 数据失败能否感知？               | **能**（`Get` 的 `Status`），但与元数据失败**混淆**。                                               |
| 不靠 TraceId 全 grep 怎么改进？ | **指标按阶段** + **结构化日志字段** + **Trace 子 Span**；长期可做 **Status/协议阶段字段** 或 **Meta 失败快速返回**。 |


---

## 4. 思路：UB Write 失败后经 GetRsp 回传 Worker 的 Host / IP / Port

### 4.1 现状行为（与「用 Get 响应携带诊断」的关系）

处理读路径 UB 写远端缓冲的逻辑在 **`GetRequest::UbWriteHelper`**（`worker_request_manager.cpp`）：

- `UrmaWritePayload` **成功**：在 `GetRspPb` 里追加 `payload_info` 等，正常完成 UB 路径。
- `UrmaWritePayload` **失败**：打 `LOG(WARNING)`，**把 `Status` 返回给上层**；但在 **`AddObjectToResponse`** 里通过 `RETURN_OK_IF_TRUE(UbWriteHelper(...).IsOk())`：**仅当 UB 成功才提前 return OK**；若 UB 失败则**不 return**，继续走 **`CopyShmUnitToPayloads`（TCP payload 回退）**。
- 因此：**多数情况下客户端仍收到成功的 `Get`**，**不会在 `last_rc` 里看到「UB Write 失败」**；UB 失败只体现在 Worker 日志与额外时延上。

若目标是「**失败也要在 GetRsp 里带 Worker 信息**」，需要先明确产品语义：

| 语义 | 做法 |
|------|------|
| **语义一：TCP 回退后仍算 RPC 成功（现状）** | 在 **`GetRspPb` 增加可选诊断字段**（见下），即使 RPC 成功也带上「曾发生 UB 失败 + 本机 HostPort」，供监控/定界，**不改变**业务成功失败。 |
| **语义二：UB 失败则整次 Get 失败** | 去掉或加开关关闭 TCP 回退；`last_rc` 填 UB 错误码，`ErrorInfoPb` 或扩展字段里带 **HostPort**；客户端可感知失败。 |

### 4.2 协议层是否可放 Worker 信息

- `GetRspPb` 已有 **`ErrorInfoPb last_rc`**（`utils.proto`：`error_code` + `error_msg`）。
- 同文件已有 **`HostPortPb { host, port }`**，可复用，避免各业务自己解析字符串。
- **推荐扩展方式**（需 proto 版本与兼容策略）：
  - 在 **`GetRspPb`** 上增加可选字段，例如：  
    `HostPortPb ub_attempt_worker = N;`（执行 UB Write 的 Worker，一般为当前处理 Get 的节点）  
    `bool ub_write_used_tcp_fallback = N;`  
    或在 **`ErrorInfoPb`** 旁增加 `HostPortPb fault_worker`（仅失败时填写）。
- **谁填**：处理该 RPC 的 Worker 进程已知本机监听地址（配置或 `HostPort`），在 **`UbWriteHelper` 失败分支** 或 **Get 响应组装处** 写入即可；若失败发生在**远端拉数据**的另一节点，还需在内部 RPC 链路上把 **Owner 的 HostPort** 逐级带回（工作量更大，需单独设计）。

### 4.3 客户端/SDK

- `ObjectClientImpl::ProcessGetResponse` 已读 `rsp.last_rc()`；扩展 proto 后在此把 **`HostPort` 附加到 `Status::AppendMsg`** 或映射为新 **Status 子类型/扩展信息**（若对外暴露 C++ API）。
- 业务或 **access log** 即可按「**无需 grep 全集群**」的方式：只看本进程 Get 返回或结构化字段。

### 4.4 小结

- **可行**：在 **`GetRspPb`（或 `ErrorInfoPb`）中增加 `HostPort` 类字段**，在 UB Write 失败路径赋值；是否与 TCP 回退共存由 **上表「语义一 / 语义二」** 的取舍决定。
- **当前默认**：UB 失败**不**经 `last_rc` 返回给客户端（因会 TCP 回退成功）；若客户要「**失败也能从 Get 响应感知**」，需 **语义二** 或在 **语义一** 下增加 **诊断字段**。

### 4.5 短超时（如 20ms）与 UB 故障检测（如 ~128ms）：推荐语义

**与你描述的场景对齐**：客户端 **20ms** 超时与 UB 侧 **~128ms** 量级故障检测/恢复窗口 **不在同一时间尺度**。在此类 SLA 下，若 UB Write 已失败或 UB 路径已判定超时，**再做 TCP 回退既不能保证在 20ms 内返回，也容易与「短超时」产品语义冲突**，因此更合理的语义是：**不再默认 TCP 回退，直接返回错误**（并建议带 **Worker HostPort**），而不是「悄悄回退成功」。

典型矛盾：**业务配置的 RPC / Get 超时很短（例如 20ms）**，而 **UB 侧故障检测或重试窗口可能长达百毫秒量级（例如文档中的 128ms 量级）**。此时若 UB Write 已失败或已消耗大量时间预算，再执行 **TCP payload 回退** 往往存在：

1. **时间预算上不可达**：剩余时间不足以完成拷贝 + 二次传输，客户端侧早已 **`K_RPC_DEADLINE_EXCEEDED`**，Worker 端回退只是在浪费 CPU/带宽。
2. **语义误导**：客户端看到超时，无法区分是「UB 慢/失败」还是「TCP 慢」；若偶发回退成功，P99 与成功率口径与「纯 20ms SLA」不一致。

**推荐语义（与「UB 失败后直接报错、并带 Worker HostPort」一致）：**

| 条件 | 行为 |
|------|------|
| **本次 Get 剩余截止时间**（Worker 侧 `reqTimeoutDuration` / 客户端传入的 `request_timeout` 等）**已不足以覆盖 TCP 回退的保守下界** | **禁止 TCP 回退**，将 UB 失败（或超时）写入 **`GetRspPb.last_rc`**（及可选 **`HostPortPb`**），整次 Get **以失败结束**。 |
| 剩余预算 **明确足够** 完成 TCP 回退 | 可保留现有「UB 失败 → 回退 TCP」作为兼容路径（或由配置项 **`allow_ub_fail_tcp_fallback=true`** 控制）。 |

**要点**：短超时场景下，**「UB 超时报错 / UB Write 失败」不应再默认触发 TCP 回退**；应 **直接报错**，错误信息中携带 **当前 Worker（或故障环节）的 host/ip/port**，便于定界。实现上需在 **`AddObjectToResponse` / `UbWriteHelper` 返回前** 比较 **剩余时间与回退成本**，并与产品约定的 **20ms vs 128ms** 关系统一写进配置或文档。

### 4.6 代码锚点

- `src/datasystem/worker/object_cache/worker_request_manager.cpp`：`GetRequest::UbWriteHelper`、`AddObjectToResponse`。  
- `src/datasystem/protos/object_posix.proto`：`GetRspPb`、`GetReqPb`；`src/datasystem/protos/utils.proto`：`ErrorInfoPb`、`HostPortPb`。

---

## 5. 代码锚点（元数据 / Meta 预取）

- 元数据预取与失败分支：`src/datasystem/client/object_cache/object_client_impl.cpp` → `GetBuffersFromWorker`（`GetObjMetaInfo` 失败仅 `LOG(WARNING)` 后仍调用 `Get`）。  
- 远端 RPC：`ClientWorkerRemoteApi::Get` / `GetObjMetaInfo`（及 `PreGet` 内 `ubTotalSize` 相关逻辑）。

