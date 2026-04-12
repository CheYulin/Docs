# temp
# URMA / OS 与 Init、读取、写入：跨模块调用、错误点、返回与重试（完整版）

**目标**：覆盖 `client1 / worker1 / worker2 / worker3` 调用链上，与 **URMA 接口**、**OS/syscall** 相关的失败点；按 `(a)/(b)/(c)` 说明错误码、日志、返回方式、是否重试。  
**仓库**：`yuanrong-datasystem`。  
**说明**：`worker2` 表示 **Directory（对象目录）** 分片所在逻辑对端（hash ring；etcd 多为租约/路由），`worker3` 表示数据副本 Worker。

## 0) 命名约定

| 记号 | 含义 |
|---|---|
| `client1` | SDK 进程内 |
| `client1->worker1` | SDK 到入口 Worker RPC |
| `worker1` | 入口 Worker 本进程 |
| `worker1->worker2` | 入口 Worker 到元数据对端 |
| `worker1->worker3` | 入口 Worker 到数据副本 Worker |
| `worker3` | 数据副本 Worker 本进程 |

---

## 1) SDK Init 逻辑

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 凭证与参数校验 | `client1` | `KVClient::Init`<br>`|_ ObjectClientImpl::Init` | 无 | (a) 参数非法 -> `K_INVALID` | 直接返回，无重试 |
| 建连+注册 | `client1->worker1` | `InitClientWorkerConnect`<br>`|_ Connect`<br>`|_ RegisterClient` | OS：socket（框架封装） | (a) 建连失败 -> `1002` + `Register client failed`<br>(b) 超时 -> `1001` | 直接返回 |
| UDS 传 fd | `client1`（对端 `worker1` 发 fd） | `PostRegisterClient`<br>`|_ RecvPageFd`<br>`|_ SockRecvFd` | syscall：`sendmsg`/`recvmsg`/`close`（`fd_pass.cpp`） | (a) `recvmsg` 异常 -> `K_UNKNOWN_ERROR` `Pass fd meets unexpected error: errno`<br>(b) 非法 fd -> `K_UNKNOWN_ERROR` `We receive the invalid fd`<br>(c) 空 fd -> WARNING `may exceed the max open fd limit` | GetClientFd 主流程不重试；失败常在后续 mmap 暴露 |
| UB 快速握手 | `client1` + `client1->worker1` | `PostRegisterClient`<br>`|_ LOG_IF_ERROR(FastTransportHandshake)`<br>`|_ InitializeFastTransportManager`<br>`|_ ExecOnceParrallelExchange`<br>`|_ ExchangeJfr` | URMA：`UrmaManager::Init` 链，JFR 导入/交换；OS：`mmap` UB 池 | (a) `urma_init` 等失败 -> `K_URMA_ERROR/1004`<br>(b) UB 池 `mmap` 失败 -> `K_OUT_OF_MEMORY/6`<br>(c) `ExchangeJfr` 失败 -> `K_URMA_ERROR/K_RUNTIME_ERROR` | **关键**：`LOG_IF_ERROR` 仅日志，不阻断 Init（可回退 TCP） |

---

## 2) 读取流程（Get/MGet，含 UB 失败切 TCP）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)/(c)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置校验与路由 | `client1` | `ObjectClientImpl::Get`<br>`|_ IsClientReady`<br>`|_ GetAvailableWorkerApi` | 无 | (a) `K_INVALID`<br>(b) `K_NOT_READY` | 直接返回 |
| **UB 缓冲准备（读）** | `client1` | `ClientWorkerRemoteApi::Get`<br>`|_ PrepareUrmaBuffer`<br>`|_ GetMemoryBufferHandle/GetMemoryBufferInfo` | URMA：客户端 UB 缓冲池 | **(a) UB 失败 -> WARNING + 回退 TCP**：`Prepare UB Get request failed: ..., fallback to TCP/IP payload.`<br>(b) UB 成功 -> 请求带 `urma_info` | **这是 UB 失败切 TCP 的核心逻辑**；不向上抛 URMA 码 |
| Get 控制面 RPC | `client1->worker1` | `ClientWorkerRemoteApi::Get`<br>`|_ RetryOnError`<br>`|_ stub_->Get` | OS：网络栈（封装） | (a) `1002/1001/19`<br>(b) `last_rc` timeout/try_again 触发重试<br>(c) `K_OUT_OF_MEMORY` 且 all failed 触发重试 | 走 `RetryOnError`（`RETRY_ERROR_CODE`） |
| worker1 元数据与远端拉取 | `worker1` + `worker1->worker2` + `worker1->worker3` | `WorkerOcServiceGetImpl::Get`<br>`|_ ProcessGetObjectRequest`<br>`|_ QueryMeta`<br>`|_ GetObjectFromRemote...` | URMA：远端数据面会进入 `urma_write/read/poll/wait` | (a) `etcd is unavailable` -> `1002`<br>(b) 远端失败 -> `Get from remote failed` | 以 `last_rc`/RPC 回 client1 |
| worker3 URMA 数据面 | `worker3` | `UrmaWritePayload`<br>`|_ urma_write/urma_read`<br>`|_ urma_poll_jfc/urma_wait_jfc` | URMA：`urma_write` `urma_read` `urma_poll_jfc` `urma_wait_jfc` `urma_ack_jfc` `urma_rearm_jfc` | (a) write/read 失败 -> `K_RUNTIME_ERROR`<br>(b) poll/wait/rearm 失败 -> `K_URMA_ERROR`<br>(c) 连接不稳 -> `K_URMA_NEED_CONNECT/1006` | worker1 汇总后返回 |
| client1 回包组装与 SHM/payload 解析 | `client1` | `FillUrmaBuffer`<br>`|_ GetBuffersFromWorker`<br>`|_ MmapShmUnit / SetNonShmObjectBuffer` | URMA：UB 回填；OS：mmap | (a) `UB payload overflow` -> `K_RUNTIME_ERROR`<br>(b) `Get mmap entry failed` -> `K_RUNTIME_ERROR`<br>(c) payload copy/index 错 -> `K_UNKNOWN_ERROR/K_RUNTIME_ERROR` | `FillUrmaBuffer` 失败直接返回；无统一重试 |

