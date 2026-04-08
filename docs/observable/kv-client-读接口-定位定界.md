# KV Client 读接口定位定界（基于 `kv_client.h`）

本文聚焦 `kv_client.h` 的读接口，按 **SDK 侧 -> Worker 侧** 串联调用链、错误码、日志与排查树。

配套：
- `docs/observable/sdk-init-定位定界.md`
- `docs/observable/kv-client-写接口-定位定界.md`
- `docs/observable/kv-场景-故障分类与责任边界.md`

---

## 1. 读接口范围

- 单 key：
  - `Get(const std::string&, std::string&, int32_t)`
  - `Get(const std::string&, Optional<ReadOnlyBuffer>&, int32_t)`
  - `Get(const std::string&, Optional<Buffer>&, int32_t)`
- 多 key：
  - `Get(const std::vector<std::string>&, std::vector<std::string>&, int32_t)`
  - `Get(const std::vector<std::string>&, std::vector<Optional<ReadOnlyBuffer>>&, int32_t)`
  - `Get(const std::vector<std::string>&, std::vector<Optional<Buffer>>&, int32_t)`
- 偏移读：
  - `Read(const std::vector<ReadParam>&, std::vector<Optional<ReadOnlyBuffer>>&)`

---

## 2. 调用链（SDK -> Worker）

以 `KVClient::Get(key, string&)` 为例：

```332:353:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/kv_cache/kv_client.cpp
Status KVClient::Get(const std::string &key, std::string &val, int32_t timeoutMs)
{
    return DispatchKVSync(
        [&]() {
            ...
            Status rc = impl_->GetWithLatch({ key }, vals, timeoutMs, buffers, dataSize);
            ...
            return rc;
        },
        "KVClient::GetString");
}
```

下钻链路：
- `ObjectClientImpl::GetWithLatch` -> `ObjectClientImpl::Get`
- `ObjectClientImpl::Get` -> `GetBuffersFromWorker(...)`
- `ClientWorkerRemoteApi::Get` -> `stub_->Get(opts, req, rsp, payloads)`（含 `RetryOnError`）
- Worker 入口：`WorkerOCServiceImpl::Get` -> `WorkerOcServiceGetImpl::Get`

Worker 入口证据：

```107:121:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp
Status WorkerOcServiceGetImpl::Get(std::shared_ptr<ServerUnaryWriterReader<GetRspPb, GetReqPb>> &serverApi)
{
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi->Read(req), "serverApi read request failed");
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(worker::Authenticate(akSkManager_, req, tenantId), "Authenticate failed.");
    ...
}
```

---

## 3. 读接口错误码（SDK 常见）

- `K_INVALID`：key 空、read offset 溢出、batch size 超限
- `K_NOT_FOUND`：对象不存在（多 key 场景可能“部分失败但总体 OK”）
- `K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED` / `K_TRY_AGAIN`：链路/超时类
- `K_OUT_OF_MEMORY`：远端拉取或组包内存不足
- `K_RUNTIME_ERROR`：内部处理异常（如 mmap entry 异常）

客户端读日志关键词：
- `Start to send rpc to get object`
- `GetObjMetaInfo failed` / `GetObjMetaInfo object count mismatch`
- `Finish to Get objects`

---

## 4. 读接口关联 Worker 日志（重点）

关键关键词：
- `serverApi read request failed`
- `Authenticate failed.`
- `RPC timeout. time elapsed ... subTimeout:...`
- `Process Get failed`
- `Get from remote failed: ...`
- `Failed to get object data from remote...`
- `Read offset verify failed`

远端拉取核心证据：

```1911:1919:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp
status = GetObjectFromRemoteWorkerAndDump(...);
if (status.GetCode() == K_OUT_OF_MEMORY || IsRpcTimeoutOrTryAgain(status)) {
    return status;
}
...
RETURN_STATUS(K_NOT_FOUND, FormatString("Get from remote worker failed, object(%s) not exist in worker, ..."));
```

