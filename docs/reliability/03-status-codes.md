# 03 · 客户端可见 StatusCode

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `include/datasystem/utils/status.h` | `enum StatusCode` 权威枚举，唯一数值来源 |
| `src/datasystem/common/util/status_code.def` | `STATUS_CODE_DEF(K_xxx, "...")` 宏生成默认英文消息 |
| `src/datasystem/common/util/status.cpp` | `Status::StatusCodeName(StatusCode)` 实现；未在 `.def` 中的枚举返回 `UNKNOWN_TYPE` |
| `src/datasystem/common/util/rpc_util.h` | `IsRpcTimeout` / `IsRpcTimeoutOrTryAgain` / `RetryOnError` |
| `src/datasystem/common/log/access_recorder.cpp` | 客户端 access log `ds_client_access_<pid>.log` 写入点 |
| `src/datasystem/common/log/access_point.def` | handle 名（`DS_KV_CLIENT_GET` 等） |

> 版本漂移时请 diff `status.h` 与 `status_code.def`。

---

## 1. 全量 StatusCode 数值表

### 1.1 公共错误 `[0, 1000)`

| 数值 | 枚举 | 典型含义 |
|----|------|----------|
| 0 | `K_OK` | OK |
| 1 | `K_DUPLICATED` | Key duplicated |
| 2 | `K_INVALID` | Invalid parameter |
| 3 | `K_NOT_FOUND` | Key not found |
| 4 | `K_KVSTORE_ERROR` | KV store error |
| 5 | `K_RUNTIME_ERROR` | Runtime error（含 executor 抛错等） |
| 6 | `K_OUT_OF_MEMORY` | Out of memory |
| 7 | `K_IO_ERROR` | IO error |
| 8 | `K_NOT_READY` | Not ready |
| 9 | `K_NOT_AUTHORIZED` | Not authorized |
| 10 | `K_UNKNOWN_ERROR` | Unknown error |
| 11 | `K_INTERRUPTED` | Interrupt detected |
| 12 | `K_OUT_OF_RANGE` | Out of range |
| 13 | `K_NO_SPACE` | No space available |
| 14 | `K_NOT_LEADER_MASTER` | Not leader master |
| 15 | `K_RECOVERY_ERROR` | Recovery error |
| 16 | `K_RECOVERY_IN_PROGRESS` | Recovery in progress |
| 17 | `K_FILE_NAME_TOO_LONG` | File name is too long |
| 18 | `K_FILE_LIMIT_REACHED` | FD 数量达到上限等 |
| 19 | `K_TRY_AGAIN` | Try again |
| 20 | `K_DATA_INCONSISTENCY` | Master/Worker 数据不一致 |
| 21 | `K_SHUTTING_DOWN` | Shutting down |
| 22 | `K_WORKER_ABNORMAL` | Worker 状态异常 |
| 23 | `K_CLIENT_WORKER_DISCONNECT` | Client 与 Worker 连接断开 |
| 24 | `K_WORKER_DEADLOCK` | Worker 可能死锁 |
| 25 | `K_MASTER_TIMEOUT` | Master 超时/不可用 |
| 26 | `K_NOT_FOUND_IN_L2CACHE` | L2 未命中（语义层） |
| 27 | `K_REPLICA_NOT_READY` | 副本未就绪 |
| 28 | `K_CLIENT_WORKER_VERSION_MISMATCH` | 版本不匹配 |
| 29 | `K_SERVER_FD_CLOSED` | 服务端 fd 已关闭 |
| 30 | `K_RETRY_IF_LEAVING` | Worker 正在退出，宜重试 |
| 31 | `K_SCALE_DOWN` | Worker 缩容退出中 |
| 32 | `K_SCALING` | 集群扩缩容进行中 |
| 33 | `K_CLIENT_DEADLOCK` | Client 侧死锁风险/检测 |
| 34 | `K_LRU_HARD_LIMIT` | LRU 硬限制 |
| 35 | `K_LRU_SOFT_LIMIT` | LRU 软限制 |
| 36 | `K_NOT_SUPPORTED` | （.def 未列；语义：不支持） |

### 1.2 RPC / URMA `[1000, 2000)`

