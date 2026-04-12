# openYuanrong DataSystem：故障码树状梳理（底层→上层）

本文从**底层到上层**梳理客户端可见 `StatusCode` 与典型故障表现，**重点覆盖 URMA（UB）数据面**，以及 **基于 TCP 控制通道完成 fd 交换、建立本地共享内存（SHM）访问**的路径。  
权威枚举见 `yuanrong-datasystem` 仓库：`include/datasystem/utils/status.h`；默认文案见 `src/datasystem/common/util/status_code.def`。

---

## 1. 分层总览（树状）

说明：**下层故障往往被上层归类或透传**；同一数值可能对应多类根因，需结合 `respMsg`、日志与路径（是否走 UB、是否已 mmap SHM）定界。

```text
[L5 应用 / 集成 / 业务语义]
    K_INVALID, K_NOT_FOUND, K_DUPLICATED, K_RUNTIME_ERROR, K_NOT_AUTHORIZED …
    K_NOT_FOUND_IN_L2CACHE, K_LRU_* …
        ↑
[L4 Object / KV 业务与 Worker 侧语义]
    K_OC_*（如 K_OC_REMOTE_GET_NOT_ENOUGH=2002）、K_WRITE_BACK_QUEUE_FULL …
    Worker 返回的 last_rc（批量路径可能与顶层 Status 不一致）
        ↑
[L3 Client↔Worker：连接、心跳、版本、缩容]
    K_NOT_READY, K_CLIENT_WORKER_DISCONNECT, K_SHUTTING_DOWN
    K_CLIENT_WORKER_VERSION_MISMATCH, K_SCALE_DOWN, K_SCALING, K_RETRY_IF_LEAVING
    K_MASTER_TIMEOUT, K_NOT_LEADER_MASTER …
        ↑
[L2 RPC 控制面：ZMQ/TCP 上的请求/响应/超时/通道状态]
    K_RPC_CANCELLED(1000), K_RPC_DEADLINE_EXCEEDED(1001), K_RPC_UNAVAILABLE(1002)
    （与 URMA 码并存时需区分「消息通道」vs「UB 数据写」）
        ↑
[L1 URMA / UB 数据面：跨节点零拷贝写、会话、JFC 完成]
    K_URMA_ERROR(1004), K_RDMA_ERROR(1005), K_URMA_NEED_CONNECT(1006)
    K_RDMA_NEED_CONNECT(1007), K_URMA_TRY_AGAIN(1008)
        ↑
[L0 基础设施：UB 平面、驱动、Jetty、主机资源]
    （通常不直接以 StatusCode 暴露；通过 L1/L2 间接体现）
```

---

## 2. 重点路径 A：URMA 数据传输（Worker↔Worker / Worker→Client UB 写）

### 2.1 逻辑位置（数据面 vs RPC 面）

| 层级 | 作用 | 与码的关系 |
|------|------|------------|
| **RPC（TCP/ZMQ）** | 传 `GetObjectRemote` 请求/响应 meta、必要时 **DATA_IN_PAYLOAD** 走 TCP payload | 失败多见 **1001/1002/1000**；**不等价**于 UB 坏了 |
| **URMA 数据面** | `UrmaWritePayload`、JFC/PollJfc、`WaitFastTransportEvent`；成功时常 **DATA_ALREADY_TRANSFERRED**（数据已进对端 SHM） | 失败多见 **1004/1006/1008** |

**区分要点**（与运维文档一致）：**URMA 瞬时/可恢复**优先看 **1008**、需重建会话看 **1006**、持久/语义失败看 **1004**；若仅见 **1002**，多属 **RPC 等回复/建连/网关** 类，**不能**默认归因 UB。

### 2.2 URMA 相关码（挂在 L1）

| 码 | 枚举 | 典型含义（排障视角） |
|----|------|----------------------|
| 1004 | `K_URMA_ERROR` | UB/URMA 数据路径错误（驱动、资源、语义失败等，依实现分支） |
| 1006 | `K_URMA_NEED_CONNECT` | 会话需重建；常与 `TryReconnectRemoteWorker`、transport exchange 后再 **K_TRY_AGAIN** 重试整次 RPC |
| 1008 | `K_URMA_TRY_AGAIN` | 可重试的瞬时失败（如 JFS 重建等策略）；batch 路径可能有专门捕获 |
| 1005/1007 | `K_RDMA_*` | RDMA 变体路径（若启用） |

### 2.3 与 Object 语义码的交界（L4）

- **`K_OC_REMOTE_GET_NOT_ENOUGH` (2002)**：远端对象大小变化等，**可能不发起 URMA 写**，按新 `data_size` 重试。
- **RPC 重试集合**（如 `client_worker_remote_api`）常包含 `K_TRY_AGAIN`、`K_RPC_*`，**整次 RPC 重发**；与 **L1** 的 URMA 重试策略叠加时需看超时预算（如 20ms 与 poll jfc ~100ms 量级的矛盾，见 `remote-get-tcp-fallback-urma-retry-polljfc.md`）。

### 2.4 树状展开（仅 URMA 子树）

```text
K_URMA_ERROR / NEED_CONNECT / TRY_AGAIN
├── 连接与会话
│   └── K_URMA_NEED_CONNECT → 重建 URMA/transport → 外层 RetryOnError → 常转 K_TRY_AGAIN 再试
├── 完成路径
│   ├── ServerEventHandleThreadMain：PollJfcWait / ds_urma_wait_jfc
│   └── 失败 → HandleUrmaEvent / RECREATE_JFS 等 → 可能 K_URMA_TRY_AGAIN
└── 与 RPC 超时
    ├── 业务 deadline 先耗尽 → K_RPC_DEADLINE_EXCEEDED / K_TRY_AGAIN / 映射后的 K_RPC_UNAVAILABLE
    └── 根因可能在 UB，但**客户端先看到**的是 RPC 层码 → 需对照 Worker URMA 日志
```