---

## 5. 读接口排查树（先 SDK 后 Worker）

1. SDK 返回码分桶
- `K_INVALID`：先查调用参数（keys、timeout、read offset）
- `K_NOT_FOUND`：查对象是否过期/删除，确认是否为预期未命中
- `K_RPC_*`/`K_TRY_AGAIN`：进入链路排查（TCP/UB）

2. 对齐 Worker 日志（同时间窗）
- **无 Get 入口日志**：更偏网络/连接前置问题（请求未到 Worker）
- **有 Get start + timeout**：更偏 Worker 负载或远端拉取慢
- **有 Get from remote failed**：优先看跨 Worker 与 UB/TCP 段

3. 结合分段时延
- 若入口 RPC 慢：TCP/网络域优先
- 若远端数据段慢：UB/远端 Worker 路径优先

---

## 6. 责任边界与模块落点

- L0（集成方）：非法参数、超时配置不合理
- L1（平台与网络）：1002/reset/unreachable、mmap/fd 内核异常
- L2（三方件）：etcd/存储依赖导致读路径退化
- L3（数据系统）：Get 处理链、重试策略、远端拉取逻辑

L3（数据系统）优先模块：
- `WorkerOcServiceGetImpl`
- `worker_oc_service_batch_get_impl`
- `ClientWorkerRemoteApi::Get`

---

## 7. UB 链路故障专项（读）

## 7.1 典型信号
- SDK 侧：
  - `K_URMA_NEED_CONNECT` / `K_URMA_ERROR` / `K_URMA_TRY_AGAIN`（若上抛）
  - 或出现降级日志：`UB Get buffer allocation failed ... fallback to TCP/IP payload`
- Worker 侧（远端拉取）：
  - `Get from remote failed: ...`
  - `Failed to get object data from remote...`

## 7.2 关键代码证据
- SDK 读请求先走 `stub_->Get`，之后才 `FillUrmaBuffer(...)`，所以“RPC 成功但 UB 段失败”是可能的：
  - `client_worker_remote_api.cpp` `ClientWorkerRemoteApi::Get`
- Worker 远端读失败直接回传状态：
  - `worker_oc_service_get_impl.cpp` `GetObjectFromRemoteOnLock`
  - 其中 `K_OUT_OF_MEMORY` / timeout-or-tryagain 会直接返回上层

## 7.3 链路排查步骤（执行顺序）
1. 看 SDK 是否有 `Start to send rpc to get object` 且 RPC 成功返回（区分“控制面”与“数据面”）。
2. 查 Worker 同时间窗是否出现：
   - `Get start from client:...`
   - `Get from remote failed: ...`
   - `Failed to get object data from remote...`
3. 若 Worker 有远端失败日志，继续按地址查远端 Worker 日志（同 key / trace）。
4. 若 SDK 出现 UB fallback 且成功率正常，这是“UB 退化为 TCP”，应记为性能劣化而非功能故障。
5. 若 UB 与 TCP 同时失败，再进入网络/OS 联合排查（L1（平台与网络））。

## 7.4 定界结论规则
- 仅 UB 失败、TCP 可用：优先 UMDK/UB 路径（L1（平台与网络）），数据系统给出端点对与失败时段自证。
- UB fallback 后读成功但 P99 变差：性能问题，归“降级运行”，不归功能失败。
- Worker 侧明确对象不存在（`K_NOT_FOUND`）：业务数据状态，不归链路。

---

## 8. TCP 链路故障专项（读）

## 8.1 典型信号
- SDK：`K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED` / `K_TRY_AGAIN`
- Worker：可能完全无该请求日志（请求未到达），或有 `RPC timeout. time elapsed...`

## 8.2 Worker 日志判据（强相关）
- 有 `Get start from client:` + 后续 `RPC timeout...` -> 请求到达但处理超时（Worker 或下游慢）
- 无 `Get start from client:` -> 更偏连接前置/网络路径问题
- 有 `serverApi read request failed` -> RPC 帧读取异常（通道层）

