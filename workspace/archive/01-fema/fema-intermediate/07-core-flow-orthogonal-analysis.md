# 核心流程 × 故障模式 正交分析

## 说明

本文档对 KVCache 数据系统的核心流程与故障模式进行正交分析，
确保每个核心流程的每个步骤都有对应的故障覆盖。

---

## 核心流程定义

根据 `observable-design/design.md` 和 `fault-tree-table.md`，KVCache 数据系统的核心流程包括：

1. **SDK Init 流程** - 客户端初始化与服务发现
2. **MCreate 流程** - 批量创建共享内存 buffer
3. **MPublish 流程** - 发布数据到缓存系统
4. **MGet 流程** - 批量获取数据（含远端拉取）
5. **Exist 流程** - 批量查询 key 是否存在
6. **远端读取流程** - Worker to Worker 数据拉取（URMA/TCP）
7. **组件生命周期流程** - Worker 心跳、扩缩容、故障检测

---

## 正交分析矩阵

### 流程 1: SDK Init 流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 1.1 | 配置解析 | ConnectOptions 未配置 host/port | K_INVALID (2) | 用户 | Validator::ValidateHostPortString | `ConnectOptions was not configured` |
| 1.2 | 服务发现 | SelectWorker 失败 | K_RPC_UNAVAILABLE (1002) | OS | ServiceDiscovery::SelectWorker | `Start to init worker client at address` |
| 1.3 | 证书加载 | AK/SK/Token 非法 | K_INVALID (2) | 用户 | RpcAuthKeyManager::CreateClientCredentials | - |
| 1.4 | 建链 | Brpc 连接失败 | K_RPC_UNAVAILABLE (1002) | OS | Channel.Init | - |
| 1.5 | 首心跳 | 首心跳超时 | K_CLIENT_WORKER_DISCONNECT (23) | OS | ListenWorker::StartListenWorker | `Cannot receive heartbeat from worker.` |
| 1.6 | etcd 连接 | Master 超时 | K_MASTER_TIMEOUT (25) | OS | etcd CM | `etcd is timeout` |

---

### 流程 2: MCreate 流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 2.1 | 参数校验 | keys 空/非法字符 | K_INVALID (2) | 用户 | CheckValidObjectKey | `The objectKey is empty` |
| 2.2 | 批量校验 | 批量超限 | K_INVALID (2) | 用户 | IsBatchSizeUnderLimit | `length of objectKeyList and dataSizeList should be the same` |
| 2.3 | SDK Ready | SDK 未 Init | K_NOT_READY (8) | 用户 | IsClientReady | - |
| 2.4 | RPC 调用 | Worker 不可达 | K_RPC_UNAVAILABLE (1002) | OS | GetAvailableWorkerApi | - |
| 2.5 | Worker 分配 | shm 池不足 | K_OUT_OF_MEMORY (6) | OS | Worker OC::MultiCreate | - |
| 2.6 | Worker 分配 | 对象已存在 | K_OC_KEY_ALREADY_EXIST (2004) | 用户 | Worker OC::MultiCreate | - |
| 2.7 | mmap 获取 | mmap entry 失败 | K_RUNTIME_ERROR (7) | OS | mmapManager_->LookupUnitsAndMmapFd | `Get mmap entry failed` |
| 2.8 | UB 注册 | urma_register_seg 失败 | K_URMA_ERROR (1004) | URMA | UB 驱动 | `[DRV_ERR]Failed to register seg` |

---

