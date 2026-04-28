# ZMQ Gateway 重建逻辑梳理

基于 `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` 等代码，说明 **「New gateway created」** 与 **`zmq_gateway_recreate_total`** 何时增加，以及**为何会频繁重建**（结合 `worker2.log` 约每 1.5s 一条的现象）。

---

## 1. Gateway 是什么、谁在跑

- **ZmqFrontend** 内有一个异步线程执行 **`WorkerEntry`**，维护本 stub 的 ZMQ **`DEALER` 前端**（`frontend_`），与对端（常为 ROUTER/服务端）通信。
- **`GetGatewayId()`**：当前 `frontend_` 上的 **WorkerId**；每次新建/更换 `ZmqSocket` 都会变，故日志里 UUID 会换。

---

## 2. 何时打印「New gateway created」、何时累加指标

有两处会打同一行 **`LOG(INFO) << "New gateway created " << GetGatewayId()`**：

1. **线程启动后第一次** `InitFrontend` 成功（`WorkerEntry` 开头）。
2. **`liveness_ == 0`** 后 **`InitFrontend` 重建**成功：`std::swap(frontend_, sock)` → `ResetLiveness()` → 再次打印，并 **`METRIC_INC(ZMQ_GATEWAY_RECREATE_TOTAL)`**（仅第二次及以后重建计数，与「第一次启动」区分时以指标为准）。

核心循环见 `ZmqFrontend::WorkerEntry()`（`zmq_stub_conn.cpp`）。

---

## 3. Liveness：充能、衰减、瞬杀

| 机制 | 行为 |
|------|------|
| **初值** | `liveness_ = maxLiveness_ = K_LIVENESS`（默认 120），`heartbeatInterval_ = 1000` ms（`K_ONE_SECOND`）。 |
| **充值** | **`ZmqSocketToBackend`** 里从 `frontend_` **成功收到对端一帧**后立刻 **`ResetLiveness()`**，将 `liveness_` 置为 **`maxLiveness_`**。 |
| **衰减（idle）** | `HandleEvent` 返回 **`K_NOT_FOUND`（Idle）**，且自上次 `t.Reset()` 起已超过 **`heartbeatInterval_`**：本圈执行 **`liveness_--`**、`SendHeartBeats()`、`t.Reset()`。若本圈有**非 TRY_AGAIN 的活动**（通常 `OK`），走 `else { continue; }`，**不进入**衰减段。 |
| **瞬杀** | `HandleEvent` 返回 **`K_TRY_AGAIN`**（注释：EAGAIN 等）：**`liveness_ = 0`**，下一圈即触发重建。 |

`UpdateLiveness(int32_t timeoutMs)` 在 **`ZmqStubConnMgrImpl::GetConn`** 创建/复用连接时调用（`frontend->UpdateLiveness(timeoutMs)`），参数为**本次 stub 的 RPC `timeoutMs`**。

当 `timeoutMs` 较小时，会把 **`maxLiveness_` 从 120 下调**（仅当 `newLiveness < maxLiveness_`），并设置 **`heartbeatInterval_`**：

- `interval = max(500, min(timeoutMs/(3+1), 30000))`（单位 ms，且 `minLiveness` 常数 3）
- `newLiveness = max(realTimeoutMs/interval, 3)`

例如 **`timeoutMs ≈ 1000`** 时，易得到 **`maxLiveness_ ≈ 3`**、**`heartbeatInterval_ ≈ 500ms`** → **约 3×0.5s = 1.5s** 无入站帧则 `liveness` 耗尽 → **与 `worker2` 日志里约 1.5s 一条 `New gateway` 一致**。

---

## 4. 频繁重建的常见原因

1. **短 `timeoutMs` 把 liveness 压得很紧**  
   与单次 RPC 相同的短 deadline 用于 `UpdateLiveness` 时，**idle 路径**上很快减到 0，**周期性整 socket 换新的 gateway id**。

2. **「对端活着」完全依赖「DEALER 上能 recv 到帧」**  
   若对端长期不回包、或只发业务层慢到无入站、或路径上无可见回包，**`ResetLiveness` 很少执行**，liveness 照样掉。

3. **`HandleEvent` 频繁返回 `K_TRY_AGAIN`**  
   直接置 `liveness_=0`，重建更密，不一定与 1.5s 同频。

4. **与 ZMQ disconnect 计数脱钩**  
   这是**应用层**认为「无有效入站/TRY_AGAIN」后换 socket；**`zmq_event_disconnect_total` 仍为 0** 完全可能。

5. **多条连接**  
   不同 `RpcChannel` / 多个 stub 各自一个 `ZmqFrontend`，可能**只有某一条**在狂刷。

---

## 5. 与 Master 慢 / RPC 超时的关系

- **RPC 超时**：发生在 **stub 调用**侧（等响应队列）。  
- **Gateway 重建**：发生在 **ZmqFrontend 线程**的 liveness/换 socket。  

二者可**同因**（对端总慢、总不回 → 既 RPC 超时也长期无入站），也可**独立**（仅某条连接参数不当）。需结合 **endpoint、同机 `update liveness from` 日志** 判断。

---

## 6. 代码位置（便于跳转）

| 内容 | 文件 |
|------|------|
| 主循环、重建、指标 | `zmq_stub_conn.cpp` — `ZmqFrontend::WorkerEntry` |
| 收包充值 | 同上 — `ZmqSocketToBackend` 内 `ResetLiveness()` |
| `UpdateLiveness` | 同上 — `ZmqFrontend::UpdateLiveness` |
| 建连时注入 liveness | 同上 — `ZmqStubConnMgrImpl::GetConn` 内 `UpdateLiveness(timeoutMs)` |
| 默认 liveness 常量 | `zmq_constants.h` — `K_LIVENESS`（120） |
| 指标名 | `kv_metrics.cpp` — `zmq_gateway_recreate_total` |

---

## 7. 与 `logs-0425` 中其它材料的关系

- `worker2.log`：`why-worker2-data-worker1` 上约 **1.5s** 周期 **`New gateway created`** 与 **`zmq_gateway_recreate_total`** 递增，与上文 **短 timeout + 小 maxLiveness + 500ms 心跳** 的推导一致。
- `worker1.log`：主要为 **CreateMeta 到 master** 的 **RPC 超时**；不直接记 worker2；若共用 master/资源，可能 **同因压力**，但需分别取证。

见同目录 **`ANALYSIS.md`** 中的总览与时间线。