## 8.3 链路排查步骤（执行顺序）
1. 先查 SDK `Status` 与 `respMsg`（1002/1001/19）。
2. 用时间窗在入口 Worker 查 `Get start from client`。
3. 分叉：
   - 无入口日志：查网络、端口监听、连接复用状态。
   - 有入口日志：看是否 `RPC timeout`、`Process Get failed`、远端拉取失败。
4. 若入口 Worker 显示远端失败，再追远端 Worker 与 worker<->worker TCP 路径。
5. 结合分段时延：判断慢在 ① 入口 RPC 还是 ②③ 跨 worker 控制面。

## 8.4 定界结论规则
- SDK 1002 + Worker无入口日志：L1（平台与网络）优先。
- SDK 1002 + Worker有入口且内部超时：L3（数据系统）优先，再细分是否远端依赖。

---

## 9. 数据系统内部问题专项（读）

## 9.1 常见内部问题信号
- `Read offset verify failed`（参数与对象边界冲突）
- `Process Get failed`（Get 主流程内部失败）
- `QueryMeta ... failed` / `Can not get meta ...`（元数据获取链问题）
- `Get from remote failed ... object not exist in worker`（元数据与数据副本状态不一致）

## 9.2 快速定位到模块
- 主入口：`WorkerOcServiceGetImpl::Get`
- 远端拉取：`GetObjectFromRemoteOnLock`
- 批处理：`worker_oc_service_batch_get_impl.cpp`

## 9.3 建议输出的自证信息
- 请求 key、clientId、入口 Worker 地址、远端地址、失败 status、elapsed、subTimeout
- 是否触发 fallback（UB->TCP）
- 同时间窗是否有 etcd/master 相关异常

---

## 10. 读接口定界表格（错误码 + 定界话术）

## 10.0 本节点读取：定界流程图与故障排查流程图（TCP+SHM / TCP+RPC）

说明：这里的“本节点读取”聚焦 **Client 与入口 Worker 在同节点** 的主路径，分两类：
- **Case A：TCP 做共享内存控制消息 + SHM 回数**（常见高性能路径）
- **Case B：TCP 做 RPC 消息与数据返回**（无 SHM 或 SHM 不可用时）

### A) 定界流程图（先定界，再下钻）

```mermaid
flowchart TD
  A0[本节点 Get 请求] --> A1{Case A: TCP + SHM?}
  A1 -->|是| A2[SDK 发送 Get RPC<br/>看: 1002/1001/19]
  A2 -->|1002: The service is currently unavailable / Network unreachable| A3{Worker 有无 Get 入口日志?}
  A3 -->|无| A4[L1（平台与网络）优先<br/>连接前置/端口/链路]
  A3 -->|有| A5[L3（数据系统）优先<br/>Worker 内部处理或下游慢]
  A2 -->|RPC OK| A6[进入 SHM 回数段 ⑥]
  A6 -->|K_RUNTIME_ERROR: Receive fd ... failed / Get mmap entry failed| A7[L1（平台与网络）+L3（数据系统）<br/>fd/mmap 链路]
  A6 -->|K_CLIENT_WORKER_DISCONNECT(23): Cannot receive heartbeat from worker| A8[先查心跳与 Worker 负载]
  A6 -->|成功| A9[判定本节点链路健康]

  A1 -->|否, Case B: TCP + RPC 消息| B1[SDK Get RPC + payload]
  B1 -->|1001: deadline exceeded| B2[看 Worker: RPC timeout. time elapsed ...]
  B1 -->|1002: unavailable| B3{Worker 有无 Get 入口日志?}
  B3 -->|无| B4[L1（平台与网络）优先]
  B3 -->|有| B5[L3（数据系统）优先]
  B1 -->|19: try again / EAGAIN| B6[短暂拥塞或非阻塞读重试]
  B1 -->|成功| B7[判定 TCP RPC 路径健康]
```

