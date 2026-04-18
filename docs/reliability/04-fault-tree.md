# 04 · 故障树：错误码 → 根因（源码证据版）

## 对应代码

本篇把"监控异常 / 接口报错"落到 **可验证的代码证据**。关键文件：

| 代码位置 | 作用 |
|---------|------|
| `include/datasystem/utils/status.h` | 错误码枚举 |
| `src/datasystem/common/rpc/zmq/zmq_msg_queue.h` | `ClientReceiveMsg` 把 `K_TRY_AGAIN` 改写为 1002 |
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | ZMQ 建连、等待、心跳 `POLLOUT` 相关 1002 |
| `src/datasystem/common/rpc/unix_sock_fd.cpp` | `ErrnoToStatus`：`ECONNRESET`/`EPIPE` → 1002 |
| `src/datasystem/client/client_worker_common_api.cpp` | `mustUds && !isConnectSuccess` → 1002（`shm fd transfer`） |
| `src/datasystem/common/rdma/urma_manager.cpp` | `CheckUrmaConnectionStable` → 1006 |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | `GetObjectRemote` + `UrmaWritePayload` |
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | `TryReconnectRemoteWorker` |
| `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp` | 远端连接失败 → 25 |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | `HealthCheck` → 31 |
| `src/datasystem/client/listen_worker.cpp` | 首次心跳超时 → 23 |
| `src/datasystem/common/util/file_util.cpp` | `pread/pwrite` → `K_IO_ERROR` |
| `src/datasystem/worker/object_cache/worker_oc_spill.cpp` | spill 空间不足 → `K_NO_SPACE` |
| `src/datasystem/common/util/rpc_util.h` | `RetryOnError` 间隔序列 `1,5,50,200,1000,5000` ms；`minOnceRpcTimeoutMs=50ms` |

接口级（Init / MCreate / MSet / MGet）的故障树独立维护：[04a-fault-tree-by-interface.md](04a-fault-tree-by-interface.md)。

---

## 1. 故障树总览（6 类）

```text
故障树（KV Client）
├─ A. TCP 链路故障（含 ZMQ / socket / UDS）
│  ├─ A1. 建连/等待超时            → 1002
│  ├─ A2. socket reset(EPIPE/ECONNRESET) → 1002
│  ├─ A3. 心跳不可写(Network unreachable) → 1002
│  └─ A4. fd 交换失败(shm fd transfer)    → 1002
├─ B. UB 链路故障（URMA）
│  ├─ B1. 连接不稳 / 实例不匹配       → 1006
│  ├─ B2. 可恢复瞬时故障             → 1008
│  ├─ B3. URMA 操作错误              → 1004
│  └─ B4. 1006 → exchange → TRY_AGAIN → Retry
├─ C. 组件本身故障（SDK / Worker）
│  ├─ C1. 客户端收不到心跳            → 23
│  ├─ C2. Worker 退出窗口             → 31
│  ├─ C3. 扩缩容 / 迁移窗口           → 32
│  └─ C4. 注册 / 初始化参数不一致     → 部署失败 / 后续不稳
├─ D. 系统资源故障
│  ├─ D1. OOM / No space / FD 限制    → 6 / 13 / 18
│  ├─ D2. 队列 / 线程池饱和           → 重试与长尾
│  └─ D3. spill / 持久化资源争用      → I/O 慢
├─ E. 第三方 etcd 故障
│  ├─ E1. 连接失败 / 超时             → 25
│  └─ E2. 控制面降级（扩缩容、隔离能力下降）
└─ F. 文件接口故障
   ├─ F1. pread / pwrite 失败         → K_IO_ERROR
   └─ F2. spill 空间不足              → K_NO_SPACE
```

FEMA 故障模式映射：UB → 25~31、39~42；TCP → 32~38；etcd → 43~48；资源/组件 → 4~24；文件/存储 → 7~9、49~53（模式编号见 [02-failure-modes-and-sli.md](02-failure-modes-and-sli.md)）。

---

## 2. 代码证据链

### 2.1 TCP / ZMQ：1002 是"桶码"而非单一根因

**证据 A：`K_TRY_AGAIN` 被改写为 1002**

- `common/rpc/zmq/zmq_msg_queue.h::ClientReceiveMsg`
- 阻塞模式下 `K_TRY_AGAIN` → `K_RPC_UNAVAILABLE`，文案：`Rpc service for client ... has not responded within the allowed time`

**证据 B：socket reset / 建连超时归入 1002**

