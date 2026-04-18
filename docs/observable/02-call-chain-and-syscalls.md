# 02 · 调用链与系统调用（Init / MCreate / MSet / MGet）

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/client/kv_cache/kv_client.cpp` | `KVClient` 对外 API |
| `src/datasystem/client/object_cache/object_client_impl.cpp` | 核心实现 |
| `src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp` | 客户端 RPC stub + `RetryOnError` |
| `src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp` | `PrepareUrmaBuffer` / `FillUrmaBuffer` / `PreGet` |
| `src/datasystem/client/client_worker_common_api.cpp` | `Connect` / `RegisterClient` / fd 交换 |
| `src/datasystem/client/listen_worker.cpp` | 心跳与 Worker 可用性检测 |
| `src/datasystem/client/mmap_manager.cpp` | `LookupUnitsAndMmapFd` / `MmapShmUnit` |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 接口封装 |
| `src/datasystem/common/rdma/urma_resource.cpp` | URMA context/jfc/jfs/jfr 创建 |
| `src/datasystem/common/util/fd_pass.cpp` | `sendmsg/recvmsg(SCM_RIGHTS)` |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | Worker Client RPC |
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | Worker Get 实现 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker↔Worker 远端读、URMA 写 |

---

## 0. 角色约定

| 代号 | 含义 |
|------|------|
| **client** | SDK 进程（`KVClient` / `ObjectClientImpl` / `ClientWorkerRemoteApi`） |
| **worker1** | 入口 Object Cache Worker（与 client 建 ZMQ 会话） |
| **worker2** | Directory Worker（对象目录 hash ring 分片，`QueryMeta` RPC 对端） |
| **worker3** | 数据副本 Worker（跨节点 UB 数据面对端） |

---

## 1. Init 接口

### 1.1 SDK 侧

```text
KVClient::Init
  └─ ObjectClientImpl::Init
      ├─ ValidateHostPortString                          [纯校验，无 I/O]
      ├─ RpcAuthKeyManager::CreateClientCredentials      [AKSK，无 I/O]
      └─ InitClientWorkerConnect
          └─ ClientWorkerRemoteApi::Init
              └─ Connect
                  ├─ CreateConnectionForTransferShmFd
                  │   ├─ GetSocketPath                   [ZMQ RPC → worker1]
                  │   └─ CreateHandShakeFunc             [OS: socket → connect（UDS/TCP）]
                  ├─ RegisterClient                      [ZMQ RPC → worker1]
                  └─ PostRegisterClient
                      └─ FastTransportHandshake          [URMA 握手；失败 LOG_IF_ERROR 不阻断]
                          ├─ UrmaManager::UrmaInit       [URMA: ds_urma_register_log_func → ds_urma_init]
                          ├─ UrmaGetEffectiveDevice      [URMA: ds_urma_get_device_list → ds_urma_get_device_by_name]
                          ├─ GetEidIndex                 [URMA: ds_urma_get_eid_list → ds_urma_free_eid_list]
                          ├─ UrmaResource::Create        [URMA: ds_urma_create_context → jfce → jfc → jfs → jfr]
                          ├─ InitMemoryBufferPool        [OS: mmap(MAP_PRIVATE|MAP_ANONYMOUS)]
                          └─ ExchangeJfr                 [URMA: ds_urma_import_jfr → ds_urma_advise_jfr]
          [并行] RecvPageFd 线程                          [OS: recvmsg(SCM_RIGHTS) 循环收 fd]
          MmapManager / InitListenWorker / 心跳线程       [OS: mmap；ZMQ 心跳]
