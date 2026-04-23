# FMEA 分析框架：边界与层次定义

## 1. 系统边界与组件层次

```
┌─────────────────────────────────────────────────────────┐
│                    用户层 (User)                         │
│         业务实例（精排/召排）调用 KVClient SDK            │
└────────────────────────┬────────────────────────────────┘
                         │ TCP/UDS + fd
┌────────────────────────▼────────────────────────────────┐
│                    KVC SDK 层                           │
│  KVClient → ObjectClientImpl → IClientWorkerApi          │
│  mmapManager / clientStateManager / AccessRecorder       │
└────────────────────────┬────────────────────────────────┘
                         │ TCP/ZMQ RPC 或 本机共享内存
┌────────────────────────▼────────────────────────────────┐
│                KVC Worker 层                             │
│  WorkerOCServiceImpl / WorkerWorkerOCServiceImpl        │
│  HealthCheck / HealthCheck / GetObjectRemote             │
└──────────┬─────────────────────────┬────────────────────┘
           │ URMA 数据面              │ RPC/ZMQ 控制面
┌──────────▼──────────┐  ┌───────────▼─────────────────────┐
│   UB 平面 (URMA)    │  │    OS 层 (TCP/ZMQ/socket)       │
│  UrmaManager        │  │  ZmqContext / ZmqStubConn      │
│  UrmaContext/JFC    │  │  unix_sock_fd / SCM_RIGHTS     │
│  JFS/JFR/JETTY      │  │  mmap / pread/pwrite           │
└─────────────────────┘  └──────────────┬──────────────────┘
                                       │ syscall
                    ┌──────────────────▼──────────────────┐
                    │           OS 基础设施               │
                    │  etcd / 分布式网盘 / 服务器硬件    │
                    └─────────────────────────────────────┘
```

## 2. 责任域划分

| 域 | 范围 | 典型故障 | 对应 StatusCode |
|----|------|---------|----------------|
| **User / 业务层** | 业务实例调用 SDK 参数/语义 | 入参非法、业务逻辑错误 | K_INVALID, K_NOT_FOUND |
| **OS 层** | socket/TCP/ZMQ/UDS/mmap/文件/sysmcall | 连接超时、fd 交换失败、磁盘 IO | 1001, 1002, 23, 29, 18 |
| **URMA 层** | UMDK / UB 数据面 / JFC/JFS/JFR | UB 写失败、连接重建、CQ 异常 | 1004, 1006, 1008 |
| **ETCD 层** | 控制面 / 路由 / 租约 | Master 超时、元数据不可用 | 25, 14 |
| **资源层** | 内存/磁盘/队列/线程池 | OOM、空间不足、FD 耗尽 | 6, 13, 18 |
| **组件层** | SDK/Worker 进程生命周期 | 进程退出/重启/挂死 | 22, 23, 31, 32 |

## 3. 三类接口的层次归属

| 流程 | 控制面 / RPC | OS / syscall | URMA / UMDK |
|------|-------------|---------------|--------------|
| **Init** | RegisterClient / Connect / GetSocketPath | socket/connect/recvmsg SCM_RIGHTS / mmap | ds_urma_init / create_context/jfc/jfs/jfr |
| **MCreate** | stub_->MCreate / ProcessMCreate | open/pwrite/fsync / sendmsg SCM_RIGHTS | ds_urma_write / poll_jfc |
| **MSet** | stub_->MultiPublish / RetryOnError | socket send/recv / mmap memcpy | UrmaWritePayload / ds_urma_write / poll_jfc |
| **MGet** | stub_->Get / RetryOnError / QueryMeta | socket send/recv / mmap / recvmsg | PrepareUrmaBuffer / ds_urma_read/write / poll_jfc |

## 4. 关键代码与故障映射

### 4.1 OS 层关键路径

| 文件 | 故障点 | 错误码 | 日志关键字 |
|------|--------|--------|-----------|
| `zmq_msg_queue.h::ClientReceiveMsg` | K_TRY_AGAIN 改写为 1002 | 1002 | `has not responded within allowed time` |
| `zmq_stub_conn.cpp` | 建连/等待/心跳 POLLOUT | 1002 | `Network unreachable` / `timeout waiting for SockConnEntry` |
| `unix_sock_fd.cpp::ErrnoToStatus` | ECONNRESET/EPIPE | 1002 | `Connect reset` |
| `client_worker_common_api.cpp` | mustUds && !isConnectSuccess | 1002 | `shm fd transfer` |
| `listen_worker.cpp` | 首次心跳超时 | 23 | `Cannot receive heartbeat` |
| `file_util.cpp::pread/pwrite` | IO 错误 | 7 | `K_IO_ERROR` |
| `worker_oc_spill.cpp` | spill 空间不足 | 13 | `No space` |

