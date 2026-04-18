# Sheet1：KV Client 调用链 — 错误码与日志（Init / MCreate / MSet / MGet）

> **与 Excel 的关系**  
> - **第二列结构（脚本已生成）**：自上而下依次为 **`【故障预期】`** → **`【调用链逻辑】`**（说明顺序与条件分支记号）→ **`【调用链树 · 正向】`**（`|_` 在格内渲染成 **`└─` 缩进树**）→ 分隔线 → **`【本行 case】` + 发生位置**。  
>   - **`【故障预期】无错误`**：表示本行描述 **健康主路径**（假定各段不发生本表后续「case」行所列故障），用于把 **Init / Get / MSet** 的 **W1→W2→W3** 逻辑一次看清。  
>   - **`【故障预期】可失败（本行专述异常或边界条件）`**：缺省语义——本行聚焦 **异常/边界**，与主路径行对照阅读即可定界。  
> - **正向（调用树）**：与下面 **§1 思维导图**、**§2.1 / §2.2 按层表**、**步骤 2/3 PlantUML** 同一语义；主路径行中的 **`→W2` / `→W3@address`** 与 §1.5 文字树一致。  
> - **逆向（定界流程图）**：排障时 **不要**指望在 Sheet1 把树倒着读；应 **先 Status/日志 → Trace 检索 → 对照 `Sheet5_定界-case`**（或与 Sheet1 某行匹配），与总图 PlantUML「先错误码+手册再 Trace」一致。详见同目录 [`README.md`](README.md) 中 **「正向分析 vs 逆向分析」**。  
> - **Sheet1 第 5～8 列（URMA / OS）**：由生成脚本从 [`../../../../scripts/documentation/observable/kv-client-excel/sheet1_system_presets.py`](../../../../scripts/documentation/observable/kv-client-excel/sheet1_system_presets.py) 逐行写入 **具体接口**（`ds_urma_*` / UMDK 与 `syscall` / `libzmq`）及 **可 grep 的日志原文、Status、步骤**。**URMA「错误」列与 OS「错误」列互斥**（`merge_exclusive`）：一行在 syscall 传输层只按 **一类** 根因排查；`NEITHER` 行为/参数类行两列可为 `—`。  
> - **维护规则**：`CHAIN_ROWS` 与 `SHEET1_URMA_OS` **必须同长度、同顺序**（脚本内有 `assert`）；增删调用链行时两处一起改，再运行 `scripts/documentation/observable/kv-client-excel/generate_kv_client_observability_xlsx.py`。  
> - 本页 **§2.1** 另含 Markdown 评审用的 **Init 分层表**（与 Excel 第 5～8 列互补对照）。

**仓库**：`yuanrong-datasystem`（附录中的路径均相对该仓库根）  
**时序图**：`vibe-coding-files/docs/flows/sequences/kv-client/`

**术语统一（Directory / 日志原文）**

- **Directory（目录）**：文档中对 **对象目录服务** 的统一称呼（不再用 **Master** 指代该角色）。查询的是 **对象在目录中的元数据/路由**（副本地址等）。
- **哈希分片**：各 **Worker** 按 **一致性哈希环（hash ring）** 各自负责 **一部分 object key** 的目录；**W1→W2** 表示向 **对端 Worker 上、环上对应分片** 发目录查询（实现上 API 名可能仍为 `QueryMeta`、`workerMasterApi` 等 **源码命名**）。
- **日志 grep**：源码/现网仍可能出现 **`Query from master failed`** 等 **英文字符串原文**，定界时理解为 **Directory 侧失败** 即可。

**角色约定（与《kv-client-定位定界手册-基于Excel》一致）**

| 代号 | 含义 |
|------|------|
| **client** | SDK 进程（`KVClient` / `ObjectClientImpl` / `ClientWorkerRemoteApi` 等） |
| **worker1** | **入口 Object Cache Worker**（与 client 建 ZMQ 会话、处理 `WorkerOCService` RPC 的进程） |
| **worker2** | **Directory Worker（对象目录分片）**：与 W1 通常为 **不同实例**；W1 经 **`QueryMeta` 等 RPC** 向 **环上负责对应 key 的目录分片** 查询；**etcd** 多用于租约/路由，**不是**该 RPC 的对端本体 |
| **worker3** | **数据副本 Worker**（跨节点拉取、UB 数据面的对端；逻辑上「worker1→worker3」或仅在 worker3 本机 URMA） |

---

## 1. 调用链思维导图（ASCII，按源码步骤）

> **记号**：`[client]` SDK；`→` 跨进程 RPC（ZMQ 多帧）；**并行** 与主链并发。括号 **(n)** 为 Init 主链上的大致顺序，与 **§1.1 对照表**、**§2.1「层」** 一一对应。

### 1.1 Init（远程 `ClientWorkerRemoteApi`，非嵌入式）

