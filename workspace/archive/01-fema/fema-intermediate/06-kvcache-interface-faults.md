# KVCache 接口级故障模式详解

## 说明

本文档基于 `fault-tree-table.md` Section 1 的 KVCache 故障树，
整理每个 KVCache 接口的完整故障模式、错误码、调用链和故障域分类。

---

## 接口 1: Init / KVClient::Init

### 基本信息

| 项目 | 内容 |
|-----|------|
| **调用场景** | SDK 首次与 Worker 建链：服务发现、证书加载、心跳注册 |
| **正常返回** | K_OK |
| **access log** | 此阶段一般无 `DS_KV_CLIENT_*` 行 |

### 错误码与调用链

| 错误 StatusCode | 枚举值 | 故障域分类 | 调用链 |
|----------------|--------|----------|--------|
| `K_INVALID` | 2 | **用户问题** | `ObjectClientImpl::Init` → `Validator::ValidateHostPortString` |
| `K_NOT_READY` | 8 | **用户问题** | `ClientStateManager::ProcessInit` → 未完成 Init 或已 ShutDown |
| `K_RPC_UNAVAILABLE` | 1002 | **OS 问题** | `ServiceDiscovery::SelectWorker` → 建链失败 |
| `K_RPC_DEADLINE_EXCEEDED` | 1001 | **OS 问题** | 建链超时 |
| `K_CLIENT_WORKER_DISCONNECT` | 23 | **OS 问题** | 首心跳失败 |
| `K_MASTER_TIMEOUT` | 25 | **OS 问题** | 控制面不可达（etcd） |

### 关键日志

**Client 日志**:
- `Start to init worker client at address: <ip:port>`
- `Start to init preferred remote fallback worker client at address: ...`
- `Invalid IP address/port. Host %s, port: %d`
- `ConnectOptions was not configured with a host and port or serviceDiscovery.`
- `[Reconnect] Reconnect local worker failed, error message: ...`

### 故障域详细分类

| 故障域 | 原因 | 排查方向 |
|-------|------|---------|
| **用户问题** | ConnectOptions 的 ip/port 配错或未配 serviceDiscovery；并发 Init/ShutDown；AK/SK、Token 失效 | 检查配置 |
| **OS 问题** | 安全组/路由不通；DNS 解析失败；证书文件权限或路径错误；本机 fd/线程规格不足 | 检查网络和系统资源 |
| **URMA 问题** | Init 阶段本身不走 URMA；Init 成功后首次 Create/Publish 才可能触发 URMA 建链 | N/A |

---

## 接口 2: MCreate / KVClient::MCreate（批量申请 shm buffer）

### 基本信息

| 项目 | 内容 |
|-----|------|
| **调用场景** | 批量为 keys 在 Worker 侧申请共享内存，返回可直接填充的 Buffer 列表 |
| **正常返回** | K_OK + buffers 对齐输出 |
| **access log** | `DS_KV_CLIENT_MCREATE`（dataSize = sizes.size()；respMsg = Status::GetMsg） |
| **Worker 日志** | `DS_POSIX_MCREATE`；`MultiCreate failed` |

### 错误码与调用链

| 错误 StatusCode | 枚举值 | 故障域分类 | 调用链 |
|----------------|--------|----------|--------|
| `K_INVALID` | 2 | **用户问题** | `CheckValidObjectKey` / `IsBatchSizeUnderLimit` → keys 空/非法字符、批量超限 |
| `K_NOT_READY` | 8 | **用户问题** | `IsClientReady` → SDK 未 Init |
| `K_RUNTIME_ERROR` | 5/7 | **OS 问题** | `mmapManager_->LookupUnitsAndMmapFd` → `Get mmap entry failed` |
| `K_OUT_OF_MEMORY` | 6 | **OS 问题** | shm 池不足 |
| `K_OC_KEY_ALREADY_EXIST` | 2004 | **用户问题** | 已存在且 existence=NX |
| `K_RPC_UNAVAILABLE` | 1002 | **OS 问题** | Worker 通信异常 |
| `K_URMA_*` | 1004/1006/1008 | **URMA 问题** | UB 建链异常 |

