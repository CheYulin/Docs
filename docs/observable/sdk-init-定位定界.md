# SDK Init 接口：定位定界手册

本文档面向 **Object Client SDK 的 `Init`（及嵌入式 `InitEmbedded`）**，说明调用链、可能错误码、日志关键词，以及如何区分 **操作系统/网络环境** 与 **数据系统（Worker/配置/IAM）** 问题。

**代码仓库**：`yuanrong-datasystem`（下文路径均相对该仓库根目录）。

---

## 1. 接口与入口

| 场景 | 典型入口 | 说明 |
|------|----------|------|
| 远程 Worker | `ObjectClientImpl::Init` | 需配置 `host:port` 或 `serviceDiscovery` |
| 嵌入式 | `ObjectClientImpl::InitEmbedded` | 同进程加载 Worker 插件，注册走本地 `WorkerRegisterClient` |

公共连接逻辑在 `InitClientWorkerConnect`：创建 `workerApi`、执行其 `Init`、启动 `ListenWorker`、初始化设备侧 `ClientDeviceObjectManager`（无设备运行时时仅打 INFO，不失败）。

---

## 2. Init 主路径（远程）

```
ObjectClientImpl::Init
  ├─ Logging / FlagsMonitor / serviceDiscovery（可选）
  ├─ 校验 HostPort
  ├─ RpcAuthKeyManager::CreateClientCredentials（可选 ZMQ CURVE）
  └─ InitClientWorkerConnect
        ├─ ClientWorkerRemoteApi::Init
        │     ├─ ClientWorkerRemoteCommonApi::Init
        │     │     ├─ TimerQueue::Initialize
        │     │     └─ Connect
        │     │           ├─ CreateConnectionForTransferShmFd（可选）
        │     │           │     ├─ RPC: GetSocketPath
        │     │           │     └─ 本地 UDS/SCMTCP 握手（传 server_fd）
        │     │           └─ RegisterClient（RPC）
        │     └─ 创建 RpcChannel + WorkerOCService_Stub（业务通道）
        ├─ MmapManager 构造
        ├─ PrepairForDecreaseShmRef
        ├─ InitListenWorker → ListenWorker::StartListenWorker
        │     └─ RPC_HEARTBEAT：connectTimeoutMs 内必须收到首帧心跳
        └─ ClientDeviceObjectManager::Init
```

**嵌入式**省略 `GetSocketPath` 与跨机 SHM 握手，`Connect` 内直接 `WorkerRegisterClient`。

---

## 3. Init 阶段涉及的 RPC / 本地动作

| 阶段 | 类型 | 名称 / 动作 |
|------|------|-------------|
| 可选 | RPC | `GetSocketPath`（`FLAGS_ipc_through_shared_memory` 且能解析出 UDS 路径或 SCMTCP 端口） |
| 可选 | 本地 socket | UDS/SCMTCP 连接 + 接收 `server_fd` |
| 核心 | RPC | `RegisterClient`（`WorkerServiceImpl::RegisterClient`） |
| 核心 | RPC 循环 | `Heartbeat`（`ListenWorker` 在 `RPC_HEARTBEAT` 模式下，`connectTimeoutMs` 内要完成首次成功） |

**注意**：`PostRegisterClient` 中的 `FastTransportHandshake`（如 URMA）失败仅 **`LOG_IF_ERROR`**，**不导致 Init 失败**。

---

## 4. 错误码与日志树（客户端可见）

客户端失败时常见形式：`LOG(ERROR) << "<前缀>. Detail: " << status.ToString()`（宏 `RETURN_IF_NOT_OK_PRINT_ERROR_MSG`）。

### 4.1 配置与本地前置（多在 Register 之前）