```text
(1) KVClient::Init
    └─ (2) ObjectClientImpl::Init  [client]
        ├─ (3) clientStateManager_->ProcessInit(needRollbackState)   // 不需 rollback 时直接 return
        ├─ (4) [可选] serviceDiscovery_->SelectWorker → ipAddress_
        ├─ (5) Validator::ValidateHostPortString  → 失败 K_INVALID
        ├─ (6) RpcAuthKeyManager::CreateClientCredentials → cred_
        └─ (7) InitClientWorkerConnect(enableHeartbeat, false)
            ├─ (7a) std::make_shared<ClientWorkerRemoteApi>(…)
            └─ (7b) ClientWorkerRemoteApi::Init(reqTmo, connTmo, fastTransportMemSize)
                ├─ (7b-1) ClientWorkerRemoteCommonApi::Init
                │   ├─ 校验超时；TimerQueue::Initialize
                │   └─ Connect(RegisterClientReqPb, connectTimeoutMs)
                │       ├─ RpcChannel + WorkerService_Stub → commonWorkerSession_
                │       ├─ CreateConnectionForTransferShmFd
                │       │   ├─ RetryOnError: commonWorkerSession_->GetSocketPath  [client→worker1]
                │       │   ├─ PrepareShmTransferEndpoint（ipc:// 或 tcp:// shm 端口）
                │       │   └─ CreateHandShakeFunc：UnixSockFd::Connect、Recv32(serverFd)  [OS]
                │       ├─ CloseSocketFd；赋值 socketFd_；req.set_server_fd(serverFd)
                │       ├─ RegisterClient → RetryOnError → commonWorkerSession_->RegisterClient  [client→worker1]
                │       └─ PostRegisterClient → FastTransportHandshake
                │           ├─ InitializeFastTransportManager(hostPort_)
                │           └─ [USE_URMA] TryUrmaHandshake / ExecOnceParrallelExchange…（`ds_urma_*`，§2.1）
                └─ (7b-2) 再建 RpcChannel；[UDS] SetServiceUdsEnabled(WorkerOCService)；WorkerOCService_Stub → stub_
            ├─ (7c) new MmapManager(workerApi, …)
            ├─ (7d) ConstructTreadPool()
            ├─ (7e) PrepairForDecreaseShmRef(→ MmapManager::LookupUnitsAndMmapFd)
            ├─ (7f) InitListenWorker → ListenWorker::StartListenWorker
            ├─ (7g) ClientDeviceObjectManager::Init
            └─ (7h) StartShmRefReconcileThread / StartPerfThread / InitParallelFor()

【并行】ClientWorkerRemoteCommonApi 构造时已启动 RecvPageFd 线程：SockRecvFd / recvmsg(SCM_RIGHTS)（socketFd_ 在 Connect 完成后才有意义）
```

### 1.2 §1.1（Init）与 §2.1「层」对照表

| §2.1 层 | §1.1 步骤（Init） | 说明 |
|--------:|-------------------|------|
| 0 | (1)(2) | `KVClient::Init` → `ObjectClientImpl::Init` |
| 1 | (4)(5) | 选点 + HostPort 校验 → `K_INVALID` |
| 2 | (6) | AKSK → `cred_` |
| 3 | (7)(7a)(7b) 起、`Connect` 前 | `InitClientWorkerConnect`、构造 `ClientWorkerRemoteApi`、`Init` 进入 `Connect` |
| 4 | (7b-1) 内 `GetSocketPath` | SHM 预连，ZMQ RPC |
| 5 | (7b-1) 内 `CreateHandShakeFunc` | 传 fd 用 UDS/TCP |
| 6 | (7b-1) 内 `RegisterClient` | ZMQ RPC |
| 7 | (7b-1) `PostRegisterClient` | 解析 Register 应答，无 I/O |
| 8 | (7b-1) `FastTransportHandshake` | UB 控制面，失败多仅日志 |
| 9～14 | (7b-1) UB 链 | `UrmaInit` / 设备 / JFC/JFR / 池 / `ExchangeJfr` |
| 15 | 【并行】`RecvPageFd` | `recvmsg(SCM_RIGHTS)` |
| 16 | (7c)～(7h) | `MmapManager`、ListenWorker、心跳线程等 |

### 1.3 MultiCreate（`ObjectClientImpl::MultiCreate`）

```text
(1) IsClientReady()
(2) ConstructMultiCreateParam  — key/size 列表、multiCreateParamList、dataSizeSum
(3) GetAvailableWorkerApi(workerApi, raii)   // 可与 Init 时 LOCAL 不同
(4) 若 canUseShm || IsUrmaEnabled() || !skipCheckExistence：
    └─ workerApi->MultiCreate(…)  → ClientWorkerRemoteApi::MultiCreate
        ├─ MultiCreateReqPb + SetTokenAndTenantId + GenerateSignature
        ├─ RetryOnError → stub_->MultiCreate(opts, req, rsp)  [client→worker1，WorkerOCService]
        └─ PostMultiCreate（client_worker_base_api.cpp：回填 shmBuf / urmaDataInfo、exists、useShmTransfer）
    否则 exists 全 false，走纯客户端 Buffer::CreateBuffer，return
(5) 若 useShmTransfer：MutiCreateParallel → CreateBufferForMultiCreateParamAtIndex
    ├─ SHM：mmapManager_->LookupUnitsAndMmapFd → GetMmapEntryByFd → MakeObjectBufferInfo … Buffer::CreateBuffer
    └─ UB：ubUrmaDataInfo 分支（无 mmap 用户指针）→ Buffer::CreateBuffer
```

