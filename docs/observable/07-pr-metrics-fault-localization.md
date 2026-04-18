# 07 · PR 集 #583 / #584 / #586 / #588 —— 基于 Metrics 的观测与定位定界实操

> **面向读者**：功能测试、现场联调、研发值班。
>
> **目标**：把 2026-04 合入主干的四个 PR 的观测能力拉通，给出「看哪条 metric / 哪个日志标签 → 落到哪段代码 → 判哪一层故障」的一站式对照。每个结论都指向具体源码位置，可用 `rg` / `grep` 脚本复核。
>
> **与本目录其它文档的关系**
>
> - 本文是 **PR 串讲 + metrics 查表** —— 直接面向"拿到一份 `worker.log` / `sdk.log` 该怎么看"的现场场景。
> - [`05-metrics-and-perf.md`](05-metrics-and-perf.md) 是 **稳定的 metrics 清单与性能路径**，不随单次 PR 变动。本文引用它，不重复列。
> - [`04-triage-handbook.md`](04-triage-handbook.md) 是 **Trace × 责任域 SOP**，本文的 §6 决策树是它的 metrics 视图补充。
> - 两份 RFC 的设计背景见 [`../../rfc/2026-04-zmq-rpc-metrics/`](../../rfc/2026-04-zmq-rpc-metrics/README.md) 与 [`../../rfc/2026-04-kvclient-urma-tcp-observability/`](../../rfc/2026-04-kvclient-urma-tcp-observability/README.md)。

---

## 0. 四个 PR 速览