| 错误码 | 典型消息 / 现象 | 可能原因 | 定界 |
|--------|-----------------|----------|------|
| `K_INVALID` (2) | `ConnectOptions was not configured with a host and port or serviceDiscovery` | 未配地址且无服务发现 | 数据系统 / 集成配置 |
| `K_INVALID` (2) | `Invalid IP address/port` | HostPort 非法 | 配置 |
| `K_INVALID` (2) | `connectTimeoutMs` / `requestTimeoutMs` 校验失败 | 超时参数非法 | 配置 |
| `K_RUNTIME_ERROR` (5) | `TimerQueue init failed!` | 客户端定时器初始化失败 | 进程环境 / 客户端 |
| `K_RPC_UNAVAILABLE` (1002) | `Can not create connection to worker for shm fd transfer.` | 必须 SHM 通道但未建立（如跨节点、Worker 未开 SHM） | 拓扑+配置偏数据系统；跨机属环境 |

**日志关键词**：`Start to init worker client at address`、`Invalid IP`、`TimerQueue init`。

### 4.2 GetSocketPath / 网络 / SHM 握手

| 错误码 | 客户端日志前缀 | 可能原因 | 定界 |
|--------|----------------|----------|------|
| 1001 / 1002 / 1000 等 | `Get socket path failed. Detail:` | Worker 不可达、超时、拒绝连接 | 优先网络、防火墙、Worker 是否监听 |
| — | `Client can not connect to server for shm fd transfer within allowed time`（WARNING） | UDS/SCMTCP 连不上或握手超时 | UDS 权限、路径、同机；Worker SHM 监听 |
| — | `Failed connect to local worker via ... falling back to TCP`（INFO） | 非本机或通道不可用 | 环境 / 配置预期 |

### 4.3 RegisterClient（Worker 返回映射到客户端 Status）

Worker 侧失败常带 `LOG(ERROR) "<步骤>. Detail: ..."`，客户端对应 `Register client failed. Detail: ...`。

| 错误码 | 典型含义 | 可能原因 | 定界 |
|--------|----------|----------|------|
| `K_NOT_AUTHORIZED` (9) | 签名校验 / 租户失败 | Token、AK/SK、租户 ID、时钟漂移 | IAM 配置；时钟属 OS |
| `K_INVALID` (2) | AK/SK 管理器未初始化等 | Worker 配置异常 | 数据系统 |
| `K_RUNTIME_ERROR` (5) | `AK/SK or token not provide` | 认证开启但未带凭证 | 客户端与 Worker 认证策略 |
| `K_NOT_READY` (8) | `Worker is exiting and unhealthy now!` | Worker 正在退出 | 数据系统生命周期 |
| `K_SERVER_FD_CLOSED` (29) | `Fd %d has been released` | 传递的 server_fd 已被 Worker 回收 | 竞态 / Worker 状态；客户端会转为 `K_TRY_AGAIN` 重试 |
| `K_TRY_AGAIN` (19) | 含由上项改写 | 可重试场景 | 结合 Worker 日志看根因 |
| `K_RUNTIME_ERROR` (5) | `Client number upper to the limit` | 连接数达 `max_client_num` | 数据系统容量或连接泄漏 |
| `K_RUNTIME_ERROR` (5) | `Failed to insert client %s to table` | 客户端表冲突等 | 数据系统状态 |
| `K_RUNTIME_ERROR` (5) | `worker add client failed`（Detail 内见 epoll/RegisterLostHandler） | UDS 心跳注册 fd 失败等 | fd/epoll 资源偏 OS；逻辑错误偏 Worker |
| `K_RUNTIME_ERROR` (5) | `worker process server reboot failed` | 重连恢复 `GIncreaseRef` 等失败 | 数据系统元数据/业务状态 |
| `K_RUNTIME_ERROR` (5) | `worker process get ShmQ unit failed` | SHM 队列未就绪、索引越界、分配失败 | Worker OC 与内存配置；mmap 失败兼看 OS |
| `K_RUNTIME_ERROR` (5) | `worker process get exclusive connection socket path failed` | 独占连接能力与版本不匹配 | 数据系统版本/特性 |