### 1.4 MSet（`ObjectClientImpl::MSet(vector<shared_ptr<Buffer>>)`）

```text
(1) batch 上限、IsClientReady()
(2) GetAvailableWorkerApi
(3) 各 buffer：CheckDeprecated；seal → K_OC_ALREADY_SEALED
(4) 组装 PublishParam、bufferInfoList
(5) workerApi->MultiPublish → ClientWorkerRemoteApi::MultiPublish
    ├─ MultiPublishReqPb；无 shm 或未 UB 内存拷贝时塞入 MemView payloads
    ├─ SetTokenAndTenantId + RetryOnError → stub_->MultiPublish(opts, req, rsp, payloads)  [client→worker1]
    └─ 重试码含 K_SCALING、K_OUT_OF_MEMORY 等（与 Get 的 lambda 内 last_rc 重试集合不同）
(6) HandleShmRefCountAfterMultiPublish(buffers, rsp)

注：UB 单对象直发多见 Put/ProcessShmPut 的 SendBufferViaUb，不是本 MSet(buffer) 主路径。
```

### 1.5 Get / Read（经 `GetBuffersFromWorker`）

**先看清三段边界**：**client→worker1** 只有 ZMQ 上的 **`WorkerOCService::Get` 流式 RPC**；**对象目录**在 **worker1→worker2**（`QueryMeta` 等到 **Directory Worker** 分片）；**对象字节**在 **worker1→worker3**（按 `QueryMetaInfoPb` 里的副本地址向 **远端 OC Worker** 拉取，或本机即 worker3 合一）。以下树从 client 根写到 worker1 内部，**W2/W3 与 §2.2 MGet 行一致**。

```text
【Client】ObjectClientImpl::Get / Read
    校验 → GetAvailableWorkerApi → GetBuffersFromWorker(workerApi, getParam, buffers)

    (3a) #ifdef USE_URMA：UB 且 !workerApi->IsShmEnable()
         └─ GetObjMetaInfo；体量过大 → GetBuffersFromWorkerBatched（多轮 stub_->Get）

    (3b) workerApi->Get → ClientWorkerRemoteApi::Get  [client→worker1，仅此一跳 ZMQ 业务 Get]
         ├─ PreGet(getParam, subTimeoutMs, req)
         ├─ [UB 且无 SHM] ResolveUBGetSize → PrepareUrmaBuffer（失败多 WARNING，payload 仍可能走 TCP）
         ├─ RetryOnError → stub_->Get(opts, req, rsp, payloads)
         │   └─ lambda 内按 rsp.last_rc() 决定是否对 1001/19/6 等再重试
         └─ FillUrmaBuffer(…)

    (3c) ProcessGetResponse → 各 key 的 Buffer / failed keys

【Worker1】stub_->Get 对端：`WorkerOcServiceGetImpl`（`worker_oc_service_get_impl.cpp`）
    Process Get from client（入口日志）→ … → ProcessGetObjectRequest(subTimeout, request)

    ├─ (W1-A) TryGetObjectFromLocal(request, remoteObjectKeys)   // 仅 worker1 本进程
    │   └─ 按 key：PreProcessGetObject → 本地表/缓存命中则填好 object params；未命中则 key 进入 remoteObjectKeys
    │
    ├─ (W1-B) [可选] subTimeout>0 时 Register(workerRequestManager_)，异步收尾用定时器
    │
    └─ (W1-C) TryGetObjectFromRemote(subTimeout, request, remoteObjectKeys)   // remoteObjectKeys 非空才往下走
            └─ 循环内：ProcessObjectsNotExistInLocal(…)   // 核心：先问元数据在哪，再去拉数据
                ├─ BatchLockForGet；AttemptGetObjectsLocally（锁后再试一次本地）
                │
                ├─ (W1→W2) QueryMetadataFromMaster(needRemoteGetObjects, …)   // **对象目录（Directory）**
                │   └─ 内层：`workerMasterApi->QueryMeta(req, …)` → **Directory Worker**（hash ring 上分片；gRPC/RPC，依实现）
                │       · 成功：得到一批 `QueryMetaInfoPb`（含 **meta + 副本 address**；可能带内联 payload 等）
                │       · 失败：日志原文常 **`Query from master failed`** → 常汇总进 **last_rc**（或 MarkFailed）
                │
                ├─ (W1→W3) GetObjectsFromAnywhere(queryMetas, …)   // **数据拉取**（与 W2 结果顺序相关）
                │   └─ 按每个 queryMeta（或 batch）：GetObjectFromAnywhereWithLock / GetObjectFromAnywhere
                │       · **对端进程** = `queryMeta.address()` 指向的 **远端 OC Worker** → 记为 **worker3**
                │       · 同机副本时 worker1 与 worker3 可为同一进程，逻辑上仍是「按地址拉取」
                │       · 数据面：Worker↔Worker stub + **RPC payload**；UB 路径上可见 **`ds_urma_write`/`read`、`poll_jfc` 等**（多发生在拉取链两端）
                │       · 典型日志：`Get object from remote, … addr:`；失败：`Get from remote failed`
                │
                └─ [配置/路径] GetObjectsWithoutMeta / L2 等分支（与 `FLAGS_oc_io_from_l2cache_need_metadata` 等相关，不展开）

    └─ 收尾：ReturnToClient() → `GetRspPb.last_rc` + Write / SendPayload → 回到 (3b) 的 client

对外 **MGet** 与 **Get(多 key)** 在 client 侧均落入上述栈；批量受 `OBJECT_KEYS_MAX_SIZE_LIMIT` 等约束。**排障**：同一 **Trace ID** 上对齐 client `Start to send rpc to get`、worker1 `Process Get from client`、**W2 Directory** 侧 QueryMeta、W3 侧远端 Get/URMA 日志。
```

