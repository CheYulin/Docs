# Client / Worker 延迟指标为何对不上：整体推导

本文档从 **代码中的计时边界** 出发，推导为何 **同一业务 Get** 在汇总指标上会出现「Client 端到端 ~3ms、Worker 子项看似 ~1.5ms、而 `worker_process_get` 只有几十微秒」等现象，并说明 **如何用现有指标近似还原** 真实耗时结构。

**分析对象**：`yuanrong-datasystem` 中 Object Cache **Get** 路径（ZMQ RPC + 可选 URMA/TCP payload）。  
**示例观测**（便于对照下文；具体环境以你当时 dump 为准）：

| 指标 | 示例 avg / 量级 |
|------|-----------------|
| `client_rpc_get_latency` | ~3336 µs |
| `worker_process_get_latency` | ~47 µs |
| `worker_rpc_query_meta_latency` | ~698 µs |
| `worker_rpc_get_remote_object_latency` | ~766 µs |
| `worker_urma_write_latency` | ~27 µs |
| `worker_urma_wait_latency` | ~601 µs |
| `client` / `worker` **count** | 可相差较大（如 99k vs 137k） |

---

## 1. 核心结论（先读这段）

1. **`worker_process_get_latency` 与真实「处理完一次 Get」不对等**  
   在 **`EnableMsgQ()` + 线程池异步** 的常见配置下，Worker 侧 `Get()` 在 **`threadPool_->Execute(...)` 入队后即返回 `OK`**。  
   `METRIC_TIMER(WORKER_PROCESS_GET_LATENCY)` 包在 `WorkerOCServiceImpl::Get` → `getProc_->Get` 上，**在 `Get` 返回时即结束**，因此只有 **校验 + Read 请求 + Init + 入队** 的同步段，**不包含** `ProcessGetObjectRequest` 及之后的元数据 RPC、跨 Worker、URMA、组包回写等。  
   **几十微秒是预期表现，不是「Worker 全链路只要几十微秒」。**

2. **`client_rpc_get_latency` 是业务视角端到端**  
   从进入 `ClientWorkerRemoteApi::Get` 到返回，包含 **`PreGet`、`PrepareGetUrmaBuffer`、带重试的 `stub_->Get`、以及 `FillUrmaBuffer`** 等。  
   它 **大于** 单次 ZMQ RPC 的 `zmq_rpc_e2e_latency` 是正常的（见第 4 节）。

3. **Worker 上多个子直方图不能简单相加后与 Client 对比**  
   - 子阶段可能 **串行**（如 query_meta 后 get_remote），也可能因路径不同 **不都触发**。  
   - **跨节点、多 Worker、批量** 会使 **Worker 侧 count 聚合自多个进程**，与 **单 Client 进程** 的 count **不必 1:1**。  
   - **`worker_rpc_get_remote_object_latency`** 等可能发生在 **B 节点**，而 **Client 连的是 A 节点**，汇总时容易混在「集群 Worker 指标」里一起看。

4. **「Client–Worker RPC 耗时」可以判断，但要用对指标**  
   应优先看 **`zmq_rpc_e2e_latency`**（`CLIENT_ENQUEUE` → `CLIENT_RECV`），并配合 **`zmq_client_queuing_latency` / `zmq_client_stub_send_latency`** 与 **`zmq_server_queue_wait_latency` / `zmq_server_exec_latency` / `zmq_server_reply_latency`**。  
   **`zmq_rpc_network_latency` = E2E − `SERVER_EXEC_NS`**：在异步 Get 下 **`SERVER_EXEC_NS` 很短**（`SERVER_EXEC_END` 在业务提前返回时就打点），因此该项 **不是「纯网络 RTT」**，而是 **「E2E 减去一段很短的同步业务窗口」**，数值会 **偏大** 且 **混合** 异步处理、排队、序列化、真实链路延迟等。

---

## 2. 时间线：MsgQ + 线程池异步下一次 Get

