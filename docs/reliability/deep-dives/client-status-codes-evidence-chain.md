# Client 侧错误码：源码证据链（yuanrong-datasystem）

本文档依据**同级仓库** `yuanrong-datasystem` 当前代码，说明 **StatusCode 定义 → 命名 → RPC/传输层语义 → 客户端重试 → KV access 落盘** 的可追溯链条。路径均相对于 **datasystem 仓库根**。

---

## 1. 码表：唯一权威枚举

**文件**：[`include/datasystem/utils/status.h`](../../yuanrong-datasystem/include/datasystem/utils/status.h)

- **公共错误** `[0, 1000)`：如 `K_OK`、`K_TRY_AGAIN`、`K_CLIENT_WORKER_DISCONNECT`、`K_SCALE_DOWN`、`K_SCALING` 等。
- **RPC 相关** `[1000, 2000)`：`K_RPC_CANCELLED`、`K_RPC_DEADLINE_EXCEEDED`、`K_RPC_UNAVAILABLE`、`K_URMA_ERROR`、`K_URMA_NEED_CONNECT`、`K_URMA_TRY_AGAIN` 等。
- **Object / Stream / 异构**：`[2000,3000)`、`[3000,4000)`、`[5000,6000]` 等分段见同一枚举。

数值与名称一一对应，**客户端最终 `Status::GetCode()`** 即该枚举值。

---

## 2. 名称字符串（日志 / `Status::ToString()`）

**实现**：[`src/datasystem/common/util/status.cpp`](../../yuanrong-datasystem/src/datasystem/common/util/status.cpp) 中 `Status::StatusCodeName(StatusCode)`，数据来自宏展开：

**文件**：[`src/datasystem/common/util/status_code.def`](../../yuanrong-datasystem/src/datasystem/common/util/status_code.def)

每条 `STATUS_CODE_DEF(K_xxx, "Human readable")` 对应枚举项的**英文短描述**。  
若某枚举值未在 `.def` 中列出，`StatusCodeName` 会落到 `default`，返回 **`UNKNOWN_TYPE`**（见 `status.cpp` 中 `returnMsg` 初值）。

---

## 3. 「RPC 超时类」在通用工具中的定义

**文件**：[`src/datasystem/common/util/rpc_util.h`](../../yuanrong-datasystem/src/datasystem/common/util/rpc_util.h)

| 函数 | 语义（证据） |
|------|----------------|
| `IsRpcTimeout(const Status &)` | 码为 **`K_RPC_CANCELLED` / `K_RPC_DEADLINE_EXCEEDED` / `K_RPC_UNAVAILABLE`** 之一则视为 RPC 超时类（L40–L44）。 |
| `IsRpcTimeoutOrTryAgain` | 在上一类基础上增加 **`K_TRY_AGAIN`**（L46–L49）。 |
| `RetryOnError` | 仅当返回码 **属于传入的 `retryCode` 集合** 时继续重试；间隔序列 `1,5,50,200,1000,5000` ms；**剩余时间 &lt; `minOnceRpcTimeoutMs`（50ms）** 则停止（L127–L189）。 |
| `RetryOnErrorRepent` | 对 `RetryOnError` 的封装，`repent=true` 打错误日志（L191–L196）。 |
| `RetryOnRPCErrorByTime` | 重试集合固定为 **三 RPC 码**（L198–L205）。 |

由此：**客户端是否重试、重试哪几种码**，以调用点传入的 `retryCode` 为准，**不是**所有 API 一致。

---

## 4. 传输层（ZMQ）向 `K_RPC_UNAVAILABLE` 等映射（示例）

**文件**：[`src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`](../../yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp)

典型证据行（节选）：

- 服务不可用、meta 上报：`K_RPC_UNAVAILABLE`（约 227、575、1304 行等）。
- 网络不可达 / 等待连接超时：`K_RPC_UNAVAILABLE`（约 270、1505–1510 行）。

**文件**：[`src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp`](../../yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp)

- `ZmqErrnoToStatus` 等路径可将底层错误映射到 **`K_RPC_UNAVAILABLE`**（约 145 行附近）。

结论：**1002（`K_RPC_UNAVAILABLE`）** 在客户端常表示「通道未就绪 / 对端不可达 / 收发包失败」等 **RPC 层**归类，与 **1004/1006/1008（URMA 数据面）** 的区分需结合调用栈与 Worker 返回（见 triage 文档）。

---

## 5. Object 路径：`ClientWorkerRemoteApi` 的重试集合

**文件**：[`src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp`](../../yuanrong-datasystem/src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp)

**静态集合** `RETRY_ERROR_CODE`（约 L36–L38）：

```text
K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED, K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY
```