---

## 2. 按调用顺序的分层总表（Markdown 评审版）

### 2.1 Init：第 0 层起，逐层向下（每行一层或一条分支）

**读表约定**

- **层**：以 **Init 为 0**，沿主调用链递增；**分支**列区分与主链并行的路径（SHM 预连、UB、收 fd 线程等）。与 **§1.1 对照表** 同步。
- **ZMQ**：指 `datasystem/common/rpc/zmq/` 下对 **libzmq** 的封装；常见底层符号为 **`zmq_socket`**（`zmq_context.cpp`）、**`zmq_connect`**（`zmq_socket_ref.cpp`）、**`zmq_msg_init` / `zmq_msg_init_size`**（`zmq_message.cpp`）；收发多帧经 **`ZmqFrontend::SendAllFrames` / `GetAllFrames`**（`zmq_stub_conn.cpp`），等待侧多为 **消息队列 `Poll` + epoll/fd**，**不保证每个阻塞点都调用 `zmq_poll`**（认证/监控路径可见 `zmq_poll`，见 `zmq_auth.cpp` / `zmq_monitor.cpp`）。
- **OS**：POSIX **syscall** 名；**URMA**：仓库内 **`ds_urma_*`**（`urma_dlopen_util.cpp` 动态绑定 UMDK **`urma_*`**）。
- **源码文件与行级锚点**：见 **§5 附录：代码位置证明**（本表不再占列）。

| 层 | 分支 | 本层数据系统调用点（C++，按发生顺序） | 本层涉及的 ZMQ / OS / URMA 接口（具体符号） | 边界 | 典型 Status / 日志 |
|---:|------|----------------------------------------|---------------------------------------------|------|---------------------|
| 0 | 主 | `KVClient::Init` → `ObjectClientImpl::Init` | （无 I/O） | client | — |
| 1 | 主 | `ObjectClientImpl::Init`：服务发现选 worker / **HostPort 校验**（失败则 `K_INVALID`） | （无 I/O） | client | `K_INVALID` |
| 2 | 主 | **`RpcAuthKeyManager::CreateClientCredentials`**（AKSK → `cred_`） | （无 I/O） | client | 鉴权相关校验失败 |
| 3 | 主 | **`InitClientWorkerConnect`** → `workerApi->Init`：`ClientWorkerRemoteApi::Init` → **`Connect`** | （尚未发业务 RPC；构造 `RpcChannel`、`WorkerService_Stub`） | client | — |
| 4 | SHM预连 | **`CreateConnectionForTransferShmFd`** 内 **`GetSocketPath`**：`commonWorkerSession_->GetSocketPath`（`RetryOnError` 包装） | **ZMQ**：请求走 stub 前端 **`SendAllFrames`**，载荷侧 **`zmq_msg_*`** 组帧；已建链路上 **`zmq_connect`** 已执行 | client→worker1 | `K_RPC_UNAVAILABLE(1002)` / `K_RPC_DEADLINE_EXCEEDED(1001)` / `K_TRY_AGAIN(19)` |
| 5 | SHM预连 | **`CreateHandShakeFunc`**：按 endpoint 建立 **传 fd 用** 的 UDS/TCP 套接字 | **OS**：**`socket`** → **`connect`**（封装在握手逻辑中；失败可降级纯 TCP 数据路径） | client→worker1（同机优先） | 连不上 UDS 时日志提示 fallback TCP |
| 6 | 主 | **`RegisterClient`**：`commonWorkerSession_->RegisterClient`（`RetryOnError`） | **ZMQ**：同上，多帧 RPC 请求/应答；与 **worker1** 上 ZMQ service 端对称收发 | client→worker1 | `Register client failed`；`1001`/`1002`/`19` |
| 7 | 主 | **`PostRegisterClient`**：解析 `RegisterClientRspPb`，更新 clientId / shm 阈值 / 版本等 | （无 I/O） | client | — |
| 8 | UB | **`FastTransportHandshake`** → **`InitializeFastTransportManager`** → （USE_URMA 且启用）**`TryUrmaHandshake`** / 异步握手 | 握手控制面仍可经 **ZMQ**（`ExecOnceParrallelExchange` 等与 worker 传 PB）；失败 **LOG_IF_ERROR**，**不阻断 Init** | client↔worker1 | `Fast transport handshake failed…fall back` |
| 9 | UB | **`UrmaManager::UrmaInit`**（`urma_dlopen::Init` 之后） | **URMA**：**`ds_urma_register_log_func`** → **`ds_urma_init`** | client | `K_URMA_ERROR(1004)`；`Failed to urma init` |
| 10 | UB | 设备解析：**`UrmaGetEffectiveDevice`** / **`UrmaGetDeviceByName`** | **URMA**：**`ds_urma_get_device_list`** → **`ds_urma_get_device_by_name`**（失败带 **errno**） | client | `1004`；`get device by name` / `eid list` 类日志 |
| 11 | UB | **`GetEidIndex`** | **URMA**：**`ds_urma_get_eid_list`** → **`ds_urma_free_eid_list`** | client | `1004` |
| 12 | UB | **`UrmaResource`** 创建：**`UrmaContext::Create`** → JFCE/JFC/JFS/JFR | **URMA**（顺序与 `urma_resource.cpp` 一致）：**`ds_urma_create_context`** → **`ds_urma_create_jfce`** → **`ds_urma_create_jfc`** → **`ds_urma_create_jfs`** → **`ds_urma_create_jfr`** | client | `Failed to urma create context/jfc/...`；`1004` |
| 13 | UB | **`InitMemoryBufferPool`**（客户端 UB 匿名池） | **OS**：**`mmap(nullptr, …, PROT_READ\|PROT_WRITE, MAP_PRIVATE\|MAP_ANONYMOUS, -1, 0)`** | client | `K_OUT_OF_MEMORY(6)`；`Failed to allocate memory buffer pool` |
| 14 | UB | **`ExchangeJfr` / import 链**（与对端 JFR 对齐） | **URMA**：**`ds_urma_import_jfr`**、**`ds_urma_advise_jfr`**；段路径见 **`ds_urma_import_seg`**（`urma_resource.cpp`） | client↔worker1 | `Failed to import` / `advise jfr`；仅 ERROR 时可仍 Init 成功 |
| 15 | SHM fd | 后台线程 **`RecvPageFd`** 循环（Register 成功后常驻） | **OS**：**`recvmsg(fd, msg, 0)`**（`SCM_RIGHTS` 收 fd，内联 **`SockRecvFd`**） | client（UDS 已连） | `K_UNKNOWN_ERROR`；`Pass fd…` / `invalid fd` |
| 16 | 主 | **`InitClientWorkerConnect` 续**：`MmapManager` / **`InitListenWorker`**（心跳与监听）等 | 心跳仍多为 **ZMQ RPC**（`ListenWorker` 路径，方法依 `HeartbeatType`）；另：**`shutdown`/`close`** 旧 fd（`CloseSocketFd`） | client；client→worker1 | `K_CLIENT_WORKER_DISCONNECT(23)` 等（运行期） |