**日志关键词（客户端）**：`Start to send rpc to register client to worker`、`Register client failed`、`Register client to worker through the ... successfully`。

**日志关键词（Worker）**：`Register client:`、`Authenticate failed`、`worker add client failed`、`worker process get ShmQ unit failed`、`Register client failed because worker is exiting`。

### 4.4 Register 成功后：首心跳超时

| 错误码 | 消息 | 可能原因 | 定界 |
|--------|------|----------|------|
| `K_CLIENT_WORKER_DISCONNECT` (23) | `Cannot receive heartbeat from worker.` | `connectTimeoutMs` 内未收到首次 Heartbeat 响应 | Worker 过载或阻塞；网络 RTT/丢包；超时过短 |

**日志关键词**：`Start listen worker, heartbeat type: RPC_HEARTBEAT`。

### 4.5 ZMQ CURVE（可选）

| 错误码 | 典型消息 | 定界 |
|--------|----------|------|
| `K_RUNTIME_ERROR` (5) | `Client public key should not be null` / `Server key should not be null` | 客户端或服务端密钥未配置 |

**代码**：`RpcAuthKeyManager::CreateClientCredentials`、`CreateCredentialsHelper`。

---

## 5. 定界决策（简表）

1. **无任何 Worker 侧 Register 日志，只有 RPC 超时 / UNAVAILABLE / DEADLINE**  
   → 优先 **网络、防火墙、Worker 进程、监听地址**（环境 + 部署）。

2. **Worker 有 `Authenticate failed`**  
   → **IAM / Token / AK-SK / 租户 / 时间同步**（配置为主，时钟为 OS）。

3. **`Get socket path failed` 成功但 SHM 握手 WARNING 不断**  
   → **同机性、UDS 目录权限、`ipc_through_shared_memory` 与路径**（环境 + Worker 配置）。

4. **`Register client failed` 且 Detail 含 `ShmQ` / `queue`**  
   → **Worker OC 服务与共享内存初始化**（数据系统为主）。

5. **`Cannot receive heartbeat from worker`**  
   → **调大 `connectTimeoutMs` 做对比**；查 Worker 负载与 Heartbeat 处理；仍失败则查 **网络**。

---

## 6. 推荐采集信息（工单模板）

- SDK 版本 / `DATASYSTEM_VERSION` 与 Worker 版本是否一致（Worker 对版本不一致会打 WARNING，Register 仍可能成功）。
- `Init` 入参：`host`、`port`、`connectTimeoutMs`、`requestTimeoutMs`、`tenantId`、是否开启跨节点 / 独占连接 / 服务发现。
- 客户端完整 **`Register client failed. Detail: ...`** 或返回的 **`Status::ToString()`**。
- 同时间点 Worker 日志片段：`Register client` 起止、`Authenticate failed`、`worker add client`、`get ShmQ`。
- 环境：是否跨机、是否开启 SHM、`unix_domain_socket_dir` 与目录权限、大致连接数。

---

## 7. 代码索引（便于对照）