- `common/rpc/unix_sock_fd.cpp::ErrnoToStatus`：`ECONNRESET / EPIPE` → `K_RPC_UNAVAILABLE`，日志含 `Connect reset. fd ...`
- `common/rpc/zmq/zmq_stub_conn.cpp`：
  - `ZMQ_POLLOUT` 不可写 → `K_RPC_UNAVAILABLE, "Network unreachable"`
  - `Timeout waiting for SockConnEntry wait` → `K_RPC_UNAVAILABLE`
  - `Remote service is not available within allowable %d ms` → `K_RPC_UNAVAILABLE`
  - 网关 / Frontend 转发失败 `ReportErrorToClient(... K_RPC_UNAVAILABLE ... "The service is currently unavailable!")`

**证据 C：fd 交换失败也返回 1002**

- `client/client_worker_common_api.cpp`：`mustUds && !isConnectSuccess` → `K_RPC_UNAVAILABLE, "Can not create connection to worker for shm fd transfer."`

**证据 D：重试策略把 1002 当"可恢复的通道类问题"**

- `RetryOnError` 使用的 `RETRY_ERROR_CODE` 含 `K_RPC_UNAVAILABLE`；`RegisterClient` 的显式列表同样含 1002；**仍不说明根因是 URMA 还是 TCP**。

**结论**：1002 同时覆盖 RPC 等待超时、socket 异常、fd 交换失败，必须结合 `respMsg` 关键词与链路上下文定界（[06-playbook.md § 2](06-playbook.md) 给出 5 类 respMsg 的分流表）。

### 2.2 UB / URMA：1006 → 重连 → TRY_AGAIN → Retry

**证据 E：URMA 连接不稳定返回 1006**

- `common/rdma/urma_manager.cpp::CheckUrmaConnectionStable`：无连接 / 实例不一致 → `K_URMA_NEED_CONNECT(1006)`

**证据 F：服务端远端读路径的码传递顺序**

- `worker/object_cache/worker_worker_oc_service_impl.cpp`：
  1. `serverApi->Read(req)`
  2. `CheckConnectionStable(req)`
  3. `GetObjectRemoteImpl(...)`
  4. URMA 分支：`UrmaWritePayload(...)` 成功后 `rsp.data_source = DATA_ALREADY_TRANSFERRED`
  5. `serverApi->Write(rsp)` + `SendAndTagPayload(...)`
- 关键日志：`GetObjectRemote read/write/send payload error`、`pull success`

**证据 G：1006 在调用侧被重连并转为 TRY_AGAIN**

- `worker/object_cache/service/worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker`：
  - `lastResult == K_URMA_NEED_CONNECT` → transport exchange → 成功后返回 `K_TRY_AGAIN("Reconnect success")`
  - 由外层 `RetryOnError` 继续重试

**结论**：UB 故障可恢复链路明确，关键看 1006/1008 与重连窗口是否足够；若窗口不足，可能先表现为 1001/1002。

### 2.3 etcd：控制面失败上抛 25

**证据 H**：`worker/cluster_manager/etcd_cluster_manager.cpp`：节点连接失败或超时 → `Disconnected from remote node ...` + `K_MASTER_TIMEOUT(25)`。

**结论**：etcd / 控制面故障与数据面 UB/TCP 需分开定界；读写可能暂时可用，但扩缩容 / 故障隔离能力受损。etcd 故障隔离与恢复的完整分析见 [deep-dives/etcd-isolation-and-recovery.md](deep-dives/etcd-isolation-and-recovery.md)。

### 2.4 组件故障：心跳与健康检查直接暴露

| 证据 | 路径 | 码 |
|------|------|----|
| I | `client/listen_worker.cpp`：首次心跳超时 → `K_CLIENT_WORKER_DISCONNECT("Cannot receive heartbeat from worker.")` | 23 |
| J | `worker/object_cache/worker_oc_service_impl.cpp::HealthCheck`：`CheckLocalNodeIsExiting()` 为真 → `K_SCALE_DOWN, "Worker is exiting now"` | 31 |
| K | `worker/object_cache/service/worker_oc_service_multi_publish_impl.cpp::RetryCreateMultiMetaWhenMoving`：`meta_is_moving` 结束仍非空 info → `K_SCALING, "The cluster is scaling, please try again."` | 32 |
| L | `worker/worker_service_impl.cpp`：`Register client: ... heartbeat: ... shmEnabled ...` | 部署阶段锚点 |

### 2.5 文件接口故障