---

## 3) 写入流程（Put/MSet）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置与分支 | `client1` | `ObjectClientImpl::Put/MSet`<br>`|_ ShmCreateable / IsUrmaEnabled` | 无 | (a) 参数非法 -> `K_INVALID` | 直接返回 |
| 单对象 UB 发送 | `client1` | `SendBufferViaUb`<br>`|_ GetMemoryBufferHandle`<br>`|_ memcpy`<br>`|_ UrmaWritePayload` | URMA：`UrmaWritePayload` | (a) 失败 -> `K_INVALID` `Failed to send buffer via UB`<br>(b) 成功 -> `[UB Put] UrmaWritePayload done` | 可退回非 UB 路径 |
| Publish / MultiPublish RPC | `client1->worker1` | `Publish/MultiPublish`<br>`|_ RetryOnError`<br>`|_ stub_->Publish/MultiPublish` | OS：网络连接（封装） | (a) `1002/1001/19` 重试<br>(b) MultiPublish 额外重试 `K_SCALING/32`、`K_OUT_OF_MEMORY/6` | 走 `RetryOnError`；Publish seal 重试遇 `K_OC_ALREADY_SEALED` 可视成功 |
| worker1->worker3 写数据面 | `worker1->worker3` + `worker3` | 写路径与读路径 URMA 对称 | URMA 同读路径 | (a) `K_URMA_ERROR/K_RUNTIME_ERROR`<br>(b) `K_URMA_NEED_CONNECT` / RPC 错 | 多由 worker 汇总回 client1 |

---

## 4) URMA 接口清单（尽可能全，`urma_manager.cpp` 直接调用）

`urma_init`, `urma_uninit`, `urma_register_log_func`, `urma_unregister_log_func`,  
`urma_get_device_list`, `urma_get_device_by_name`, `urma_query_device`,  
`urma_get_eid_list`, `urma_free_eid_list`,  
`urma_create_context`, `urma_delete_context`,  
`urma_create_jfce`, `urma_delete_jfce`,  
`urma_create_jfc`, `urma_delete_jfc`, `urma_rearm_jfc`,  
`urma_create_jfs`, `urma_delete_jfs`,  
`urma_create_jfr`, `urma_delete_jfr`,  
`urma_register_seg`, `urma_unregister_seg`,  
`urma_import_seg`, `urma_unimport_seg`,  
`urma_import_jfr`, `urma_unimport_jfr`, `urma_advise_jfr`,  
`urma_write`, `urma_read`, `urma_post_jfs_wr`,  
`urma_wait_jfc`, `urma_poll_jfc`, `urma_ack_jfc`.

---

## 5) OS/syscall 清单（读写初始化链路）

| syscall / OS 接口 | 主要位置 | 关联流程 |
|---|---|---|
| `sendmsg` / `recvmsg` | `common/util/fd_pass.cpp` | Init UDS 传 fd、读路径 SHM 回数 |
| `close` | `fd_pass.cpp`、`client_worker_common_api.cpp` | 过期 fd 清理 |
| `mmap` / `munmap` | `urma_manager.cpp` | UB 客户端缓冲池 |
| socket 建连（封装） | `client_worker_common_api.cpp` | Init、读写控制面 |
| `usleep` | `urma_manager.cpp::PollJfcWait` | URMA 轮询等待 |
| `memcpy` / `MemoryCopy` | `client_worker_base_api.cpp`、`object_client_impl.cpp` | payload/UB 组装 |

---

## 6) 本次补齐点

1. 明确补齐读取流程 **“UB 失败 -> TCP 回退”** 分支和日志。  
2. 增加 URMA 接口覆盖清单（`urma_manager.cpp` 直接调用集合）。  
3. 增加 OS/syscall 清单并标注到链路。  
4. 每个大步骤补 `(a)/(b)/(c)` 的错误码、日志、返回与重试语义。

# URMA / OS 与 Init、读取、写入：跨模块调用、错误点、返回与重试（完整版）

**目标**：覆盖 `client1 / worker1 / worker2 / worker3` 调用链上，和 **URMA 接口**、**OS/syscall** 相关的主要失败点；按 `(a)/(b)/(c)` 形式说明：失败条件、错误码、日志、返回方式、是否重试。  
**仓库**：`yuanrong-datasystem`。  
**说明**：`worker2` 表示 **Directory** 逻辑对端（实现上 API 名可能仍含 Master/QueryMeta；etcd 多为租约）；`worker3` 表示数据副本 Worker。

---

## 0) 命名约定

| 记号 | 含义 |
|---|---|
| `client1` | SDK 进程内逻辑 |
| `client1->worker1` | SDK 到入口 Worker 的 RPC |
| `worker1` | 入口 Worker 本进程处理 |
| `worker1->worker2` | 入口 Worker 到元数据对端 |
| `worker1->worker3` | 入口 Worker 到数据副本 Worker |
| `worker3` | 数据副本 Worker 本进程处理 |

---