| 内容 | 路径 |
|------|------|
| Init | `src/datasystem/client/object_cache/object_client_impl.cpp`（`Init` / `InitClientWorkerConnect`） |
| 远程 Connect / Register | `src/datasystem/client/client_worker_common_api.cpp` |
| Worker Register | `src/datasystem/worker/worker_service_impl.cpp`（`RegisterClient`） |
| 认证 | `src/datasystem/worker/authenticate.cpp` |
| 客户端数 / lockId | `src/datasystem/worker/client_manager/client_manager.cpp`（`GetLockId`、`AddClient`） |
| SHM 队列单元 | `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp`（`GetShmQueueUnit`） |
| 首心跳 | `src/datasystem/client/listen_worker.cpp`（`StartListenWorker`） |
| 错误码枚举 | `include/datasystem/utils/status.h` |
| 错误日志宏 | `src/datasystem/common/util/status_helper.h`（`RETURN_IF_NOT_OK_PRINT_ERROR_MSG`） |
| FD 传递 / mmap 表 | `src/datasystem/client/mmap_manager.cpp`、`src/datasystem/client/mmap/shm_mmap_table_entry.cpp`、`src/datasystem/common/util/fd_pass.cpp` |
| Socket errno → Status | `src/datasystem/common/rpc/unix_sock_fd.cpp`（`ErrnoToStatus`） |
| ZMQ 层 UNAVAILABLE | `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp`、`zmq_stub_conn.cpp` |
| URMA 管理器 | `src/datasystem/common/rdma/urma_manager.cpp` |
| Worker `GetClientFd` | `src/datasystem/worker/worker_service_impl.cpp` |
| Arena 物理分配 | `src/datasystem/common/shared_memory/arena.cpp`、`arena_group_key.h` |

---

## 8. FD 交换与 `mmap`：错误码、消息与调用栈（代码证据）

**说明**：Init 完成后，业务路径在需要把 **Worker 侧 shm fd** 映射到客户端地址空间时，走 **`MmapManager::LookupUnitsAndMmapFds`**；其中远程场景会 **RPC `GetClientFd` + UDS/SCMTCP 收 fd + `mmap`**。下列栈以 **`ObjectClientImpl::MmapShmUnit`** 为典型入口（Create/Get 等路径也会调用 `LookupUnitsAndMmapFd`）。

### 8.1 调用栈（自顶向下）

1. **`ObjectClientImpl::MmapShmUnit`**（或 `Create` / `MGet` 等内联路径）  
   - 文件：`src/datasystem/client/object_cache/object_client_impl.cpp`  
   - 行为：组 `ShmUnitInfo`，调用 `mmapManager_->LookupUnitsAndMmapFd`；失败时可能 **`K_RUNTIME_ERROR` + `"Get mmap entry failed"`**。

```1813:1826:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::MmapShmUnit(int64_t fd, uint64_t mmapSize, ptrdiff_t offset,
                                     std::shared_ptr<client::IMmapTableEntry> &mmapEntry, uint8_t *&pointer)
{
    auto shmBuf = std::make_shared<ShmUnitInfo>();
    shmBuf->fd = fd;
    shmBuf->mmapSize = mmapSize;
    shmBuf->offset = offset;
    PerfPoint mmapPoint(PerfKey::CLIENT_LOOK_UP_MMAP_FD);
    RETURN_IF_NOT_OK(mmapManager_->LookupUnitsAndMmapFd("", shmBuf));
    mmapEntry = mmapManager_->GetMmapEntryByFd(shmBuf->fd);
    CHECK_FAIL_RETURN_STATUS(mmapEntry != nullptr, StatusCode::K_RUNTIME_ERROR, "Get mmap entry failed");
    mmapPoint.Record();
    pointer = static_cast<uint8_t *>(shmBuf->pointer) + shmBuf->offset;
    return Status::OK();
}
```

2. **`MmapManager::LookupUnitsAndMmapFd` → `LookupUnitsAndMmapFds`**  
   - 文件：`src/datasystem/client/mmap_manager.cpp`  
   - 对已登记 fd 只做表查询；对未 mmap 的 worker fd：**非嵌入式** 调 **`clientWorker_->GetClientFd`**，再 **`mmapTable_->MmapAndStoreFd`**。

```82:90:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/mmap_manager.cpp
    if (!toRecvFds.empty()) {
        // Notify worker to send fds and receive the client fd.
        if (!enableEmbeddedClient_) {
            RETURN_IF_NOT_OK(clientWorker_->GetClientFd(toRecvFds, clientFds, tenantId));
            // Mmap the new client fd.
            for (size_t i = 0; i < clientFds.size(); i++) {
                RETURN_IF_NOT_OK(mmapTable_->MmapAndStoreFd(clientFds[i], toRecvFds[i], mmapSizes[i], tenantId));
            }
```