```

### 1.2 Worker 侧（worker1）

收到 `RegisterClient` RPC 后：

- 分配 client 资源（client id、心跳参数、SHM 阈值）
- 通过 UDS 发送 fd：**OS: `sendmsg(SCM_RIGHTS)`**
- UB 信息交换：URMA `ExchangeJfr` 对端处理

---

## 2. MCreate 接口

### 2.1 SDK 侧

```text
ObjectClientImpl::MultiCreate
  ├─ IsClientReady()
  ├─ ConstructMultiCreateParam                           [key/size 组装]
  ├─ GetAvailableWorkerApi                               [注意：始终走 LOCAL_WORKER]
  └─ workerApi_[LOCAL_WORKER]->MultiCreate
      ├─ MultiCreateReqPb + SetTokenAndTenantId
      ├─ RetryOnError → stub_->MultiCreate                [ZMQ RPC → worker1]
      └─ PostMultiCreate                                  [回填 shmBuf / urmaDataInfo]
  └─ [useShmTransfer] MultiCreateParallel
      ├─ SHM: mmapManager_->LookupUnitsAndMmapFd          [OS: mmap(store_fd)]
      └─ UB: ubUrmaDataInfo 分支
```

### 2.2 Worker 侧（worker1）

- `ProcessMCreate` → 按条件分配 SHM/UB 空间
- 若落盘：**OS: `open → pwrite → fsync`**
- fd 传输：**OS: `sendmsg(SCM_RIGHTS)`**

---

## 3. MSet 接口

### 3.1 SDK 侧

```text
ObjectClientImpl::MSet(buffers)
  ├─ batch 上限 + IsClientReady()
  ├─ GetAvailableWorkerApi
  ├─ 各 buffer: CheckDeprecated; seal → K_OC_ALREADY_SEALED
  ├─ 组装 PublishParam / bufferInfoList
  └─ workerApi->MultiPublish
      ├─ MultiPublishReqPb + payload 组装
      ├─ RetryOnError → stub_->MultiPublish              [ZMQ RPC → worker1]
      │   重试码: K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED,
      │           K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY, K_SCALING
      └─ [可选] SendBufferViaUb → UrmaWritePayload        [URMA: ds_urma_write]
  └─ HandleShmRefCountAfterMultiPublish
```

### 3.2 Worker 侧

```text
worker1: MultiPublish 处理
  ├─ Directory 提交 (worker1→worker2)                    [RPC]
  └─ 数据面 UB 写 (worker1→worker3)
      └─ UrmaWritePayload
          ├─ ds_urma_write                                [URMA]
          └─ ds_urma_poll_jfc / ds_urma_wait_jfc          [URMA]
```

---

## 4. MGet 接口（含 UB 与 fallback）

### 4.1 SDK 侧

```text
ObjectClientImpl::Get(objectKeys, subTimeoutMs, buffers)
  ├─ 校验 + GetAvailableWorkerApi
  └─ GetBuffersFromWorker
      └─ ClientWorkerRemoteApi::Get
          ├─ PreGet
          ├─ [USE_URMA && !shmEnabled_] PrepareUrmaBuffer  [URMA 缓冲池]
          │   失败 → WARNING + fallback TCP payload        [不抛 URMA 码]
          ├─ RetryOnError → stub_->Get                     [ZMQ RPC → worker1]
          │   lambda: last_rc 为 timeout/try_again/OOM+全失败 → 重试
          └─ FillUrmaBuffer                                [URMA: UB 回填；OS: mmap]
  └─ ProcessGetResponse → 各 key 的 Buffer / failed keys
```

### 4.2 Worker 侧

```text
worker1: WorkerOcServiceGetImpl::Get
  ├─ (W1-A) TryGetObjectFromLocal                         [本地缓存命中]
  │
  ├─ (W1→W2) QueryMetadataFromMaster → Directory Worker   [RPC]
  │   └─ workerMasterApi->QueryMeta
  │       成功: QueryMetaInfoPb（含副本 address）
  │       失败: 日志原文 "Query from master failed"
  │
  └─ (W1→W3) GetObjectsFromAnywhere                       [远端数据拉取]
      └─ GetObjectFromAnywhereWithLock
          ├─ workerStub->GetObjectRemote → clientApi       [W↔W RPC]
          ├─ worker3: CheckConnectionStable                [URMA: CheckUrmaConnectionStable]
          ├─ worker3: UrmaWritePayload                     [URMA: ds_urma_write / ds_urma_read]
          │   └─ rsp.data_source = DATA_ALREADY_TRANSFERRED
          └─ worker1: PollJfcWait                          [URMA: ds_urma_wait_jfc / poll_jfc / ack_jfc / rearm_jfc]
              ├─ [event mode] ds_urma_wait_jfc → ds_urma_poll_jfc → ds_urma_ack_jfc → ds_urma_rearm_jfc
              └─ [poll mode] 循环 ds_urma_poll_jfc + usleep(0)
  └─ ReturnToClient → last_rc + Write + SendPayload → 回到 client