### B) 故障排查流程图（执行顺序）

```mermaid
flowchart TD
  T0[Step1: 收集 SDK 证据] --> T1[记录 status_code + message + trace_id + request_id]
  T1 --> T2{是否 Case A(TCP+SHM)?}

  T2 -->|是| S1[Step2A: 查 Worker Get 入口日志]
  S1 --> S2{有 Get start from client?}
  S2 -->|无| S3[结论A1: 请求未到 Worker<br/>优先 L1（平台与网络）]
  S2 -->|有| S4[Step3A: 查 Worker 内日志<br/>RPC timeout / Process Get failed / Get from remote failed]
  S4 --> S5{SDK 是否为 mmap/fd 相关错误?}
  S5 -->|是: Receive fd failed / Get mmap entry failed| S6[结论A2: SHM/fd 段异常(⑥)<br/>L1（平台与网络）+L3（数据系统）]
  S5 -->|否| S7[结论A3: Worker 处理链或下游依赖慢(②~⑤)]

  T2 -->|否, Case B(TCP+RPC)| R1[Step2B: 查 Worker Get 入口日志]
  R1 --> R2{有入口日志?}
  R2 -->|无| R3[结论B1: TCP 前置链路问题(①)<br/>1002/1001 优先 L1（平台与网络）]
  R2 -->|有| R4[Step3B: 查 timeout 与远端拉取日志]
  R4 --> R5{是否 Get from remote failed?}
  R5 -->|是| R6[结论B2: 远端数据段问题(③~⑤)<br/>优先 L3（数据系统）]
  R5 -->|否| R7[结论B3: 入口 Worker 内部处理慢(①/②)]

  S3 --> Z[Step4: 输出定界结论]
  S6 --> Z
  S7 --> Z
  R3 --> Z
  R6 --> Z
  R7 --> Z
  Z --> Z1[输出: 责任域 + 流程段 + 错误码/消息 + 级联日志证据]
```

### C) 两个 Case 的“错误码 + 错误消息”最小对照

| Case | 关键错误码 | 典型错误消息（示例） | 重点看段 |
|------|------------|----------------------|----------|
| TCP + SHM | `K_RPC_UNAVAILABLE(1002)` | `The service is currently unavailable` / `Network unreachable` | ① |
| TCP + SHM | `K_RUNTIME_ERROR(5)` | `Receive fd[...] from ... failed` / `Get mmap entry failed` | ⑥ |
| TCP + SHM | `K_CLIENT_WORKER_DISCONNECT(23)` | `Cannot receive heartbeat from worker` | 心跳/连接维持 |
| TCP + RPC | `K_RPC_UNAVAILABLE(1002)` | `The service is currently unavailable` | ① |
| TCP + RPC | `K_RPC_DEADLINE_EXCEEDED(1001)` | `RPC timeout. time elapsed...` | ①/② |
| TCP + RPC | `K_TRY_AGAIN(19)` | `Socket receive error ... EAGAIN` | ①（重试窗口） |

| 场景信号 | 首选证据（SDK + Worker） | 初判责任域 | 数据系统内优先模块 |
|------|------------------|------------|---------------------|
| SDK `K_INVALID` | SDK 入参 + `Read offset verify failed`（若有） | L0（集成方） | `KVClient` 参数校验、`ObjectClientImpl::Read` |
| SDK `K_RPC_UNAVAILABLE(1002)` 且 Worker 无入口日志 | SDK `respMsg` + Worker 无 `Get start from client` | L1（平台与网络） | `ClientWorkerRemoteApi::Get`（请求发起侧） |
| SDK `K_RPC_UNAVAILABLE(1002)` 且 Worker 有入口超时 | Worker `RPC timeout. time elapsed...` | L3（数据系统）或 L2（三方件）/L1（平台与网络）下游依赖 | `WorkerOcServiceGetImpl::Get` |
| 远端读失败 + `Get from remote failed` | 入口 Worker 远端拉取日志 + 远端 Worker 对应窗口 | L3（数据系统）优先 | `GetObjectFromRemoteOnLock`、`batch_get_impl` |
| UB fallback 但功能成功 | SDK `UB ... fallback to TCP/IP payload` + success_rate 正常 | 性能退化，非功能故障 | `ClientWorkerBaseApi::PrepareUrmaBuffer` |
| `K_NOT_FOUND` 且 Worker 明确对象不存在 | Worker not found 相关日志 | 业务数据状态（非链路） | `worker_oc_service_get_impl` |