3. **`ClientWorkerRemoteCommonApi::GetClientFd`**  
   - 文件：`src/datasystem/client/client_worker_common_api.cpp`  
   - RPC **`GetClientFd`**（不自动重试）+ 后台线程经 **`SockRecvFd`** 收 fd；失败时 **`CHECK_FAIL_RETURN_STATUS_PRINT_ERROR`**。

| 错误码 | 典型 `Status` 消息 / 日志 | 说明 |
|--------|---------------------------|------|
| `K_RUNTIME_ERROR` (5) | `Current client can not support uds, so query client fd failed.` | 未启用 SHM 或 `socketFd_ == INVALID_SOCKET_FD` |
| `K_RUNTIME_ERROR` (5) | `Receive fd[...] from <socket> failed, detail: <status.ToString()>` | RPC 失败 **或** 超时内未收到 fd（`clientFds` 仍为空） |
| 随 RPC 层 | `Detail` 内可为 `K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED` / `K_NOT_AUTHORIZED` 等 | 同 `GetClientFd` 的 Worker 返回或 ZMQ/网络 |

```670:714:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/client_worker_common_api.cpp
Status ClientWorkerRemoteCommonApi::GetClientFd(const std::vector<int> &workerFds, std::vector<int> &clientFds,
                                                const std::string &tenantId)
{
    if (!IsShmEnable() || socketFd_ == INVALID_SOCKET_FD) {
        return { K_RUNTIME_ERROR, "Current client can not support uds, so query client fd failed." };
    }
    ...
    Status status = commonWorkerSession_->GetClientFd(opts, req, rsp);
    if (status.IsOk()) {
        RecvFdAfterNotify(workerFds, requestId, time, clientFds);
    }
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(!clientFds.empty(), K_RUNTIME_ERROR,
                                         FormatString("Receive fd[%s] from %d failed, detail: %s",
                                                      VectorToString(workerFds), socketFd_, status.ToString()));
```

4. **`ShmMmapTableEntry::Init`（实际 `mmap`）**  
   - 文件：`src/datasystem/client/mmap/shm_mmap_table_entry.cpp`  

| 错误码 | 消息 | 说明 |
|--------|------|------|
| `K_INVALID` (2) | `The mmap size [<size>] is invalid for fd [<fd>]` | `size_ <= 0` |
| `K_RUNTIME_ERROR` (5) | `Mmap [fd = <fd>] failed. Error no: [<errno str>]` | `mmap()` 返回 `MAP_FAILED`（内核/资源/权限） |

```33:52:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/mmap/shm_mmap_table_entry.cpp
Status ShmMmapTableEntry::Init(bool enableHugeTlb, const std::string &tenantId)
{
    ...
    if (size_ <= 0) {
        err << "The mmap size [" << size_ << "] is invalid for fd [" << fd_ << "]";
        ...
        RETURN_STATUS(StatusCode::K_INVALID, err.str());
    }
    ...
    pointer_ = reinterpret_cast<uint8_t *>(mmap(nullptr, size_, PROT_READ | PROT_WRITE, mFlag, fd_, 0));
    if (pointer_ == MAP_FAILED) {
        RETURN_STATUS_LOG_ERROR(StatusCode::K_RUNTIME_ERROR,
                                FormatString("Mmap [fd = %d] failed. Error no: [%s]", fd_, StrErr(errno)));
    }
```

5. **`MmapManager` 查表**  
   - 可能 **`K_RUNTIME_ERROR`**：`The pointer which is looked up from mmap table is nullptr!`（`mmap_manager.cpp`）。

### 8.2 Worker 侧 `GetClientFd`（与客户端 RPC 成对）