## 1) SDK Init 逻辑（重点：建连、fd 传递、UB 握手）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 凭证与参数校验 | `client1` | `KVClient::Init`<br>`|_ ObjectClientImpl::Init`<br>`|_ ValidatePort/HostPort` | OS/URMA 无直接调用 | (a) 参数非法 -> `K_INVALID`，日志含 host/port 校验信息 | 直接 `RETURN`，无重试 |
| 连接 worker 并注册客户端 | `client1->worker1` | `InitClientWorkerConnect`<br>`|_ ClientWorkerRemoteApi::Init`<br>`|_ Connect`<br>`|_ RegisterClient` | OS：socket 建连（框架封装） | (a) 建连失败 -> `K_RPC_UNAVAILABLE/1002`，`Register client failed`<br>(b) 超时 -> `K_RPC_DEADLINE_EXCEEDED/1001` | 失败直接返回；该步通常不走 `RetryOnError` |
| UDS fd 通道与收 fd | `client1`（对端 `worker1` 发 fd） | `PostRegisterClient`<br>`|_ RecvPageFd`<br>`|_ SockRecvFd` | OS/syscall：`sendmsg`、`recvmsg`、`close`（`fd_pass.cpp`） | (a) `recvmsg` 异常 -> `K_UNKNOWN_ERROR`，`Pass fd meets unexpected error: errno`<br>(b) 收到非法 fd -> `K_UNKNOWN_ERROR`，`We receive the invalid fd`<br>(c) 空 fd 列表 -> WARNING：`may exceed the max open fd limit` | 读线程持续等待；GetClientFd 主流程注明“不重试”，失败多在后续 mmap 暴露 |
| UB 快速传输握手（可选） | `client1` + `client1->worker1` | `PostRegisterClient`<br>`|_ LOG_IF_ERROR(FastTransportHandshake)`<br>`|_ InitializeFastTransportManager`<br>`|_ ExecOnceParrallelExchange`<br>`|_ ExchangeJfr` | URMA：`UrmaManager::Init` 链 + JFR 交换；OS：客户端 UB 池 `mmap` | (a) `urma_init` 等失败 -> `K_URMA_ERROR/1004`，`Failed to urma init...`<br>(b) UB 池 `mmap` 失败 -> `K_OUT_OF_MEMORY/6`，`Failed to allocate memory buffer pool...`<br>(c) `ExchangeJfr` 失败 -> `K_URMA_ERROR/K_RUNTIME_ERROR` | **关键**：`LOG_IF_ERROR` 只打 ERROR，不阻断 Init；表现为“握手失败但回退 TCP” |

---

## 2) 读取流程（Get/MGet，重点补齐：UB 失败 -> TCP 回退）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)/(c)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置校验与路由 | `client1` | `ObjectClientImpl::Get`<br>`|_ IsClientReady`<br>`|_ CheckValidObjectKeyVector`<br>`|_ GetAvailableWorkerApi` | 无 URMA/syscall 直接调用 | (a) 参数问题 -> `K_INVALID`<br>(b) 客户端状态问题 -> `K_NOT_READY` | 直接返回，无重试 |
| **UB 缓冲准备（读）** | `client1` | `ClientWorkerRemoteApi::Get`<br>`|_ PrepareUrmaBuffer`<br>`|_ GetMemoryBufferHandle/GetMemoryBufferInfo` | URMA：客户端 UB 缓冲池与地址信息 | **(a) UB 准备失败 -> WARNING + 回退 TCP**：`Prepare UB Get request failed: ..., fallback to TCP/IP payload.`（`client_worker_base_api.cpp`）<br>(b) UB 准备成功 -> 请求携带 `urma_info` + `ub_buffer_size` | **这是“UB 失败切 TCP”的核心逻辑**；不抛 URMA 码给上层，继续走 Get RPC |
| Get 控制面 RPC | `client1->worker1` | `ClientWorkerRemoteApi::Get`<br>`|_ RetryOnError`<br>`|_ stub_->Get` | OS：网络连接（框架封装） | (a) RPC 不可用/超时/try_again -> `1002/1001/19`<br>(b) worker `last_rc` 为 timeout/try_again 触发重试<br>(c) `last_rc=K_OUT_OF_MEMORY` 且 all failed 触发重试 | 走 `RetryOnError`（`RETRY_ERROR_CODE`）；失败消息追加 `RPC Retry detail` |
| worker1 处理与元数据查询 | `worker1` + `worker1->worker2` | `WorkerOcServiceGetImpl::Get`<br>`|_ ProcessGetObjectRequest`<br>`|_ TryGetObjectFromLocal`<br>`|_ QueryMeta / etcd` | OS：etcd/grpc 网络；URMA 无直接 | (a) `etcd is unavailable` -> `K_RPC_UNAVAILABLE/1002`<br>(b) query meta 失败 -> `K_RUNTIME_ERROR` 等 | 多经 worker 响应 `last_rc` 回 client1 |
| 远端拉取与 URMA 数据面 | `worker1->worker3` + `worker3` | `GetObjectFromRemote...`<br>`|_ worker3 处理`<br>`|_ UrmaWritePayload/urma_write`<br>`|_ worker1 PollJfcWait` | URMA：`urma_write`、`urma_read`、`urma_poll_jfc`、`urma_wait_jfc`、`urma_ack_jfc`、`urma_rearm_jfc` | (a) `urma_write/read` 失败 -> `K_RUNTIME_ERROR`，`Failed to urma write/read...`<br>(b) poll/wait/rearm 失败 -> `K_URMA_ERROR`，`Failed to poll/wait/rearm jfc...`<br>(c) 连接不稳 -> `K_URMA_NEED_CONNECT/1006` | 由 worker1 汇总为 `last_rc` 或 RPC 状态返回；与 client1 重试叠加 |
| 返回后 UB 组装与 SHM/payload 解析 | `client1` | `FillUrmaBuffer`<br>`|_ GetBuffersFromWorker`<br>`|_ GetObjectBuffers`<br>`|_ MmapShmUnit / SetNonShmObjectBuffer` | URMA：UB 数据回填；OS：`mmap`（通过 mmap manager） | (a) UB payload 越界/非法 -> `K_RUNTIME_ERROR`，`Invalid UB payload size` / `UB payload overflow`<br>(b) SHM 映射失败 -> `K_RUNTIME_ERROR`，`Get mmap entry failed`<br>(c) payload 索引或拷贝失败 -> `K_UNKNOWN_ERROR/K_RUNTIME_ERROR` | `FillUrmaBuffer` 失败会直接返回（即使 RPC 已成功）；本段无统一重试 |

---