### 调用链详解

```
KVClient::MCreate → ObjectClientImpl::MCreate → MultiCreate
 ├─ IsClientReady → K_NOT_READY
 ├─ CheckValidObjectKey / IsBatchSizeUnderLimit → K_INVALID
 ├─ GetAvailableWorkerApi → K_RPC_UNAVAILABLE / K_CLIENT_WORKER_DISCONNECT
 ├─ workerApi->MultiCreate（RPC）
 │    └─ Worker OC::MultiCreate → K_OUT_OF_MEMORY / K_OC_KEY_ALREADY_EXIST / K_SCALING
 └─ mmapManager_->LookupUnitsAndMmapFd → K_RUNTIME_ERROR（'Get mmap entry failed'）
```

### 关键日志

**Client 日志**:
- `Start to MultiCreate %zu`（size）
- `Begin to create object, object_key: ...`
- `Get mmap entry failed`
- `The objectKey is empty` / `The dataSize value should be bigger than zero.` / `length of objectKeyList and dataSizeList should be the same.`

### 故障域详细分类

| 故障域 | 原因 | 排查方向 |
|-------|------|---------|
| **用户问题** | 空/非法 key；批量超 OBJECT_KEYS_MAX_SIZE_LIMIT；写同名 key+NX；size=0 | 检查业务参数 |
| **OS 问题** | 本机 shm 池满 / hugepage 不足；client fd 超限导致 mmap 失败；磁盘没空间（spill） | 检查内存和磁盘 |
| **URMA 问题** | UB 开启时 Worker 侧 `urma_register_seg` 失败 → 透传为 K_URMA_ERROR | 见 URMA API 故障表 |

---

## 接口 3: MPublish / KVClient::MSet（批量发布）

### 基本信息

| 项目 | 内容 |
|-----|------|
| **调用场景** | 把 MCreate 拿到的 shm buffer 发布到数据系统：写元数据、可选二级落盘 |
| **正常返回** | K_OK |
| **access log** | `DS_KV_CLIENT_MSET`（dataSize = buffers.size()；respMsg = Status::GetMsg） |
| **Worker 日志** | `DS_POSIX_PUBLISH`；`MultiPublish` 相关错误 / Master `CreateMultiMeta failed` |

### 错误码与调用链

| 错误 StatusCode | 枚举值 | 故障域分类 | 调用链 |
|----------------|--------|----------|--------|
| `K_INVALID` | 2 | **用户问题** | buffer 列表为空/含 nullptr；批量超限 |
| `K_OC_ALREADY_SEALED` | 2000 | **用户问题** | `Buffer::CheckDeprecated` / `isSeal` → buffer 已 Publish 过 |
| `K_RUNTIME_ERROR` | 5/7 | **OS 问题** | `DispatchKVSync` 异常 |
| `K_RPC_UNAVAILABLE` | 1002 | **OS 问题** | Worker/Master 不可达 |
| `K_RPC_DEADLINE_EXCEEDED` | 1001 | **OS 问题** | RPC 超时 |
| `K_MASTER_TIMEOUT` | 25 | **OS 问题** | 元数据中心（etcd）不可达 |
| `K_SCALING` | 32 | **组件问题** | 扩缩容重试到上限（产品语义对业务透明） |
| `K_URMA_ERROR` | 1004 | **URMA 问题** | UB 传输异常 |
| `K_URMA_NEED_CONNECT` | 1006 | **URMA 问题** | UB 连接需重建 |
| `K_WRITE_BACK_QUEUE_FULL` | 2003 | **OS 问题** | 二级回写队列满 |

### 调用链详解

```
KVClient::MSet(buffers) → ObjectClientImpl::MSet
 ├─ IsClientReady → K_NOT_READY
 ├─ IsBatchSizeUnderLimit → K_INVALID
 ├─ Buffer::CheckDeprecated / isSeal → K_OC_ALREADY_SEALED
 ├─ workerApi->MultiPublish（RPC，内部对 K_SCALING 自动重试）
 │    ├─ Worker CreateMultiMeta → Master
 │    │    └─ K_MASTER_TIMEOUT / K_NOT_LEADER_MASTER / K_SCALING
 │    └─ WriteMode=WRITE_THROUGH → 二级存储写 → K_IO_ERROR / K_WRITE_BACK_QUEUE_FULL
 └─ HandleShmRefCountAfterMultiPublish → 维护引用计数
```