下列顺序与 `worker_oc_service_get_impl.cpp`、`zmq_service.cpp`、`zmq_rpc_metrics.h` 一致。

```text
[Client]
  PreGet / PrepareGetUrmaBuffer（可能含 GetObjMetaInfo 等，不一定打在 worker_* 上）
       ↓
  stub_->Get  →  ZMQ：CLIENT_ENQUEUE … CLIENT_SEND …（对端处理）… CLIENT_RECV
       ↓
  FillUrmaBuffer（URMA 路径下，RPC 返回后客户端仍要干活）

[ZMQ Worker 线程]
  SERVER_RECV → SERVER_DEQUEUE → CallMethod → Service::Get
       ↓
  Read(req) / Authenticate / GetRequest::Init
       ↓
  threadPool_->Execute(ProcessGetObjectRequest)   ← 仅入队
       ↓
  Get 返回 OK
       ↓
  TICK_SERVER_EXEC_END   ← 此处 zmq_server_exec、worker_process_get 的「业务同步段」结束

[OC 线程池线程]
  （排队等待）← 无独立 KV 直方图
       ↓
  ProcessGetObjectRequest：TryGetObjectFromLocal（无 KV 直方图，有 PerfPoint）
       ↓
  TryGetObjectFromRemote：worker_rpc_query_meta、worker_rpc_get_remote_object …
       ↓
  ReturnToClient：ConstructResponse、Write、SendPayload；URMA/TCP：worker_urma_*、worker_tcp_write
       ↓
  SendAll → 经 Backend 最终 TICK_SERVER_SEND → zmq_server_reply 等
```

**因此：**  
- **`worker_process_get_latency` ≈ 到「入队」为止**（外加最外层 `ValidateWorkerState`）。  
- **真正占毫秒级的处理** 落在 **线程池内** 与 **ZMQ 的 reply 段**，对应 **`worker_rpc_*` / `worker_urma_*`** 以及 **`zmq_server_reply_latency`**，而不是 `worker_process_get`。

---

## 3. 指标对照表（记什么、不记什么）

| 指标 | 计时边界（直觉） | 异步 Get 下注意 |
|------|------------------|-----------------|
| `client_rpc_get_latency` | 整次 `Get()` | 含 RPC 前/后；可含重试叠加 |
| `zmq_rpc_e2e_latency` | Client 侧 enqueue → recv | **单次 RPC 传输层端到端** |
| `zmq_rpc_network_latency` | E2E − SERVER_EXEC_NS | **勿当纯 RTT**；异步下 SERVER_EXEC_NS 很短 |
| `zmq_server_exec_latency` | DEQUEUE → EXEC_END | 与 `worker_process_get` 同类 **短** |
| `zmq_server_reply_latency` | EXEC_END → SEND | **常含异步处理 + 组包发送准备** |
| `worker_process_get_latency` | `Get` 同步返回 | **MsgQ 下严重低估** |
| `worker_rpc_query_meta_latency` | Master 元数据 RPC | 在异步线程内 |
| `worker_rpc_get_remote_object_latency` | 跨 Worker 拉对象 | 可能在其他节点也有样本 |
| `worker_urma_write_latency` / `wait` | URMA 写与等待完成 | 仅 URMA 路径 |
| `worker_tcp_write_latency` | TCP payload 拷贝路径 | 与 URMA 二选一或回退 |

**观测缺口（若要做「Worker 异步段总耗时」）**：  
线程池 **入队 → lambda 开始**、**TryGetObjectFromLocal 整段**、**ConstructResponse 整段** 等 **没有** 与 `worker_process_get` 同级的单一 histogram（部分仅有 **PerfPoint**）。

---

## 4. 推导：为什么数字「对不上」

### 4.1 Client avg ≫ Worker 子项之和的错觉

若把 **`worker_process_get`** 当成「Worker 处理时间」，会得到 **47 µs + …**，与 **3336 µs** 对比，必然「对不上」。  
正确对比应使用：