## 3) 写入流程（Put/MSet，重点：UB 写、Publish 重试）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置校验与路径选择 | `client1` | `ObjectClientImpl::Put/MSet`<br>`|_ ShmCreateable / IsUrmaEnabled` | 无直接 URMA/syscall | (a) 参数非法 -> `K_INVALID` | 直接返回 |
| 单对象 UB 发送（可选） | `client1` | `SendBufferViaUb`<br>`|_ GetMemoryBufferHandle`<br>`|_ memcpy`<br>`|_ UrmaWritePayload` | URMA：`UrmaWritePayload`；OS：内存拷贝 | (a) UB 发送失败 -> `K_INVALID`，`Failed to send buffer via UB`<br>(b) UB 成功 -> INFO `[UB Put] UrmaWritePayload done...` | 失败回上层，可退回非 UB 路径 |
| Publish / MultiPublish 控制面 | `client1->worker1` | `Publish/MultiPublish`<br>`|_ RetryOnError`<br>`|_ stub_->Publish/MultiPublish` | OS：网络连接 | (a) 传输失败 -> `1002/1001/19`（重试）<br>(b) MultiPublish 还可重试 `K_SCALING/32`、`K_OUT_OF_MEMORY/6` | 走 `RetryOnError`；Publish 重试 seal 时 `K_OC_ALREADY_SEALED` 可视成功 |
| worker1/worker3 写入数据面 | `worker1->worker3` + `worker3` | 写路径对称读路径<br>`|_ URMA write/poll` | URMA 同读路径 | (a) URMA 完成错误 -> `K_URMA_ERROR/K_RUNTIME_ERROR`<br>(b) 远端不可达 -> `K_URMA_NEED_CONNECT` / RPC 错 | 多由 worker 响应回 client1 |

---

## 4) URMA 接口清单（尽可能全，来自 `urma_manager.cpp` 直接调用）

> 这一节是“接口覆盖清单”，用于确认表格没漏大类调用。以下均在仓库里有直接符号调用。

`urma_init`, `urma_uninit`, `urma_register_log_func`, `urma_unregister_log_func`,  
`urma_get_device_list`, `urma_get_device_by_name`, `urma_query_device`,  
`urma_get_eid_list`, `urma_free_eid_list`,  
`urma_create_context`, `urma_delete_context`,  
`urma_create_jfce`, `urma_delete_jfce`,  
`urma_create_jfc`, `urma_delete_jfc`, `urma_rearm_jfc`,  
`urma_create_jfs`, `urma_delete_jfs`,  
`urma_create_jfr`, `urma_delete_jfr`,  
`urma_register_seg`, `urma_unregister_seg`,  
`urma_import_seg`, `urma_unimport_seg`,  
`urma_import_jfr`, `urma_unimport_jfr`, `urma_advise_jfr`,  
`urma_write`, `urma_read`, `urma_post_jfs_wr`,  
`urma_wait_jfc`, `urma_poll_jfc`, `urma_ack_jfc`.

---

## 5) OS/syscall 清单（读写初始化链路，尽可能全）

| syscall / OS 接口 | 主要位置 | 关联流程 |
|---|---|---|
| `sendmsg` / `recvmsg` | `common/util/fd_pass.cpp` (`SockSendFd`/`SockRecvFd`) | Init 后 UDS 传 fd，读路径 SHM 回数 |
| `close` | `fd_pass.cpp`；`client_worker_common_api.cpp`（过期 fd 清理） | Init/运行期 fd 生命周期 |
| `mmap` / `munmap` | `urma_manager.cpp`（UB 客户端缓冲池） | Init、UB 数据面 |
| socket 建连（框架封装） | `client_worker_common_api.cpp` 连接链 | Init、读写控制面 RPC |
| `usleep` | `urma_manager.cpp::PollJfcWait` | URMA 轮询等待路径 |
| 内存拷贝（`memcpy`/`MemoryCopy`） | `client_worker_base_api.cpp`、`object_client_impl.cpp` | 读写 payload/UB 组装（非 syscall，但关键 OS 资源点） |

---

## 6) 这版相对上一版补齐点

1. 补了读取流程里 **“UB 失败切 TCP”** 的明确行和日志原文。  
2. 增加 URMA 接口全集（`urma_manager.cpp` 直接调用集合）。  
3. 增加 OS/syscall 清单，并指明在哪条链路使用。  
4. 每个大步骤按 `(a)/(b)/(c)` 给出错误码、日志、返回方式、是否重试。

# URMA / OS 与 Init、读取、写入：跨模块调用、错误点、返回与重试（完整版）

**目标**：覆盖 `client1 / worker1 / worker2 / worker3` 调用链上，和 **URMA 接口**、**OS/syscall** 相关的主要失败点；按 `(a)/(b)/(c)` 形式说明：失败条件、错误码、日志、返回方式、是否重试。  
**仓库**：`yuanrong-datasystem`。  
**说明**：`worker2` 表示 **Directory** 逻辑对端（实现上 API 名可能仍含 Master/QueryMeta；etcd 多为租约）；`worker3` 表示数据副本 Worker。

---

## 0) 命名约定

| 记号 | 含义 |
|---|---|
| `client1` | SDK 进程内逻辑 |
| `client1->worker1` | SDK 到入口 Worker 的 RPC |
| `worker1` | 入口 Worker 本进程处理 |
| `worker1->worker2` | 入口 Worker 到元数据对端 |
| `worker1->worker3` | 入口 Worker 到数据副本 Worker |
| `worker3` | 数据副本 Worker 本进程处理 |

---