### 关键日志

**Client 日志**:
- `Start putting buffer`
- `Client object is already sealed`
- `The buffer should not be empty.` / `The buffer size cannot exceed %d.`

### 故障域详细分类

| 故障域 | 原因 | 排查方向 |
|-------|------|---------|
| **用户问题** | 对同一个 buffer 重复 Publish；WriteMode 选错导致阻塞写二级；超时配得过紧 | 检查业务流程 |
| **OS 问题** | RPC 慢/抖动（CPU 打满、内存压力、网络拥塞）；二级存储盘满 / OBS 不可达 | 检查系统资源和网络 |
| **URMA 问题** | UB 传输链路异常 → K_URMA_ERROR / K_URMA_NEED_CONNECT / K_URMA_TRY_AGAIN | 见 URMA API 故障表 |
| **组件问题** | 扩缩容中 | 等待扩缩容完成 |

---

## 接口 4: MGet / KVClient::Get（批量读取）

### 基本信息

| 项目 | 内容 |
|-----|------|
| **调用场景** | 按 key 批量取数；Worker 优先读 L1，未命中则 L2 / 远端 Worker（URMA/TCP 拉取） |
| **正常返回** | K_OK（**即使部分 key 不存在，顶层仍为 K_OK；per-key 以 buffer 是否有值为准**） |
| **access log** | `DS_KV_CLIENT_GET`（**NOT_FOUND → 0 陷阱**；microseconds 贴 timeout 判断预算耗尽） |
| **Worker 日志** | `DS_POSIX_GET`；`[Remote]Pull object` / `Remote get failed` / `Read L2 cache failed` |

### 错误码与调用链

| 错误 StatusCode | 枚举值 | 故障域分类 | 调用链 |
|----------------|--------|----------|--------|
| `K_INVALID` | 2 | **用户问题** | keys 为空 / 含空 key / 超 QUERY_SIZE_OBJECT_LIMIT |
| `K_NOT_FOUND` | 3 | **用户问题** | 全部 key 都不存在（access log 中被映射为 0 / K_OK） |
| `K_RPC_DEADLINE_EXCEEDED` | 1001 | **OS 问题** | 超时 |
| `K_RPC_UNAVAILABLE` | 1002 | **OS 问题** | RPC 不可达 / 传输 bucket 错误 |
| `K_URMA_ERROR` | 1004 | **URMA 问题** | UB 路径异常 |
| `K_URMA_TRY_AGAIN` | 1008 | **URMA 问题** | UB 路径需重试 |
| `K_URMA_NEED_CONNECT` | 1006 | **URMA 问题** | UB 连接需重建 |
| `K_RUNTIME_ERROR` | 5/7 | **OS 问题** | mmap / 内部异常 |
| `K_CLIENT_WORKER_DISCONNECT` | 23 | **OS 问题** | Worker 心跳断 |

### 调用链详解

```
KVClient::Get → ObjectClientImpl::Get → workerApi->MultiGet（RPC）
 ├─ Worker 命中 L1：直接返回 shm / urma 描述
 │    └─ client mmap 新 fd → K_RUNTIME_ERROR（'Get mmap entry failed'）
 ├─ Worker 未命中 L1：
 │    ├─ 远端 Worker 拉取（UB 优先，TCP 降级）
 │    │    └─ K_URMA_* / K_RPC_UNAVAILABLE / K_RPC_DEADLINE_EXCEEDED
 │    └─ L2 存储读 → K_IO_ERROR / K_NOT_FOUND
 └─ per-key 结果放 buffers[i]；per-object last_rc 可能为失败而顶层 K_OK
```

### 关键日志

**Client 日志**:
- `Cannot get value from worker` / `Get mmap entry failed`