| 错误码 | Worker 日志前缀（`RETURN_IF_NOT_OK_PRINT_ERROR_MSG`） | 含义 |
|--------|------------------------------------------------------|------|
| 随认证 | `Authenticate failed. Detail:` | 同 Register |
| `K_RUNTIME_ERROR` 等 | `worker get client socketfd failed` | `ClientManager::GetClientSocketFd` 失败 |
| `K_RUNTIME_ERROR` 等 | `Authenticate workerFd failed.` | `Allocator::CheckWorkerFdTenant` |
| `K_UNKNOWN_ERROR` 等 | `worker socketfd send failed` | `SockSendFd` 失败 |

```152:177:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/worker_service_impl.cpp
Status WorkerServiceImpl::GetClientFd(const GetClientFdReqPb &req, GetClientFdRspPb &rsp)
{
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(AuthenticateRequest(akSkManager_, req, authTenantId, tenantId),
                                     "Authenticate failed");
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(ClientManager::Instance().GetClientSocketFd(clientId, socketFd),
                                     "worker get client socketfd failed");
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(memory::Allocator::Instance()->CheckWorkerFdTenant(tenantId, workerFds),
                                     "Authenticate workerFd failed.");
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(SockSendFd(socketFd, shmWorkerPort_ > 0, workerFds, req.request_id()),
                                     "worker socketfd send failed");
```

### 8.3 本地 FD 传递（`SockRecvFd` / `SockSendFd`）常见消息

| 错误码 | 消息 | 典型场景 |
|--------|------|----------|
| `K_UNKNOWN_ERROR` (10) | `Unexpected EOF read.` | 对端关闭，`recvmsg` 返回 0 |
| `K_UNKNOWN_ERROR` (10) | `Pass fd meets unexpected error: <errno>` | 非 EAGAIN/EINTR 的 `recvmsg/sendmsg` 失败 |
| `K_UNKNOWN_ERROR` (10) | `We receive the invalid fd` | SCM_RIGHTS 中带非法 fd |
| `K_RUNTIME_ERROR` (5) | `memset_s failed...` / `Copy cmsg failed...` | 本地组装消息失败 |

（实现：`src/datasystem/common/util/fd_pass.cpp`。）

### 8.4 Init 阶段的 FD 交换（补充）

Register 之前的 **SHM 握手**在 **`ClientWorkerRemoteCommonApi::CreateHandShakeFunc`**：`fd.Connect`、`Recv32`、`SockRecvFd`（SCMTCP 同机校验）等；失败信息多为 **连接/接收** 相关 Status（见 4.2 节 WARNING 日志），成功日志示例：`Connects to local server ... Client fd ... Server fd ...`（`client_worker_common_api.cpp`）。

---

## 9. URMA Manager 与物理内存分配：错误码与消息

### 9.1 客户端 `UrmaManager`（`clientMode_ == true` 时的缓冲池）

**文件**：`src/datasystem/common/rdma/urma_manager.cpp`。

| 阶段 | 错误码 | 典型消息 | 说明 |
|------|--------|----------|------|
| `Init` 并发 | `K_URMA_ERROR` (1004) | `UrmaManager initialization failed` | 他线程初始化失败，本线程 `waitInit_` 结束仍非 `INITIALIZED` |
| `InitMemoryBufferPool` | `K_RUNTIME_ERROR` (5) | `Env <name> value ... parse to number failed: ...` | 环境变量解析失败（`ParseEnvUint64`） |
| `InitMemoryBufferPool` | `K_INVALID` (2) | `ubTransportMemSize <n> is invalid, must be between ...` | 传输内存大小非法 |
| `hostAllocFunc`（`mmap` 匿名内存池） | `K_OUT_OF_MEMORY` (6) | `Failed to allocate memory buffer pool for client` | `mmap(MAP_ANONYMOUS)` 得到 `MAP_FAILED` |
| `CreateArenaGroup` | 透传 Allocator | `Failed to get arena group for client. Detail: ...` | `RETURN_IF_NOT_OK_PRINT_ERROR_MSG` |
| 注册失败分支 | 可能降级为 WARNING | `Failed to register memory buffer pool for client, error: ...` | `InitWithFlexibleRegister` 失败；`K_DUPLICATED` 会被视为 OK |