## 1) SDK Init 逻辑（重点：建连、fd 传递、UB 握手）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 凭证与参数校验 | `client1` | `KVClient::Init`<br>`|_ ObjectClientImpl::Init`<br>`|_ ValidatePort/HostPort` | OS/URMA 无直接调用 | (a) 参数非法 -> `K_INVALID`，日志含 host/port 校验信息 | 直接 `RETURN`，无重试 |
| 连接 worker 并注册客户端 | `client1->worker1` | `InitClientWorkerConnect`<br>`|_ ClientWorkerRemoteApi::Init`<br>`|_ Connect`<br>`|_ RegisterClient` | OS：socket 建连（框架封装） | (a) 建连失败 -> `K_RPC_UNAVAILABLE/1002`，`Register client failed`<br>(b) 超时 -> `K_RPC_DEADLINE_EXCEEDED/1001` | 失败直接返回；该步通常不走 `RetryOnError` |
| UDS fd 通道与收 fd | `client1`（对端 `worker1` 发 fd） | `PostRegisterClient`<br>`|_ RecvPageFd`<br>`|_ SockRecvFd` | OS/syscall：`sendmsg`、`recvmsg`、`close`（`fd_pass.cpp`） | (a) `recvmsg` 异常 -> `K_UNKNOWN_ERROR`，`Pass fd meets unexpected error: errno`<br>(b) 收到非法 fd -> `K_UNKNOWN_ERROR`，`We receive the invalid fd`<br>(c) 空 fd 列表 -> WARNING：`may exceed the max open fd limit` | 读线程持续等待；GetClientFd 主流程注明“不重试”，失败多在后续 mmap 暴露 |
| UB 快速传输握手（可选） | `client1` + `client1->worker1` | `PostRegisterClient`<br>`|_ LOG_IF_ERROR(FastTransportHandshake)`<br>`|_ InitializeFastTransportManager`<br>`|_ ExecOnceParrallelExchange`<br>`|_ ExchangeJfr` | URMA：`UrmaManager::Init` 链 + JFR 交换；OS：客户端 UB 池 `mmap` | (a) `urma_init` 等失败 -> `K_URMA_ERROR/1004`，`Failed to urma init...`<br>(b) UB 池 `mmap` 失败 -> `K_OUT_OF_MEMORY/6`，`Failed to allocate memory buffer pool...`<br>(c) `ExchangeJfr` 失败 -> `K_URMA_ERROR/K_RUNTIME_ERROR` | **关键**：`LOG_IF_ERROR` 只打 ERROR，不阻断 Init；表现为“握手失败但回退 TCP” |

---

## 2) 读取流程（Get/MGet，重点补齐：UB 失败 -> TCP 回退）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)/(c)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置校验与路由 | `client1` | `ObjectClientImpl::Get`<br>`|_ IsClientReady`<br>`|_ CheckValidObjectKeyVector`<br>`|_ GetAvailableWorkerApi` | 无 URMA/syscall 直接调用 | (a) 参数问题 -> `K_INVALID`<br>(b) 客户端状态问题 -> `K_NOT_READY` | 直接返回，无重试 |
| **UB 缓冲准备（读）** | `client1` | `ClientWorkerRemoteApi::Get`<br>`|_ PrepareUrmaBuffer`<br>`|_ GetMemoryBufferHandle/GetMemoryBufferInfo` | URMA：客户端 UB 缓冲池与地址信息 | **(a) UB 准备失败 -> WARNING + 回退 TCP**：`Prepare UB Get request failed: ..., fallback to TCP/IP payload.`（`client_worker_base_api.cpp`）<br>(b) UB 准备成功 -> 请求携带 `urma_info` + `ub_buffer_size` | **这是“UB 失败切 TCP”的核心逻辑**；不抛 URMA 码给上层，继续走 Get RPC |
| Get 控制面 RPC | `client1->worker1` | `ClientWorkerRemoteApi::Get`<br>`|_ RetryOnError`<br>`|_ stub_->Get` | OS：网络连接（框架封装） | (a) RPC 不可用/超时/try_again -> `1002/1001/19`<br>(b) worker `last_rc` 为 timeout/try_again 触发重试<br>(c) `last_rc=K_OUT_OF_MEMORY` 且 all failed 触发重试 | 走 `RetryOnError`（`RETRY_ERROR_CODE`）；失败消息追加 `RPC Retry detail` |
| worker1 处理与元数据查询 | `worker1` + `worker1->worker2` | `WorkerOcServiceGetImpl::Get`<br>`|_ ProcessGetObjectRequest`<br>`|_ TryGetObjectFromLocal`<br>`|_ QueryMeta / etcd` | OS：etcd/grpc 网络；URMA 无直接 | (a) `etcd is unavailable` -> `K_RPC_UNAVAILABLE/1002`<br>(b) query meta 失败 -> `K_RUNTIME_ERROR` 等 | 多经 worker 响应 `last_rc` 回 client1 |
| 远端拉取与 URMA 数据面 | `worker1->worker3` + `worker3` | `GetObjectFromRemote...`<br>`|_ worker3 处理`<br>`|_ UrmaWritePayload/urma_write`<br>`|_ worker1 PollJfcWait` | URMA：`urma_write`、`urma_read`、`urma_poll_jfc`、`urma_wait_jfc`、`urma_ack_jfc`、`urma_rearm_jfc` | (a) `urma_write/read` 失败 -> `K_RUNTIME_ERROR`，`Failed to urma write/read...`<br>(b) poll/wait/rearm 失败 -> `K_URMA_ERROR`，`Failed to poll/wait/rearm jfc...`<br>(c) 连接不稳 -> `K_URMA_NEED_CONNECT/1006` | 由 worker1 汇总为 `last_rc` 或 RPC 状态返回；与 client1 重试叠加 |
| 返回后 UB 组装与 SHM/payload 解析 | `client1` | `FillUrmaBuffer`<br>`|_ GetBuffersFromWorker`<br>`|_ GetObjectBuffers`<br>`|_ MmapShmUnit / SetNonShmObjectBuffer` | URMA：UB 数据回填；OS：`mmap`（通过 mmap manager） | (a) UB payload 越界/非法 -> `K_RUNTIME_ERROR`，`Invalid UB payload size` / `UB payload overflow`<br>(b) SHM 映射失败 -> `K_RUNTIME_ERROR`，`Get mmap entry failed`<br>(c) payload 索引或拷贝失败 -> `K_UNKNOWN_ERROR/K_RUNTIME_ERROR` | `FillUrmaBuffer` 失败会直接返回（即使 RPC 已成功）；本段无统一重试 |

---

## 3) 写入流程（Put/MSet，重点：UB 写、Publish 重试）