### 流程 3: MPublish 流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 3.1 | 参数校验 | buffer 为空/超限 | K_INVALID (2) | 用户 | IsBatchSizeUnderLimit | `The buffer should not be empty` |
| 3.2 | Seal 检查 | buffer 已 Publish | K_OC_ALREADY_SEALED (2000) | 用户 | Buffer::CheckDeprecated | `Client object is already sealed` |
| 3.3 | RPC 调用 | Worker/Master 不可达 | K_RPC_UNAVAILABLE (1002) | OS | workerApi->MultiPublish | - |
| 3.4 | RPC 调用 | RPC 超时 | K_RPC_DEADLINE_EXCEEDED (1001) | OS | workerApi->MultiPublish | `RPC timeout` |
| 3.5 | Master 元数据 | etcd 超时 | K_MASTER_TIMEOUT (25) | OS | CreateMultiMeta | `etcd is timeout` |
| 3.6 | 扩缩容 | K_SCALING | K_SCALING (32) | 组件 | Worker OC | `meta_is_moving = true` |
| 3.7 | 二级落盘 | 队列满 | K_WRITE_BACK_QUEUE_FULL (2003) | OS | WriteMode=WRITE_THROUGH | - |
| 3.8 | 二级落盘 | IO 错误 | K_IO_ERROR (7) | OS | 二级存储 | `K_IO_ERROR` |
| 3.9 | UB 传输 | UB 异常 | K_URMA_ERROR (1004) | URMA | fast_transport | - |

---

### 流程 4: MGet 流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 4.1 | 参数校验 | keys 空/超限 | K_INVALID (2) | 用户 | CheckValidObjectKey | `The objectKeys size exceed` |
| 4.2 | SDK Ready | SDK 未 Init | K_NOT_READY (8) | 用户 | IsClientReady | - |
| 4.3 | RPC 调用 | Worker 不可达 | K_RPC_UNAVAILABLE (1002) | OS | workerApi->MultiGet | - |
| 4.4 | RPC 调用 | RPC 超时 | K_RPC_DEADLINE_EXCEEDED (1001) | OS | workerApi->MultiGet | `RPC timeout` |
| 4.5 | L1 命中 | mmap 获取失败 | K_RUNTIME_ERROR (7) | OS | client mmap | `Get mmap entry failed` |
| 4.6 | L1 未命中 | 远端 Worker 不可达 | K_RPC_UNAVAILABLE (1002) | OS | PullObjectDataFromRemoteWorker | - |
| 4.7 | 远端拉取(UB) | UB 连接需重建 | K_URMA_NEED_CONNECT (1006) | URMA | CheckUrmaConnectionStable | `[URMA_NEED_CONNECT] Connection stale` |
| 4.8 | 远端拉取(UB) | JFS 重建 | K_URMA_ERROR (1004) | URMA | OnUrmaSendEvent | `[URMA_RECREATE_JFS]` |
| 4.9 | 远端拉取(UB) | UB 降级 TCP | 无上抛 | URMA | fast_transport | `fallback to TCP/IP payload` |
| 4.10 | L2 读取 | IO 错误 | K_IO_ERROR (7) | OS | Read L2 cache | `Read L2 cache failed` |
| 4.11 | L2 读取 | 数据不存在 | K_NOT_FOUND (3) | 用户 | Worker OC | - |
| 4.12 | 心跳检测 | Worker 退出 | K_SCALE_DOWN (31) | 组件 | HealthCheck | `[HealthCheck] Worker is exiting now` |

---

### 流程 5: Exist 流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 5.1 | 参数校验 | keys 空/超限 | K_INVALID (2) | 用户 | CheckValidObjectKeyVector | `The objectKeys size exceed` |
| 5.2 | SDK Ready | SDK 未 Init | K_NOT_READY (8) | 用户 | IsClientReady | - |
| 5.3 | RPC 调用 | Worker 不可达 | K_RPC_UNAVAILABLE (1002) | OS | workerApi->Exist | - |
| 5.4 | RPC 调用 | RPC 超时 | K_RPC_DEADLINE_EXCEEDED (1001) | OS | workerApi->Exist | - |
| 5.5 | etcd 查询 | Master 超时 | K_MASTER_TIMEOUT (25) | OS | etcd CM | `Disconnected from remote node` |
| 5.6 | 响应校验 | 大小不一致 | K_RUNTIME_ERROR (7) | OS | ObjectClientImpl::Exist | `Exist response size X is not equal to key size Y` |

---