**Init 表注**

- **`RecvPageFd` 线程**：在 **`ClientWorkerRemoteCommonApi` 构造函数**里已 `Thread(...)` 启动；表中放在 **第 15 行** 是指 **`recvmsg` 有效循环**——通常需在 **`Connect` 设置 `socketFd_`** 之后才有意义，与主链 **时间并行**。
- **纯 TCP、关闭 URMA**：第 8～14 行 UB 分支可不执行或快速返回；数据面走 RPC payload，不改变 **ZMQ + OS socket** 控制面主链（4、5、6 行仍关键）。
- **嵌入式 / Local API**：`ClientWorkerLocalCommonApi::Connect` 走 **`WorkerRegisterClient`** 而非 ZMQ stub，本表以 **远程 `ClientWorkerRemoteCommonApi`** 为准。

### 2.2 MCreate / MSet / MGet：分层表（占位 · 深度将与 §2.1 对齐后补全）

以下先保留 **一层一行** 的骨架；**§2.1 层号** 与 Init 独立编号（本表从 0 再起），与 **§1.3～1.5** 步骤对应。

| 层 | 接口根 | 分支 | 本层调用点（摘要） | ZMQ / OS / URMA（待写全具体符号） | 边界 | 对照 §1 |
|---:|--------|------|-------------------|-------------------------------------|------|---------|
| 0 | MCreate | 主 | `ObjectClientImpl::MultiCreate` → 入参校验 | — | client | 1.3 (1)(2) |
| 1 | MCreate | 主 | `LOCAL_WORKER->MultiCreate`（stub） | **ZMQ** 同 Init Register 路径 | client→worker1 | 1.3 (4) |
| 2 | MCreate | SHM | Worker 分配 + Client **`mmap`** | **OS**：`shm_open`/`mmap`/…（依实现） | worker1；client | 1.3 (5) |
| 0 | MSet | 主 | `MSet` → **`MultiPublish`** | **ZMQ** stub 路径 | client→worker1 | 1.4 (5) |
| 1 | MSet | UB | **`UrmaWritePayload`** → **`ds_urma_write`** 链 | **URMA** + **OS** 内存注册 | client；worker3 | 注：Put 直发多见 |
| 0 | MGet | client 控制面 | `Get` → **`GetBuffersFromWorker`** → **`stub_->Get`**（流式 RPC） | **ZMQ** `SendAllFrames` / `zmq_msg_*` + `RetryOnError` | client→worker1 | 1.5 【Client】(3b) |
| 1 | MGet | client UB | **`PrepareUrmaBuffer`** / **`FillUrmaBuffer`** | **URMA** 客户端池；可降级 TCP payload | client | 1.5 (3b)(3c) |
| 2 | MGet | worker1 本地 | **`TryGetObjectFromLocal`** → **`PreProcessGetObject`**（本地命中则不必 W2/W3） | 内存表 / 本地状态机（无跨进程） | worker1 | 1.5 (W1-A) |
| 3 | MGet | **worker1→worker2** | **`ProcessObjectsNotExistInLocal`** → **`QueryMetadataFromMaster`** → **`workerMasterApi->QueryMeta`** | **Directory RPC**（对 hash ring 上目录分片；gRPC 等，非 client 的 ZMQ） | worker1→worker2 | 1.5 (W1→W2) |
| 4 | MGet | **worker1→worker3** | **`GetObjectsFromAnywhere`** → **`GetObjectFromAnywhereWithLock`**（目标 = **`queryMeta.address()`**） | **Worker↔Worker** 数据 RPC + 可选 **URMA** 数据面 | worker1→worker3 | 1.5 (W1→W3) |
| 5 | MGet | worker3 本机数据面 | 副本节点上 **`UrmaWritePayload`/`ds_urma_*`**、**`poll_jfc`/`wait_jfc`** 等（与是否 UB/SHM 有关） | **URMA** / **OS** | worker3（可与 worker1 同进程） | 1.5 (W1→W3) 对端 |
| 6 | MGet | 回包 | worker1 **`ReturnToClient`** → client **`mmap` SHM** / 组装 payload | **OS** `mmap`；越界等 → `K_RUNTIME_ERROR(5)` | worker1→client | 1.5 (3c) |