**Worker 日志**:
- `[Remote]Pull object` / `Remote get failed` / `Read L2 cache failed`

**resource.log**:
- 线程池 waiting、SHM rate、OBS 成功率

### 故障域详细分类

| 故障域 | 原因 | 排查方向 |
|-------|------|---------|
| **用户问题** | key 格式非法；批量 > QUERY_SIZE_OBJECT_LIMIT；timeout 过紧；业务把 NOT_FOUND 当错误 | 检查业务参数和逻辑 |
| **OS 问题** | 网络拥塞 / 丢包；本机 CPU 饱和；shm fd 超限 / mmap 失败；磁盘或 OBS 延迟高 | 检查系统资源 |
| **URMA 问题** | 跨节点拉数走 UB：UB 降 lane / Jetty / 平面切换 → K_URMA_* | 见 URMA API 故障表 |

### 重要陷阱

> **K_NOT_FOUND → 0 陷阱**: access log 中 GET 的 `NOT_FOUND` 响应被映射为 `0`（K_OK），需通过 per-key buffer 是否有值判断。

---

## 接口 5: Exist / KVClient::Exist（批量查询存在性）

### 基本信息

| 项目 | 内容 |
|-----|------|
| **调用场景** | 批量查询 key 是否存在：查 Worker 元数据 + 可选 etcd |
| **正常返回** | K_OK + exists[] 与 keys[] 一一对应 |
| **access log** | Exist **当前未挂** `DS_KV_*` access 点，依赖应用日志定位 |
| **Worker 日志** | Exist 相关 RPC 错误 / etcd 读失败 |

### 错误码与调用链

| 错误 StatusCode | 枚举值 | 故障域分类 | 调用链 |
|----------------|--------|----------|--------|
| `K_INVALID` | 2 | **用户问题** | keys 空 / 含空 key / size > QUERY_SIZE_OBJECT_LIMIT（10000） |
| `K_NOT_READY` | 8 | **用户问题** | SDK 未 Init |
| `K_RPC_UNAVAILABLE` | 1002 | **OS 问题** | Worker 不可达 |
| `K_RPC_DEADLINE_EXCEEDED` | 1001 | **OS 问题** | RPC 超时 |
| `K_MASTER_TIMEOUT` | 25 | **OS 问题** | 查 etcd 时 Master 不可达 |
| `K_RUNTIME_ERROR` | 5/7 | **OS 问题** | 响应大小与请求不一致 |

### 调用链详解

```
KVClient::Exist → ObjectClientImpl::Exist
 ├─ IsClientReady → K_NOT_READY
 ├─ CheckValidObjectKeyVector → K_INVALID
 ├─ size <= QUERY_SIZE_OBJECT_LIMIT → K_INVALID
 └─ workerApi->Exist（RPC）
       ├─ Worker 查本地元数据 / etcd（queryEtcd=true 时）
       │    └─ K_MASTER_TIMEOUT / K_KVSTORE_ERROR
       └─ 返回 exists.size() 必须等于 keys.size()，否则 K_RUNTIME_ERROR
```

### 关键日志

**Client 日志**:
- `Exist resp error, msg:...`
- `Exist response size X is not equal to key size Y`
- `The objectKeys size exceed %d.`

### 故障域详细分类

| 故障域 | 原因 | 排查方向 |
|-------|------|---------|
| **用户问题** | 批量过大；传入空字符串 key；把『不存在』当错误处理 | 检查业务参数 |
| **OS 问题** | client ↔ worker 网络不通；etcd 访问异常或高延迟 | 检查网络和 etcd |
| **URMA 问题** | 纯元数据路径，**不走 URMA** | N/A |

---

## 接口 6: 其他常用操作（Del / Expire / QuerySize / Create+Set）

### 基本信息