## 10.1 读接口定界话术模板（可直接复用）

## 10.2 读场景中“可直接判非数据系统”的现象清单（重点）

以下现象满足时，可优先定界到 **非数据系统责任**（L0（集成方）/L1（平台与网络）/L2（三方件）），数据系统仅配合提供证据。

| 观察到的现象 | 可直接定界结论 | 证据要求（最小） |
|------|------------------|------------------|
| SDK 返回 `K_RPC_UNAVAILABLE(1002)`，且入口 Worker **同时间窗无** `Get start from client` | 优先 L1（平台与网络）前置链路问题（请求未到数据系统） | SDK 错误码+message、入口 Worker 空日志、时间窗对齐 |
| SDK 错误消息含 `Network unreachable` / `Connect reset` / `EPIPE` / `ECONNRESET`，Worker 无入口日志 | L1（平台与网络）网络/连接层问题 | SDK 连接类错误消息、Worker 空日志、网络侧事件 |
| SDK 返回 `K_INVALID`，并且可复现为非法 key/offset/timeout 入参 | L0（集成方）调用参数问题 | 调用参数快照、SDK 参数校验日志 |
| Worker 启动与运行健康，但客户端持续访问旧地址/错误服务发现目标 | L0（集成方）+L1（平台与网络）服务发现与路由问题 | 客户端目标地址、服务发现记录、Worker 健康日志 |
| 读请求功能成功，但仅出现 `UB ... fallback to TCP/IP payload` 且成功率正常 | 非数据系统功能故障；属于链路退化/性能问题（优先 L1（平台与网络）） | fallback 日志、成功率正常、P99 变化曲线 |
| 扩缩容窗口内 `K_SCALING(32)` 与 etcd Watch/租约异常同窗出现 | 优先 L2（三方件）控制面问题（数据系统为受影响方） | etcd 健康/延迟指标、`K_SCALING` 分布、迁移时间线 |

**反例提醒（避免误判）**：
- 虽是 `1002`，但若 Worker 有入口日志并出现 `RPC timeout` / `Process Get failed` / `Get from remote failed`，则不能判“非数据系统”，应继续按 L3（数据系统）链路下钻。

- **网络/连接侧（L1（平台与网络））**  
  “本次读请求在 SDK 返回 `K_RPC_UNAVAILABLE(1002)`，同时间窗入口 Worker 未看到 `Get start from client`，请求未进入 Worker 处理链，优先定界为网络/连接前置问题。数据系统侧附带请求时间窗、客户端错误明细和 Worker 空日志证据。”

- **数据系统处理链（L3（数据系统））**  
  “本次读请求已进入 Worker（存在 `Get start from client`），并在 Worker 内出现 `RPC timeout` / `Process Get failed` / `Get from remote failed`，故优先定界在数据系统读处理链，再按远端拉取与元数据步骤细分模块。”

- **UB 性能退化（非功能故障）**  
  “读请求出现 `UB ... fallback to TCP/IP payload`，功能成功但链路降级，定性为性能劣化事件而非功能故障；需跟踪 P99 与降级比例。”

- **业务数据未命中**  
  “返回 `K_NOT_FOUND` 且 Worker 侧存在对象不存在/过期证据，属于业务数据状态，不归链路故障。”