`Get` / `Publish` 等通过 `RetryOnError(..., RETRY_ERROR_CODE, rpcTimeoutMs_)` 包裹（例如约 L304–L323：`stub_->Get` 返回后，还会根据 `rsp.last_rc()` 再构造 `Status` 并判断是否继续重试）。

**业务 PB 返回码**：`Status(static_cast<StatusCode>(rsp.last_rc().error_code()), rsp.last_rc().error_msg())` —— **与 RPC 层 `stub_->Get` 的 `Status` 是两层**，批量 Get 时 **per-object 错误**可能在 `last_rc` 而不在 RPC 外层（与 Playbook 中「32 在 access 与顶层 Status 不一致」现象一致）。

---

## 6. 注册与公共 API：`RegisterClient` 的重试集合

**文件**：[`src/datasystem/client/client_worker_common_api.cpp`](../../yuanrong-datasystem/src/datasystem/client/client_worker_common_api.cpp)

约 L573–L585：`RegisterClient` 的 `RetryOnError` 使用显式列表：

`K_TRY_AGAIN`, `K_RPC_CANCELLED`, `K_RPC_DEADLINE_EXCEEDED`, `K_RPC_UNAVAILABLE`

若返回 **`K_SERVER_FD_CLOSED`**，会 **改写为 `K_TRY_AGAIN`** 再向上返回（约 L586–L589），便于上层按「可重试」处理。

---

## 7. KV API → Access 日志：码如何从 `Status` 写入 `ds_client_access_*.log`

**记录器**：[`src/datasystem/common/log/access_recorder.cpp`](../../yuanrong-datasystem/src/datasystem/common/log/access_recorder.cpp)

- `AccessRecorder::Record(StatusCode code, ...)` 将 **整型码**交给 `AccessRecorderManager::LogPerformance`（约 L64–L88）。
- 客户端日志文件名：`CLIENT_ACCESS_LOG_NAME + "_" + pid`，环境变量可覆盖（约 L112–L119）。

**KV 示例**：[`src/datasystem/client/kv_cache/kv_client.cpp`](../../yuanrong-datasystem/src/datasystem/client/kv_cache/kv_client.cpp)

- `Set`：`accessPoint.Record(rc.GetCode(), ..., rc.GetMsg())`（约 L177–L181）。
- `Get`：**特殊规则** —— `StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode()`，再 `Record(code, ...)`（约 L217–L218、L239–L240）。

**证据结论**：**`K_NOT_FOUND` 在 KV Get 的 access 日志中会被记为 `K_OK(0)`**；排障时若只看 access **第一列码**，会与 `Status`/业务语义不一致，需结合 `rc.GetMsg()` 或上层返回值。

**handle 名称**：来自 [`src/datasystem/common/log/access_point.def`](../../yuanrong-datasystem/src/datasystem/common/log/access_point.def) 生成的 `AccessRecorderKey`（如 `DS_KV_CLIENT_GET`）。

---

## 8. 端到端链条（小结）

```text
include/datasystem/utils/status.h  (枚举值)
        ↓
status_code.def → Status::StatusCodeName  (可读名)
        ↓
ZMQ stub / socket 路径 → Status(K_RPC_*)   (传输层)
        ↓
ClientWorkerRemoteApi::RetryOnError + RETRY_ERROR_CODE / Register 列表
        ↓
KVClient / ObjectClientImpl::… → Status 返回应用
        ↓
AccessRecorder::Record(code) → ds_client_access_<pid>.log  (第一列整数码；Get+NOT_FOUND 例外见 §7)
```

---

## 9. 与排障文档的衔接

- **跑测时对照码表与 FEMA 启发式映射**：[../00-kv-client-visible-status-codes.md](../00-kv-client-visible-status-codes.md)。
- 错误码分层与 **1002 vs URMA** 的讨论：本仓库 [`plans/kv_client_triage/details/rpc_unavailable_triggers_and_urma_vs_transport.md`](../../../plans/kv_client_triage/details/rpc_unavailable_triggers_and_urma_vs_transport.md)（若已镜像则见 [`docs/reliability/operations/kv-client-rpc-unavailable-triggers.md`](../operations/kv-client-rpc-unavailable-triggers.md)）。
- Playbook 中的 **31/32** 与客户端可见性：[`plans/kv_client_triage/`](../../plans/kv_client_triage/) 下 Playbook / scaling 专文。

---

## 10. 修订说明

- 枚举或 `status_code.def` 增删时，应同步更新本文 **§1–§2** 的引用行号（若 CI 有校验可自动化）。
- 本文**不**替代官方对外 API 文档；仅服务**源码级证据链**与 on-call 对齐。