### 流程 6: 远端读取流程（Worker to Worker）

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 6.1 | 连接检查 | 连接不存在 | K_URMA_NEED_CONNECT (1006) | URMA | CheckUrmaConnectionStable | `[URMA_NEED_CONNECT] No existing connection` |
| 6.2 | 连接检查 | 实例不匹配 | K_URMA_NEED_CONNECT (1006) | URMA | CheckUrmaConnectionStable | `[URMA_NEED_CONNECT] Connection stale` |
| 6.3 | JFS 事件 | cqeStatus=9 | K_URMA_ERROR (1004) | URMA | OnUrmaSendEvent | `[URMA_RECREATE_JFS] cqeStatus=9` |
| 6.4 | 重连 | 重连成功 | K_TRY_AGAIN (19) | URMA | TryReconnectRemoteWorker | `[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered` |
| 6.5 | 数据传输 | UB write 失败 | K_URMA_ERROR (1004) | URMA | urma_write | - |
| 6.6 | 数据传输 | TCP 降级 | 无上抛 | OS | fast_transport | `fallback to TCP/IP payload` |
| 6.7 | CQ poll | poll 失败 | K_URMA_ERROR (1004) | URMA | urma_poll_jfc | `Failed to poll jfc` |
| 6.8 | CQ wait | wait 超时 | K_URMA_ERROR (1004) | URMA | urma_wait_jfc | `Failed to wait jfc` |

---

### 流程 7: 组件生命周期流程

| 步骤 | 操作 | 故障模式 | 错误码 | 故障域 | 检测方法 | 定位日志 |
|-----|------|---------|--------|-------|---------|---------|
| 7.1 | 心跳检测 | socket fd 断开 | K_CLIENT_WORKER_DISCONNECT (23) | OS | ListenWorker | `The client detects that the worker is disconnected` |
| 7.2 | 心跳检测 | 首心跳超时 | K_CLIENT_WORKER_DISCONNECT (23) | OS | ListenWorker | `Cannot receive heartbeat from worker` |
| 7.3 | 心跳检测 | 心跳超时 | K_CLIENT_WORKER_DISCONNECT (23) | OS | CheckHeartbeat | `Heartbeat timeout, clientDeadTimeoutMs: xxx` |
| 7.4 | HealthCheck | Worker 退出中 | K_SCALE_DOWN (31) | 组件 | HealthCheck | `[HealthCheck] Worker is exiting now` |
| 7.5 | etcd 心跳 | 节点超时 | K_MASTER_TIMEOUT (25) | OS | etcd CM | `Disconnected from remote node xxx` |
| 7.6 | etcd 心跳 | etcd 超时 | K_RUNTIME_ERROR (7) | OS | replica_manager | `etcd is timeout` |
| 7.7 | 扩缩容 | meta_is_moving | K_SCALING (32) | 组件 | Worker OC | `meta_is_moving = true` |

---

## 故障模式 × 严酷度 分布

| 严酷度 | 定义 | 故障模式数量 | 占比 |
|-------|------|------------|------|
| **Ⅰ类（严重）** | 系统完全不可用，数据可能丢失 | 6 | 5.5% |
| **Ⅱ类（较严重）** | 系统部分功能不可用，业务中断 | 32 | 29.4% |
| **Ⅲ类（一般）** | 系统可降级运行 | 45 | 41.3% |
| **Ⅳ类（轻微）** | 非故障场景或轻微异常 | 26 | 23.8% |

---

## 故障域 × 严酷度 分布

| 故障域 | Ⅰ类 | Ⅱ类 | Ⅲ类 | Ⅳ类 | 小计 |
|-------|-----|-----|-----|-----|------|
| **用户问题** | 0 | 2 | 8 | 20 | 30 |
| **OS 问题** | 3 | 15 | 12 | 4 | 34 |
| **URMA 问题** | 1 | 8 | 18 | 2 | 29 |
| **组件问题** | 2 | 7 | 7 | 0 | 16 |
| **合计** | 6 | 32 | 45 | 26 | 109 |