| 数值 | 枚举 | 典型含义 |
|----|------|----------|
| 1000 | `K_RPC_CANCELLED` | RPC cancelled / 通道意外关闭 |
| 1001 | `K_RPC_DEADLINE_EXCEEDED` | RPC deadline exceeded |
| 1002 | `K_RPC_UNAVAILABLE` | RPC unavailable（**桶码**，含多种根因） |
| 1003 | `K_RPC_STREAM_END` | RPC stream finished |
| 1004 | `K_URMA_ERROR` | URMA operation failed |
| 1005 | `K_RDMA_ERROR` | RDMA 错误 |
| 1006 | `K_URMA_NEED_CONNECT` | URMA 需要重连 |
| 1007 | `K_RDMA_NEED_CONNECT` | RDMA 需要重连 |
| 1008 | `K_URMA_TRY_AGAIN` | URMA 瞬时可重试 |

### 1.3 Object / Stream / 异构

| 数值区间 | 说明 |
|---------|------|
| `[2000, 3000)` | `K_OC_*`：`K_OC_ALREADY_SEALED`、`K_OC_REMOTE_GET_NOT_ENOUGH` (2002)、`K_WRITE_BACK_QUEUE_FULL`、`K_OC_KEY_ALREADY_EXIST` 等 |
| `[3000, 4000)` | `K_SC_*`：Stream / Producer / Consumer 相关 |
| `[5000, 6000]` | 设备侧：`K_ACL_ERROR`、`K_HCCL_ERROR`、`K_FUTURE_TIMEOUT`、`K_CUDA_ERROR`、`K_NCCL_ERROR` |

Python / Java / Go SDK 最终映射到同一套数值。

---

## 2. L0 → L5 分层视图

**下层故障往往被上层归类或透传**；同一数值可能对应多类根因，必须结合 `respMsg`、日志与路径（是否走 UB、是否已 mmap SHM）定界。

```text
[L5 应用 / 业务语义]
    K_INVALID, K_NOT_FOUND, K_DUPLICATED, K_RUNTIME_ERROR,
    K_NOT_AUTHORIZED, K_NOT_FOUND_IN_L2CACHE, K_LRU_* …

[L4 Object / KV 业务与 Worker 侧语义]
    K_OC_* (如 K_OC_REMOTE_GET_NOT_ENOUGH=2002), K_WRITE_BACK_QUEUE_FULL …
    Worker 返回的 last_rc（批量路径可能与顶层 Status 不一致）

[L3 Client ↔ Worker：连接、心跳、版本、缩容]
    K_NOT_READY, K_CLIENT_WORKER_DISCONNECT, K_SHUTTING_DOWN,
    K_CLIENT_WORKER_VERSION_MISMATCH, K_SCALE_DOWN, K_SCALING,
    K_RETRY_IF_LEAVING, K_MASTER_TIMEOUT, K_NOT_LEADER_MASTER …

[L2 RPC 控制面：ZMQ/TCP 上的请求/响应/超时/通道状态]
    K_RPC_CANCELLED(1000), K_RPC_DEADLINE_EXCEEDED(1001),
    K_RPC_UNAVAILABLE(1002)

[L1 URMA / UB 数据面：跨节点零拷贝写、会话、JFC 完成]
    K_URMA_ERROR(1004), K_RDMA_ERROR(1005),
    K_URMA_NEED_CONNECT(1006), K_RDMA_NEED_CONNECT(1007),
    K_URMA_TRY_AGAIN(1008)

[L0 基础设施：UB 平面、驱动、Jetty、主机资源]
    通常不直接以 StatusCode 暴露；通过 L1/L2 间接体现
```

---

## 3. 关键码的语义细节

### 3.1 1002（`K_RPC_UNAVAILABLE`）是桶码，不等于"UB 坏了"

**同一码值覆盖多种 Case**（客户端侧常见来源）：

| 子类 | 触发位置 | 典型文案 |
|------|----------|----------|
| ZMQ 阻塞收包 `K_TRY_AGAIN` 被改写 | `common/rpc/zmq/zmq_msg_queue.h::ClientReceiveMsg` | `Rpc service for client ... has not responded within the allowed time` |
| ZMQ 建连/等待对端超时 | `common/rpc/zmq/zmq_stub_conn.cpp`（`WaitFor`/`SockConnEntry`） | `Timeout waiting for SockConnEntry wait` / `Remote service is not available within allowable %d ms` |
| ZMQ 网关/Frontend 转发失败 | `zmq_stub_conn.cpp::ReportErrorToClient` | `The service is currently unavailable!` |
| ZMQ 心跳发送时 `POLLOUT` 不可写 | `zmq_stub_conn.cpp` | `Network unreachable` |
| UnixSockFd socket reset | `common/rpc/unix_sock_fd.cpp::ErrnoToStatus` | `Connect reset. fd %d. err ...` |
| 必须走 SHM/UDS 传 fd 却建失败 | `client/client_worker_common_api.cpp` | `Can not create connection to worker for shm fd transfer` |