- Client：**`client_rpc_get_latency`** 与 **`zmq_rpc_e2e_latency`**（拆出纯 RPC）。
- Worker：**`zmq_server_reply_latency`** + 各 **`worker_rpc_*` / `worker_urma_*`**（理解重叠与路径，勿机械相加）。

### 4.2 子项相加 ≠ 单次请求墙钟

即使只论 Worker：**query_meta** 与 **get_remote** 对单次远程 Get 常 **串行**，粗略 **698 + 766 ≈ 1.46 ms** 仅描述 **部分阶段**；另有 **local 阶段、ReturnToClient、序列化、ZMQ 排队** 等。  
Client 侧还有 **PreGet / FillUrmaBuffer / 元数据预解析**，故 **3336 µs** 与 **~1.5 ms 量级 Worker 子项** 之间 **差 1–2 ms** 仍可来自：**客户端额外工作 + ZMQ 多段 + 重试一次尾巴** 等。

### 4.3 count 不一致

- 多 **Worker 进程** 汇总 vs **单 Client**。  
- **重试**：Client 一次业务 Get 可能对应 **多次 stub 调用**（或相反，视失败路径）。  
- **远程 Get**：元数据与数据可能在 **不同 Worker** 上打点。  

因此 **avg 对比** 时 **应用同一进程、同一时间窗、同一路径** 过滤，或接受 **聚合偏差**。

---

## 5. 建议的排障读法（实操）

1. 同一窗口看 **`zmq_rpc_e2e_latency`** 与 **`client_rpc_get_latency`**：**差值** 粗看 **PreGet / meta / FillUrmaBuffer / 重试**。  
2. 看 **`zmq_server_exec_latency`**（应短）与 **`zmq_server_reply_latency`**（常长）：确认 **异步尾巴** 是否主导。  
3. 看 **`worker_rpc_query_meta_latency`、`worker_rpc_get_remote_object_latency`、`worker_urma_*`**：拆 **业务慢** 还是 **传输慢**。  
4. **不要** 用 **`worker_process_get_latency`** 代表 Worker Get 总耗时（MsgQ 异步下）。  
5. **不要** 用 **`zmq_rpc_network_latency`** 当 **ping RTT**。

---

## 6. 相关源码索引

| 主题 | 文件（仓库 `yuanrong-datasystem`） |
|------|-------------------------------------|
| Client `Get` 计时范围 | `client/object_cache/client_worker_api/client_worker_remote_api.cpp` |
| Worker `Get` 入队与 `ProcessGetObjectRequest` | `worker/object_cache/service/worker_oc_service_get_impl.cpp` |
| `WORKER_PROCESS_GET_LATENCY` 外层 | `worker/object_cache/worker_oc_service_impl.cpp` |
| Client 侧 RPC E2E / network 推导 | `common/rpc/zmq/zmq_rpc_metrics.h`（`RecordRpcLatencyMetrics`） |
| Server 侧 queue / exec / reply | `common/rpc/zmq/zmq_service.cpp`（`RecordServerLatencyMetrics`） |
| `ReturnToClient`、URMA/TCP 打点 | `worker/object_cache/worker_request_manager.cpp` |

---

## 7. 与 `ANALYSIS.md`（logs-0425 故障摘要）的关系

- **`ANALYSIS.md`**：侧重 **2026-04-25 窗口内 Publish/CreateMeta 超时与 ZMQ gateway 现象** 的日志推导。  
- **本文档**：侧重 **Get 路径上 Prometheus/KV 风格延迟指标为何在数值上不一致**，与具体故障日志 **正交**；若你在同一环境中同时看 **Get 延迟** 与 **Master 慢**，可将 **`zmq_rpc_e2e`** 与 **`worker_rpc_query_meta_latency`** 等一并拉出，避免把 **`worker_process_get`** 误判为「Worker 很快所以不是 Worker 问题」。

---

*文档随当前仓库代码路径整理；若 MsgQ/线程池策略变更，以 `EnableMsgQ()` 分支与 `WorkerEntry` 打点为准。*