```232:272:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
    if (ubTransportMemSize_.load() > MAX_TRANSPORT_MEM_SIZE || ubTransportMemSize_.load() <= 0) {
        RETURN_STATUS_LOG_ERROR(StatusCode::K_INVALID,
                                FormatString("ubTransportMemSize %lu is invalid, must be between %lu and %lu",
                                             ubTransportMemSize_.load(), 0, MAX_TRANSPORT_MEM_SIZE));
    }
    ...
        if (memoryBuffer_ == MAP_FAILED) {
            RETURN_STATUS(K_OUT_OF_MEMORY, "Failed to allocate memory buffer pool for client");
        }
    ...
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(rc, "Failed to get arena group for client");
    ...
        LOG(WARNING) << "Failed to register memory buffer pool for client, error: " << rc.ToString();
```

**`GetMemoryBufferHandle`**：`K_INVALID` + `UB Get buffer size is 0`；否则经 **`ShmUnit::AllocateMemory`** 走全局 **`Allocator`**，可能返回 **`K_OUT_OF_MEMORY`** 等（与 Worker 共用分配器逻辑）。

### 9.2 Worker 侧物理内存（Arena / UB_TRANSPORT）

Worker 与 Client 共用 **`memory::Allocator` / `ArenaGroup::AllocateMemoryImpl`**（`src/datasystem/common/shared_memory/arena.cpp`）。当 **jemalloc 分配返回 `K_OUT_OF_MEMORY`** 时，会包装为：

| 错误码 | 消息模式 | 备注 |
|--------|----------|------|
| `K_OUT_OF_MEMORY` (6) | `FormatString("%s no space in arena: %d", errHint, arenaId)` | `errHint` 来自 `CACHE_TYPE_STR`；**当前 `arena_group_key.h` 未包含 `UB_TRANSPORT`**，该类型可能显示为 **`UnknowType`** |

```150:159:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/shared_memory/arena.cpp
    auto status = Jemalloc::Allocate(arenaId, size, pointer);
    if (status.GetCode() == StatusCode::K_OUT_OF_MEMORY) {
        auto it = CACHE_TYPE_STR.find(cacheType_);
        std::string errHint = "UnknowType";
        if (it != CACHE_TYPE_STR.end()) {
            errHint = it->second;
        }
        std::string errorMsg = FormatString("%s no space in arena: %d", errHint, arenaId);
        status = Status(StatusCode::K_OUT_OF_MEMORY, errorMsg);
    }
```

**定界**：`K_OUT_OF_MEMORY` + `no space in arena` → **Worker/客户端进程地址空间或预分配物理池耗尽**（资源类）；若伴随系统 OOM → **OS**。

---

## 10. `K_RPC_UNAVAILABLE`（1002）：Worker 问题还是 Socket？能否用心跳定界？

### 10.1 错误码在框架中的典型来源（消息形态）

`K_RPC_UNAVAILABLE` 是 **传输/框架层** 对「当前无法完成 RPC」的统称，**不等价于**「一定是 Worker 业务 bug」。常见代码证据：

| 来源 | 文件 / 符号 | 典型消息 |
|------|-------------|----------|
| Socket `errno` | `UnixSockFd::ErrnoToStatus` | `Connect reset. fd <fd>. err <str>`（`ECONNRESET` / `EPIPE` → **1002**） |
| Socket 其他错误 | 同上 | `Socket receive error. err <str>` → 多为 **`K_RUNTIME_ERROR`**（非 1002） |
| ZMQ | `zmq_socket_ref.cpp` | `ZMQ recv msg unsuccessful` / connect 失败等 → **1002** |
| Stub 连接 | `zmq_stub_conn.cpp` | `The service is currently unavailable! ...`、`Network unreachable`、`Timeout waiting for SockConnEntry wait`、`Remote service is not available within allowable <n> ms` 等 → **1002** |