| 大处理内容 | 发生位置 | 调用链（树） | URMA / OS 接口覆盖 | 失败分支（`(a)/(b)`） | 返回方式与重试 |
|---|---|---|---|---|---|
| 前置校验与路径选择 | `client1` | `ObjectClientImpl::Put/MSet`<br>`|_ ShmCreateable / IsUrmaEnabled` | 无直接 URMA/syscall | (a) 参数非法 -> `K_INVALID` | 直接返回 |
| 单对象 UB 发送（可选） | `client1` | `SendBufferViaUb`<br>`|_ GetMemoryBufferHandle`<br>`|_ memcpy`<br>`|_ UrmaWritePayload` | URMA：`UrmaWritePayload`；OS：内存拷贝 | (a) UB 发送失败 -> `K_INVALID`，`Failed to send buffer via UB`<br>(b) UB 成功 -> INFO `[UB Put] UrmaWritePayload done...` | 失败回上层，可退回非 UB 路径 |
| Publish / MultiPublish 控制面 | `client1->worker1` | `Publish/MultiPublish`<br>`|_ RetryOnError`<br>`|_ stub_->Publish/MultiPublish` | OS：网络连接 | (a) 传输失败 -> `1002/1001/19`（重试）<br>(b) MultiPublish 还可重试 `K_SCALING/32`、`K_OUT_OF_MEMORY/6` | 走 `RetryOnError`；Publish 重试 seal 时 `K_OC_ALREADY_SEALED` 可视成功 |
| worker1/worker3 写入数据面 | `worker1->worker3` + `worker3` | 写路径对称读路径<br>`|_ URMA write/poll` | URMA 同读路径 | (a) URMA 完成错误 -> `K_URMA_ERROR/K_RUNTIME_ERROR`<br>(b) 远端不可达 -> `K_URMA_NEED_CONNECT` / RPC 错 | 多由 worker 响应回 client1 |

---

## 4) URMA 接口清单（尽可能全，来自 `urma_manager.cpp` 直接调用）

> 这一节是“接口覆盖清单”，用于确认表格没漏大类调用。以下均在仓库里有直接符号调用。

`urma_init`, `urma_uninit`, `urma_register_log_func`, `urma_unregister_log_func`,  
`urma_get_device_list`, `urma_get_device_by_name`, `urma_query_device`,  
`urma_get_eid_list`, `urma_free_eid_list`,  
`urma_create_context`, `urma_delete_context`,  
`urma_create_jfce`, `urma_delete_jfce`,  
`urma_create_jfc`, `urma_delete_jfc`, `urma_rearm_jfc`,  
`urma_create_jfs`, `urma_delete_jfs`,  
`urma_create_jfr`, `urma_delete_jfr`,  
`urma_register_seg`, `urma_unregister_seg`,  
`urma_import_seg`, `urma_unimport_seg`,  
`urma_import_jfr`, `urma_unimport_jfr`, `urma_advise_jfr`,  
`urma_write`, `urma_read`, `urma_post_jfs_wr`,  
`urma_wait_jfc`, `urma_poll_jfc`, `urma_ack_jfc`.

---

## 5) OS/syscall 清单（读写初始化链路，尽可能全）

| syscall / OS 接口 | 主要位置 | 关联流程 |
|---|---|---|
| `sendmsg` / `recvmsg` | `common/util/fd_pass.cpp` (`SockSendFd`/`SockRecvFd`) | Init 后 UDS 传 fd，读路径 SHM 回数 |
| `close` | `fd_pass.cpp`；`client_worker_common_api.cpp`（过期 fd 清理） | Init/运行期 fd 生命周期 |
| `mmap` / `munmap` | `urma_manager.cpp`（UB 客户端缓冲池） | Init、UB 数据面 |
| socket 建连（框架封装） | `client_worker_common_api.cpp` 连接链 | Init、读写控制面 RPC |
| `usleep` | `urma_manager.cpp::PollJfcWait` | URMA 轮询等待路径 |
| 内存拷贝（`memcpy`/`MemoryCopy`） | `client_worker_base_api.cpp`、`object_client_impl.cpp` | 读写 payload/UB 组装（非 syscall，但关键 OS 资源点） |

---

## 6) 这版相对上一版补齐点

1. 补了读取流程里 **“UB 失败切 TCP”** 的明确行和日志原文。  
2. 增加 URMA 接口全集（`urma_manager.cpp` 直接调用集合）。  
3. 增加 OS/syscall 清单，并指明在哪条链路使用。  
4. 每个大步骤按 `(a)/(b)/(c)` 给出错误码、日志、返回方式、是否重试。

# URMA / OS（文件与系统调用）与读写、Init：跨模块报错、返回方式与重试

**仓库**：`yuanrong-datasystem`。  
**目标**：按 **大处理步骤**（每表一行）对齐 **发生位置（client1 / worker1 / 跨进程箭头）**、**树状调用链**、**URMA**、**OS**、**错误传播**、**重试**。

---

## §0 模块命名约定（与 Excel / 工单对齐）

| 符号 | 含义 |
|------|------|
| **client1** | SDK 进程内（无跨进程 RPC）。 |
| **client1→worker1** | 客户端 **stub** 发往 **入口 Worker**（Register/Get/Publish 连的那台）。 |
| **worker1** | **入口 Worker** 进程内逻辑（不强调对哪发 RPC 时）。 |
| **worker1→worker2** | 入口 Worker 访问 **对象目录 Directory**（hash ring 分片；gRPC 等到 **另一 Worker**；etcd 多为租约；填表时 **worker2 = 逻辑对端**）。 |
| **worker2** | 元数据对端 **本进程内**处理。 |
| **worker1→worker3** | 入口 Worker 对 **数据副本 Worker** 发 Worker↔Worker RPC。 |
| **worker3** | 数据副本 Worker **本进程内**处理（含 URMA Write 等）。 |
| **client1**（RPC 返回后） | 响应已在 client1 进程内解析、UB 组装、mmap 等。 |

**单元格内树状可读性**：下一行以 `|_` 表示相对上一行的子步骤（子调用）；多跳 RPC 仍用 **粗线** `client1→worker1` 标在父行，子行 `|_` 只展开符号/文件。

---

## 列说明（下列三表共用）