| 操作 | access log | 错误码 |
|------|-----------|--------|
| Del | `DS_KV_CLIENT_DELETE` | K_INVALID / K_NOT_FOUND / K_RPC_* |
| Expire | `DS_KV_CLIENT_EXPIRE` | K_INVALID / K_NOT_FOUND / K_RPC_* |
| QuerySize | `DS_KV_CLIENT_QUERY_SIZE` | K_INVALID / K_NOT_FOUND / K_RPC_* |
| Create+Set | `DS_KV_CLIENT_CREATE` / `DS_KV_CLIENT_SET` | K_INVALID / K_RPC_* / K_URMA_* |

### 调用链模式

与前述通用路径一致：
```
IsClientReady → 校验 → GetAvailableWorkerApi → workerApi->RPC → Worker 元数据 / 数据路径
```

### 故障域分类

| 操作 | 用户问题 | OS 问题 | URMA 问题 |
|------|---------|---------|----------|
| Del | 参数校验类 | 同 MGet | 不走 URMA |
| Expire | 参数校验类 | 同 MGet | 不走 URMA |
| QuerySize | 参数校验类 | 同 MGet | 不走 URMA |
| Create+Set | 参数校验类 | 同 MCreate/MPublish | 仅 Create+Set 走 URMA（同 MPublish 行） |

---

## 故障域分类汇总

### KVCache 接口故障域矩阵

| 接口 | 用户问题 | OS 问题 | URMA 问题 |
|-----|---------|---------|----------|
| Init | K_INVALID, K_NOT_READY | K_RPC_*, K_CLIENT_WORKER_DISCONNECT, K_MASTER_TIMEOUT | 不走 URMA |
| MCreate | K_INVALID, K_NOT_READY, K_OC_KEY_ALREADY_EXIST | K_RUNTIME_ERROR, K_OUT_OF_MEMORY, K_RPC_UNAVAILABLE | K_URMA_* |
| MPublish | K_INVALID, K_OC_ALREADY_SEALED | K_RUNTIME_ERROR, K_RPC_*, K_MASTER_TIMEOUT, K_WRITE_BACK_QUEUE_FULL | K_URMA_* |
| MGet | K_INVALID, K_NOT_FOUND | K_RPC_*, K_RUNTIME_ERROR, K_CLIENT_WORKER_DISCONNECT | K_URMA_* |
| Exist | K_INVALID, K_NOT_READY | K_RPC_*, K_MASTER_TIMEOUT, K_RUNTIME_ERROR | 不走 URMA |
| Del/Expire/QuerySize | K_INVALID, K_NOT_FOUND | K_RPC_* | 不走 URMA |
| Create+Set | K_INVALID | K_RPC_* | 同 MPublish |

### OS 层故障分类

| 故障类型 | 错误码 | 关键日志 |
|---------|--------|---------|
| 网络闪断 | K_RPC_UNAVAILABLE, K_RPC_DEADLINE_EXCEEDED | `RPC timeout` / `Connect reset` |
| mmap 失败 | K_RUNTIME_ERROR | `Get mmap entry failed` |
| 内存不足 | K_OUT_OF_MEMORY | `Failed to allocate memory buffer pool` |
| etcd 不可用 | K_MASTER_TIMEOUT | `etcd is timeout` / `Disconnected from remote node` |
| 磁盘满/IO错误 | K_IO_ERROR, K_NO_SPACE | `No space` / `K_IO_ERROR` |
| fd 不足 | K_FILE_LIMIT_REACHED | - |

### URMA 层故障分类

| 故障类型 | 错误码 | 关键日志 |
|---------|--------|---------|
| UB 初始化失败 | K_URMA_ERROR (1004) | `dlopen failed` / `UrmaManager initialization failed` |
| 连接需重建 | K_URMA_NEED_CONNECT (1006) | `[URMA_NEED_CONNECT] No existing connection` |
| 连接需重试 | K_URMA_TRY_AGAIN (1008) | `[URMA_TRY_AGAIN]` |
| JFS 重建 | K_URMA_ERROR (1004) | `[URMA_RECREATE_JFS] requestId=xxx, cqeStatus=9` |
| CQ poll 失败 | K_URMA_ERROR (1004) | `Failed to poll jfc` |
| UB 降级 TCP | 无上抛错误 | `fallback to TCP/IP payload` |
