# KV Client 可观测「定位 / 定界」增强 — 测试串讲（合并版）

**读者**：功能测试、联调、现场排障  
**目标**：在监控侧已识别 **Status code、接口、时延** 的前提下，能用 **§3.1** 的流程把问题缩到 **客户端 / Worker / ZMQ 传输** 等层次；并结合 **§2** 日志与 **§3.2** 指标区分 **ZMQ/TCP 控制面** vs **URMA 数据面** vs **`K_RPC_UNAVAILABLE`(1002) 子类**，避免误判。

**关联 PR（GitCode）**：[!583](https://gitcode.com/openeuler/yuanrong-datasystem/pull/583)、[!584](https://gitcode.com/openeuler/yuanrong-datasystem/pull/584)、[!586](https://gitcode.com/openeuler/yuanrong-datasystem/pull/586)、[!588](https://gitcode.com/openeuler/yuanrong-datasystem/pull/588)  
**详细计划**：`../2026-04-zmq-rpc-metrics/`、`./`

---

## 1. 两条主线（串讲时先画这条线）

| 主线 | 解决什么问题 | 主要信号 |
|------|----------------|----------|
| **A. ZMQ/TCP RPC：性能 + 故障定界** | RPC 慢/失败时，是 **I/O 等 socket**、**序列化**、还是 **对端挂/连不上**？ | **§3.1**：监控上 **Status + 接口 + 时延** 后的 **定界步骤**；**§3.2**：**`Metrics Summary`** 中 **`client_*` / `worker_*` / `zmq_*`** 表与样例；**§2.1**：日志 / Status 的 **`[ZMQ_*]` / `[TCP_*]` / `[RPC_*]`** 等 |
| **B. URMA vs TCP：错误域** | 同一类「超时 / 不可用」，根因是 **URMA 握手/轮询/JFS** 还是 **TCP/Unix/ZMQ 连接**？ | **§4**：状态码 1001/1010/1002 与 grep 套路；**§2.2**：`URMA_*` 日志字段（`remoteAddress`、`cqeStatus` 等） |

---

## 2. 源代码修改后的日志：关键字段与样例（当前 `yuanrong-datasystem` 树）

对应 GitCode PR [!583](https://gitcode.com/openeuler/yuanrong-datasystem/pull/583)、[!584](https://gitcode.com/openeuler/yuanrong-datasystem/pull/584)、[!586](https://gitcode.com/openeuler/yuanrong-datasystem/pull/586)、[!588](https://gitcode.com/openeuler/yuanrong-datasystem/pull/588) 合入能力；下列表格按**源码路径**归纳，便于测试在故障单里贴**日志原句 + 字段**。

### 2.1 ZMQ / TCP / RPC：`1002` 与 ZMQ 硬错误 — 标签、字段、样例

| 源码 | 条件 | 固定标签（日志或 Status 消息前缀） | 关键字段 |
|------|------|--------------------------------------|----------|
| `common/rpc/zmq/zmq_socket_ref.cpp` `RecvMsg` | `zmq_msg_recv == -1`，errno 非 EAGAIN/EINTR | `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `errno=%d`、`(%s)` 为 `zmq_strerror`；并更新 metrics：`zmq_receive_failure_total`、`zmq_last_error_number`，网络类 errno 递增 `zmq_network_error_total` |
| 同上 `SendMsg` | `zmq_msg_send` 同上 | `[ZMQ_SEND_FAILURE_TOTAL]` | 同上，对应 `zmq_send_failure_total` 等 |
| `common/rpc/zmq/zmq_socket.cpp` `ZmqRecvMsg` | 阻塞 recv 路径上长期无数据 | `[ZMQ_RECV_TIMEOUT]` | 日志：`Blocking recv timed out after %d seconds`；Status：`Waited %d seconds. Didn't receive any response from server` |
| `common/rpc/zmq/zmq_stub_conn.cpp` `SendHeartBeats` | 无 `ZMQ_POLLOUT` | `[TCP_NETWORK_UNREACHABLE]` | 固定后缀 `Network unreachable` |
| `common/rpc/zmq/zmq_stub_conn.cpp` `SockConnEntry::WaitForConnected` | 等待后台建连超时 | `[SOCK_CONN_WAIT_TIMEOUT]` | 固定文案 `Timeout waiting for SockConnEntry wait` |
| 同上 | 超时后仍 `connInProgress_` | `[REMOTE_SERVICE_WAIT_TIMEOUT]` | **`%d ms`** = 入参 `timeout` |
| `common/rpc/zmq/zmq_msg_queue.h` `ClientReceiveMsg` | 非 DONTWAIT 且 `K_TRY_AGAIN` | `[RPC_RECV_TIMEOUT]` | `Rpc service for client %s has not responded... Detail: %s`（`GetId()` + `rc.ToString()`） |
| `common/rpc/zmq/zmq_stub_conn.cpp` 建连 | 等路径回复超时 | `[RPC_RECV_TIMEOUT]` | `Remote host %s is not available`（`GetZmqEndPoint()`） |
| `common/rpc/zmq/zmq_stub_impl.h` 异步收 | 超时升格 | `[RPC_RECV_TIMEOUT]` | 前缀 + 原 `rc.GetMsg()`；另有独立 `LOG(WARNING)`：`Rpc service for client <id> has not responded within the allowed time.` |
| `common/rpc/zmq/zmq_stub_conn.cpp` `HandleOneFrontendEvent` | 前端处理失败 | `[RPC_SERVICE_UNAVAILABLE]` | `The service is currently unavailable!` + `Message que %s service %s method %d ... gateway ... Elapsed` |
| `common/rpc/unix_sock_fd.cpp` `ErrnoToStatus` | ECONNRESET / EPIPE | `[TCP_CONNECT_RESET]` | `fd %d`、`err %s` |
| 同上 TCP 建连 | 失败汇总 | `[TCP_CONNECT_FAILED]` | `Last Error: %s` |
| 同上 | UDS 失败 | `[UDS_CONNECT_FAILED]` | 拼接流 `oss` 细节 |
| `client/client_worker_common_api.cpp` | 必须 UDS 但 SHM FD 通道建连失败 | `[SHM_FD_TRANSFER_FAILED]` | 固定一句 |

**说明**：`[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]` 为 `LOG(WARNING)`，且 **`LogFirstEveryNShouldEmit`**（默认每 `LOG_ZMQ_ERROR_FREQUENCY` 次 + 时间窗）限频，风暴时不是每条失败都有一行日志，**以 metrics 计数为准**。

**合成样例（与 `FormatString` / 字面量一致，数值示意）**：

```text
[ZMQ_RECEIVE_FAILURE_TOTAL] errno=104(Connection reset by peer)
[ZMQ_SEND_FAILURE_TOTAL] errno=11(Resource temporarily unavailable)
[ZMQ_RECV_TIMEOUT] Blocking recv timed out after 30 seconds
msg: [[ZMQ_RECV_TIMEOUT] Waited 30 seconds. Didn't receive any response from server ...]
msg: [[TCP_CONNECT_RESET] Connect reset. fd 42. err Connection reset by peer]
msg: [[TCP_CONNECT_FAILED] Tcpip Connect failed. Last Error: Connection refused]
msg: [[UDS_CONNECT_FAILED] ...]
msg: [[SOCK_CONN_WAIT_TIMEOUT] Timeout waiting for SockConnEntry wait]
msg: [[REMOTE_SERVICE_WAIT_TIMEOUT] Remote service is not available within allowable 5000 ms]
msg: [[RPC_RECV_TIMEOUT] Rpc service for client <clientId> has not responded within the allowed time. Detail: ...]
msg: [[RPC_RECV_TIMEOUT] Remote host tcp://10.0.0.1:8080 is not available]
msg: [[RPC_SERVICE_UNAVAILABLE] The service is currently unavailable! Message que ...]
msg: [[TCP_NETWORK_UNREACHABLE] Network unreachable]
msg: [[SHM_FD_TRANSFER_FAILED] Can not create connection to worker for shm fd transfer.]
```

**同源 metrics（586 一类改动）**：`zmq_socket_ref.cpp` 上 **`METRIC_TIMER(ZMQ_*_IO_LATENCY)`** 与失败/try_again/network 计数；`zmq_stub_conn.cpp` 网关 **`METRIC_INC(ZMQ_GATEWAY_RECREATE_TOTAL)`**；`zmq_monitor.cpp` 上 **`ZMQ_EVENT_DISCONNECT_TOTAL`** / **`ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL`**。排障时除 grep 方括号标签外，应在 **Metrics Summary** 中对照 **`client_*` / `worker_*` / `zmq_*`**（见 **§3.1** 步骤与 **§3.2** 表）。

### 2.2 URMA：轮询、等待、建连、JFS 重建 — 标签、字段、样例

| 源码 | 条件 | 固定标签 | 关键字段 |
|------|------|----------|----------|
| `common/rdma/urma_manager.cpp` `ServerEventHandleThreadMain` | `PollJfcWait` 错误且非 `K_TRY_AGAIN` | `[URMA_POLL_ERROR]` | `PollJfcWait failed: ` + **`rc.ToString()`**；**`successCount=`**、**`failedCount=`**（完成集合大小） |
| 同上 `WaitToFinish` | `timeoutMs < 0` | `[URMA_WAIT_TIMEOUT]` | `timedout waiting for request: <requestId>` → 对外 **1010** |
| 同上 `WaitToFinish` | `Event::WaitFor` 返回 **1001** | （继承 `rdma_util.h` 通用文案） | 映射为 **1010** `K_URMA_WAIT_TIMEOUT`，日志常见为 **`Timed out waiting for request: <id>`**（无方括号 URMA 前缀） |
| 同上 `CheckUrmaConnectionStable` | 无连接 / instance 不一致 / 无 instance 不稳定 | `[URMA_NEED_CONNECT]` | **`remoteAddress:`**；**`remoteInstanceId=`** / **`cachedRemoteInstanceId=`** / **`requestRemoteInstanceId=`** / `UNKNOWN` |
| 同上 `HandleUrmaEvent` | 策略 **RECREATE_JFS** | `[URMA_RECREATE_JFS]` | **`requestId=`**、**`op=`**、**`remoteAddress=`**、**`remoteInstanceId=`**、**`cqeStatus=`** |
| 同上 `ReCreateJfs` 失败 | `LOG_IF_ERROR` | `[URMA_RECREATE_JFS_FAILED]` | **`requestId=`**、**`op=`**、**`remoteAddress=`**、**`remoteInstanceId=`** |
| 同上 connection 过期 | | `[URMA_RECREATE_JFS_SKIP]` | `Event connection expired` + `requestId` / `op` / `remoteAddress` / `remoteInstanceId` |
| `common/rdma/urma_resource.cpp` `ReCreateJfs` | JFS 多种边界 | `[URMA_RECREATE_JFS]` / `[URMA_RECREATE_JFS_SKIP]` | **`remoteAddress=`**、**`remoteInstanceId=`**、**`JFS <id>`**、**`newJfsId=`** |
| `worker/.../worker_oc_service_get_impl.cpp` | `TryReconnectRemoteWorker` | `[URMA_NEED_CONNECT]` | **`remoteAddress=`**、**`remoteWorkerId=`**（etcd 映射，否则 `UNKNOWN`）、**`lastResult=`** |
| `worker/.../worker_worker_oc_service_impl.cpp` | `CheckTransportConnectionStable` 失败 | `[URMA_NEED_CONNECT]` | **`remoteAddress=`**、**`remoteWorkerId=`**、**`remoteInstanceId=`**、**`rc=`** |

**限频**：上述大量 `LOG_FIRST_AND_EVERY_N(WARNING/ERROR, 100)`（`K_URMA_WARNING_LOG_EVERY_N` / `K_URMA_ERROR_LOG_EVERY_N`），现场要 **结合时间窗口多看几条** 或看 **Status / metrics**。

**合成样例**：

```text
[URMA_POLL_ERROR] PollJfcWait failed: ..., successCount=0, failedCount=3
[URMA_WAIT_TIMEOUT] timedout waiting for request: 123456789
[URMA_NEED_CONNECT] No existing connection for remoteAddress: 10.0.0.2:9000, remoteInstanceId=inst-a, requires creation.
[URMA_NEED_CONNECT] Connection stale for remoteAddress: 10.0.0.2:9000, cachedRemoteInstanceId=old-id, requestRemoteInstanceId=new-id, need reconnect.
[URMA_NEED_CONNECT] Connection unstable for remoteAddress: 10.0.0.2:9000, remoteInstanceId=UNKNOWN, need to reconnect.
[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered, remoteAddress=tcp://10.0.0.2:9000, remoteWorkerId=worker-7, lastResult=...
[URMA_NEED_CONNECT] CheckConnectionStable failed, remoteAddress=10.0.0.2:9000, remoteWorkerId=worker-7, remoteInstanceId=inst-a, rc=...
[URMA_RECREATE_JFS] requestId=123, op=READ, remoteAddress=10.0.0.2:9000, remoteInstanceId=inst-a, cqeStatus=-1
[URMA_RECREATE_JFS_FAILED] requestId=123, op=READ, remoteAddress=10.0.0.2:9000, remoteInstanceId=inst-a, ...
[URMA_RECREATE_JFS_SKIP] Event connection expired, requestId=123, op=READ, remoteAddress=..., remoteInstanceId=...
[URMA_RECREATE_JFS] Mark JFS 8 invalid and recreate, remoteAddress=..., remoteInstanceId=...
[URMA_RECREATE_JFS] connection switched to newJfsId=9, remoteAddress=..., remoteInstanceId=...
```

**1001 通用等待（共享 `Event`，非 URMA 专用）**：`common/rdma/rdma_util.h` — `Timed out waiting for request: ...` 或 `Timed out waiting for any event`。

### 2.3 定界口诀（现场日志 + metrics）

- 日志 / Status 里 **`URMA_`、`cqeStatus`、`remoteInstanceId`、`JFS`、`PollJfcWait`** → **URMA 域**。  
- **`[TCP_` / `[UDS_` / `[ZMQ_` / `[SOCK_CONN_` / `[REMOTE_SERVICE_` / `[SHM_FD_`** → **TCP/UDS/ZMQ/建连池/SHM 域**。  
- **`[RPC_RECV_TIMEOUT]` / `[RPC_SERVICE_UNAVAILABLE]`** → 多属 **RPC 语义或服务侧**；与 **§3.2.2** 中 **`zmq_*_failure_total` 是否为 0** 对照读。  
- 所有标签均可 **`grep -E '\[URMA_|\[TCP_|\[RPC_|\[ZMQ_|\[UDS_|\[SOCK_|\[REMOTE_|\[SHM_'`** 一次性扫日志附件。

---

## 3. 主线 A — Client / Worker / ZMQ 可观测与定界

本章覆盖 **同一 `Metrics Summary` 中的 `client_*`、`worker_*`、`zmq_*`** 如何与 **接口返回、日志里的 Status code** 一起用于定界；**ZMQ 只是其中一层**，不是本章唯一主题。具体日志标签仍以 **§2** 为准。

### 3.1 监控平台已有「Status code + 接口 + 时延」时，如何定界与定位

监控告警多是 **聚合结果**（某接口错误率升、P99 抖动、某返回码突增）。建议按固定顺序把问题 **缩到可改模块**，再下钻 §2 / §4。

1. **对齐时间与维度**  
   记录告警的 **时间窗、集群/实例、接口或 RPC 名**（能与日志里的 service/method、Trace 对齐）。拉 **同一窗口** 的：网关或业务 **接口日志**（含 **Status code**、msg 前缀）、进程 **Metrics Summary**（**必须含 Compare 段**，看 `+delta`）。

2. **用 Status code 划第一层**（与 **§4**、**§2** 联动）  
   - **1002** 且消息带 **`[TCP_*]`、`[UDS_*]`、`[SOCK_*]`、`[RPC_*]`**（非 URMA 前缀）→ 优先 **TCP / 建连池 / ZMQ 控制面 / RPC 语义**；再看同窗口 **`zmq_*_failure_total`、`zmq_gateway_recreate_total`** 是否上升。  
   - **1010** 或日志出现 **`URMA_*`、`cqeStatus`** → 优先 **URMA 数据面**（§2.2、§4）。  
   - **1001** 或 **仅慢、无明显传输硬错** → 可能是 **通用等待或服务端处理慢**；进入下一步用 **时延直方图** 拆。

3. **用时延拆「客户端框架 / Worker / 传输 I/O」**（指标见 **§3.2** 各表）  
   - **`client_rpc_*_latency`** 明显高，**`worker_process_*_latency`、`zmq_*_io_latency`** 相对平 → 偏 **客户端路径**（排队、本地序列化、等待回复等），结合是否 **`[RPC_RECV_TIMEOUT]`** 等。  
   - **`worker_process_*_latency` 或 `worker_rpc_get_remote_object_latency`** 高 → 偏 **Worker 处理或远端对象/元数据路径**。  
   - **`zmq_send_io_latency` / `zmq_receive_io_latency` 的 avg 相对 `zmq_rpc_serialize_latency` / `deserialize` 大很多** → 时间多在 **等 socket I/O**；若 **`zmq_*_failure_total` 仍接近 0**，不宜单凭「网卡必坏」定案。  
   - **`client_*_urma_*_bytes` vs `client_*_tcp_*_bytes`**（worker 侧 **`worker_urma_*` / `worker_tcp_*`**）与业务预期传输是否一致，用于区分 **数据面走 URMA 还是 TCP** 的异常。

4. **用「接口 ↔ 指标族」缩小范围**  
   读路径 → **`client_get_*`、`worker_process_get_*`**；写/发布 → **`client_put_*`、`worker_process_create_*` / `publish_*`**；元数据 → **`worker_rpc_create_meta_latency`、`worker_rpc_query_meta_latency`**。对比 **`*_request_total` 与 `*_error_total`** 比例相对基线的变化，避免只看绝对值。

5. **工单证据链（便于复盘）**  
   建议固定包含：**告警三要素（Status code + 接口 + 时延/曲线）** + **同窗口一条含码/前缀的日志或 Status 原文** + **同窗口 Metrics 摘录**（至少覆盖与本接口相关的 **`client_*` / `worker_*` / `zmq_*`** 的 Total 与 Compare）。若已排除某一层，写明依据（例如：`zmq_*_failure=0`，传输硬错误概率低）。

### 3.2 PR [!586](https://gitcode.com/openeuler/yuanrong-datasystem/pull/586)：`InitKvMetrics()` 统一注册的 **KV + ZMQ** 指标

PR 描述写明：`InitKvMetrics()` **统一注册 KV + ZMQ** 的 `MetricDesc`（见 `kv_metrics.h` / `kv_metrics.cpp`）。即 **`Metrics Summary` 同一块** 中，除本 PR 新增的 **`zmq_*`（ID 23–35）** 外，还会带上既有的 **`client_*` / `worker_*`（ID 0–22）**——与 ZMQ/TCP RPC 及对象读写路径相关的吞吐、时延与资源观测。

在 **Total:** 与 **Compare with … before:** 两段中都会出现；定界时 **必须看 Compare 的 `+delta`**。

#### 3.2.1 `client_*` / `worker_*`（ID 0–22，与 `zmq_*` 同册）

| 指标名（日志里原样） | 类型 | 单位 | 含义（简述） |
|----------------------|------|------|----------------|
| `client_put_request_total` | COUNTER | count | 客户端 Put 请求次数 |
| `client_put_error_total` | COUNTER | count | 客户端 Put 错误次数 |
| `client_get_request_total` | COUNTER | count | 客户端 Get 请求次数 |
| `client_get_error_total` | COUNTER | count | 客户端 Get 错误次数 |
| `client_rpc_create_latency` | HISTOGRAM | us | 客户端 RPC create 路径耗时 |
| `client_rpc_publish_latency` | HISTOGRAM | us | 客户端 RPC publish 路径耗时 |
| `client_rpc_get_latency` | HISTOGRAM | us | 客户端 RPC get 路径耗时 |
| `client_put_urma_write_total_bytes` | COUNTER | bytes | 客户端 Put 经 URMA 写字节 |
| `client_put_tcp_write_total_bytes` | COUNTER | bytes | 客户端 Put 经 TCP 写字节 |
| `client_get_urma_read_total_bytes` | COUNTER | bytes | 客户端 Get 经 URMA 读字节 |
| `client_get_tcp_read_total_bytes` | COUNTER | bytes | 客户端 Get 经 TCP 读字节 |
| `worker_rpc_create_meta_latency` | HISTOGRAM | us | Worker 侧 create meta 耗时 |
| `worker_rpc_query_meta_latency` | HISTOGRAM | us | Worker 侧 query meta 耗时 |
| `worker_rpc_get_remote_object_latency` | HISTOGRAM | us | Worker 侧远程取对象耗时 |
| `worker_process_create_latency` | HISTOGRAM | us | Worker 处理 create 耗时 |
| `worker_process_publish_latency` | HISTOGRAM | us | Worker 处理 publish 耗时 |
| `worker_process_get_latency` | HISTOGRAM | us | Worker 处理 get 耗时 |
| `worker_urma_write_latency` | HISTOGRAM | us | Worker URMA 写耗时 |
| `worker_tcp_write_latency` | HISTOGRAM | us | Worker TCP 写耗时 |
| `worker_to_client_total_bytes` | COUNTER | bytes | Worker → Client 字节量 |
| `worker_from_client_total_bytes` | COUNTER | bytes | Client → Worker 字节量 |
| `worker_object_count` | GAUGE | count | Worker 对象数量 |
| `worker_allocated_memory_size` | GAUGE | bytes | Worker 分配内存量 |

与 **传输定界** 联调时，可把 **`client_*_urma_*` / `client_*_tcp_*`**、**`worker_urma_*` / `worker_tcp_*`** 与 **`zmq_*`** 对照，区分数据面走 URMA/TCP 与 ZMQ 传输层计数是否异常。

#### 3.2.2 `zmq_*`（ID 23–35，本 PR 新增：故障定界 + 性能自证）

| 指标名（日志里原样） | 类型 | 单位 | PR 586 归类 | 代码打点位置（摘要） |
|----------------------|------|------|-------------|----------------------|
| `zmq_send_failure_total` | COUNTER | count | 故障定界 | `zmq_socket_ref.cpp` `SendMsg` 硬失败 |
| `zmq_receive_failure_total` | COUNTER | count | 故障定界 | `zmq_socket_ref.cpp` `RecvMsg` 硬失败 |
| `zmq_send_try_again_total` | COUNTER | count | 故障定界 | `SendMsg` EAGAIN |
| `zmq_receive_try_again_total` | COUNTER | count | 故障定界 | 阻塞 recv 路径 EAGAIN |
| `zmq_network_error_total` | COUNTER | count | 故障定界 | errno 判为网络类时 |
| `zmq_last_error_number` | GAUGE | （无） | 故障定界 | 最近一次上述失败 errno |
| `zmq_gateway_recreate_total` | COUNTER | count | 故障定界 | `zmq_stub_conn.cpp` 强制重建 frontend |
| `zmq_event_disconnect_total` | COUNTER | count | 故障定界 | `zmq_monitor.cpp` disconnect 事件 |
| `zmq_event_handshake_failure_total` | COUNTER | count | 故障定界 | `zmq_monitor.cpp` 握手失败 |
| `zmq_send_io_latency` | HISTOGRAM | us | 性能自证 | `SendMsg` 包裹 `METRIC_TIMER` |
| `zmq_receive_io_latency` | HISTOGRAM | us | 性能自证 | `RecvMsg` 包裹 `METRIC_TIMER` |
| `zmq_rpc_serialize_latency` | HISTOGRAM | us | 性能自证 | `zmq_common.h` 序列化路径 |
| `zmq_rpc_deserialize_latency` | HISTOGRAM | us | 性能自证 | `zmq_common.h` 反序列化路径 |

**定界速查（`zmq_*`）**：

- `zmq_gateway_recreate_total` 的 **Compare 段 +delta > 0** → 客户端感知断连并重建网关，**连接层**优先排查。
- RPC 失败但 **各类 `zmq_*_failure` / `net_error` 仍为 0** → 多为 **服务端慢或 RPC 超时路径**，不要当成「网卡必坏」。
- **I/O histogram avg** 远大于 **serialize/deserialize avg** → 时间主要在 **等 I/O**，框架未必是瓶颈。

#### 3.2.3 与 PR 描述一致的回归命令 + `Metrics Summary` 全量 grep 样例

PR [!586](https://gitcode.com/openeuler/yuanrong-datasystem/pull/586) **验证结果**中给出的 UT 组合为：

```bash
./tests/ut/ds_ut --gtest_filter='ZmqMetricsTest.*:MetricsTest.*'
```

已在 **`root@38.76.164.55`** 上执行，结果：**82/82 PASSED**（`MetricsTest` 62 + `ZmqMetricsTest` 20）。

要在**日志里**拿到 **client / worker / zmq 全量指标名各一行**（便于核对注册与 `grep` 脚本），可执行（需 **`--alsologtostderr`**，`PrintSummary` 走 `LOG(INFO)`）：

```bash
./tests/ut/ds_ut --gtest_filter='MetricsTest.kv_metrics_print_summary_test' --alsologtostderr 2>&1 | tee kv_metrics_summary.log
```

从上述输出中 **只抽指标行** 的示例（若行首带 glog 前缀，可去掉 `^` 或改用 `grep -E '(client|worker|zmq)_[a-z0-9_]+='`）：

```bash
grep -E '^\s*(client|worker|zmq)_' kv_metrics_summary.log
```

**本工作区归档（节选前的完整原始输出）**：`vibe-coding-files/workspace/observability/kv_metrics_print_summary_ut.log`（与上条命令等价的一次采集）。

**`Metrics Summary` 全量摘录**（来自该归档；`client_put_request_total=1` 来自该用例内一次 `METRIC_INC`，其余为 0 基线）：

```text
Metrics Summary, version=v0, cycle=1, interval=10000ms

Total:
client_put_request_total=1
client_put_error_total=0
client_get_request_total=0
client_get_error_total=0
client_rpc_create_latency,count=0,avg=0us,max=0us
client_rpc_publish_latency,count=0,avg=0us,max=0us
client_rpc_get_latency,count=0,avg=0us,max=0us
client_put_urma_write_total_bytes=0B
client_put_tcp_write_total_bytes=0B
client_get_urma_read_total_bytes=0B
client_get_tcp_read_total_bytes=0B
worker_rpc_create_meta_latency,count=0,avg=0us,max=0us
worker_rpc_query_meta_latency,count=0,avg=0us,max=0us
worker_rpc_get_remote_object_latency,count=0,avg=0us,max=0us
worker_process_create_latency,count=0,avg=0us,max=0us
worker_process_publish_latency,count=0,avg=0us,max=0us
worker_process_get_latency,count=0,avg=0us,max=0us
worker_urma_write_latency,count=0,avg=0us,max=0us
worker_tcp_write_latency,count=0,avg=0us,max=0us
worker_to_client_total_bytes=0B
worker_from_client_total_bytes=0B
worker_object_count=0
worker_allocated_memory_size=0B
zmq_send_failure_total=0
zmq_receive_failure_total=0
zmq_send_try_again_total=0
zmq_receive_try_again_total=0
zmq_network_error_total=0
zmq_last_error_number=0
zmq_gateway_recreate_total=0
zmq_event_disconnect_total=0
zmq_event_handshake_failure_total=0
zmq_send_io_latency,count=0,avg=0us,max=0us
zmq_receive_io_latency,count=0,avg=0us,max=0us
zmq_rpc_serialize_latency,count=0,avg=0us,max=0us
zmq_rpc_deserialize_latency,count=0,avg=0us,max=0us

Compare with 10000ms before:
client_put_request_total=+1
client_put_error_total=+0
client_get_request_total=+0
client_get_error_total=+0
client_rpc_create_latency,count=+0,avg=0us,max=0us
client_rpc_publish_latency,count=+0,avg=0us,max=0us
client_rpc_get_latency,count=+0,avg=0us,max=0us
client_put_urma_write_total_bytes=+0B
client_put_tcp_write_total_bytes=+0B
client_get_urma_read_total_bytes=+0B
client_get_tcp_read_total_bytes=+0B
worker_rpc_create_meta_latency,count=+0,avg=0us,max=0us
worker_rpc_query_meta_latency,count=+0,avg=0us,max=0us
worker_rpc_get_remote_object_latency,count=+0,avg=0us,max=0us
worker_process_create_latency,count=+0,avg=0us,max=0us
worker_process_publish_latency,count=+0,avg=0us,max=0us
worker_process_get_latency,count=+0,avg=0us,max=0us
worker_urma_write_latency,count=+0,avg=0us,max=0us
worker_tcp_write_latency,count=+0,avg=0us,max=0us
worker_to_client_total_bytes=+0B
worker_from_client_total_bytes=+0B
worker_object_count=+0
worker_allocated_memory_size=+0B
zmq_send_failure_total=+0
zmq_receive_failure_total=+0
zmq_send_try_again_total=+0
zmq_receive_try_again_total=+0
zmq_network_error_total=+0
zmq_last_error_number=+0
zmq_gateway_recreate_total=+0
zmq_event_disconnect_total=+0
zmq_event_handshake_failure_total=+0
zmq_send_io_latency,count=+0,avg=0us,max=0us
zmq_receive_io_latency,count=+0,avg=0us,max=0us
zmq_rpc_serialize_latency,count=+0,avg=0us,max=0us
zmq_rpc_deserialize_latency,count=+0,avg=0us,max=0us
```

### 3.3 运行时从哪里看 `client_*` / `worker_*` / `zmq_*`

- 进程按配置周期性（或触发）打印的 **`Metrics Summary`** 文本块（格式以实际输出为准）。
- **`grep` 建议**：`grep -E '^(client|worker|zmq)_' <文件>` 或分前缀：`grep '^client_'`、`grep '^worker_'`、`grep '^zmq_'`。
- **定界务必对照 Compare 段的 `+delta`**，不要只看 Total 累积值。

### 3.4 产品日志中与 metrics 呼应的检索（非测试埋点）

下列字符串来自 **`src/datasystem`** 产品代码（如 `zmq_stub_conn.cpp`、`zmq_socket_ref.cpp`），可与 **§3.2** 中指标一起用于定界：

```bash
# ZMQ 硬错误（限频，可能条数少于 metrics 增量）
grep -E '\[ZMQ_RECEIVE_FAILURE_TOTAL\]|\[ZMQ_SEND_FAILURE_TOTAL\]|\[ZMQ_RECV_TIMEOUT\]' <日志>

# 网关重建路径（常与 zmq_gateway_recreate_total、EAGAIN 相关）
grep -E 'Received EAGAIN at HandleEvent|force ZmqFrontend recreation|New gateway created' <日志>

# RPC 不可用子类（Status 或日志中的 msg）
grep -E '\[RPC_RECV_TIMEOUT\]|\[RPC_SERVICE_UNAVAILABLE\]|\[TCP_NETWORK_UNREACHABLE\]' <日志>
```

**注意**：`[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]` 带 **LogFirstEveryN** 限频；**日志条数少于 metrics 计数属正常**，以 **metrics** 为准。

### 3.5 格式说明

**`Metrics Summary` 的完整形态（含 `client_*` / `worker_*` / `zmq_*`）** 见 **§3.2.3** 摘录。连接抖动场景下，可关注 **`zmq_gateway_recreate_total=+N`**、**`zmq_send_try_again_total`** 等与 §3.4 中网关重建日志是否同窗口出现。

---

## 4. 主线 B — URMA 与 TCP 错误如何区分

### 4.1 先看出什么码

| 码 | 含义（现场记这个就够） | 日志上怎么认 |
|----|------------------------|----------------|
| **1001** `K_RPC_DEADLINE_EXCEEDED` | 通用 **`Event::WaitFor` / `WaitAny` 超时**（**不是** URMA 专用） | `Timed out waiting for request` / `Timed out waiting for any event` |
| **1010** `K_URMA_WAIT_TIMEOUT` | **仅 URMA 完成等待**对外映射（`UrmaManager::WaitToFinish`） | 业务 Status；`UrmaManager` 部分路径带 **`[URMA_WAIT_TIMEOUT]`** 前缀文案 |
| **1002** `K_RPC_UNAVAILABLE` | TCP/UDS/ZMQ/RPC 等「不可用」大类 | **Status 消息前缀** 区分子场景（下表） |

详细语义与评审后约定见：`plans/urma-tcp-定界修复需求/kv-client-URMA环境验证执行清单.md` §1、§5。**日志字面量与字段级说明以本文 §2 为准。**

### 4.2 URMA 域：检索关键字

```bash
LOG_PATH=/path/to/logs   # 文件或目录

grep -R -E 'URMA_NEED_CONNECT|remoteAddress=|remoteInstanceId=|remoteWorkerId=' "$LOG_PATH"
grep -R -E 'URMA_POLL_ERROR|PollJfcWait failed' "$LOG_PATH"
grep -R -E 'URMA_RECREATE_JFS|URMA_RECREATE_JFS_FAILED|URMA_RECREATE_JFS_SKIP|newJfsId' "$LOG_PATH"
grep -R -E '\[URMA_WAIT_TIMEOUT\]' "$LOG_PATH"
```

**代码侧验证（本地仓库 grep，确认字符串存在）**：`URMA_NEED_CONNECT` / `URMA_POLL_ERROR` / `URMA_RECREATE_JFS` 等出现在  
`src/datasystem/common/rdma/urma_manager.cpp`、`urma_resource.cpp` 及 worker OC 服务路径（如 `worker_oc_service_get_impl.cpp`）。

### 4.3 TCP / RPC 域：`1002` 子分类前缀（检索）

至少掌握下列前缀之一出现在 **Status 或日志正文** 即属 TCP/RPC 域定界（与 `validate_urma_tcp_observability_logs.sh` 一致）：

`[RPC_RECV_TIMEOUT]`、`[RPC_SERVICE_UNAVAILABLE]`、`[TCP_CONNECT_RESET]`、`[TCP_CONNECT_FAILED]`、`[UDS_CONNECT_FAILED]`、`[SOCK_CONN_WAIT_TIMEOUT]`、`[REMOTE_SERVICE_WAIT_TIMEOUT]`、`[SHM_FD_TRANSFER_FAILED]`、`[TCP_NETWORK_UNREACHABLE]`

前缀与字段含义见 **本文 §2.1**。

### 4.4 自动化：URMA/TCP 日志脚本

```bash
cd /path/to/vibe-coding-files
bash scripts/testing/verify/validate_urma_tcp_observability_logs.sh /path/to/logs
```

脚本要求（面向**已采集含故障的**联调日志）：命中 `URMA_NEED_CONNECT` + `remoteAddress=`、`URMA_POLL_ERROR`、`URMA_RECREATE_JFS*` 至少一类，且 **1002 子类前缀至少 3 种**。若现场日志不满足（例如无 URMA 故障），脚本会失败 —— 此时用 §4.2/4.3 **手工 grep** 分项验收即可。

URMA 环境专项验证步骤见：`./env-validation.md`。

---

## 5. 现场验收 Checklist（简版）

- [ ] **定界流程**：拿到监控上的 **Status + 接口 + 时延** 后，能按 **§3.1** 五步走到「客户端 / Worker / 传输」之一并说明依据  
- [ ] **KV + ZMQ metrics**：能在 **Metrics Summary** 中定位 **`client_*` / `worker_*` / `zmq_*`**，并读懂 **Total** 与 **Compare +delta**（§3.2）  
- [ ] **产品日志**：能解释 **限频** 下「`zmq_*` metrics 涨了但未必每行都有 `[ZMQ_*_FAILURE_TOTAL]`」  
- [ ] **URMA/TCP**：能区分 **1001 / 1010 / 1002**，并各举 **1 个** 可 grep 的关键字（§2 / §4）  
- [ ] **1002**：能说出至少 **3 个** 子分类前缀（§2.1 / §4.3）  

---

## 6. 相关文件索引

| 路径 | 用途 |
|------|------|
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | `[TCP_NETWORK_UNREACHABLE]`、`[SOCK_CONN_WAIT_TIMEOUT]`、`[REMOTE_SERVICE_WAIT_TIMEOUT]`、`[RPC_RECV_TIMEOUT]` 建连、`[RPC_SERVICE_UNAVAILABLE]`、`ZMQ_GATEWAY_RECREATE_TOTAL` |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | ZMQ send/recv metrics + `[ZMQ_*_FAILURE_TOTAL]` |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_socket.cpp` | `[ZMQ_RECV_TIMEOUT]` 阻塞路径 |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_msg_queue.h` | `[RPC_RECV_TIMEOUT]`（MsgQ 客户端升格） |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_stub_impl.h` | `[RPC_RECV_TIMEOUT]` + `LOG(WARNING)` 异步收 |
| `yuanrong-datasystem/src/datasystem/common/rpc/unix_sock_fd.cpp` | `[TCP_CONNECT_*]`、`[UDS_CONNECT_FAILED]` |
| `yuanrong-datasystem/src/datasystem/client/client_worker_common_api.cpp` | `[SHM_FD_TRANSFER_FAILED]` |
| `yuanrong-datasystem/src/datasystem/common/rdma/rdma_util.h` | 1001 通用 `Timed out waiting for ...` |
| `yuanrong-datasystem/src/datasystem/common/metrics/kv_metrics.cpp` | **`client_*` / `worker_*` / `zmq_*`** 全量 `MetricDesc` 注册 |
| `vibe-coding-files/workspace/observability/kv_metrics_print_summary_ut.log` | 一次 **`PrintSummary`** 全量输出归档（含 0–35 全部指标名，便于 `grep` 对照） |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_monitor.cpp` | `zmq_event_disconnect_total`、`zmq_event_handshake_failure_total` |
| `yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp` | URMA 日志前缀主路径 |
| `vibe-coding-files/scripts/testing/verify/validate_urma_tcp_observability_logs.sh` | URMA/TCP 关键字批量验收 |
| `../2026-04-zmq-rpc-metrics/test-walkthrough.md` | plans 内 ZMQ 专题（含仓库 `tests/` 故障注入说明，与本文独立） |
| `./env-validation.md` | URMA 构建与日志 §5 |

---

*文档版本：与 yuanrong-datasystem + vibe-coding-files 当前 tree 对齐；§2 按源码 `FormatString` 核对；§3.1 为监控侧 **Status + 接口 + 时延** 定界流程；§3.2 对齐 PR !586 与 `kv_metrics.cpp`（**KV + ZMQ** 全表）；§3.2.3 中 **82/82** 与 **`MetricsTest.kv_metrics_print_summary_test`** 摘录为 2026-04-17 远端 `ds_ut` 实测；本文正文不写 ST 专用埋点，故障注入串讲见 plans 内专题文档。*