---

## 3. 错误码、日志与 Trace 串联（client / worker1 / worker2 / worker3）

本节回答：**各角色上会出现什么日志、错误码从哪来、是否最终体现在 client 的 `Status`（或 `last_rc`）里**，便于用 **同一 Trace ID** 串日志。

### 3.1 两条「回传 client」的通道（必须先分清）

| 通道 | 典型场景 | client 侧表现 | worker 侧落点 |
|------|----------|----------------|---------------|
| **A. RPC 层 `Status`** | ZMQ 断连、poll 超时、`stub_` 返回失败 | `RetryOnError` 可能重试；耗尽后直接 **`Status` 返回**调用方（如 `1001`/`1002`/`19`） | 不一定有业务日志；或仅有框架层错误 |
| **B. 业务 `GetRspPb.last_rc`（仅 Get 流）** | worker 已接入请求、处理中/结束时汇总错误 | `ClientWorkerRemoteApi::Get` 在 **RPC 成功后**再构造 `Status(last_rc)`，**特定码会触发 RPC 层重试**（如 `1001`、`19`、**全体失败时的 `6`**） | `GetRequest::ReturnToClient` 写入 `resp.mutable_last_rc()` 后 `Write`+`SendPayload` |

**MultiPublish / MultiCreate**：client 主要认 **`stub_` 返回的 `Status`**；`MultiPublish` 的 `RetryOnError` **额外允许** `K_SCALING`、`K_OUT_OF_MEMORY` 等与 Get 的 lambda 内策略**不完全相同**。业务失败多在 **worker1 日志** + **RPC 错误码**，而不是 `last_rc` 字段（与 Get 流式不同）。

### 3.2 按角色归纳（排障时按 Trace 搜关键字）

#### Client（SDK）

| 场景 | 常见日志/关键字 | 常见错误码 | 说明 |
|------|-----------------|------------|------|
| Init Register / GetSocketPath 失败 | `Register client failed`；RPC retry 相关 | `1001` `1002` `19` | 纯 RPC 通道 A，未到业务 last_rc |
| Get 发 RPC | `Start to send rpc to get object`（VLOG） | — | 对齐 worker1 同 Trace 的 `Process Get from client` |
| Get 收到应答后 | — | `last_rc` 展开为 `Status` | 见 worker1 写入的 code/msg |
| UB 准备降级 | `PrepareUrmaBuffer` 路径 WARNING | 常 **不**以 URMA 码失败返回，可能继续走 TCP payload | 性能问题多于功能失败 |
| MultiPublish 失败 | `Send multi publish request error` 等 | `1001`/`1002`/`19`/`6`/`K_SCALING(32)` 等 | 以 `RetryOnError` 集合为准 |
| Get 后组装 SHM/UB | `Failed for <key> :` | `K_UNKNOWN_ERROR` / `K_RUNTIME_ERROR` 等 | 属 client 侧组装；需对照 rsp 与本地 fd/UB 池 |

#### Worker1（入口 OC Worker）