```55:63:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rpc/unix_sock_fd.cpp
Status UnixSockFd::ErrnoToStatus(int err, int fd)
{
    if (err == EAGAIN || err == EWOULDBLOCK || err == EINTR || err == EINPROGRESS) {
        RETURN_STATUS(K_TRY_AGAIN, FormatString("Socket receive error. err %s", StrErr(err)));
    }
    if (err == ECONNRESET || err == EPIPE) {
        RETURN_STATUS(StatusCode::K_RPC_UNAVAILABLE, FormatString("Connect reset. fd %d. err %s", fd, StrErr(err)));
    }
    RETURN_STATUS(K_RUNTIME_ERROR, FormatString("Socket receive error. err %s", StrErr(err)));
}
```

### 10.2 定界思路（Socket / 网络 vs Worker 进程与逻辑）

| 现象 | 更倾向 | 依据 |
|------|--------|------|
| `Detail` 含 **`Connect reset` / `EPIPE` / `ECONNRESET`** | **链路或对端关闭** | 对端崩溃、重启、防火墙 RST、代理断开 |
| `Network unreachable`、连接超时、`allowable <n> ms` | **网络或 Worker 未监听** | 路由/端口/进程未起 |
| Worker 日志 **同一时间无请求入口**，客户端仅 1002 | **包未到达或前置连接失败** | 对齐时间线、抓包、查监听 |
| Worker 日志有 **Authenticate / 业务返回错误** | **数据系统逻辑** | 错误码通常 **非** 单纯 1002，或 1002 来自 ZMQ「服务不可用」包装 |

### 10.3 能否通过「心跳」定界？

- **可以，但要看心跳与失败 RPC 是否同通道、同生命周期。**  
  - **`Heartbeat`** 与 **`GetSocketPath` / `RegisterClient`** 一样走 **`WorkerService_Stub`（ZMQ）**。若 **Heartbeat 成功** 而 **偶发业务 RPC 1002**，更倾向 **瞬时网络、连接池、或独占通道差异**，需对比 **是否同一 `RpcChannel`/endpoint**。  
  - 若 **Heartbeat 也失败** 且 `Status` 为 **`K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED`**，则 **整体链路或 Worker 不可用** 概率高。  
- **首心跳**（Init 阶段）：`ListenWorker::StartListenWorker` 在 **`connectTimeoutMs_`** 内必须收到 **第一次成功的 `SendHeartbeat`**，否则 **`K_CLIENT_WORKER_DISCONNECT` (23)** + **`Cannot receive heartbeat from worker.`** — 这表示 **「注册后 RPC 心跳路径不通」**，可能是 **网络、Worker 阻塞、超时过短**，不能单独区分「socket」与「Worker 逻辑」需结合 Worker 日志。  
- **持续心跳失败**：`ListenWorker::CheckHeartbeat` 中 `SendHeartbeat` 返回 error 会累计；超时后 **`LOG(WARNING) Lost heartbeat, set worker available to false ... Detail:<status.ToString()>`**（`listen_worker.cpp`），此时 `Detail` 中的 **1002/1001** 同样反映 **RPC 传输层**，与上表一致。

**结论**：**心跳是有效的「同通道可达性」探针**，但 **1002 本身不区分**「Socket 断了」与「Worker 进程拒绝服务」；定界需 **消息字符串 + Worker 侧同一时刻日志 + 端口/进程存活**。

---

## 11. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-08 | 初版：基于 `ObjectClientImpl::Init` / `WorkerServiceImpl::RegisterClient` 代码路径整理 |
| 2026-04-08 | 增补：FD 交换与 mmap 调用栈与错误表；UrmaManager / Arena 物理内存；`K_RPC_UNAVAILABLE` 与心跳定界 |