| 列 | 含义 |
|----|------|
| **大处理内容** | 可独立观测的一段逻辑（工单分桶）。 |
| **发生位置** | §0 符号；跨 RPC 必写箭头。 |
| **调用链（树）** | `|_` 缩进树 + 文件/符号，便于下钻。 |
| **URMA** | UMDK / UB 相关问题。 |
| **OS / 文件 /  syscall** | socket、`mmap`、`recvmsg` fd、`close` 等。 |
| **跨模块报错与传播** | `Status` / `last_rc` / 仅日志。 |
| **重试** | `RetryOnError` 等。 |
| **典型 Status / 关键词** | 常见码与日志。 |

**重试与码集**（未改）：`rpc_util.h` 的 `RetryOnError`；`IsRpcTimeoutOrTryAgain`；`client_worker_remote_api.cpp` 的 `RETRY_ERROR_CODE`。

---

## 1. SDK 初始化（`KVClient::Init` → `ObjectClientImpl::Init` → `InitClientWorkerConnect`）

| 大处理内容 | 发生位置 | 调用链（树） | URMA | OS / syscall | 跨模块报错与传播 | 重试 | 典型 Status / 关键词 |
|------------|----------|--------------|------|--------------|------------------|------|----------------------|
| 凭证与 HostPort 校验 | **client1** | `KVClient::Init`<br>`|_ ObjectClientImpl::Init`<br>`|_ RpcAuthKeyManager::CreateClientCredentials`<br>`|_ Validator::{ValidatePort,ValidateHostPortString}` | — | — | **直接 `RETURN`**，未出本进程 | 无 | `K_INVALID` |
| Remote API 构造与 Init | **client1** | `ObjectClientImpl::InitClientWorkerConnect`<br>`|_ ClientWorkerRemoteApi::Init`<br>`|_ decreaseRPCQ_->Init`（SHM 环形队列） | — | 队列底层或带 errno | `RETURN_IF_NOT_OK_PRINT_ERROR_MSG` → **Init 失败** | 无 | `Init failed with shm circular queue` |
| TCP 建连 + RegisterClient | **client1→worker1** | `ClientWorkerRemoteCommonApi::Connect`<br>`|_ stub_->RegisterClient`（ZMQ 等）<br>`worker1`（对端）<br>`|_ Worker 侧 Register 处理` | — | **client1**：socket 创建/连接 | **RPC `Status` 原样返回**；`Register client failed` | 无（本步无 `RetryOnError`） | `1002`/`1001`/`19` |
| 注册后：心跳参数、UDS 收 fd | **client1**<br>（对端 **worker1** 发 fd） | `PostRegisterClient`<br>`|_ RecvPageFd 线程`<br>`|_ SockRecvFd(socketFd_, …)` | — | **`recvmsg` SCM_RIGHTS**；`close` 过期 fd | 收 fd 失败多 **`LOG(WARNING)`**；致命则后续 mmap 才暴露 | 线程循环等待 | `recv page fd … failed` |
| UB 快速传输握手（可选） | **client1**<br>**client1→worker1** | `PostRegisterClient`<br>`|_ LOG_IF_ERROR(FastTransportHandshake)`<br>`client1`<br>`|_ UrmaManager::Init` → `UrmaInit`…`InitMemoryBufferPool`<br>`client1→worker1`<br>`|_ InitializeFastTransportManager`<br>`|_ WorkerRemoteWorkerTransApi::Init`<br>`|_ ExecOnceParrallelExchange`<br>`|_ ExchangeJfr`（与入口 Worker UB 信息交换） | `urma_*` 失败 → `K_URMA_ERROR` 等<br>（见握手链） | **UB 池** `mmap(ANON)` 失败 | **`LOG_IF_ERROR`：只 `LOG(ERROR)`，不 `RETURN` Init** → Init 仍可能 OK，运行期退 **TCP** | 握手内无全局 `RetryOnError` | `Fast transport handshake failed…fall back to TCP` |
| MmapManager / ListenWorker | **client1** | `InitClientWorkerConnect`<br>`|_ MmapManager(...)`<br>`|_ ListenWorker::StartListenWorker` | — | 运行期大量 mmap | 启动失败 `RETURN` | 视实现 | 心跳/切流 `1002`/`23` 多运行期 |

---

## 2. 读路径（`Get` / `MGet`）

