# 01 · 架构与读写路径

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/client/kv_cache/kv_client.cpp` | `KVClient` 对外 API（Init / MGet / MSet / MCreate / Publish） |
| `src/datasystem/client/object_cache/object_client_impl.cpp` | 核心实现，承载重试与错误传递 |
| `src/datasystem/client/client_worker_common_api.cpp` | Client ↔ Worker 注册 / 心跳 / fd 交换 |
| `src/datasystem/client/listen_worker.cpp` | Client 侧心跳监听 |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | Worker 端 Client RPC 服务（含 `HealthCheck`） |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | Worker ↔ Worker 远端读、URMA 写 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 连接与会话 |

---

## 1. 组件与调用链

典型部署：

```text
业务请求处理实例（集成 KVC SDK）── TCP / UDS + fd ──▶ 本机 KVC Worker
                                                         │
                                                         │ ZMQ/TCP（RPC）
                                                         │ URMA（数据面零拷贝）
                                                         ▼
                                                   其它 KVC Worker
```

| 组件 | 职责 | 失败时典型现象 |
|------|------|----------------|
| **业务请求处理实例** | 调用 `KVClient` API（精排 / 召排） | 精排：E2E 失败；召排：TP99 拉高 |
| **KVC SDK** | 参数校验、重试、心跳、fd 交换、共享内存 mmap | `StatusCode` 返回给业务 |
| **本机 Worker** | 接收 RPC，本地缓存命中直接走 SHM；未命中跨机拉取 | 31/32、1001/1002 |
| **远端 Worker** | 持有主副本，URMA 写回到请求端 SHM | 1004 / 1006 / 1008 |
| **etcd** | 控制面：节点成员、hash ring、租约 | 25（`K_MASTER_TIMEOUT`） |

> 业务类型影响 SLI 口径：**精排**对成功率敏感（读失败直接 E2E 失败），**召排**对尾延迟敏感（失败子路径拉高 TP99）。同一基础设施故障在两条业务线上现象不同，DryRun 记录必须写明业务线。

---

## 2. 关键读写路径

时序图：

- 正常：[`../flows/sequences/kv-client/kv_client_read_path_normal_sequence.puml`](../flows/sequences/kv-client/kv_client_read_path_normal_sequence.puml)
- 切流：[`../flows/sequences/kv-client/kv_client_read_path_switch_worker_sequence.puml`](../flows/sequences/kv-client/kv_client_read_path_switch_worker_sequence.puml)

### 2.1 正常远端读（6 步）

| 步骤 | 路径 | 备注 |
|-----|------|------|
| 1 | client → worker1（本机 TCP/UDS） | 不涉及 TCP 网卡；失败 → 1002（多为 fd 交换类） |
| 2 | worker1 → worker2（跨机 TCP，元数据访问） | Master/Meta 路径；失败 → 1001/1002/25 |
| 3 | worker1 → worker3（跨机 TCP，触发数据拉取） | `GetObjectRemote` 发起 |
| 4 | worker3 → worker1（跨机 URMA write） | `UrmaWritePayload`；失败 → 1004/1006/1008 |
| 5 | worker3 → worker1（跨机 TCP，get resp） | 失败时应携带 worker3 的 IP:Port，便于定位 |
| 6 | worker1 → client（本地 SHM，返回偏移） | 成功返回对象引用 |

### 2.2 SDK 切流（Client 连新 Worker）

触发：本机 Worker 故障 / 心跳超时（约 2s）。切流后跨机跳数增加，超时预算更紧：

| 步骤 | 路径 |
|-----|------|
| 1 | client → worker2（跨机 TCP） |
| 2 | worker2 → worker3（跨机 TCP，元数据） |
| 3 | worker2 → worker4（跨机 TCP，触发数据拉取） |
| 4 | worker4 → worker2（跨机 URMA write） |
| 5 | worker4 → worker2（跨机 TCP，get resp） |
| 6 | worker2 → client（本地 SHM） |

---

## 3. 建链：TCP + fd + 共享内存

本机 Client 与 Worker 之间的 **SHM 免拷贝**依赖一条"TCP（或 UDS）控制通道 + fd 传递 + mmap"链路：

```text
Register / 建连 / 必须 UDS 路径         [client_worker_common_api.cpp]
    → CreateConnectionForTransferShmFd
    → GetClientFd + Mmap                [mmap_manager.cpp]
    → 后续 KV/Object 访问走本地 SHM 偏移
```

失败点与错误码落在 **RPC/连接类**（见 03-status-codes § 3.3），不是 URMA 三码：

- 强制 SHM 却建连失败 → 1002（文案含 `shm fd transfer`）
- 服务端 fd 已关闭 → 29（`K_SERVER_FD_CLOSED`）
- FD 耗尽 → 18（`K_FILE_LIMIT_REACHED`）
- 首次心跳超时 → 23（`K_CLIENT_WORKER_DISCONNECT`）

---

## 4. 数据面：URMA 与 RPC 的分工

| 层级 | 作用 | 关键码域 |
|------|------|----------|
| RPC（TCP/ZMQ） | 传 `GetObjectRemote` meta、必要时 payload（`DATA_IN_PAYLOAD`） | 1000 / 1001 / 1002 |
| URMA 数据面 | `UrmaWritePayload` + JFC 完成事件；成功 `DATA_ALREADY_TRANSFERRED` | 1004 / 1006 / 1008 |

**fd+SHM** 解决的是"本机 Client 与本机 Worker 之间的映射与句柄"；**跨机大块数据**在 UB 开启时走 **URMA 写**。一次远端读将两者 **串联**：先 RPC 元数据 → URMA 写对端 SHM → RPC 回包。

---

## 5. 下一步

- 想知道各种故障对应的现象 → [02-failure-modes-and-sli.md](02-failure-modes-and-sli.md)
- 想把现象落到错误码 → [03-status-codes.md](03-status-codes.md)
- 想从错误码定位到根因 → [04-fault-tree.md](04-fault-tree.md)