> **结论**：URMA 瞬时失效应优先看 **1008 / 1006 / 1004**；只看到 1002 时必须结合 `respMsg` 文案和路径判断。区分方法见 [06-playbook.md § 2](06-playbook.md)。

### 3.2 URMA 三码的关系

```text
K_URMA_NEED_CONNECT (1006)
    → TryReconnectRemoteWorker → transport exchange
    → 成功后返回 K_TRY_AGAIN("Reconnect success")
    → 外层 RetryOnError 继续重试
K_URMA_TRY_AGAIN (1008)  瞬时可恢复，RECREATE_JFS 等策略
K_URMA_ERROR    (1004)  持久错误；驱动/资源/语义失败
```

**证据**：`src/datasystem/common/rdma/urma_manager.cpp::CheckUrmaConnectionStable` → 1006；`src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker`。

### 3.3 fd + SHM 路径的典型码

| 码 | 关系 |
|----|------|
| 1002（`Can not create connection to worker for shm fd transfer`） | 强制 UDS/fd 传输失败 |
| 29（`K_SERVER_FD_CLOSED`） | 服务端已关闭传递的 fd |
| 18（`K_FILE_LIMIT_REACHED`） | FD 耗尽，影响 fd 接收与连接复用 |
| 8（`K_NOT_READY`） | 未完成初始化，SHM 路径未就绪 |

### 3.4 K_NOT_FOUND 在 KV Get access log 中记为 K_OK

源码：`src/datasystem/client/kv_cache/kv_client.cpp::Get` —

```cpp
StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode();
accessPoint.Record(code, ...);
```

**含义**：排障时若只看 access log 第一列，`K_NOT_FOUND` 看起来是成功。需结合 `rc.GetMsg()` 或业务语义判断。

### 3.5 K_SCALING (32) 在 Get 批量路径上可能不冒顶层

`Get` 的 `RetryOnError` 集合只包含 `IsRpcTimeoutOrTryAgain`（`K_TRY_AGAIN` + RPC 超时类）+ 特定 OOM。`K_SCALING` 放在 `GetRspPb.last_rc` 时，lambda 返回 OK 结束重试，顶层 `Get()` 可能返回 `Status::OK()`，错误落在 **per-object 状态**。详见 [06-playbook.md § 3](06-playbook.md)。

---

## 4. FEMA 故障模式 → StatusCode（启发式映射）

| FEMA 类别 | 客户端常见表现 | 优先对照的码 |
|-----------|----------------|--------------|
| Worker 宕机 / 反复重启 / 容器退出 | 连接失败、读写过半失败 | 1002、23、29 |
| Master 故障 / etcd 异常 | 路由/元数据长时间不可用 | 25、14、19、RPC 超时类 |
| 网络闪断 / UB / TCP 丢包抖动 | 间歇失败、重试后可恢复 | 1001、19、1008 |
| URMA / RDMA 路径 | 远端读、高性能路径失败 | 1004、1006、1005、1007 |
| 缩容 / 主动下线 | 特定 key 连续失败，带"重试"语义 | 31、30、32 |
| 资源耗尽（内存 / 磁盘 / FD） | 批量操作失败 | 6、13、18 |
| L2 / 缓存策略 | 未命中与淘汰 | 3、26、34、35 |
| 业务逻辑 / 参数错误 | 稳定复现，与负载无关 | 2、3、1 |

> 该映射仅作 triage 起点，具体根因仍需看 [04-fault-tree.md](04-fault-tree.md) 的源码证据。

---

## 5. 端到端链条：从 enum 到 access log

```text
status.h  (枚举值)
    ↓
status_code.def → Status::StatusCodeName  (可读名)
    ↓
ZMQ stub / socket 路径 → Status(K_RPC_*)   (传输层映射)
    ↓
ClientWorkerRemoteApi::RetryOnError + RETRY_ERROR_CODE / Register 列表
    ↓
KVClient / ObjectClientImpl → Status 返回应用
    ↓
AccessRecorder::Record(code) → ds_client_access_<pid>.log
（第一列整数码；Get + K_NOT_FOUND 例外见 § 3.4）
```

`RETRY_ERROR_CODE` 默认集合（`client/object_cache/client_worker_api/client_worker_remote_api.cpp`）：

```cpp
{ K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED,
  K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY }
```

`MultiPublish` 在此基础上额外纳入 `K_SCALING`；`Get` 的 lambda 通过 `IsRpcTimeoutOrTryAgain` 裁剪。`RegisterClient` 另外把 `K_SERVER_FD_CLOSED` 改写为 `K_TRY_AGAIN` 再向上返回。