| 大处理内容 | 发生位置 | 调用链（树） | URMA | OS / syscall | 跨模块报错与传播 | 重试 | 典型 Status / 关键词 |
|------------|----------|--------------|------|--------------|------------------|------|----------------------|
| 就绪、batch、选入口 Worker | **client1** | `ObjectClientImpl::Get`<br>`|_ IsClientReady / CheckValidObjectKeyVector`<br>`|_ GetAvailableWorkerApi` | — | — | **`RETURN`** | 无 | `K_INVALID`/`K_NOT_READY`/`1002` |
| 组 Get 请求 + UB 缓冲准备 | **client1** | `ClientWorkerRemoteApi::Get`<br>`|_ PreGet`<br>`|_ PrepareUrmaBuffer` | 池未初始化、`GetMemoryBufferHandle` 失败 | — | **仅 `LOG(WARNING)` + 降级**，**不返回 URMA 码** | 无 | `fallback to TCP/IP payload` |
| Get 控制面 RPC | **client1→worker1** | `ClientWorkerRemoteApi::Get`<br>`|_ RetryOnError`<br>`|_ stub_->Get`<br>`worker1`<br>`|_ WorkerOcServiceGetImpl::Get` → `ProcessGetObjectRequest`（总入口） | — | 网络栈 | 传输：**`Status`**；业务：**`rsp.last_rc`**；lambda 内 **timeout/try-again 或 OOM+全失败** 触发重试 | **是** `RETRY_ERROR_CODE` + 上式 | `1001`/`1002`/`19`/`6`；`Start to send rpc…` |
| worker1 本地命中 / 未命中分支 | **worker1** | `ProcessGetObjectRequest`<br>`|_ TryGetObjectFromLocal`<br>`|_ TryGetObjectFromRemote`（未命中时） | — | 本地盘/L2 等 | `last_rc` / RPC | 部分路径 Worker 内重连 | `K_NOT_FOUND` 等 |
| 查对象目录 | **worker1→worker2** | `TryGetObjectFromRemote` 前置链<br>`|_ QueryMeta → Directory 分片`（源码名可能仍含 Master）<br>`worker2`<br>`|_ 返回 meta 与地址` | — | etcd 租约等 syscall | **`K_RPC_UNAVAILABLE`（如 etcd 续约）** 等经 worker1 填响应 | Directory 侧常有自有重试 | `etcd is unavailable`；`Query from master failed` |
| 向数据副本发拉取 RPC | **worker1→worker3** | `GetObjectFromRemote…`<br>`|_ CreateRemoteWorkerApi` / `stub` 对 worker3<br>`worker3`<br>`|_ GetObjectRemote*` 处理 | — | W↔W socket | RPC **`Status`** / 后续填 **`last_rc`** | `TryReconnectRemoteWorker` 等 | `Get from remote failed` |
| worker3 UB 数据面 | **worker3** | `UrmaWritePayload` / `urma_write` / `PollJfcWait` 等<br>`|_ （对端常为 worker1 侧 import/read）` | **主战场** | TCP 回退时 socket | 错误经 **worker1 编排** 写入 **`last_rc`** 或 RPC | 与 client1 `RetryOnError` **独立** | `1004`/`5`/`6` |
| RPC 成功后 client1 UB 组装 | **client1** | `ClientWorkerRemoteApi::Get`<br>`|_ FillUrmaBuffer` | — | `CopyBuffer` / 分配 | **`RETURN_IF_NOT_OK`**（晚于 stub OK） | 无 | `UB payload overflow` 等 `K_RUNTIME_ERROR` |
| 解析响应 SHM / payload | **client1** | `GetBuffersFromWorker`<br>`|_ GetObjectBuffers`<br>`|_ MmapShmUnit` / `SetNonShmObjectBuffer` | 数据已在 UB 时多逻辑拷贝 | **`mmap` store_fd**；`MemoryCopy` | `failedObjectKey`；全失败 **`last_rc`/`K_NOT_FOUND`** | 无 | `Get mmap entry failed` |

---

## 3. 写路径（`Put` / `MSet` → `Publish` / `MultiPublish`）

| 大处理内容 | 发生位置 | 调用链（树） | URMA | OS / syscall | 跨模块报错与传播 | 重试 | 典型 Status / 关键词 |
|------------|----------|--------------|------|--------------|------------------|------|----------------------|
| 前置与 SHM/UB 分支 | **client1** | `ObjectClientImpl::Put` / `MSet`<br>`|_ ShmCreateable / IsUrmaEnabled` | — | SHM 路径 fd | **`RETURN`** | 无 | `K_INVALID` |
| 单对象 UB 发送（可选） | **client1** | `SendBufferViaUb`<br>`|_ UrmaWritePayload`（可向 worker1 方向 UB） | `UrmaWritePayload` 失败 | `memcpy` 入池 | **`RETURN` `K_INVALID`**，可改走非 UB | 无 | `Failed to send buffer via UB` |
| Publish 控制面 + payload | **client1→worker1** | `ClientWorkerRemoteApi::Publish`<br>`|_ RetryOnError`<br>`|_ stub_->Publish`<br>`worker1`<br>`|_ Worker Publish 链` | UB 已发则 RPC 偏元数据 | payload 随 RPC | **传输重试**；**`K_OC_ALREADY_SEALED` 重试当成功** | **是** `RETRY_ERROR_CODE` | `Send Publish request error` |
| MultiPublish | **client1→worker1** | `ClientWorkerRemoteApi::MultiPublish`<br>`|_ RetryOnError`（含 **`K_SCALING`/`K_OUT_OF_MEMORY`**）<br>`|_ stub_->MultiPublish` | 同上单对象放大 | 大块内存 | 同上 | **是**（码集 ⊃ Publish） | `32`/`6`/`1002` |
| worker1 目录与下推 | **worker1**<br>**worker1→worker2** | `worker_oc_service_multi_publish_impl` 等<br>`|_ Directory / 目录提交`<br>`worker2` | — | — | RPC / `last_rc` | Worker 策略 | `scaling`；日志或仍有 master 文案 |
| worker1→worker3 数据面 UB | **worker1→worker3**<br>**worker3** | `UrmaWritePayload` 等（写路径对称读）<br>`worker3`<br>`|_ 接收 / 落盘 / 缓存` | **主战场** | 磁盘等 | 经 **worker1** 汇总回 **client1** | 视实现 | 与读类似 URMA 日志 |

---

## 4. 跨模块要点速记（排障）

1. **Init UB 握手**：`LOG_IF_ERROR` → **Init 可不失败**，仅 ERROR 日志 + 退 TCP。  
2. **读 `PrepareUrmaBuffer`**：WARNING 降级，**无** URMA 码上抛。  
3. **读 `FillUrmaBuffer`**：stub 成功后仍可能 **`RETURN` 失败**。  
4. **`RetryOnError`**：不在集合内的码 **不重试**。  
5. **Get + `last_rc`**：`IsRpcTimeoutOrTryAgain` 或 **OOM 且全 key 失败** → 触发客户端重试。

---

## 5. 配套与修订

| 文档 | 用途 |
|------|------|
| [workbook/kv-client-Sheet2-URMA-C接口映射.md](../workbook/kv-client/kv-client-Sheet2-URMA-C接口映射.md) | URMA C API 映射 |
| [kv-client-SDK与Worker-读路径-快速定位定界.md](../kv-client-SDK与Worker-读路径-快速定位定界.md) | 分诊与 W_entry/W_remote |
| [kv-client-调用链行模板-示例-MGet最长路径.md](./kv-client-调用链行模板-示例-MGet最长路径.md) | 与 1～5 段 backbone 对齐 |

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 初版 |
| 2026-04-09 | 增加 §0 约定；**发生位置**列；调用链 `|_` 树；读/写拆 worker1→worker2/worker3 |