| 场景 | 常见日志/关键字 | 常见错误码 / 结构 | 是否到 client |
|------|-----------------|-------------------|---------------|
| Get 入口 | `Process Get from client:` … `objects:` … `elapsed ms:` | — | 用于 Trace 对齐 |
| 本地命中 / 仅 W1 | `TryGetObjectFromLocal` 链；`PreProcessGetObject failed` 等 | 按 key 的 `K_NOT_FOUND` 等 | **是**（进入 `GetRspPb` / last_rc 聚合） |
| **W1→W2** QueryMeta / Directory | `Begin to process … doesn't exist in local` → `QueryMetadataFromMaster` 失败时日志原文 **`Query from master failed`** | `K_RUNTIME_ERROR` / RPC 超时重试类 | **是**（worker1 写回 last_rc 或 MarkFailed） |
| **W1→W3** 拉副本 | `Query meta success` 之后；`Get object from remote, … addr:`；失败 **`Get from remote failed`** | 依对端；常见 `1002`、拉取专用码 | **是**（worker1 汇总 last_rc） |
| Get 排队超时 | `The get request times out`；`ReturnFromGetRequest timeout when get object` | 可能 `1001` + `"Rpc timeout"` 经 **last_rc 或 SendStatus** | **是**（Get 流） |
| Get 线程内 RPC 超时 | `RPC timeout. time elapsed` | `SendStatus(K_RUNTIME_ERROR, "Rpc timeout")`（msg 可辨） | **是**（早返回路径） |
| 返回前 | `Begin to ReturnToClient, client id:` | `last_rc` 写入 `GetRspPb` | **是** |
| MultiPublish | `Process multi pub from client:`；失败时 `Fail to lock/verify/create all the objects` 等 | 多为 **RPC Status** 或业务 rc | **是**（经 stub，非 last_rc） |
| QueryMeta / etcd 租约 | 手册与脚本中的 **etcd unavailable** 类（多为 **Directory 路由/租约** 间接问题） | 可映射 `1002` 等 | 常进 **last_rc**（Get） |

#### Worker2（Directory / 对象目录分片）

| 场景 | 常见日志/关键字 | 常见错误码 | 是否到 client |
|------|-----------------|------------|---------------|
| **`workerMasterApi->QueryMeta`（Directory）** | **Directory Worker** 进程内日志（命名依部署）；**worker1** 失败时统一可见日志原文 **`Query from master failed : …`**（`ProcessObjectsNotExistInLocal`） | 目录分片不可达、非 Leader、RPC 超时等 → 常 **`K_RUNTIME_ERROR(5)`** 或原 RPC 码经 worker1 处理 | **是**（**last_rc** / MarkFailed） |

*注：在 **worker2（Directory 分片所在 Worker）** 上要按 **同一业务 Trace** 或 **关联 request id** 检索；client 通常只能看到 worker1 回传的码与 msg。*

#### Worker3（副本 / 数据面 Worker）

| 场景 | 常见日志/关键字 | 常见错误码 | 是否到 client |
|------|-----------------|------------|---------------|
| 作为 **副本地址** 被 W1 访问 | 与 `queryMeta.address()` 对应节点上的 **Worker OC Get/serve** 路径日志 | 与本地读一致的业务/RPC 码 | **是**（错误回到 **W1** 再进 client） |
| W1 视角的拉取失败 | worker1 打：`Get from remote failed`；`Failed to get object data from remote` | `1002`、**`K_WORKER_PULL_OBJECT_NOT_FOUND`** 等 | **是**（last_rc 聚合） |
| URMA write/read | `Failed to urma write` / `read` 类 | `K_RUNTIME_ERROR` / `1004` 等 | **是**（经 worker1 或本机逻辑汇总） |
| URMA poll/wait jfc | `Failed to poll jfc` / `wait jfc` | `K_URMA_ERROR(1004)` | **是** |
| 对象不存在 | 各层 `NOT_FOUND` 相关 | `K_NOT_FOUND` | **是**（last_rc；client 侧可能对 `NOT_FOUND` 做统计归一） |

### 3.3 Trace 排查建议（最短路径）

1. **client 日志**：取 **Trace ID**（`KVClient::Init` 等入口会 `SetTraceUUID`；RPC 链上 worker 侧常用 `SetTraceNewID` 继承）。  
2. **worker1**：搜 **`Process Get from client`** + 同一 Trace；再看是否出现 **`doesn't exist in local`**（将走 W2/W3）、**`Query from master failed`**（日志原文；卡在 **W1→W2 Directory**）、**`Query meta success`** 后出现 **`Get object from remote` / `Get from remote failed`**（卡在 **W1→W3**）。  
3. 若出现 **QueryMeta / Directory** 失败或超时 → **worker2（承担该 key 在 hash ring 上目录分片的 Worker）** 同时间段、同 key/租户。  
4. 若元数据成功、拉取失败或 URMA 报错 → **worker3**（`queryMeta.address()` 指向节点）日志 + UB/UMDK。  
5. **对照 client 最终 `Status`**：Get 路径同时核对 **是否曾打印 RPC retry**（通道 A）与 **`last_rc` 码**（通道 B）；二者可能先后出现多次。

---

## 4. 校验清单（给评审兄弟）

1. **Init**：对照 **§2.1** 与 **§1.1 对照表** 各层顺序与 **ZMQ/OS/URMA 符号**是否与你们分支一致（**USE_URMA** / 纯 TCP / 嵌入式 Local API）。  
2. **MCreate**：是否认可「**MultiCreate 始终走 LOCAL_WORKER API 对象**」这一事实（与「切流后 Get 可走远端 Worker」不同）。  
3. **MSet/MGet**：§2.2 占位行深度不足是刻意的；确认 §2.1 样式 OK 后，再按同样规则补全 **Publish/Get** 的 ZMQ 与 **ds_urma_*** / **mmap** 分层。Excel 侧是否增「层/分支」列可再定。  
4. **§3**：若你们线上日志字符串有定制（国际化/裁剪），以现网为准，但 **last_rc 与 RetryOnError 语义**应以源码为准做回归。