**证据 M**：`common/util/file_util.cpp::ReadFile/WriteFile`：`pread/pwrite` 失败 → `K_IO_ERROR`；`WriteFile` 有恢复日志 `WriteFile failed... / WriteFile success again`。

**证据 N**：`worker/object_cache/worker_oc_spill.cpp`：`K_NO_SPACE, "No space when WorkerOcSpill::Spill"`。

---

## 3. 流程化定位：按路径分的排障链

### 3.1 本地读（client → 本机 worker）

1. 首看：成功率、读 P99
2. 定位链：
   - `status_code` 分布（1002 / 23 / 31 / 6 / 18）
   - fd 交换日志（`shm fd transfer`）
   - 心跳日志（`Cannot receive heartbeat...`）
3. 定界：
   - 1002 + fd 关键词 → TCP / UDS / fd 交换
   - 23 → Worker 心跳 / 进程
   - 31 / 32 → 生命周期窗口（运维变更）

### 3.2 远端读（worker → worker，含 URMA）

1. 首看：成功率、remote_get P99
2. 定位链：
   - `K_URMA_*` vs `1001 / 1002`
   - `GetObjectRemote` 三段日志（read / urma_write / write / send payload）
   - `TryReconnectRemoteWorker` 是否触发及是否成功
3. 定界：
   - 1006 / 1008 主导 → UB / URMA
   - 仅 1002 / 1001 且无 URMA 码 → 先查 TCP / ZMQ 或 budget 不足

### 3.3 本地写

1. 首看：写成功率、写 P99
2. 定位链：
   - 资源码（6 / 13 / 18）
   - spill / 文件日志（`K_NO_SPACE`、`WriteFile failed`）
   - 控制面码（25）
3. 定界：
   - 6 / 13 / 18 + 资源日志打满 → 系统资源
   - `K_IO_ERROR` / `K_NO_SPACE` → 文件接口 / 磁盘

### 3.4 部署 SDK / Worker

- SDK 关键检查：`Register client` 日志（heartbeat / shmEnabled / socket fd）、`GetSocketPath` 与 fd 握手
  - `shm fd transfer` 失败 → TCP / UDS / fd 通道
  - 心跳首轮失败 → 23
- Worker 关键检查：`HealthCheck` 是否 `OK` / `K_SCALE_DOWN`、etcd 连接稳定性
  - 31 → 退出态 / 缩容流程
  - 25 → etcd 控制面

---

## 4. 告警设计

### 4.1 触发总原则

双 SLI 入口：

- 读 / 写成功率下降
- 读 / 写 P99 不达标

再用错误码 + 日志分流到故障域。

### 4.2 告警规则（第一版）

| ID | 条件 | 子类关键词 | 含义 |
|----|------|------------|------|
| R1 | `read_p99` / `write_p99` 连续 N 窗口超阈 或 `success_rate` 连续 N 窗口低于阈值 | — | SLI 违约（P1/P2） |
| R2 | `1004 / 1006 / 1008` 速率或占比突增，且 remote_get 相关动作异常 | `UrmaWritePayload`、`TryReconnect` | UB 专项 |
| R3 | `1001 / 1002 / 23` 突增 | `shm fd transfer` / `Connect reset` / `Network unreachable` | TCP / ZMQ 专项（含子类） |
| R4 | `K_MASTER_TIMEOUT(25)` 突增 + etcd 访问成功率下降 | — | etcd 专项（控制面降级） |
| R5 | `6 / 13 / 18` 或 `K_IO_ERROR / K_NO_SPACE` 突增 | 资源日志内存 / 队列 / 线程池高位 | 资源与文件接口 |

### 4.3 分级与抑制

- P1：全局成功率明显下降或 P99 严重超阈，持续 T
- P2：单 AZ / 单 worker 持续异常
- P3：单信号异常（观察）
- 抑制：变更窗口（部署 / 扩缩容）适度延迟升级
- 去重：按 `cluster + domain + status_code` 聚合

---

## 5. 实操定界（最短路径）

1. **先看是否存在 1004 / 1006 / 1008**：有则优先按 URMA 数据面 + Worker 侧 UB 日志。
2. **仅 1001 / 1002**：看 `respMsg` 是否"等回复超时"、"shm fd transfer"、"Connect reset"；区分 RPC / SHM 建连与纯网络慢。
3. **2002**：对象大小 / 协议语义，与 URMA 是否发起写无关，按业务重试。
4. **23 / 31 / 32**：连接与集群状态，与 UB 独立排查后再合并时间线。