| PR | 标题 | 承担角色 | 产物 |
|----|------|---------|------|
| [#584](https://gitcode.com/openeuler/yuanrong-datasystem/pull/584) | Add lightweight metrics framework | **地基** | `common/metrics/metrics.{h,cpp}`：`Counter` / `Gauge` / `Histogram` / `ScopedTimer`；周期 `Metrics Summary` 文本输出 |
| [#586](https://gitcode.com/openeuler/yuanrong-datasystem/pull/586) | Add KV metrics instrumentation | **业务埋点** | `common/metrics/kv_metrics.{h,cpp}`：`KvMetricId` 枚举 + `InitKvMetrics()`；Client / Worker 关键接口 23 条 KV metrics |
| [#588](https://gitcode.com/openeuler/yuanrong-datasystem/pull/588) | `feat(zmq)`: add metrics for ZMQ I/O fault isolation and performance profiling | **传输面埋点** | 13 条 ZMQ metrics（合并到同一个 `KvMetricId` 枚举，ID 23–35）；`[ZMQ_*_FAILURE_TOTAL]`、`[ZMQ_RECV_TIMEOUT]` 日志标签；`LOG_FIRST_EVERY_N` 限流宏 |
| [#583](https://gitcode.com/openeuler/yuanrong-datasystem/pull/583) | `feat`: improve URMA/TCP observability | **日志/错误码** | 新错误码 `K_URMA_WAIT_TIMEOUT=1010`；`[URMA_*]` / `[TCP_*]` / `[RPC_*]` / `[UDS_*]` / `[SHM_*]` 结构化日志标签；`UrmaEvent` 新增 remoteAddress/instanceId/OperationType |

**依赖关系**：`#584` → `#586` + `#588`（后两者都依赖框架）；`#583` 与 `#586`/`#588` 并行合入，`#588` 在 `#586` 的枚举尾部追加了 ZMQ 段。`#583` 不新增 metrics，而是补齐 **1002 桶码的日志分流前缀**，与 metrics 相辅相成（metrics 看计数，日志看现场）。

> 实际 merge order：`46867bad (#584)` → `749f90db (#586)` → `ca14e25b (#583)` → `1b98d5c6 (#588)`。
> 可执行 `cd yuanrong-datasystem && git log --all --oneline | grep -E '!58[34568]'` 复核。

---

## 1. metrics 落地位置全览（代码锚点）

### 1.1 metric 名 ↔ 枚举 ↔ 采集点

以下表格的三列名称可以**逐字**在代码中找到（脚注给出最短 `rg` 复核命令）。

| ID | `KvMetricId` 枚举 | 文本 metric 名（Summary 输出用） | 类型 | 单位 | 采集点（源码） |
|----|-------------------|-----------------------------------|------|------|----------------|
| 0  | `CLIENT_PUT_REQUEST_TOTAL` | `client_put_request_total` | Counter | count | `client/kv_cache/kv_client.cpp`（`Create` / `MCreate` / `MSet` / `MSetTx` 等） |
| 1  | `CLIENT_PUT_ERROR_TOTAL` | `client_put_error_total` | Counter | count | 同上（`METRIC_ERROR_IF(rc.IsError(), ...)`） |
| 2  | `CLIENT_GET_REQUEST_TOTAL` | `client_get_request_total` | Counter | count | `client/kv_cache/kv_client.cpp`（`Get` 一族） |
| 3  | `CLIENT_GET_ERROR_TOTAL` | `client_get_error_total` | Counter | count | 同上 |
| 4  | `CLIENT_RPC_CREATE_LATENCY` | `client_rpc_create_latency` | Histogram | us | `client/.../client_worker_local_api.cpp` & `client_worker_remote_api.cpp` 的 `Create` / `MultiCreate` |
| 5  | `CLIENT_RPC_PUBLISH_LATENCY` | `client_rpc_publish_latency` | Histogram | us | 同上的 `Publish` / `MultiPublish` |
| 6  | `CLIENT_RPC_GET_LATENCY` | `client_rpc_get_latency` | Histogram | us | 同上的 `Get` |
| 7  | `CLIENT_PUT_URMA_WRITE_TOTAL_BYTES` | `client_put_urma_write_total_bytes` | Counter | bytes | `client/object_cache/client_worker_api/client_worker_base_api.cpp::SendBufferViaUb` |
| 8  | `CLIENT_PUT_TCP_WRITE_TOTAL_BYTES` | `client_put_tcp_write_total_bytes` | Counter | bytes | `client_worker_local_api.cpp::Publish / MultiPublish`、`client_worker_remote_api.cpp::Publish` |
| 9  | `CLIENT_GET_URMA_READ_TOTAL_BYTES` | `client_get_urma_read_total_bytes` | Counter | bytes | `worker/object_cache/worker_request_manager.cpp::UbWriteHelper` |
| 10 | `CLIENT_GET_TCP_READ_TOTAL_BYTES` | `client_get_tcp_read_total_bytes` | Counter | bytes | `worker/object_cache/worker_request_manager.cpp::AddObjectToResponse` |
| 11 | `WORKER_RPC_CREATE_META_LATENCY` | `worker_rpc_create_meta_latency` | Histogram | us | `worker/object_cache/worker_master_oc_api.cpp::CreateMeta`（Local+Remote） |
| 12 | `WORKER_RPC_QUERY_META_LATENCY` | `worker_rpc_query_meta_latency` | Histogram | us | 同上 `QueryMeta` |
| 13 | `WORKER_RPC_GET_REMOTE_OBJECT_LATENCY` | `worker_rpc_get_remote_object_latency` | Histogram | us | `worker/object_cache/worker_worker_oc_api.cpp::GetObjectRemote` & 对应 service impl |
| 14 | `WORKER_PROCESS_CREATE_LATENCY` | `worker_process_create_latency` | Histogram | us | `worker/object_cache/worker_oc_service_impl.cpp::Create / MultiCreate` |
| 15 | `WORKER_PROCESS_PUBLISH_LATENCY` | `worker_process_publish_latency` | Histogram | us | 同上 `Publish / MultiPublish` |
| 16 | `WORKER_PROCESS_GET_LATENCY` | `worker_process_get_latency` | Histogram | us | 同上 `Get` |
| 17 | `WORKER_URMA_WRITE_LATENCY` | `worker_urma_write_latency` | Histogram | us | `worker/object_cache/worker_request_manager.cpp::UbWriteHelper` |
| 18 | `WORKER_TCP_WRITE_LATENCY` | `worker_tcp_write_latency` | Histogram | us | `worker/object_cache/worker_request_manager.cpp::AddObjectToResponse` |
| 19 | `WORKER_TO_CLIENT_TOTAL_BYTES` | `worker_to_client_total_bytes` | Counter | bytes | 同上两个函数 |
| 20 | `WORKER_FROM_CLIENT_TOTAL_BYTES` | `worker_from_client_total_bytes` | Counter | bytes | `worker_oc_service_impl.cpp::Publish / MultiPublish` |
| 21 | `WORKER_OBJECT_COUNT` | `worker_object_count` | Gauge | count | `worker_oc_service_impl.cpp::UpdateWorkerObjectGauge`（随每次 Create/Publish 更新） |
| 22 | `WORKER_ALLOCATED_MEMORY_SIZE` | `worker_allocated_memory_size` | Gauge | bytes | 同上（`Allocator::GetMemStat(stat).objectMemoryUsage`） |
| 23 | `ZMQ_SEND_FAILURE_TOTAL` | `zmq_send_failure_total` | Counter | count | `common/rpc/zmq/zmq_socket_ref.cpp::SendMsg`（硬失败，非 EAGAIN/EINTR） |
| 24 | `ZMQ_RECEIVE_FAILURE_TOTAL` | `zmq_receive_failure_total` | Counter | count | 同上 `RecvMsg` |
| 25 | `ZMQ_SEND_TRY_AGAIN_TOTAL` | `zmq_send_try_again_total` | Counter | count | 同上 `SendMsg`（`errno == EAGAIN`） |
| 26 | `ZMQ_RECEIVE_TRY_AGAIN_TOTAL` | `zmq_receive_try_again_total` | Counter | count | 同上 `RecvMsg`（**仅 `flags == NONE` 即 blocking 模式**） |
| 27 | `ZMQ_NETWORK_ERROR_TOTAL` | `zmq_network_error_total` | Counter | count | 同上（`IsZmqSocketNetworkErrno(errno)` 命中） |
| 28 | `ZMQ_LAST_ERROR_NUMBER` | `zmq_last_error_number` | **Gauge** | — | 同上（`Set(errno)`，最近一次硬失败） |
| 29 | `ZMQ_GATEWAY_RECREATE_TOTAL` | `zmq_gateway_recreate_total` | Counter | count | `common/rpc/zmq/zmq_stub_conn.cpp::ZmqFrontend::WorkerEntry`（紧跟 "New gateway created" 日志） |
| 30 | `ZMQ_EVENT_DISCONNECT_TOTAL` | `zmq_event_disconnect_total` | Counter | count | `common/rpc/zmq/zmq_monitor.cpp::OnEventDisconnected` |
| 31 | `ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL` | `zmq_event_handshake_failure_total` | Counter | count | 同上 `OnEventHandshakeFailed{NoDetail,Protocol,Auth}` 三个回调 |
| 32 | `ZMQ_SEND_IO_LATENCY` | `zmq_send_io_latency` | Histogram | us | `zmq_socket_ref.cpp::SendMsg` 包住 `zmq_msg_send` 的 `METRIC_TIMER` 作用域 |
| 33 | `ZMQ_RECEIVE_IO_LATENCY` | `zmq_receive_io_latency` | Histogram | us | 同上 `RecvMsg` 包住 `zmq_msg_recv` |
| 34 | `ZMQ_RPC_SERIALIZE_LATENCY` | `zmq_rpc_serialize_latency` | Histogram | us | `common/rpc/zmq/zmq_common.h::SerializeToZmqMessage`（只覆 `pb.SerializeToArray`） |
| 35 | `ZMQ_RPC_DESERIALIZE_LATENCY` | `zmq_rpc_deserialize_latency` | Histogram | us | 同上 `ParseFromZmqMessage`（只覆 `pb.ParseFromArray`） |

**ID / 名称 ↔ 代码对齐证据（可复核）**：

```bash
# 枚举顺序
rg -n "enum class KvMetricId" -A 40 yuanrong-datasystem/src/datasystem/common/metrics/kv_metrics.h

# 文本名与 ID 一一对应（顺序即 ID）
rg -n "KV_METRIC_DESCS" -A 45 yuanrong-datasystem/src/datasystem/common/metrics/kv_metrics.cpp

# 所有采集点（1 条命令看全局埋点地图）
rg -n "KvMetricId::" yuanrong-datasystem/src
```

### 1.2 两个 Init / 两种周期驱动（研发必看）

| 进程 | `metrics::InitKvMetrics` 位置 | `metrics::Tick()` 触发点 | `PrintSummary()` |
|------|-------------------------------|--------------------------|------------------|
| **Worker** | `worker/worker_oc_server.cpp::WorkerOCServer::Start`（`ReadinessProbe()` 之后） | `worker/worker_main.cpp` 主循环每秒 `metrics::Tick()` | `worker_main.cpp` 退出前 `metrics::PrintSummary()` |
| **Client (SDK)** | `client/kv_cache/kv_client.cpp::Init` / `InitEmbedded`；`client/object_cache/object_client.cpp::Init`（`(void)metrics::InitKvMetrics();`） | `client/object_cache/object_client_impl.cpp::StartMetricsThread` 启的后台线程每 1s `metrics::Tick()`（受 `FLAGS_log_monitor` 门控） | `ObjectClientImpl::ShutdownMetricsThread(dumpSummary=true)`（非析构路径） |

`Tick()` 内部若距上一次 `Tick` 不满 `FLAGS_log_monitor_interval_ms`（默认 **10000 ms**）直接 return；达到周期才会走 `LogSummary`，打出 `Metrics Summary` 文本块 —— 所以实际 **summary 周期是 `log_monitor_interval_ms`**，1s 只是 tick 调度粒度。

> 关键 gflag：`-log_monitor=true`（默认开）、`-log_monitor_interval_ms=10000`。关掉 `log_monitor` 会让 `Tick()` / `PrintSummary()` 都变空操作，但 metric 值**仍然累加**，只是不再周期落盘。

### 1.3 输出格式（`BuildSummary`，`metrics.cpp:128-171`）

```
Metrics Summary, version=v0, cycle=<N>, interval=<intervalMs>ms

Total:
<metric_name>=<value>[<suffix>]
<hist_name>,count=<c>,avg=<a><suffix>,max=<m><suffix>
...

Compare with <intervalMs>ms before:
<metric_name>=+<delta>[<suffix>]
<hist_name>,count=+<dc>,avg=<da><suffix>,max=<period_max><suffix>
...
```

关键特征：

- **`Total` 段**：累计量（Counter / Gauge 当前值 / Histogram 的 count+avg+max）。
- **`Compare with ... before` 段**：与上一次 Summary 的 **delta**。Histogram 的 `max` 在 delta 段是 **本周期 `periodMax`**，每次 dump 后清零。
- **`cycle` 是本机计数器**，与时钟无关 —— 跨机器对齐用 cycle 号，不要用时间戳（见 §5）。
- `suffix` 规则（`BuildSuffix`）：`count` → 空；`bytes` → `B`；其它原样保留（如 `us`）。

---

## 2. PR #583 补齐的日志标签清单

`#583` 不改 `StatusCode` 枚举值（除了新增 1010 = `K_URMA_WAIT_TIMEOUT`），而是在每个会返回 RPC/URMA 错误的点**加前缀**，让测试可以用「标签 + grep」无歧义分流 1002 桶码。

| 标签 | 源码位置 | 触发语义 |
|------|----------|---------|
| `[URMA_WAIT_TIMEOUT]` | `common/rdma/urma_manager.cpp::WaitToFinish`（2 处：`timeoutMs<0` 分支 + 注入点） | URMA 事件等待超时（`K_URMA_WAIT_TIMEOUT` = 1010） |
| `[URMA_POLL_ERROR]` | `common/rdma/urma_manager.cpp::ServerEventHandleThreadMain` | `PollJfcWait` 报错（非 `K_TRY_AGAIN`），带 success/failed 计数 |
| `[URMA_NEED_CONNECT]` | `common/rdma/urma_manager.cpp::CheckUrmaConnectionStable`（3 处：无连接 / 陈旧 / 无 instanceId）<br>`worker/object_cache/service/worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker`<br>`worker/object_cache/worker_worker_oc_service_impl.cpp::CheckConnectionStable` | 触发 URMA 重连；`LOG_FIRST_AND_EVERY_N(100)` 限流，**首次一定会打** |
| `[URMA_RECREATE_JFS]` | `common/rdma/urma_manager.cpp::HandleUrmaEvent`<br>`common/rdma/urma_resource.cpp::MarkAndRecreate` | JFS 重建（带 `requestId / op / remoteAddress / remoteInstanceId / cqeStatus`） |
| `[URMA_RECREATE_JFS_FAILED]` | `urma_manager.cpp::HandleUrmaEvent` | `ReCreateJfs` 返回错误 |
| `[URMA_RECREATE_JFS_SKIP]` | `urma_manager.cpp` + `urma_resource.cpp` | connection 已过期 / 已无效，跳过重建 |
| `[ZMQ_RECV_TIMEOUT]` | `common/rpc/zmq/zmq_socket.cpp::ZmqRecvMsg` | **阻塞 recv + ZMQ_RCVTIMEO** 路径超时（非 client stub 的 `poll+DONTWAIT` 路径） |
| `[ZMQ_SEND_FAILURE_TOTAL]` | `common/rpc/zmq/zmq_socket_ref.cpp::SendMsg`（#588 引入，标签沿用） | `zmq_msg_send` 返回 -1 且 `errno != EAGAIN/EINTR`；带 `errno=<n>(<str>)`；`LogFirstEveryNShouldEmit(100, ...)` 限流 |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | 同上 `RecvMsg` | `zmq_msg_recv` 硬失败 |
| `[RPC_RECV_TIMEOUT]` | `common/rpc/zmq/zmq_stub_conn.cpp::ZmqSockConnHelper::GetEndPoint`<br>`common/rpc/zmq/zmq_msg_queue.h::RpcStub::Recv`<br>`common/rpc/zmq/zmq_stub_impl.h::Recv` | `K_RPC_UNAVAILABLE` 场景下 client 侧等应答超时 |
| `[RPC_SERVICE_UNAVAILABLE]` | `zmq_stub_conn.cpp::BackendToFrontend` / `Outbound` | 服务端把错误回包给 client（队列清空时） |
| `[SOCK_CONN_WAIT_TIMEOUT]` | `zmq_stub_conn.cpp::SockConnEntry::WaitForConnected` | 连接建立等待超时 |
| `[REMOTE_SERVICE_WAIT_TIMEOUT]` | 同上（`connInProgress` 仍为 true 超时） | 连接尚未完成但已超时 |
| `[TCP_NETWORK_UNREACHABLE]` | `zmq_stub_conn.cpp::SendHeartBeats` | `ZMQ_POLLOUT` 失败 |
| `[TCP_CONNECT_RESET]` | `common/rpc/unix_sock_fd.cpp::ErrnoToStatus` | `ECONNRESET` / `EPIPE` |
| `[TCP_CONNECT_FAILED]` | 同上 `ConnectTcp` | `addrinfo` 遍历完仍无法 `connect()` |
| `[UDS_CONNECT_FAILED]` | 同上 `Connect`（Unix domain socket） | UDS `connect()` 失败 |
| `[SHM_FD_TRANSFER_FAILED]` | `client/client_worker_common_api.cpp::Connect` | 无法建立传 shm fd 的辅助连接（`mustUds=true`） |

**可复核命令**：

```bash
# 本仓 source 中所有带方括号前缀的日志/errMsg
rg -n "\[URMA_[A-Z_]+\]|\[ZMQ_[A-Z_]+\]|\[TCP_[A-Z_]+\]|\[UDS_[A-Z_]+\]|\[SHM_[A-Z_]+\]|\[RPC_[A-Z_]+\]|\[SOCK_[A-Z_]+\]|\[REMOTE_[A-Z_]+\]" yuanrong-datasystem/src
```

---

## 3. 场景 × Metrics × Log 标签对照表

**使用方法**：按业务现象找行 → 在 `sdk.log` / `worker.log` 先 grep 「主证据」→ 再看 metrics Summary 印证。**缺其中一侧不是失败** —— 测试串讲（[`../../rfc/2026-04-zmq-rpc-metrics/test-walkthrough.md`](../../rfc/2026-04-zmq-rpc-metrics/test-walkthrough.md) §6）已说明为何 stub 的 `poll+DONTWAIT` 主路径下 `zmq_receive_failure_total` 常为 0。

### 3.1 控制面 / 传输面（ZMQ）

| 现象 | 主证据（看什么） | 次证据（再看什么） | 定界结论 |
|------|-------------------|--------------------|----------|
| 杀 server / 对端 crash | `zmq_gateway_recreate_total` delta > 0；`[RPC_SERVICE_UNAVAILABLE]` | `zmq_event_disconnect_total` 可能 +N（异步，可迟到）；`zmq_last_error_number` 可能为 0（走 stub poll，不落硬 errno） | **连接层** 感知到断连（#588 埋点）；stub 通过重建网关恢复 |
| 网卡/路由硬故障 | `zmq_send_failure_total` 或 `zmq_receive_failure_total` +N；`[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECEIVE_FAILURE_TOTAL]` 日志 | `zmq_network_error_total` +N；`zmq_last_error_number`=113(`EHOSTUNREACH`) / 104(`ECONNRESET`) 等 | **底层网络** 失败，`IsZmqSocketNetworkErrno` 命中（`zmq_network_errno.h`） |
| server 响应慢，client RPC 超时 | `zmq_receive_io_latency` max / avg 上升；`[RPC_RECV_TIMEOUT]` | ZMQ fault Counter **全 0**；`zmq_gateway_recreate_total` 不涨 | **服务端慢** 或 **框架排队**；**不**是 ZMQ 硬失败 |
| 阻塞 recv 超时（RCVTIMEO 路径） | `[ZMQ_RECV_TIMEOUT]` 日志 | `zmq_receive_try_again_total` +N（因为 blocking + EAGAIN） | 走到 `ZmqSocket::ZmqRecvMsg` 的阻塞分支（非 stub DONTWAIT） |
| 连接建不上 / 握手失败 | `zmq_event_handshake_failure_total` +N；`[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]` | `zmq_event_disconnect_total` +N | 证书/认证/协议层面（`OnEventHandshakeFailed*`） |
| HWM 背压 | `zmq_send_try_again_total` 持续上涨 | ZMQ fault 其它 Counter 全 0；`zmq_send_io_latency max` 偶发 | 本端或对端 send 队列满，不算硬错 |
| TCP/UDS 建连失败 | `[TCP_CONNECT_FAILED]` / `[UDS_CONNECT_FAILED]` / `[TCP_CONNECT_RESET]` / `[TCP_NETWORK_UNREACHABLE]` | StatusCode 仍为 `K_RPC_UNAVAILABLE`（1002）；不直接对应 metrics | #583 日志分流：同一 1002 靠标签区分根因 |

### 3.2 数据面（URMA）

| 现象 | 主证据 | 次证据 | 定界结论 |
|------|--------|--------|----------|
| URMA 事件等待超时 | `[URMA_WAIT_TIMEOUT]`；StatusCode=1010 (`K_URMA_WAIT_TIMEOUT`) | `worker_urma_write_latency` 有值但 `client_get_urma_read_total_bytes` delta 没涨上去 | #583 新错误码（原 `K_RPC_DEADLINE_EXCEEDED` 拆分出来）；进入 `RetryOnRPCErrorByTime` / batch get 的重试白名单 |
| URMA 连接失效 / 需要重连 | `[URMA_NEED_CONNECT]`（远端地址 + 远端 instanceId） | 之后可能出现 `[URMA_RECREATE_JFS]` + `worker_urma_write_latency` 先跌后恢复 | 三种子场景：无连接 / cachedInstanceId 与请求不一致 / instanceId 为空（见 `CheckUrmaConnectionStable` 三个分支） |
| URMA poll jfc 异常 | `[URMA_POLL_ERROR] PollJfcWait failed: ...` | `worker_urma_write_latency` max 飙升；`client_get_urma_read_total_bytes` 不涨 | 驱动 / 硬件层异常（`ServerEventHandleThreadMain`） |
| URMA JFS 重建 | `[URMA_RECREATE_JFS] requestId=... op=READ/WRITE remoteAddress=... cqeStatus=...` | 可能伴随 `[URMA_RECREATE_JFS_FAILED]` 或 `[URMA_RECREATE_JFS_SKIP]` | cqe 状态异常后主动重建；**首次** 100% 打，后续 `LOG_FIRST_AND_EVERY_N(100)` 采样 |
| URMA 降级到 TCP | `client_put_tcp_write_total_bytes` / `client_get_tcp_read_total_bytes` **delta 突增** 的同时 `client_put_urma_write_total_bytes` / `client_get_urma_read_total_bytes` delta 不涨 | 与 `worker_tcp_write_latency` / `worker_urma_write_latency` 分布对比 | UB 面不可用，走 TCP payload；注意：**降级本身不会** 增加 ZMQ fault Counter |

### 3.3 业务面（KV Client ↔ Worker）

| 现象 | 主证据 | 次证据 | 定界结论 |
|------|--------|--------|----------|
| KV Put 报错率上升 | `client_put_error_total` delta / `client_put_request_total` delta | `worker_process_publish_latency` / `worker_process_create_latency` avg 是否同步涨；worker 侧 `access log` | Client 统计 ≠ Worker 收到：差值反映 **client→worker 传输层** 丢失（看 §3.1） |
| KV Get 报错率上升 | `client_get_error_total` / `client_get_request_total` delta | `worker_process_get_latency`；`worker_rpc_get_remote_object_latency`（跨 worker） | 同上 |
| 写放大检测 | `worker_from_client_total_bytes` delta / `client_put_request_total` delta | 看单次请求写入字节数 | 客户端是否切了批量 / 压缩策略有效 |
| Worker 内存被吃爆 | `worker_allocated_memory_size` gauge；`worker_object_count` gauge | 对照 `resource.log` `SHARED_MEMORY` | `objectMemoryUsage` 与对象数分别定位「大对象」 vs「对象泄漏」 |
| 跨 worker Get 慢 | `worker_rpc_get_remote_object_latency` avg/max 高 | 远端 worker 的 `worker_process_get_latency` | Remote 侧业务慢 vs 网络慢可对分 |
| master 元数据慢 | `worker_rpc_create_meta_latency` / `worker_rpc_query_meta_latency` | etcd resource.log 中 `ETCD_QUEUE` / `ETCD_REQUEST_SUCCESS_RATE` | Master / etcd 控制面瓶颈 |

---

## 4. 测试现场速查 grep 模板

> 假定日志路径：Worker 进程 stderr/`worker.log`、Client 进程 `sdk.log`（取决于调用方如何重定向）。若只有混合输出，同一 `grep` 命令即可。

```bash
# 4.1 先看 metrics summary 总览（cycle 编号可用来做时间锚点）
grep -E "^Metrics Summary|^Total:|^Compare with" worker.log sdk.log

# 4.2 ZMQ 传输面指标（建议按 delta 看）
grep -E "zmq_(send|receive)_(failure|try_again)_total|zmq_network_error_total|zmq_last_error_number|zmq_gateway_recreate_total|zmq_event_(disconnect|handshake_failure)_total|zmq_(send|receive)_io_latency|zmq_rpc_(serialize|deserialize)_latency" worker.log sdk.log

# 4.3 KV 业务面指标
grep -E "client_(put|get)_(request|error)_total|client_(put|get)_(urma_write|tcp_write|urma_read|tcp_read)_total_bytes|client_rpc_(create|publish|get)_latency|worker_(process|rpc)_(create|publish|get|query_meta|get_remote_object)(_meta)?_latency|worker_(urma|tcp)_write_latency|worker_(to|from)_client_total_bytes|worker_(object_count|allocated_memory_size)" worker.log sdk.log

# 4.4 #583 结构化日志标签（1002 桶码分流 + URMA）
grep -E "\[URMA_(WAIT_TIMEOUT|POLL_ERROR|NEED_CONNECT|RECREATE_JFS(_FAILED|_SKIP)?)\]|\[ZMQ_(RECV_TIMEOUT|SEND_FAILURE_TOTAL|RECEIVE_FAILURE_TOTAL)\]|\[RPC_(RECV_TIMEOUT|SERVICE_UNAVAILABLE)\]|\[(SOCK_CONN_WAIT_TIMEOUT|REMOTE_SERVICE_WAIT_TIMEOUT|TCP_CONNECT_RESET|TCP_CONNECT_FAILED|TCP_NETWORK_UNREACHABLE|UDS_CONNECT_FAILED|SHM_FD_TRANSFER_FAILED)\]" worker.log sdk.log

# 4.5 故障注入串讲标签（仅 ZmqMetricsFaultTest 这类 ST 会打）
grep -E "\[FAULT INJECT\]|\[METRICS DUMP -|\[ISOLATION\]|\[SELF-PROOF( REPORT)?\]|^CONCLUSION:" st_fault.log
```

仓库内已有自动化脚本可直接跑：

- `vibe-coding-files/scripts/testing/verify/summarize_observability_log.sh <log>` —— **本次 PR 集的聚合表**：把 metrics 最近一次 delta + 所有结构化日志标签命中次数打成速查表，跑一次即拿到 §3 场景表所需全部信号。
- `vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh <log>` —— ZMQ 故障四场景校验（来自 #588 的 ST）。
- `vibe-coding-files/scripts/testing/verify/validate_urma_tcp_observability_logs.sh <log>` —— URMA/TCP 日志前缀数量校验（来自 #583 的验收，目标 ≥3 个前缀出现过）。

### 4.6 ST 跑 `ds_st_kv_cache`：mock OBS、`rootDir` 子进程日志、远端一键采集

`ds_st` 父进程的 **stderr / 聚合 glog** 里常常**看不到** `Metrics Summary`：`LogSummary` 打在 **worker**（`datasystem_worker`）与 **client**（`ds_client`）各自进程里，路径在当次用例的 **`rootDir`** 下，例如：

- `…/KVClientMSetPerfTest.MsetNtxSmallObj/worker0/log/`（`datasystem_worker.*.INFO.*`）
- `…/KVClientMSetPerfTest.MsetNtxSmallObj/client/`（`ds_client*.INFO.*`）

`ds_st_full.log` 首条含 `rootDir:` 的行给出本次目录（可能带 `cluster/../ds/…` 段）；拉取后可用 `readlink -f` 规范化再 `grep`。

**mock OBS**：`external_cluster.cpp::StartOBS` 使用 `getcwd() + "/../../../tests/st/cluster/mock_obs_service.py"`。工作目录必须是仓库根下**恰好三层**子目录（例如 `yuanrong-datasystem/.st_metrics_wr/a/b`），否则相对路径会指到仓库外并报找不到 mock。采集脚本已按此 `cd` 再启动二进制。

**异步缓冲**：子进程日志常见 `Async logging buffer duration: 10 s`。若 wall 时间只略大于 `log_monitor_interval_ms`，可能出现「周期 Summary 已触发但尚未 flush」或进程过早退出导致 **grep 仍为空**。需要稳定样本时：令 **worker 存活 ≥ 2× `log_monitor_interval_ms` + ~15s**，或把 `-log_monitor_interval_ms` 降到 5000–8000 并略延长用例；远端 **worker/client 需为含 `InitKvMetrics` 的构建**，否则子进程日志里也不会有 `Metrics Summary, version=v0`。

**一键远端采集（≈30s KV ST + grep + 可选子目录 tar）**：流程与 [`run_zmq_rpc_metrics_remote.sh`](../../scripts/testing/verify/run_zmq_rpc_metrics_remote.sh) 对齐——默认 **`rsync` 源码到远端**、`**BUILD_BACKEND=bazel**` 下 `bazel build //tests/st/client/kv_cache:kv_client_mset_test` 后从 `bazel-bin/.../kv_client_mset_test` 启动（仍 `cd` 到 `.st_metrics_wr/a/b` 以满足 mock OBS）。`BUILD_BACKEND=cmake` 时仍用 `${REMOTE_BUILD}/tests/st/ds_st_kv_cache`。Bazel 编译的 `st_cluster` 将 **`WORKER_BIN_PATH` 固定为 `/usr/local/bin/datasystem_worker`**（与 ZMQ ST 相同），远端需已有该可执行文件或与当前 metrics 代码一致的安装；否则改用 cmake 全量构建或先同步 worker 到该路径。

```bash
# 默认：bazel、root@38.76.164.55、MsetNtxSmallObj、LOG_MONITOR_MS=8000、拉 worker*/log + client
bash vibe-coding-files/scripts/testing/verify/run_kv_rw_metrics_remote_capture.sh

# 仅远端已有树：SKIP_RSYNC=1；纯 CMake：BUILD_BACKEND=cmake
# SKIP_RSYNC=1 BUILD_BACKEND=cmake bash vibe-coding-files/scripts/testing/verify/run_kv_rw_metrics_remote_capture.sh
```

产物：`results/kv_rw_metrics_<UTC>/` 下的 `ds_st_full.log`、`grep_metrics_summary.txt`（仅父日志）、`grep_metrics_summary_children.txt`（子目录 tar 后）、`cluster_logs/`、`summary.txt`（若存在 `summarize_observability_log.sh`）。一次真实跑法的说明与空 grep 排查见样例目录 [`../../results/kv_rw_metrics_20260418_160823/OBSERVABILITY.md`](../../results/kv_rw_metrics_20260418_160823/OBSERVABILITY.md)。

---

## 5. 性能定界：自证清白方法论（#588 原创）

**核心对比**：同一周期内，`zmq_send_io_latency` + `zmq_receive_io_latency` 表示 **socket I/O 耗时**；`zmq_rpc_serialize_latency` + `zmq_rpc_deserialize_latency` 表示 **RPC 框架自身** 在调用线程的开销（protobuf 序列化）。

```
RPC 框架占比 = (ser + deser) / (send + recv + ser + deser)
```

**示例（稳态）**：

```
zmq_send_io_latency,count=+5000,avg=120us,max=800us
zmq_receive_io_latency,count=+5000,avg=450us,max=12000us
zmq_rpc_serialize_latency,count=+5000,avg=12us,max=85us
zmq_rpc_deserialize_latency,count=+5000,avg=8us,max=60us
→ (12+8) / (120+450+12+8) = 20/590 ≈ 3.4%
→ 框架开销 <5%，瓶颈明确在 socket I/O
```

**跨机器不比对绝对时间戳**：各节点独立采集 `steady_clock`，跨节点对齐用 Summary 头的 `cycle=<N>` 或日志行号区间。若 client 的 `zmq_receive_io_latency max` 在 cycle=K 突飙升，server 同窗口 `zmq_send_failure_total` 也 +N，即可定位「同一时间窗网络层故障」。

**KV 层也有同类方法**：

- 若 `client_rpc_get_latency avg >> worker_process_get_latency avg`：差值在 **client→worker RPC 链路 / URMA** 上。
- 若两者接近而 `worker_rpc_get_remote_object_latency avg` 高：远端 worker 慢（跨 worker 流量）。
- 若 `worker_urma_write_latency avg` 低但 `client_get_urma_read_total_bytes` delta 为 0：URMA 未真正走数据面，降级到了 TCP（看 `client_get_tcp_read_total_bytes`）。

---

## 6. 定位定界决策树（拿到一份日志该怎么走）

```
① 客户端返回 Status？
   ├─ 0        → 只是性能问题，跳 §5 自证清白
   ├─ 1002     → 看 §3.1 主证据 + §4.4 日志标签
   │            ├─ [TCP_CONNECT_FAILED] / [TCP_CONNECT_RESET]  → 网络/端口
   │            ├─ [RPC_RECV_TIMEOUT]                           → 对端慢或未响应
   │            ├─ [RPC_SERVICE_UNAVAILABLE]                    → 服务端主动下发失败
   │            ├─ [UDS_CONNECT_FAILED] / [SHM_FD_TRANSFER_FAILED] → 本机同机通道
   │            └─ [SOCK_CONN_WAIT_TIMEOUT] / [REMOTE_SERVICE_WAIT_TIMEOUT] → 建连阶段
   ├─ 1010     → URMA wait 超时（见 §3.2 第一行）
   ├─ 1001     → RPC DEADLINE（参考 reliability 目录 01/03）
   ├─ 其它 10xx → URMA 族（见 reliability/03-status-codes.md）
   └─ 2xxx     → 对象语义错误，与本 PR 集不强相关

② metrics summary 里的 fault Counter 是否有 +delta？
   ├─ 是 → §3.1 行一、行二；定性「底层网络/ZMQ 硬错」
   └─ 否 → 看 histogram：
            ├─ zmq_receive_io_latency avg 高 且 fault Counter=0 → 对端慢
            ├─ 4 个 histogram avg 都低        → 瓶颈不在 RPC 栈
            ├─ ser/deser avg >> io avg        → 极少见，框架内部瓶颈
            └─ worker_urma_write_latency 偶发高 → URMA 抖动

③ URMA 相关？
   ├─ [URMA_NEED_CONNECT] 连续出现  → 远端 instanceId 飘/重启，走 reconnect 流程
   ├─ [URMA_POLL_ERROR]             → 驱动/硬件 异常，停看 resource.log 时间线
   ├─ [URMA_RECREATE_JFS*]          → 有 cqeStatus，直接交 URMA 团队
   └─ 无任何 URMA 标签但读写 bytes 计数为 0 → 数据面根本没走，检查 worker→worker 是否降级
```

---

## 7. 验收 checklist（测试签字用）

**最小集**（功能回归）：

- [ ] `sdk.log` / `worker.log` 都能看到至少一次 `Metrics Summary, version=v0, cycle=...`
- [ ] `Total:` 段包含**至少** 23 个 KV metric + 13 个 ZMQ metric（总 36 行，数量与 `KvMetricId::KV_METRIC_END` 一致）
- [ ] `client_put_request_total` 或 `client_get_request_total` 有 `+delta > 0`（端到端有业务流量）
- [ ] `client_put_error_total` / `client_get_error_total` 等于预期（正常场景应为 `+0`）

**故障注入验证**（至少通过一组）：

- [ ] 执行 `bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh --remote`，`Mandatory RESULT: X matched | 0 missing`
- [ ] 执行 `bash vibe-coding-files/scripts/testing/verify/validate_urma_tcp_observability_logs.sh <log-dir>`，`URMA_NEED_CONNECT count > 0` 且 1002 前缀命中 ≥ 3 种

**自证清白**（性能场景）：

- [ ] `zmq_send_io_latency` / `zmq_receive_io_latency` / `zmq_rpc_serialize_latency` / `zmq_rpc_deserialize_latency` **四行都有 count>0**
- [ ] 按 §5 公式算出的「框架占比」和故障注入日志的 `[SELF-PROOF REPORT]` / `CONCLUSION:` 行方向一致

**误区提醒**（务必在验收会前让每个测试能口头答）：

1. **没看到 `[ZMQ_RECEIVE_FAILURE_TOTAL]` 不代表埋点没生效** —— client stub 以 `DONTWAIT + poll` 为主，很多超时不会走到 `zmq_msg_recv` 的硬失败分支。主证据看 `zmq_gateway_recreate_total` delta + `[RPC_RECV_TIMEOUT]`。
2. **`zmq_receive_try_again_total` 只在 blocking 模式计数**（见 `zmq_socket_ref.cpp:158` 的 `flags == NONE` 判断）—— stub 走非阻塞，delta 长期为 0 是预期。
3. **`zmq_gateway_recreate_total` 的 Total 会计入首次建网关**（非故障），**看 Compare 段的 `+delta`** 判断本次故障窗口内是否发生重建。
4. **`zmq_last_error_number` 是 Gauge**（当前值，不是累加）—— 它存的是 **最近一次硬失败的 errno**，一次故障后可能长期停留在那个数字。要判断"是否又发生了新故障"应结合 `zmq_network_error_total` 和 `zmq_*_failure_total` 的 **delta**。
5. **KV Client 侧打完 `client_put_request_total` 后请求才真正发给 Worker**，所以 Client 的 total 和 Worker 的 `worker_from_client_total_bytes` 不是严格同步的；跨进程对齐靠业务流量稳态假设，不靠单次 1:1 匹配。

---

## 8. 回到代码：开发排障常用锚点

| 我想知道… | 直接读 |
|-----------|--------|
| metric 框架的 `Observe` / `Tick` / `Summary` 实现 | `src/datasystem/common/metrics/metrics.cpp`（250 行，整文件读就够） |
| 为什么 Summary 里 Histogram delta 的 `max` 是周期最大值 | `metrics.cpp::BuildSummary` 中 `slot.periodMax.exchange(0, ...)` |
| ZMQ I/O 的 METRIC_TIMER 作用域怎么写的 | `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp::SendMsg`（L183-217）、`RecvMsg`（L147-181） |
| 为什么 EAGAIN / EINTR 不算硬失败 | 同上 `RecvMsg` / `SendMsg` 的 `if (e == EAGAIN)` / `else if (e != EINTR)` 分支 |
| `LOG_FIRST_EVERY_N(severity, n)` 宏怎么工作 | `src/datasystem/common/log/log.h`（由 #588 引入，首次一定打 + 每 interval 重置 + 每 N 次打一次） |
| URMA `UrmaEvent` 新字段（remoteAddress / instanceId / OperationType）从哪传进来 | `src/datasystem/common/rdma/urma_manager.cpp::CreateEvent` + `urma_resource.h::UrmaEvent::OperationTypeName` |
| 为什么 `K_URMA_WAIT_TIMEOUT` 要从 `K_RPC_DEADLINE_EXCEEDED` 拆出来 | `src/datasystem/common/util/rpc_util.h::IsRpcTimeout` + `RetryOnRPCErrorByTime`，Urma 超时也进重试白名单但语义上不是 RPC 超时 |
| Client 进程的 Tick 线程谁启谁停 | `src/datasystem/client/object_cache/object_client_impl.cpp::StartMetricsThread` / `ShutdownMetricsThread`（依赖 `FLAGS_log_monitor`） |

---

## 9. 本文维护约定

1. **ID 表以 `kv_metrics.cpp` 的 `KV_METRIC_DESCS` 顺序为准**。若将来新增 metric，追加在末尾 + 同步更新 §1.1。
2. **日志标签只列仓库中真实存在的前缀**。添加前用 `rg -n "\\[<PREFIX>\\]" src/` 核实至少一个采集点。
3. **不复述 `05-metrics-and-perf.md`**。本文偏"PR 故事线 + 场景对照"；稳定清单让 05 承担。
4. **故障注入测试串讲放 `../../rfc/2026-04-zmq-rpc-metrics/test-walkthrough.md`**，本文在 §4.5 只给入口命令。
5. **性能数字不直接写进本文**。实际性能在 `results.md` 中按环境归档，避免文档与现网背离。