---

## 5. 附录：代码位置证明（原「代码参考」与入口片段）

### 5.1 §2.1 Init 分层 → 源文件

| §2.1 层 | 代码参考（相对仓库根） |
|--------:|-------------------------|
| 0～3 | `src/datasystem/client/kv_cache/kv_client.cpp`；`src/datasystem/client/object_cache/object_client_impl.cpp`（`Init`） |
| 4～8、15 | `src/datasystem/client/object_cache/client_worker_api/client_worker_common_api.cpp`（`Init`/`Connect`/`CreateConnectionForTransferShmFd`/`RegisterClient`/`PostRegisterClient`/`RecvPageFd`） |
| 9～14 | `src/datasystem/client/object_cache/urma/urma_manager.cpp`；`src/datasystem/client/object_cache/urma/urma_resource.cpp` |
| 15（OS） | `src/datasystem/common/.../fd_pass.cpp`（`SockRecvFd`） |
| 16 | `object_client_impl.cpp`；`client_worker_common_api.cpp`（`CloseSocketFd`）；ListenWorker 相关实现 |

### 5.2 关键入口片段（节选）

**`KVClient::Init` → `ObjectClientImpl::Init`**

```66:72:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/kv_cache/kv_client.cpp
Status KVClient::Init()
{
    TraceGuard traceGuard = Trace::Instance().SetTraceUUID();
    bool needRollbackState;
    auto rc = impl_->Init(needRollbackState, true);
    impl_->CompleteHandler(rc.IsError(), needRollbackState);
    return rc;
}
```

```345:366:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::Init(bool &needRollbackState, bool enableHeartbeat)
{
    ...
    RETURN_IF_NOT_OK(InitClientWorkerConnect(enableHeartbeat, false));
    return Status::OK();
}
```

**`MultiCreate`（LOCAL_WORKER + 条件 SHM）**

```1155:1182:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::MultiCreate(...){
    ...
    bool canUseShm = workerApi_[LOCAL_WORKER]->shmEnabled_ && dataSizeSum >= workerApi_[LOCAL_WORKER]->shmThreshold_;
    if (canUseShm || !skipCheckExistence) {
        RETURN_IF_NOT_OK(workerApi_[LOCAL_WORKER]->MultiCreate(skipCheckExistence, multiCreateParamList, version,
                                                               exists, useShmTransfer));
    } else {
        ...
    }
```

**`MSet` → `MultiPublish`**

```2180:2202:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::MSet(const std::vector<std::shared_ptr<Buffer>> &buffers)
{
    ...
    RETURN_IF_NOT_OK(workerApi->MultiPublish(bufferInfoList, publishParam, rsp));
    return HandleShmRefCountAfterMultiPublish(buffers, rsp);
}
```

**`Get` → `GetBuffersFromWorker`**

```1568:1596:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::Get(const std::vector<std::string> &objectKeys, int64_t subTimeoutMs,
                             std::vector<Optional<Buffer>> &buffers, bool queryL2Cache, bool isRH2DSupported)
{
    ...
    RETURN_IF_NOT_OK(GetAvailableWorkerApi(workerApi, raii));
    ...
    Status rc = GetBuffersFromWorker(workerApi, getParam, objectBuffers);
    ...
}
```

**Get：`last_rc` 与重试（client）**

```303:323:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
    Status getStatus;
    PerfPoint perfPoint(PerfKey::RPC_CLIENT_GET_OBJECT);
    Status status = RetryOnError(
        std::max<int32_t>(requestTimeoutMs_, subTimeoutMs),
        [this, &req, &rsp, &payloads, &getStatus](int32_t realRpcTimeout) {
            ...
            getStatus = stub_->Get(opts, req, rsp, payloads);
            ...
            Status recvStatus = Status(static_cast<StatusCode>(rsp.last_rc().error_code()), rsp.last_rc().error_msg());
            if (IsRpcTimeoutOrTryAgain(recvStatus)
                || (recvStatus.GetCode() == StatusCode::K_OUT_OF_MEMORY && IsAllGetFailed(rsp))) {
                return recvStatus;
            }
            return Status::OK();
        },
```

**Get：写回 `last_rc`（worker1）**

```348:352:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/object_cache/worker_request_manager.cpp
    resp.mutable_last_rc()->set_error_code(lastRc.GetCode());
    resp.mutable_last_rc()->set_error_msg(lastRc.GetMsg());
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi_->Write(resp), "Write reply to client stream failed.");
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(serverApi_->SendPayload(payloads), "SendPayload to client stream failed");
```

**错误码枚举（节选，完整见 `status_code.def`）**

```1:42:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/util/status_code.def
// common
STATUS_CODE_DEF(K_OK, "OK")
...
STATUS_CODE_DEF(K_TRY_AGAIN, "Try again")
...
// rpc
STATUS_CODE_DEF(K_RPC_DEADLINE_EXCEEDED, "RPC deadline exceeded")
STATUS_CODE_DEF(K_RPC_UNAVAILABLE, "RPC unavailable")
```