```

### 4.3 MGet 请求的 6 步（与 reliability 对应）

reliability/01 定义的正常远端读 6 步：

| 步骤 | 路径 | 本文对应 |
|-----|------|----------|
| 1 | client → worker1（本机 TCP/UDS）| § 4.1 `stub_->Get` |
| 2 | worker1 → worker2（跨机 TCP，元数据）| § 4.2 QueryMeta |
| 3 | worker1 → worker3（跨机 TCP，数据触发）| § 4.2 GetObjectRemote |
| 4 | worker3 → worker1（URMA write）| § 4.2 UrmaWritePayload |
| 5 | worker3 → worker1（TCP get resp）| § 4.2 ReturnToClient |
| 6 | worker1 → client（本地 SHM）| § 4.1 FillUrmaBuffer / mmap |

---

## 5. URMA 接口全量清单

来自 `urma_manager.cpp` 直接调用（经 `urma_dlopen_util.cpp` 动态绑定 UMDK `urma_*`）：

| 分类 | 接口 |
|------|------|
| 生命周期 | `urma_init`, `urma_uninit`, `urma_register_log_func`, `urma_unregister_log_func` |
| 设备发现 | `urma_get_device_list`, `urma_get_device_by_name`, `urma_query_device` |
| EID | `urma_get_eid_list`, `urma_free_eid_list` |
| 上下文 | `urma_create_context`, `urma_delete_context` |
| 完成队列 | `urma_create_jfce`, `urma_delete_jfce`, `urma_create_jfc`, `urma_delete_jfc`, `urma_rearm_jfc` |
| 发送/接收 | `urma_create_jfs`, `urma_delete_jfs`, `urma_create_jfr`, `urma_delete_jfr` |
| 内存注册 | `urma_register_seg`, `urma_unregister_seg`, `urma_import_seg`, `urma_unimport_seg` |
| JFR 导入 | `urma_import_jfr`, `urma_unimport_jfr`, `urma_advise_jfr` |
| 数据操作 | `urma_write`, `urma_read`, `urma_post_jfs_wr` |
| 完成处理 | `urma_wait_jfc`, `urma_poll_jfc`, `urma_ack_jfc` |

URMA 枚举与错误日志证据：[`06-dependencies/urma.md`](06-dependencies/urma.md)。

---

## 6. OS / syscall 全量清单

| syscall / OS 接口 | 主要位置 | 关联流程 |
|------------------|----------|----------|
| `sendmsg` / `recvmsg` | `common/util/fd_pass.cpp` | Init UDS 传 fd、读路径 SHM 回数 |
| `close` | `fd_pass.cpp`; `client_worker_common_api.cpp` | fd 生命周期 |
| `mmap` / `munmap` | `urma_manager.cpp`; `object_client_impl.cpp` | UB 缓冲池、SHM 映射 |
| `socket` / `connect` | `client_worker_common_api.cpp` | Init 建连 |
| `usleep(0)` | `urma_manager.cpp::PollJfcWait` | URMA poll 等待（让出 CPU） |
| `memcpy` | `client_worker_base_api.cpp`; `object_client_impl.cpp` | payload / UB 组装 |
| `open` / `pwrite` / `fsync` | Worker 侧落盘路径 | MCreate 持久化 |

OS 失败语义与错误映射：[`06-dependencies/os-syscalls.md`](06-dependencies/os-syscalls.md)。

---

## 7. 调用链行模板（Excel Sheet1 对照）

Sheet1 第二列的"正向调用树"写法，示例（MGet 最长路径）：

```text
[root] ObjectClientImpl::Get
  └─ GetAvailableWorkerApi
  └─ GetBuffersFromWorker
     └─ ClientWorkerRemoteApi::Get
        └─ PreGet
        └─ PrepareUrmaBuffer        [URMA: GetMemoryBufferHandle]
        └─ RetryOnError → stub_->Get
           └─ [worker1] WorkerOcServiceGetImpl::Get
              └─ TryGetObjectFromLocal
              └─ QueryMetadataFromMaster   [worker1→worker2 RPC]
              └─ GetObjectFromAnywhere
                 └─ workerStub->GetObjectRemote
                    └─ [worker3] UrmaWritePayload  [URMA: ds_urma_write]
                    └─ [worker1] PollJfcWait       [URMA: ds_urma_wait_jfc]
              └─ ReturnToClient
        └─ FillUrmaBuffer            [URMA: UB 回填；OS: mmap]