### 4.2 URMA 层关键路径

| 文件 | 故障点 | 错误码 | 日志关键字 |
|------|--------|--------|-----------|
| `urma_manager.cpp::CheckUrmaConnectionStable` | 连接不稳/实例不匹配 | 1006 | `URMA_NEED_CONNECT` / `remoteInstanceId` |
| `urma_manager.cpp` | URMA 初始化失败 | 1004 | `Failed to urma init` / `create context` |
| `urma_manager.cpp` | JFS 重建 | 1004/1008 | `URMA_RECREATE_JFS` |
| `urma_manager.cpp` | CQ poll/wait/rearm | 1004 | `Failed to wait jfc` / `poll jfc` |
| `worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker` | 1006 → 重连 → TRY_AGAIN | 1008 | `Reconnect success` |

### 4.3 etcd 层关键路径

| 文件 | 故障点 | 错误码 | 日志关键字 |
|------|--------|--------|-----------|
| `etcd_cluster_manager.cpp` | 节点连接/超时 | 25 | `Disconnected from remote node` / `K_MASTER_TIMEOUT` |
| `worker_oc_service_get_impl.cpp` | IsKeepAliveTimeout | 1002 | `etcd is unavailable` |

### 4.4 组件生命周期

| 文件 | 故障点 | 错误码 | 日志关键字 |
|------|--------|--------|-----------|
| `worker_oc_service_impl.cpp::HealthCheck` | CheckLocalNodeIsExiting | 31 | `Worker is exiting now` |
| `worker_oc_service_multi_publish_impl.cpp` | meta_is_moving | 32 | `The cluster is scaling` |
| `listen_worker.cpp` | 首次心跳超时 | 23 | `Cannot receive heartbeat from worker` |

## 5. FM-xxx 故障模式 → 边界映射表

| FM编号 | 故障模式 | 边界域 | StatusCode | 关键日志 |
|--------|----------|--------|-----------|---------|
| FM-001 | Init Register/ZMQ 不可达 | OS | 1001/1002 | `Register client failed` |
| FM-002 | RPC 半开连接抖动 | OS | 1002/19 | `try again` / `timeout` |
| FM-003 | UB 初始化失败 | URMA | 1004 | `Failed to urma init` |
| FM-004 | 客户端 UB 匿名内存池 mmap 失败 | OS | 6 | `K_OUT_OF_MEMORY` |
| FM-005 | FastTransport/import jfr 失败 | URMA | 1004 | `Fast transport handshake failed` |
| FM-006 | SCM_RIGHTS fd 传递异常 | OS | 5/10 | `invalid fd` / `Unexpected EOF` |
| FM-007 | Get 请求未达/ZMQ 超时 | OS | 1001/1002/19 | `Start to send rpc to get object` |
| FM-008 | Directory QueryMeta 失败 | OS | 5 | `Query from master failed` |
| FM-009 | W1→W3 拉对象数据失败 | OS | 依封装 | `Get from remote failed` |
| FM-010 | UB write/read 失败 | URMA | 5/1004 | `Failed to urma write/read` |
| FM-011 | CQ poll/wait/rearm 失败 | URMA | 1004 | `Failed to wait jfc` |
| FM-012 | UB 连接需重建 | URMA | 1006 | `URMA_NEED_CONNECT` |
| FM-013 | JFS 重建策略 | URMA | 1004/1008 | `URMA_RECREATE_JFS` |
| FM-014 | UB Get buffer 降级 TCP | NEITHER | 无上抛 | `fallback to TCP/IP payload` |
| FM-015 | UB payload 尺寸不一致 | NEITHER | 依封装 | `UB payload overflow` |
| FM-016 | 客户端 SHM mmap 失败 | OS | 依 ToString | `Get mmap entry failed` |
| FM-017 | 对象不存在 | NEITHER | 3 | `K_NOT_FOUND` |
| FM-018 | etcd 不可用 | OS(etcd) | 1002等 | `etcd is unavailable` |
| FM-019 | Publish/MultiPublish 超时 | OS | 1001/1002/19 | `Start to send rpc to publish object` |
| FM-020 | UB 直发失败 | URMA | 依封装 | `Failed to send buffer via UB` |
| FM-021 | 扩缩容/内存策略拒绝 | NEITHER | 32/6 | `K_SCALING` |
| FM-022 | 入参非法 | NEITHER | 2 | `Invalid` |
| FM-023 | 业务 last_rc 部分 key 重试 | NEITHER | 混合 | `last_rc` |