---

## 3. 重点路径 B：TCP 控制面 + fd 交换 → 共享内存（Client↔Worker）

本地 **免拷贝读写的 SHM** 依赖：在 **TCP（及配套 UDS）控制通道**上完成 **fd 传递**，再 **mmap** 映射到进程地址空间。该路径上的失败多落在 **RPC/连接类码**，而不是 L1 的 URMA 三码。

### 3.1 逻辑链

```text
Register / 建连 / 必须 UDS 路径
    → GetClientFd + Mmap（mmap 共享段）
    → 后续 KV/Object 访问走本地 SHM 偏移
```

### 3.2 典型 `StatusCode`（挂在 L2/L3）

| 码 | 枚举 | 与「TCP + fd + SHM」的关系 |
|----|------|---------------------------|
| 1002 | `K_RPC_UNAVAILABLE` | **强制 SHM/fd 传输**却建连失败时，可出现文案 **`Can not create connection to worker for shm fd transfer`**；另含 ZMQ 等回复超时、建连超时、`UnixSockFd` reset 等（**桶码**） |
| 29 | `K_SERVER_FD_CLOSED` | 服务端已关闭传递的 fd，本地 mmap 会话失效 |
| 18 | `K_FILE_LIMIT_REACHED` | FD 耗尽等，影响 fd 接收与连接复用 |
| 8 | `K_NOT_READY` | 未完成初始化/记录器未就绪，SHM 路径未就绪 |

### 3.3 树状展开（fd/SHM 子树）

```text
共享内存访问路径
├── 控制通道正常（TCP/ZMQ/UDS）
│   ├── fd 交换成功 → mmap → 本地读写
│   └── 失败 → K_RPC_UNAVAILABLE（含 shm fd transfer 文案）/ Connect reset …
├── 对端生命周期
│   └── Worker 退出/缩容 → K_CLIENT_WORKER_DISCONNECT / K_SCALE_DOWN / K_RETRY_IF_LEAVING …
└── 资源
    └── K_FILE_LIMIT_REACHED / K_OUT_OF_MEMORY / K_NO_SPACE …
```

**与 URMA 路径的边界**：**fd+SHM** 解决的是 **本机 Client 与本地 Worker** 之间的 **映射与句柄**；**跨机大块数据**在 UB 开启时常走 **URMA 写**（L1），二者 **串联**于一次远端读：先 **RPC 元数据**，再 **URMA 写对端 SHM**，最后 **RPC 回包**；见 `00-kv-client-fema-read-paths-reliability.md` 步骤 4～6 与 `remote-get-ub-urma-flow.md`。

---

## 4. 合并视图：一次「远端 Get + UB」上的码从哪一层来

（概念顺序，非严格调用栈）

| 阶段 | 主要机制 | 常见码域 |
|------|----------|----------|
| Client 与本地 Worker 建立 SHM | TCP/UDS + fd | 1002、29、8、18 |
| Client↔Worker RPC（元数据/控制） | ZMQ/TCP | 1001、1002、1000、23 |
| Worker↔Worker 拉数 | URMA 写 + RPC meta/payload | **1004/1006/1008**、2002、1001/1002 |
| Master/etcd | 元数据与控制面 | 25、14、19 … |

---

## 5. 实操定界（最短路径）

1. **先看是否存在 1004/1006/1008**：有则优先按 **URMA 数据面** + Worker 侧 UB 日志。  
2. **仅 1001/1002**：看 `respMsg` 是否 **等回复超时**、**shm fd transfer**、**Connect reset**；区分 **RPC/SHM 建连** 与 **纯网络慢**。  
3. **2002**：对象大小/协议语义，与 URMA 是否发起写无关，按业务重试。  
4. **23/31/32**：连接与集群状态，与 UB 独立排查后再合并时间线。

---

## 6. 参考文档（仓库内）

| 文档 | 用途 |
|------|------|
| [`../00-kv-client-visible-status-codes.md`](../00-kv-client-visible-status-codes.md) | 全量码表与 FEMA 启发式对照 |
| [`client-status-codes-evidence-chain.md`](client-status-codes-evidence-chain.md) | 码 → RPC 重试 → 证据链 |
| [`../operations/kv-client-rpc-unavailable-triggers.md`](../operations/kv-client-rpc-unavailable-triggers.md) | 1002 与 URMA 码区分、SHM fd 失败文案 |
| [`../00-kv-client-fema-read-paths-reliability.md`](../00-kv-client-fema-read-paths-reliability.md) | 读写步骤 1～6（含 URMA 与回 Client SHM） |
| [`../../flows/narratives/remote-get-ub-urma-flow.md`](../../flows/narratives/remote-get-ub-urma-flow.md) | Remote Get UB 同步与文件锚点 |
| [`../../flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md`](../../flows/narratives/remote-get-tcp-fallback-urma-retry-polljfc.md) | TCP 回包、URMA 重试、poll jfc 与超时 |

---

## 7. 修订说明

- 本文档为 **知识梳理**，枚举数值以 **`status.h` 为准**；产品迭代时请 diff 源码。  
- **树状节点**为排障抽象，**非**严格类继承关系。