```

完整的 Sheet 对照稿：[`workbook/sheet1-call-chain.md`](workbook/sheet1-call-chain.md)。

---

## 8. `K_RUNTIME_ERROR` 与 `K_RPC_UNAVAILABLE` 的触发时机

`KVClient` 基本不改写这两个错误码，主要由 `ObjectClientImpl` / `ClientWorkerRemoteApi` / Worker 服务侧生成后透传。

### 8.1 触发路径速查

| 接口阶段 | 触发条件 | 返回码 | 关键位置 |
|---------|---------|-------|---------|
| 前置选路 | worker 断连（`workerAvailable_ == false`）| `K_RPC_UNAVAILABLE` | `listen_worker.cpp::CheckWorkerAvailable` |
| 选路内部状态 | `listenWorker_` 容器异常/空指针 | `K_RUNTIME_ERROR` | `object_client_impl.cpp::CheckConnection` |
| 控制面 RPC 超时/不可达 | `stub_->Get` / `MultiCreate` / `MultiPublish` 重试耗尽 | `K_RPC_UNAVAILABLE` | `client_worker_remote_api.cpp`（`RETRY_ERROR_CODE`） |
| ZMQ 阻塞收包 `K_TRY_AGAIN` 被改写 | 阻塞模式 | `K_RPC_UNAVAILABLE` | `common/rpc/zmq/zmq_msg_queue.h::ClientReceiveMsg` |
| Worker 非 RPC 错误聚合 | 多次失败后封装 | `K_RUNTIME_ERROR` | `worker_oc_service_get_impl.cpp::CheckAndResetStatus` |
| Worker 查元数据失败 | `QueryMetadataFromMaster` 失败 | `K_RUNTIME_ERROR` | `worker_oc_service_get_impl.cpp`（`"Query from master failed"`） |
| client 汇总响应 | 全 key 失败返回 `rsp.last_rc` | 透传 | `object_client_impl.cpp::GetBuffersFromWorker` |

### 8.2 判别建议

| 返回码 | 更可能的边界 | 首查点 |
|-------|-------------|-------|
| `K_RPC_UNAVAILABLE` | client ↔ worker / worker ↔ 上游的网络可达性、RPC 通道 | `CheckWorkerAvailable`、`ClientReceiveMsg`、`RetryOnError` |
| `K_RUNTIME_ERROR` | 业务 / 流程内部状态异常、数据一致性 / 映射异常、worker 统一封装 | `worker_oc_service_get_impl.cpp` 的封装点、`object_client_impl.cpp::CheckConnection` |

1002 的桶码分流详见 [`../reliability/06-playbook.md § 2`](../reliability/06-playbook.md)；URMA 三码参见 [`../reliability/04-fault-tree.md § 2.2`](../reliability/04-fault-tree.md)。
