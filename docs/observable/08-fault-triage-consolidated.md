# 08 · 故障定位定界三板斧

> **本文是什么**：一份**自包含**的现场定位定界操作手册。看到现象 → 三步拿结论。
>
> **面向谁**：开发、运维、测试、值班。不要求先读任何其它文档。
>
> **凭什么准**：所有错误码、日志字符串、metric 名、gflag 默认值都以 `yuanrong-datasystem` 主干代码为 ground truth 验证过；对应源码锚点见附录 B/C/D。
>
> **如何用**：遇到异常先走 §1 → §2 → §3 三板斧。速查卡在 §5，工程细节（路径、gflag、代码行号、维护规则）在 §6 附录。

---

## 0. 三板斧一图流

```
观察到现象（成功率↓ / P99↑ / 功能失败 / 抖动）
   │
   ▼
┌─────────────────────────────────────────────┐
│ 第一板斧：归类                                │
│   看 StatusCode 数值，落到 A/B/C/D 四大域    │
│   （30 秒出初判结论）                         │
└─────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────┐
│ 第二板斧：分流                                │
│   grep 结构化日志前缀 + 看 metrics delta     │
│   锁定具体故障点（3~5 分钟）                  │
└─────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────┐
│ 第三板斧：落点                                │
│   日志 × metric 交叉验证，给出根因 + 处理动作  │
│   输出工单结论模板                            │
└─────────────────────────────────────────────┘
```

**四大故障域速记**：

| 域 | 定位 | 典型 Status | 看什么 |
|----|------|------------|--------|
| **A** | 用户层 | 2 / 3 / 8 | access log 的 `respMsg` |
| **B** | 控制面（TCP/ZMQ/RPC） | 1001 / 1002 / 19 | `[TCP_*]` / `[ZMQ_*]` / `[RPC_*]` 等前缀 + `zmq_*` 指标 |
| **C** | URMA 数据面 | 1004 / 1006 / 1008 / 1009 / 1010 | `[URMA_*]` 前缀 + UB/TCP 字节对比 |
| **D** | 组件层（心跳/etcd/资源） | 6 / 7 / 13 / 18 / 23 / 25 / 29 / 31 / 32 | `[HealthCheck]` / `etcd is ...` / `resource.log` |

---

## 1. 第一板斧 · 归类

> 目标：看一眼 Status，就知道该查哪一类、下一步用什么关键词。

### 1.1 决策树

```
客户端拿到 Status →

├─ 0（K_OK）但业务失败？
│    └─ 看 respMsg：含 NOT_FOUND / "Can't find object" → A 类
│       否则是"成功但慢" → §3 性能自证清白
│
├─ 2 / 3 / 8  ............. A 类 · 用户层
│
├─ 1001 / 1002 / 19 ........ B 类 · 控制面
│                            ⚠️ 1002 是桶码，必须再看 [...] 前缀分流
│
├─ 1004 / 1006 / 1008 / 1009 / 1010 ........ C 类 · URMA
│
├─ 23 / 25 / 31 / 32 ........ D 类 · 组件-可用性
│
└─ 5 / 6 / 7 / 13 / 18 / 29 ........ D 类 · 组件-资源
```

### 1.2 错误码 → 故障域（完整表）

| 码 | 枚举 | 域 | 第一反应 |
|---|------|----|---------|
| `0` | `K_OK` | ⚠️陷阱 | `KVClient::Get` 把 `K_NOT_FOUND` 改成 `K_OK` 记账；**必须看 respMsg** |
| `2` | `K_INVALID` | A | 参数校验失败 |
| `3` | `K_NOT_FOUND` | A | 对象不存在（业务语义） |
| `5` | `K_RUNTIME_ERROR` | D/A | mmap / UB payload / Master `etcd is timeout` |
| `6` | `K_OUT_OF_MEMORY` | D | 内存 / SHM 池不足 |
| `7` | `K_IO_ERROR` | D | IO 错 |
| `8` | `K_NOT_READY` | A | 未 `Init` 或正在 `ShutDown` |
| `13` | `K_NO_SPACE` | D | 磁盘满 |
| `18` | `K_FILE_LIMIT_REACHED` | D | fd / open files 耗尽 |
| `19` | `K_TRY_AGAIN` | B | 瞬时可恢复 |
| `20` | `K_DATA_INCONSISTENCY` | D | 数据不一致 |
| `23` | `K_CLIENT_WORKER_DISCONNECT` | D | 心跳断 |
| `25` | `K_MASTER_TIMEOUT` | D | Master/etcd 超时 |
| `29` | `K_SERVER_FD_CLOSED` | D | 服务端 fd 关闭 |
| `31` | `K_SCALE_DOWN` | D | Worker 退出中，SDK 会重试 |
| `32` | `K_SCALING` | D | 扩缩容中，SDK 会重试 |
| `1001` | `K_RPC_DEADLINE_EXCEEDED` | B | RPC 超时（网络/对端/拥塞） |
| `1002` | `K_RPC_UNAVAILABLE` | B | RPC 不可达（**桶码**） |
| `1004` | `K_URMA_ERROR` | C | UB 硬件/驱动路径失败 |
| `1006` | `K_URMA_NEED_CONNECT` | C | URMA 连接需重建 |
| `1008` | `K_URMA_TRY_AGAIN` | C | URMA 瞬时可恢复 |
| `1009` | `K_URMA_CONNECT_FAILED` | C | URMA 建连失败 |
| `1010` | `K_URMA_WAIT_TIMEOUT` | C | URMA 事件等待超时 |

> **1002 桶码必须再分流**。相同 1002 可能来自 TCP 建连、UDS 建连、ZMQ recv、SCM_RIGHTS 辅助通道等完全不同路径。一律走第二板斧靠 `[...]` 前缀定位。

---

## 2. 第二板斧 · 分流

> 目标：按四大域查表，锁定"是哪个具体故障点"。每个域给出：**日志前缀 → 含义 → 指标 → 根因判断**。

### 2.1 A 类 · 用户层

**现象**：`Status = 2/3/8`，或 `Status = 0` 但业务不符合预期。

**看 Client Access Log**（格式：`code | handleName | microseconds | dataSize | reqMsg | respMsg`）：

| respMsg 片段 | 含义 | 处理 |
|--------------|------|------|
| `The objectKey is empty` | key 为空 | 业务校验 |
| `dataSize should be bigger than zero` | size=0 | 业务校验 |
| `length not match` | keys/sizes 数组长度不等 | 业务校验 |
| `ConnectOptions was not configured` | 未配置连接参数 | 检查 `Init` |
| `Client object is already sealed` | buffer 重复 Publish | 业务逻辑 |
| `OBJECT_KEYS_MAX_SIZE_LIMIT` | 批次超限 | 拆 batch |
| `Can't find object` / `K_NOT_FOUND` | 对象不存在 | 业务正常 |

**速查 grep**：

```bash
# 错误码分布（按接口）
grep "DS_KV_CLIENT_GET" ${log_dir}/ds_client_access_<pid>.log \
  | awk -F'|' '{print $1}' | sort | uniq -c

# INVALID 类
grep '^2 |' ${log_dir}/ds_client_access_<pid>.log

# NOT_FOUND（注意 code=0 + msg=NOT_FOUND 的陷阱）
grep -E "K_NOT_FOUND|Can.?t find object" ${log_dir}/ds_client_<pid>.INFO.log
```

---

### 2.2 B 类 · 控制面（TCP / UDS / ZMQ / RPC）

**现象**：`Status = 1001/1002/19`；access log 中 `microseconds` 接近 timeout。

#### 2.2.1 结构化日志前缀对照表

| 前缀 | 触发语义 | 根因方向 |
|------|---------|---------|
| `[TCP_CONNECT_FAILED]` | addrinfo 遍历完仍 `connect()` 失败 | 端口未监听 / 防火墙 / 路由 |
| `[TCP_CONNECT_RESET]` | `ECONNRESET` / `EPIPE` | 对端 crash / 网络闪断 |
| `[TCP_NETWORK_UNREACHABLE]` | `ZMQ_POLLOUT` 失败 | 路由不可达 / 网卡挂了 |
| `[UDS_CONNECT_FAILED]` | UDS `connect()` 失败 | 同机 socket path 不对 / 权限 |
| `[SHM_FD_TRANSFER_FAILED]` | 无法建立传 shm fd 的辅助连接 | Worker 侧 UDS 未就绪 |
| `[SOCK_CONN_WAIT_TIMEOUT]` | 连接建立等待超时 | 建连阶段被拖慢 |
| `[REMOTE_SERVICE_WAIT_TIMEOUT]` | `connInProgress=true` 已超时 | 对端未响应握手 |
| `[RPC_RECV_TIMEOUT]` | Client 等应答超时 | **对端处理慢** / 框架排队 |
| `[RPC_SERVICE_UNAVAILABLE]` | 服务端主动把错误回包 | 服务端队列清空 / Worker 状态不对 |
| `[ZMQ_SEND_FAILURE_TOTAL]` | `zmq_msg_send` 硬失败（errno 非 EAGAIN/EINTR） | iptables drop / 网络闪断 |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `zmq_msg_recv` 硬失败 | 同上 |
| `[ZMQ_RECV_TIMEOUT]` | 阻塞 recv + `ZMQ_RCVTIMEO` 路径超时 | 非 stub 主路径（stub 用 `DONTWAIT + poll`） |

> ⚠️ 旧内部文档里写的 `[TCP_CONN_WAIT_TIMEOUT]` 在代码里**不存在**，请替换为 `[SOCK_CONN_WAIT_TIMEOUT]` 或 `[REMOTE_SERVICE_WAIT_TIMEOUT]`。

#### 2.2.2 ZMQ 指标对照

| Metric | 类型 | 故障信号 / 要点 |
|--------|------|----------------|
| `zmq_send_failure_total` | Counter | delta > 0 → 发送硬失败 |
| `zmq_receive_failure_total` | Counter | delta > 0 → 接收硬失败 |
| `zmq_send_try_again_total` | Counter | 持续涨 ≈ HWM 背压（非错） |
| `zmq_receive_try_again_total` | Counter | **仅在 blocking 模式计数**；stub DONTWAIT 路径永远 0 |
| `zmq_network_error_total` | Counter | 命中网络类 errno（`EHOSTUNREACH` / `ECONNRESET` 等） |
| `zmq_last_error_number` | **Gauge** | 最近一次硬失败的 errno；**不累加**，停留在那个值 |
| `zmq_gateway_recreate_total` | Counter | Total 含首次建网关；**看 delta** 判断故障窗口内是否重建 |
| `zmq_event_disconnect_total` | Counter | ZMQ Monitor 异步断开事件，可能晚几秒 |
| `zmq_event_handshake_failure_total` | Counter | 证书 / 协议 / 认证 |
| `zmq_send_io_latency` | Histogram(us) | 只包 `zmq_msg_send` |
| `zmq_receive_io_latency` | Histogram(us) | 只包 `zmq_msg_recv` |
| `zmq_rpc_serialize_latency` | Histogram(us) | 只包 `pb.SerializeToArray` |
| `zmq_rpc_deserialize_latency` | Histogram(us) | 只包 `pb.ParseFromArray` |

#### 2.2.3 组合判断（日志 × 指标 → 根因）

| 日志前缀 + 指标信号 | 根因 | 处置 |
|---------------------|------|------|
| `[TCP_CONNECT_FAILED]` + `zmq_last_error_number=111`(ECONNREFUSED) | 端口不可达 | 检查 Worker 进程 / 端口 |
| `[TCP_CONNECT_RESET]` + `zmq_network_error_total`↑ | 对端 crash / 闪断 | 检查对端 Worker 状态 |
| `[RPC_RECV_TIMEOUT]` + **所有 ZMQ fault counter = 0** | **对端处理慢**，不是网络 | 查 Worker CPU / 线程池 waiting |
| `[ZMQ_SEND_FAILURE_TOTAL]` + `zmq_send_failure_total` delta>0 | ZMQ 发送硬失败 | iptables / 网络闪断 |
| `zmq_gateway_recreate_total`↑ + `zmq_event_disconnect_total`↑ | 连接被重置后重建 | 正常恢复；频率高再查网络 |
| `zmq_event_handshake_failure_total`↑ + `[SOCK_CONN_WAIT_TIMEOUT]` | 证书/认证/协议 | 安全组件 + 配置 |
| `zmq_send_try_again_total` 持续涨 + 其它 counter 为 0 | HWM 背压 | 不算硬错，观察接收侧消费速度 |

**速查 grep**：

```bash
# 一把抓（所有控制面前缀）
grep -E '\[(TCP|UDS|ZMQ|RPC|SOCK|REMOTE|SHM_FD)_' \
  ${log_dir}/datasystem_worker.INFO.log \
  ${log_dir}/ds_client_<pid>.INFO.log

# RPC 超时细分
grep -E '\[RPC_RECV_TIMEOUT\]|\[RPC_SERVICE_UNAVAILABLE\]' \
  ${log_dir}/datasystem_worker.INFO.log

# ZMQ 硬失败
grep -E '\[ZMQ_(SEND|RECEIVE)_FAILURE_TOTAL\]' \
  ${log_dir}/datasystem_worker.INFO.log
```

---

### 2.3 C 类 · URMA 数据面

**现象**：`Status = 1004/1006/1008/1009/1010`，或 Status OK 但日志出现 `fallback to TCP/IP payload`（降级）。

#### 2.3.1 结构化日志前缀对照表

| 前缀 | 触发语义 | 限流 |
|------|---------|------|
| `[URMA_NEED_CONNECT]` | 连接不存在 / 陈旧 / 无 `instanceId` | `LOG_FIRST_AND_EVERY_N(100)`，首次必打 |
| `[URMA_RECREATE_JFS]` | JFS 重建（带 `requestId/op/remoteAddress/remoteInstanceId/cqeStatus`） | 首次必打 |
| `[URMA_RECREATE_JFS_FAILED]` | `ReCreateJfs` 返回错误 | 首次必打 |
| `[URMA_RECREATE_JFS_SKIP]` | connection 已过期 / 无效，跳过 | — |
| `[URMA_POLL_ERROR]` | `PollJfcWait` 非 `K_TRY_AGAIN` 失败 | — |
| `[URMA_WAIT_TIMEOUT]` | URMA 事件等待超时 → `K_URMA_WAIT_TIMEOUT (1010)` | — |

降级关键字：**`fallback to TCP/IP payload`**（在客户端侧打 WARNING；功能可能仍成功）。

#### 2.3.2 URMA / TCP 字节指标

| Metric | 用法 |
|--------|------|
| `client_put_urma_write_total_bytes` | 降级时 delta=0 |
| `client_put_tcp_write_total_bytes` | 降级时突增 |
| `client_get_urma_read_total_bytes` | 同上 |
| `client_get_tcp_read_total_bytes` | 同上 |
| `worker_urma_write_latency` | Histogram(us)；max 飙升 → UB 硬件/驱动 |
| `worker_tcp_write_latency` | Histogram(us) |

#### 2.3.3 组合判断

| 日志 + 指标 | 根因 | 处置 |
|-----------|------|------|
| `[URMA_NEED_CONNECT]` + `remoteInstanceId` 前后变化 | 对端 Worker 重启 | 等 SDK 自动重连 |
| `[URMA_NEED_CONNECT]` 持续、instanceId 一致 | 连接不稳定 | 检查 UB 设备 / 链路 |
| `[URMA_RECREATE_JFS]` + `cqeStatus=9` | ACK timeout，JFS 状态异常 | 自动重建；反复出现再报硬件 |
| `[URMA_RECREATE_JFS_FAILED]` 连续出现 | 重建失败 | 交 URMA 团队查驱动 |
| `fallback to TCP/IP payload` 突增 + `*_tcp_*_bytes`↑ + `*_urma_*_bytes` delta=0 | UB 池/设备故障，降级 TCP | 查 UB 端口 / Jetty 配置 |
| `[URMA_POLL_ERROR]` + `worker_urma_write_latency` max 飙升 | 驱动 / 硬件异常 | 查 UMDK 日志 |
| `[URMA_WAIT_TIMEOUT]` + Status=1010 | URMA 事件等待超时 | 进入重试白名单 |

**速查 grep**：

```bash
# 全部 URMA 前缀
grep -E '\[URMA_' ${log_dir}/datasystem_worker.INFO.log

# 降级
grep 'fallback to TCP/IP payload' \
  ${log_dir}/datasystem_worker.INFO.log \
  ${log_dir}/ds_client_<pid>.INFO.log

# JFS 重建事件链
grep -E '\[URMA_RECREATE_JFS(_FAILED|_SKIP)?\]' \
  ${log_dir}/datasystem_worker.INFO.log
```

---

### 2.4 D 类 · 组件层（心跳 / etcd / 资源）

**现象**：`Status = 6/7/13/18/23/25/29/31/32`；或 Worker 下线 / etcd 抖动；或内存 / SHM 异常。

#### 2.4.1 关键日志字符串

| 日志字符串 | 错误码 | 含义 |
|-----------|-------|------|
| `[HealthCheck] Worker is exiting now` | — | Worker 主动退出中 |
| `Cannot receive heartbeat from worker.` | `K_CLIENT_WORKER_DISCONNECT(23)` | 心跳超时 |
| `etcd is timeout` | `K_RUNTIME_ERROR(5)` | **Master 视角** |
| `etcd is unavailable` | `K_RPC_UNAVAILABLE(1002)` | **Worker 视角** |
| `Disconnected from remote node` | — | Master 超时 / 网络断 |
| `meta_is_moving`（RPC 字段） | `K_SCALING(32)` | 扩缩容中 |
| `Get mmap entry failed` | `K_RUNTIME_ERROR(5)` | fd 无效 / mmap 表项未建 |

> **etcd 有两种字符串并存**：Master 用 `etcd is timeout`，Worker 用 `etcd is unavailable`。grep 时**两个都要加**。

#### 2.4.2 `resource.log` 关键字段（周期聚合）

| # | 顶层字段 | 子项 / 信号 |
|---|---------|-------------|
| 1 | `SHARED_MEMORY` | `MEMORY_USAGE` / `PHYSICAL_MEMORY_USAGE` / `TOTAL_LIMIT` 等；突增 → 内存异常 |
| 2 | `SPILL_HARD_DISK` | spill 磁盘用量 |
| 3 | `ACTIVE_CLIENT_COUNT` | 已建连 client 数（连接泄漏线索） |
| 4 | `OBJECT_COUNT` | 对象数；异常变化 → Worker 重启 / 泄漏 |
| 5 | `OBJECT_SIZE` | 对象总字节 |
| 6-9 | `*_OC_SERVICE_THREAD_POOL` | RPC 线程池五元组：`IDLE_NUM/CURRENT_TOTAL/MAX/WAITING/USAGE` |
| 10 | `ETCD_QUEUE` | `CURRENT_SIZE/TOTAL_LIMIT/USAGE`；堆积 → 控制面受阻 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | etcd 成功率，下降 → etcd 问题 |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | OBS 二级存储成功率 |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | Master 异步池 |
| 22 | `OC_HIT_NUM` | `MEM/DISK/L2/REMOTE/MISS` 命中五元组 |

完整 22 字段见附录 E。

#### 2.4.3 SHM 钉住泄漏指标（判据）

| Metric | 类型 | 含义 |
|--------|------|------|
| `worker_allocated_memory_size` | Gauge(B) | Worker 总内存使用 |
| `worker_allocator_alloc_bytes_total` | Counter(B) | 分配总字节 |
| `worker_allocator_free_bytes_total` | Counter(B) | 释放总字节 |
| `worker_shm_unit_created_total` | Counter | ShmUnit 创建次数 |
| `worker_shm_unit_destroyed_total` | Counter | ShmUnit 销毁次数 |
| `worker_shm_ref_add_total` | Counter | ref 加持次数 |
| `worker_shm_ref_remove_total` | Counter | ref 释放次数 |
| `worker_shm_ref_table_size` | Gauge | ref_table 表项数 |
| `worker_shm_ref_table_bytes` | Gauge(B) | ref_table 钉住字节 |
| `worker_object_count` | Gauge | 当前对象数 |

**钉住泄漏判据**（三条同时成立）：

```
① worker_allocator_alloc_bytes_total delta > worker_allocator_free_bytes_total delta
② worker_shm_ref_table_bytes（gauge）持续上涨
③ worker_object_count（gauge）持平或下降
→ 元数据已删但物理 SHM 被 ref_table 钉住
```

> ⚠️ 老内部文档里的 `worker_shm_alloc_total` / `worker_shm_free_total` / `worker_shm_alloc_bytes` / `worker_shm_free_bytes` / `worker_shm_unit_ref_count` **在代码里不存在**，使用上表的真实名字。

#### 2.4.4 组合判断

| 日志 + 指标 | 根因 | 处置 |
|-----------|------|------|
| `[HealthCheck] Worker is exiting now` | Worker 主动退出 | k8s / 进程管理器自动拉起 |
| `Cannot receive heartbeat from worker.` + Status=23 | 心跳超时 | 检查 Worker 状态；`kill -CONT <pid>` 若手工 STOP |
| `etcd is timeout` / `etcd is unavailable` 持续 | etcd 集群故障 | 紧急介入，`systemctl start etcd` |
| `SHARED_MEMORY` 突增 + `worker_shm_ref_table_bytes` 涨 + `OBJECT_COUNT` 持平 | SHM 钉住泄漏 | 查 client 释放路径 |
| `OBJECT_COUNT` 突降 + 新 Worker pid | Worker 重启 / 数据丢失 | 查稳定性 |
| `ETCD_QUEUE` 堆积 | 元数据链路瓶颈 | 查 Master/etcd |
| `Get mmap entry failed` + Status=5 | fd 无效 / mmap 失败 | `ulimit -l unlimited` / 排查 SCM_RIGHTS |
| Status=18（`K_FILE_LIMIT_REACHED`） | fd 上限 | `ulimit -n` 调整 |

**速查 grep**：

```bash
# Worker 生命周期 / 心跳
grep -E '\[HealthCheck\] Worker is exiting now|Cannot receive heartbeat from worker' \
  ${log_dir}/datasystem_worker.INFO.log \
  ${log_dir}/ds_client_<pid>.INFO.log

# etcd（两种字符串都要加）
grep -E 'etcd is (timeout|unavailable)|Disconnected from remote node' \
  ${log_dir}/datasystem_worker.INFO.log

# 扩缩容
grep -E 'meta_is_moving|K_SCALING|K_SCALE_DOWN' \
  ${log_dir}/datasystem_worker.INFO.log

# SHM 钉住
grep -E 'worker_shm_ref_table_(bytes|size)|worker_allocator_(alloc|free)_bytes_total' \
  ${log_dir}/datasystem_worker.INFO.log

# resource.log 资源视图
grep -E 'SHARED_MEMORY|ETCD_QUEUE|ETCD_REQUEST_SUCCESS_RATE|OC_HIT_NUM' \
  ${log_dir}/resource.log
```

---

## 3. 第三板斧 · 落点

> 目标：用 metrics 与日志**交叉验证**，给出根因 + 处理动作；输出可贴工单的定界结论。

### 3.1 Metrics Summary 读法

Worker / Client 进程周期（默认 10s）打印：

```
Metrics Summary, version=v0, cycle=<N>, interval=<intervalMs>ms

Total:
<metric_name>=<value>[<suffix>]
<hist_name>,count=<c>,avg=<a><suffix>,max=<m><suffix>
...

Compare with <intervalMs>ms before:
<metric_name>=+<delta>[<suffix>]
<hist_name>,count=+<dc>,avg=<da><suffix>,max=<period_max><suffix>
```

**读的顺序**：

1. **`cycle` 连续吗**？丢号说明进程被拖死或 metrics 线程被卡。
2. **`Total:` 段有 ≥ 54 行 metric 吗**？少了 = 构建没带 `InitKvMetrics` 或 `-log_monitor=false`。
3. **`Compare with` 段是重点**：看业务流量 → 看错误 → 看 ZMQ / URMA / SHM。
4. Histogram 的 `max`：delta 段是 **本周期 periodMax**（每次 dump 后清零），不是累计。跨周期比较必须按 `cycle=N` 锚定。

**跨进程对齐**：不要拼绝对时间戳（各节点独立采集 `steady_clock`）；用 **`cycle=N` 行号区间** 或日志 TraceID 粘合。

### 3.2 性能劣化定位查表

| 现象 | 主查 | 次查 | 结论 |
|------|------|------|------|
| Get P99↑ | `client_rpc_get_latency` max | `worker_process_get_latency` | 两者差大 → client→worker 链路 / URMA；齐升 → Worker 慢 |
| Get P99↑ + **所有 ZMQ fault counter = 0** | `zmq_receive_io_latency` max | `zmq_send_io_latency` | 对端慢 / 排队，非网络 |
| Publish P99↑ | `client_rpc_publish_latency` max | `worker_process_publish_latency` + `worker_rpc_create_meta_latency` | meta/etcd 瓶颈在 Master |
| 跨 Worker Get 慢 | `worker_rpc_get_remote_object_latency` max | 远端 `worker_process_get_latency` | 远端业务慢 vs 网络慢 |
| UB P99↑ + 降级 TCP | `worker_urma_write_latency` max | `client_get_tcp_read_total_bytes` | UB 设备故障 |

### 3.3 成功率劣化定位查表

| 现象 | 主查 | 次查日志 | 结论 |
|------|------|---------|------|
| Get 错误率↑ | `client_get_error_total` / `client_get_request_total` | `[RPC_RECV_TIMEOUT]` / `[URMA_*]` | 看**第一个出现**的前缀 |
| Put 错误率↑ | `client_put_error_total` / `client_put_request_total` | `[ZMQ_SEND_FAILURE_TOTAL]` / `etcd is ...` | ZMQ vs 元数据 |
| URMA 错误↑ | `client_*_urma_*_bytes` delta=0 | `[URMA_NEED_CONNECT]` / `[URMA_RECREATE_JFS]` | UB 连接 / JFS |
| 降级 TCP↑ | `client_*_tcp_*_bytes` delta↑ | `fallback to TCP/IP payload` | UB 池 / 设备 |
| etcd 超时↑ | `worker_rpc_create_meta_latency` max | `etcd is {timeout,unavailable}` | etcd 集群 |

### 3.4 性能自证清白公式

当 RPC 整体慢，但 ZMQ 所有 fault counter = 0 时，用这个公式排除框架自身：

```
RPC 框架占比 = (zmq_rpc_serialize_latency + zmq_rpc_deserialize_latency)
             / (zmq_send_io_latency + zmq_receive_io_latency + 上两项)
```

`<5%` → 瓶颈不在 ZMQ / protobuf 框架，继续往业务层追。

### 3.5 处理措施速查

| 故障 | 恢复动作 | 验证信号 |
|------|---------|---------|
| ZMQ 发送失败（iptables 注入） | `iptables -D OUTPUT -p tcp --dport X -j DROP` | `zmq_send_failure_total` delta 归零 |
| RPC 超时（tc 注入） | `tc qdisc del dev eth0 root netem` | latency 回 baseline |
| TCP 建连失败 | `iptables -D INPUT -p tcp --dport X -j REJECT` | `[TCP_CONNECT_FAILED]` 消失 |
| URMA 需重连 | SDK 自动重连（等 `K_TRY_AGAIN`） | `[URMA_NEED_CONNECT]` 消失 |
| UB 降级 TCP | `ifconfig ub0 up` | `client_*_urma_*_bytes` delta>0 |
| Worker 退出 | k8s 自动拉起 | 新 pid 建连 |
| 心跳超时（手工 STOP） | `kill -CONT <worker_pid>` | 心跳恢复 |
| etcd 超时 | `systemctl start etcd` | `etcd is ...` 消失 |
| mmap 失败 | `ulimit -l unlimited` | `Get mmap entry failed` 消失 |
| fd 耗尽 | `ulimit -n` 调大 | Status=18 消失 |

### 3.6 定界结论模板（可直接贴工单）

```
【域】A / B / C / D（主因写第一，可并列）
【错误码】<code> <枚举名> + rc.GetMsg()
【日志证据】
  <SDK 日志一行，含 TraceID 或时间戳 + objectKey>
  <Worker 日志一行，含同时间窗 + [PREFIX] 前缀>
【Metrics delta】
  cycle=<N>, interval=<ms>ms
  <Counter>=+<N>；<Histogram> count=+<N>,max=<val>
【根因】<一句话>
【处理】§3.5 对应行
```

---

## 4. 三板斧实战示例（5 个典型场景）

### 4.1 Get 错误率升高（B 类）

```
现象：client_get_error_total delta=+12，client_get_request_total delta=+500

第一板斧：rc.GetCode() = 1002 → B 类·控制面
第二板斧：grep [TCP_CONNECT_FAILED]|[RPC_RECV_TIMEOUT] 命中；
         zmq_last_error_number=111(ECONNREFUSED)
第三板斧：__zmq_send_failure_total delta=0，但 zmq_gateway_recreate_total delta=+3
         → Worker 进程被拉起中，连接被重置
         处置：等 SDK 自动恢复；若频繁，查 Worker OOM / k8s 调度
```

### 4.2 Get 成功但 P99 飙升（B 类·性能）

```
现象：client_rpc_get_latency max=50ms，baseline 2ms

第一板斧：Status=0 → 性能问题，跳 §3 自证清白
第二板斧：所有 ZMQ fault counter=0；zmq_receive_io_latency max=40ms
第三板斧：公式算框架占比 ≈ 3%，非框架问题
         worker_process_get_latency max=38ms
         → Worker 侧慢，查 CPU / 线程池 waiting
```

### 4.3 UB 性能退化（C 类·降级）

```
现象：Put 延迟 avg 从 500us → 3000us，但 Status=0

第一板斧：Status=0 → 性能类
第二板斧：grep 'fallback to TCP/IP payload' 命中 200 次/min
第三板斧：client_put_urma_write_total_bytes delta=0
         client_put_tcp_write_total_bytes delta=+50MB
         → UB 池/设备故障，已降级 TCP，功能未挂但 CPU 拷贝放大
         处置：ifconfig ub0 / 查 UMDK 日志
```

### 4.4 心跳超时（D 类）

```
现象：业务侧周期性收到 Status=23

第一板斧：23 = K_CLIENT_WORKER_DISCONNECT → D 类·组件-可用性
第二板斧：Client log "Cannot receive heartbeat from worker."
         Worker log 同时间窗找不到对应 access 记录
第三板斧：resource.log 该 Worker 该时段 CPU 打满（看 thread pool WAITING_TASK_NUM 堆积）
         → Worker 被挂起（被 STOP / GC / 阻塞 syscall）
         处置：kill -CONT；或排查 Worker 内部阻塞点
```

### 4.5 SHM 钉住泄漏（D 类·资源）

```
现象：shm.memUsage 从 3.58GB → 37.5GB（100s），业务无明显报错

第一板斧：无错误码，但 resource.log SHARED_MEMORY 突增 → D 类·资源
第二板斧：worker_shm_ref_table_bytes gauge 持续上涨
         worker_object_count gauge 持平或下降
第三板斧：worker_allocator_alloc_bytes_total delta > worker_allocator_free_bytes_total delta
         worker_shm_ref_remove_total delta << worker_shm_ref_add_total delta
         → 元数据已删但 ref 未释放，物理 SHM 被钉住
         处置：排查 client 侧 DecRef 路径；Worker 清理超时机制
```

---

## 5. 现场速查卡

### 5.1 错误码一览

```
0    K_OK                         ⚠️ 注意 K_NOT_FOUND→K_OK 陷阱
2    K_INVALID                    用户参数非法
3    K_NOT_FOUND                  对象不存在
5    K_RUNTIME_ERROR              mmap / UB payload / Master etcd-timeout
6    K_OUT_OF_MEMORY              内存 / 池不足
7    K_IO_ERROR                   IO 错
8    K_NOT_READY                  未 Init
13   K_NO_SPACE                   磁盘满
18   K_FILE_LIMIT_REACHED         fd 满
19   K_TRY_AGAIN                  瞬时可重试
20   K_DATA_INCONSISTENCY         数据不一致
23   K_CLIENT_WORKER_DISCONNECT   心跳断
25   K_MASTER_TIMEOUT             Master/etcd 超时
29   K_SERVER_FD_CLOSED           服务端 fd 关
31   K_SCALE_DOWN                 Worker 退出中
32   K_SCALING                    扩缩容中
1001 K_RPC_DEADLINE_EXCEEDED      RPC 超时
1002 K_RPC_UNAVAILABLE            RPC 不可达（桶码）
1004 K_URMA_ERROR                 UB 错误
1006 K_URMA_NEED_CONNECT          UB 需重连
1008 K_URMA_TRY_AGAIN             UB 重试
1009 K_URMA_CONNECT_FAILED        UB 建连失败
1010 K_URMA_WAIT_TIMEOUT          UB 事件等待超时
```

### 5.2 一纸禅 grep

```bash
LOG=${log_dir:-/var/log/datasystem}

# 全部结构化日志前缀（B/C 类最常用）
grep -E '\[(TCP|UDS|ZMQ|RPC|SOCK|REMOTE|SHM_FD|URMA)_' \
  $LOG/datasystem_worker.INFO.log $LOG/ds_client_*.INFO.log

# Metrics delta 段
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3

# 降级
grep 'fallback to TCP/IP payload' $LOG/*.INFO.log

# Worker 退出 / 心跳
grep -E '\[HealthCheck\] Worker is exiting now|Cannot receive heartbeat from worker' \
  $LOG/*.INFO.log

# etcd 问题（两种字符串）
grep -E 'etcd is (timeout|unavailable)' $LOG/datasystem_worker.INFO.log

# SHM 钉住
grep -E 'worker_shm_(ref_table_(bytes|size)|unit_(created|destroyed)_total|ref_(add|remove)_total)|worker_allocator_(alloc|free)_bytes_total' \
  $LOG/datasystem_worker.INFO.log

# resource.log 核心
grep -E 'SHARED_MEMORY|ETCD_QUEUE|ETCD_REQUEST_SUCCESS_RATE|OC_HIT_NUM' \
  $LOG/resource.log

# Client 错误码分布（按接口）
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log \
  | awk -F'|' '{print $1}' | sort | uniq -c
```

### 5.3 日志文件路径速查

| 文件 | 用途 |
|------|------|
| `${log_dir}/datasystem_worker.INFO.log` | Worker 运行日志（结构化标签主源） |
| `${log_dir}/access.log` | Worker 接口访问日志 |
| `${log_dir}/resource.log` | 资源指标周期聚合 |
| `${log_dir}/request_out.log` | Worker 访问 etcd / OBS 记录 |
| `${log_dir}/ds_client_<pid>.INFO.log` | SDK 运行日志 |
| `${log_dir}/ds_client_access_<pid>.log` | SDK 访问日志 |

`${log_dir}` 由 gflag `--log_dir` 决定（默认读环境变量 `GOOGLE_LOG_DIR`），详见附录 D。

---

## 6. 附录

### 附录 A · 错误码的代码锚点

所有 `StatusCode` 枚举定义于 `include/datasystem/utils/status.h`，节选：

```28:79:include/datasystem/utils/status.h
enum StatusCode : uint32_t {
    K_OK = 0,
    K_DUPLICATED = 1,
    K_INVALID = 2,
    K_NOT_FOUND = 3,
    K_KVSTORE_ERROR = 4,
    K_RUNTIME_ERROR = 5,
    K_OUT_OF_MEMORY = 6,
    K_IO_ERROR = 7,
    K_NOT_READY = 8,
    // ...
    K_FILE_LIMIT_REACHED = 18,
    K_TRY_AGAIN = 19,
    K_DATA_INCONSISTENCY = 20,
    // ...
    K_RPC_DEADLINE_EXCEEDED = 1001,
    K_RPC_UNAVAILABLE = 1002,
    K_URMA_ERROR = 1004,
    K_URMA_NEED_CONNECT = 1006,
    K_URMA_TRY_AGAIN = 1008,
    K_URMA_CONNECT_FAILED = 1009,
    K_URMA_WAIT_TIMEOUT = 1010,
```

**陷阱代码**（Get 把 NOT_FOUND 映射成 K_OK 记 access log）：

```187:189:src/datasystem/client/kv_cache/kv_client.cpp
    StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode();
    accessPoint.Record(code, std::to_string(dataSize), reqParam, rc.GetMsg());
```

---

### 附录 B · 日志前缀 → 源码锚点

所有前缀均已在当前主干代码中用 `rg` 验证存在。

| 前缀 | 源码位置 |
|------|---------|
| `[TCP_CONNECT_FAILED]` | `src/datasystem/common/rpc/unix_sock_fd.cpp::ConnectTcp` (~477) |
| `[TCP_CONNECT_RESET]` | `src/datasystem/common/rpc/unix_sock_fd.cpp::ErrnoToStatus` (~60) |
| `[TCP_NETWORK_UNREACHABLE]` | `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp::SendHeartBeats` (~264) |
| `[UDS_CONNECT_FAILED]` | `src/datasystem/common/rpc/unix_sock_fd.cpp::Connect` (~437) |
| `[SHM_FD_TRANSFER_FAILED]` | `src/datasystem/client/client_worker_common_api.cpp::Connect` (~319) |
| `[SOCK_CONN_WAIT_TIMEOUT]` | `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp::WaitForConnected` (~1503) |
| `[REMOTE_SERVICE_WAIT_TIMEOUT]` | 同上 (~1509) |
| `[RPC_RECV_TIMEOUT]` | `zmq_stub_conn.cpp` (~572) / `zmq_msg_queue.h` (~890) / `zmq_stub_impl.h` (~143) |
| `[RPC_SERVICE_UNAVAILABLE]` | `zmq_stub_conn.cpp::BackendToFrontend/Outbound` (~223, ~1303) |
| `[ZMQ_SEND_FAILURE_TOTAL]` | `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp::SendMsg` (~203) |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `zmq_socket_ref.cpp::RecvMsg` (~167) |
| `[ZMQ_RECV_TIMEOUT]` | `src/datasystem/common/rpc/zmq/zmq_socket.cpp::ZmqRecvMsg` (~79) |
| `[URMA_NEED_CONNECT]` | `src/datasystem/common/rdma/urma_manager.cpp::CheckUrmaConnectionStable`（3 处）+ `worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker` (~947) + `worker_worker_oc_service_impl.cpp::CheckConnectionStable` (~599) |
| `[URMA_RECREATE_JFS]` | `urma_manager.cpp::HandleUrmaEvent` (~772) + `urma_resource.cpp::MarkAndRecreate` (~392, ~407) |
| `[URMA_RECREATE_JFS_FAILED]` | `urma_manager.cpp` (~779) |
| `[URMA_RECREATE_JFS_SKIP]` | `urma_manager.cpp` (~784) + `urma_resource.cpp` (~370, ~386, ~398) |
| `[URMA_POLL_ERROR]` | `urma_manager.cpp::ServerEventHandleThreadMain` (~625) |
| `[URMA_WAIT_TIMEOUT]` | `urma_manager.cpp::WaitToFinish` (~732) |
| `[HealthCheck] Worker is exiting now` | `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` (~371) |
| `Cannot receive heartbeat from worker.` | `src/datasystem/client/listen_worker.cpp` (~114) |
| `etcd is timeout` | `src/datasystem/master/replica_manager.cpp` (~1190) |
| `etcd is unavailable` | `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` (~1631) |
| `Get mmap entry failed` | `src/datasystem/client/object_cache/object_client_impl.cpp`（多处 ~1509/1807/2150/2967/3032） |
| `fallback to TCP/IP payload` | `src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp` (~117, ~131) |

---

### 附录 C · Metrics 完整清单（54 条，以代码为准）

定义在 `src/datasystem/common/metrics/kv_metrics.{h,cpp}`（`KvMetricId` 枚举 + `KV_METRIC_DESCS`），`static_assert` 保证 `KV_METRIC_END = 54`。

| ID | 文本名 | 类型 | 单位 |
|----|--------|------|------|
| 0 | `client_put_request_total` | Counter | count |
| 1 | `client_put_error_total` | Counter | count |
| 2 | `client_get_request_total` | Counter | count |
| 3 | `client_get_error_total` | Counter | count |
| 4 | `client_rpc_create_latency` | Histogram | us |
| 5 | `client_rpc_publish_latency` | Histogram | us |
| 6 | `client_rpc_get_latency` | Histogram | us |
| 7 | `client_put_urma_write_total_bytes` | Counter | bytes |
| 8 | `client_put_tcp_write_total_bytes` | Counter | bytes |
| 9 | `client_get_urma_read_total_bytes` | Counter | bytes |
| 10 | `client_get_tcp_read_total_bytes` | Counter | bytes |
| 11 | `worker_rpc_create_meta_latency` | Histogram | us |
| 12 | `worker_rpc_query_meta_latency` | Histogram | us |
| 13 | `worker_rpc_get_remote_object_latency` | Histogram | us |
| 14 | `worker_process_create_latency` | Histogram | us |
| 15 | `worker_process_publish_latency` | Histogram | us |
| 16 | `worker_process_get_latency` | Histogram | us |
| 17 | `worker_urma_write_latency` | Histogram | us |
| 18 | `worker_tcp_write_latency` | Histogram | us |
| 19 | `worker_to_client_total_bytes` | Counter | bytes |
| 20 | `worker_from_client_total_bytes` | Counter | bytes |
| 21 | `worker_object_count` | Gauge | count |
| 22 | `worker_allocated_memory_size` | Gauge | bytes |
| 23 | `zmq_send_failure_total` | Counter | count |
| 24 | `zmq_receive_failure_total` | Counter | count |
| 25 | `zmq_send_try_again_total` | Counter | count |
| 26 | `zmq_receive_try_again_total` | Counter | count |
| 27 | `zmq_network_error_total` | Counter | count |
| 28 | `zmq_last_error_number` | **Gauge** | — |
| 29 | `zmq_gateway_recreate_total` | Counter | count |
| 30 | `zmq_event_disconnect_total` | Counter | count |
| 31 | `zmq_event_handshake_failure_total` | Counter | count |
| 32 | `zmq_send_io_latency` | Histogram | us |
| 33 | `zmq_receive_io_latency` | Histogram | us |
| 34 | `zmq_rpc_serialize_latency` | Histogram | us |
| 35 | `zmq_rpc_deserialize_latency` | Histogram | us |
| 36 | `worker_allocator_alloc_bytes_total` | Counter | bytes |
| 37 | `worker_allocator_free_bytes_total` | Counter | bytes |
| 38 | `worker_shm_unit_created_total` | Counter | count |
| 39 | `worker_shm_unit_destroyed_total` | Counter | count |
| 40 | `worker_shm_ref_add_total` | Counter | count |
| 41 | `worker_shm_ref_remove_total` | Counter | count |
| 42 | `worker_shm_ref_table_size` | Gauge | count |
| 43 | `worker_shm_ref_table_bytes` | Gauge | bytes |
| 44 | `worker_remove_client_refs_total` | Counter | count |
| 45 | `worker_object_erase_total` | Counter | count |
| 46 | `master_object_meta_table_size` | Gauge | count |
| 47 | `master_ttl_pending_size` | Gauge | count |
| 48 | `master_ttl_fire_total` | Counter | count |
| 49 | `master_ttl_delete_success_total` | Counter | count |
| 50 | `master_ttl_delete_failed_total` | Counter | count |
| 51 | `master_ttl_retry_total` | Counter | count |
| 52 | `client_async_release_queue_size` | Gauge | count |
| 53 | `client_dec_ref_skipped_total` | Counter | count |

`suffix` 规则：`count` → 空；`bytes` → `B`；其它（如 `us`）原样保留。

---

### 附录 D · 日志产出路径与关键 gflag

#### D.1 路径来源（代码）

| 文件 | 代码出处 |
|------|---------|
| `${log_dir}` | gflag `--log_dir`（默认 `$GOOGLE_LOG_DIR`，否则空 → glog 默认目录）；`src/datasystem/common/util/gflag/common_gflag_define.cpp:28` |
| `${log_dir}/access.log` | `FLAGS_log_dir + "/" + "access" + ".log"`；`include/datasystem/common/constants.h:29` |
| `${log_dir}/ds_client_access_<pid>.log` | `src/datasystem/common/log/access_recorder.cpp:112-125`；支持环境变量 `DATASYSTEM_CLIENT_ACCESS_LOG_NAME` 覆盖前缀 |
| `${log_dir}/resource.log` | `FLAGS_log_dir + "/" + "resource" + ".log"`；`src/datasystem/common/metrics/res_metric_collector.cpp:61-62` |

#### D.2 关键 gflag

| gflag | 默认 | 语义 / 出处 |
|-------|------|-------------|
| `log_monitor` | `true` | 全局总开关。关掉后 `Tick()` / `PrintSummary()` 变空操作，metric 值仍累加但不落盘。`common_gflag_define.cpp:79` |
| `log_monitor_interval_ms` | `10000` | Summary 真实打印周期（不是 `Tick` 调度粒度）。`res_metric_collector.cpp:40` |
| `log_monitor_exporter` | `"harddisk"` | **当前代码仅接受 `"harddisk"`**；其它值（含帮助文本里的 `"backend"`）被 `ResMetricCollector::Init` 显式 reject 为 `K_INVALID`。 |
| `log_dir` | `$GOOGLE_LOG_DIR` / glog 默认 | 控制上表全部文件路径。`common_gflag_define.cpp:28` |

#### D.3 Metrics Summary 格式代码

```167:169:src/datasystem/common/metrics/metrics.cpp
    os << "Metrics Summary, version=" << VERSION << ", cycle=" << ++g_cycle
       << ", interval=" << intervalMs << "ms\n\n";
    os << "Total:\n" << total.str() << "\nCompare with "
       << intervalMs << "ms before:\n" << delta.str();
```

`VERSION = "v0"`（`metrics.cpp:33`）。

#### D.4 两种进程如何启 metrics

| 进程 | `InitKvMetrics` 位置 | `Tick` 驱动 |
|------|---------------------|-------------|
| **Worker** | `src/datasystem/worker/worker_oc_server.cpp::WorkerOCServer::Start`（`ReadinessProbe()` 之后） | `worker/worker_main.cpp` 主循环每秒 `metrics::Tick()` |
| **Client (SDK)** | `src/datasystem/client/kv_cache/kv_client.cpp::Init` / `InitEmbedded`；`client/object_cache/object_client.cpp::Init` | `client/object_cache/object_client_impl.cpp::StartMetricsThread` 后台线程每 1s tick（`FLAGS_log_monitor` 门控） |

---

### 附录 E · resource.log 完整字段（22 项）

字段定义于 `src/datasystem/common/metrics/res_metrics.def`，严格按此顺序输出。

| # | 顶层字段 | 子项 |
|---|---------|------|
| 1 | `SHARED_MEMORY` | `MEMORY_USAGE` / `PHYSICAL_MEMORY_USAGE` / `TOTAL_LIMIT` / `WORKER_SHARE_MEMORY_USAGE` / `SC_MEMORY_USAGE` / `SC_MEMORY_LIMIT` |
| 2 | `SPILL_HARD_DISK` | `SPACE_USAGE` / `PHYSICAL_SPACE_USAGE` / `TOTAL_LIMIT` / `WORKER_SPILL_HARD_DISK_USAGE` |
| 3 | `ACTIVE_CLIENT_COUNT` | `ACTIVE_CLIENT_COUNT` |
| 4 | `OBJECT_COUNT` | `OBJECT_COUNT` |
| 5 | `OBJECT_SIZE` | `OBJECT_SIZE` |
| 6 | `WORKER_OC_SERVICE_THREAD_POOL` | `IDLE_NUM / CURRENT_TOTAL_NUM / MAX_THREAD_NUM / WAITING_TASK_NUM / THREAD_POOL_USAGE` |
| 7 | `WORKER_WORKER_OC_SERVICE_THREAD_POOL` | （同上） |
| 8 | `MASTER_WORKER_OC_SERVICE_THREAD_POOL` | （同上） |
| 9 | `MASTER_OC_SERVICE_THREAD_POOL` | （同上） |
| 10 | `ETCD_QUEUE` | `CURRENT_SIZE / TOTAL_LIMIT / ETCD_QUEUE_USAGE` |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | `SUCCESS_RATE` |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | `SUCCESS_RATE` |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | （线程池五元组） |
| 14 | `STREAM_COUNT` | `STREAM_COUNT` |
| 15 | `WORKER_SC_SERVICE_THREAD_POOL` | （线程池五元组） |
| 16 | `WORKER_WORKER_SC_SERVICE_THREAD_POOL` | （线程池五元组） |
| 17 | `MASTER_WORKER_SC_SERVICE_THREAD_POOL` | （线程池五元组） |
| 18 | `MASTER_SC_SERVICE_THREAD_POOL` | （线程池五元组） |
| 19 | `STREAM_REMOTE_SEND_SUCCESS_RATE` | `SUCCESS_RATE` |
| 20 | `SHARED_DISK` | `USAGE / PHYSICAL_USAGE / TOTAL_LIMIT / USAGE_RATE` |
| 21 | `SC_LOCAL_CACHE` | `USAGE / RESERVED_USAGE / TOTAL_LIMIT / USAGE_RATE` |
| 22 | `OC_HIT_NUM` | `MEM_HIT_NUM / DISK_HIT_NUM / L2_HIT_NUM / REMOTE_HIT_NUM / MISS_NUM` |

---

### 附录 F · 对旧版文档（`fema-intermediate/08,10,11`）的修正项

现场已流传的几个**错误**，以代码为准纠正如下：

1. **`[TCP_CONN_WAIT_TIMEOUT]` 不存在**。真实前缀为 `[SOCK_CONN_WAIT_TIMEOUT]`（`zmq_stub_conn.cpp:1503`）和 `[REMOTE_SERVICE_WAIT_TIMEOUT]`（:1509）。
2. **`K_FILE_LIMIT_REACHED = 18`**，不是 20。`20 = K_DATA_INCONSISTENCY`。
3. **etcd 两种字符串并存**：Master 抛 `etcd is timeout`（`K_RUNTIME_ERROR`）；Worker 抛 `etcd is unavailable`（`K_RPC_UNAVAILABLE`）。grep 必须都加。
4. **SHM 泄漏 metric 旧名大多不存在**。正确名见 §2.4.3 及附录 C：`worker_allocator_alloc_bytes_total` / `worker_allocator_free_bytes_total` / `worker_shm_unit_created_total` / `worker_shm_unit_destroyed_total` / `worker_shm_ref_add_total` / `worker_shm_ref_remove_total` / `worker_shm_ref_table_size` / `worker_shm_ref_table_bytes`。旧文档中唯一还能用的是 `worker_shm_ref_table_bytes`。
5. **Metrics 总数 54**（`KvMetricId::KV_METRIC_END=54`），不是 36。新增 Master/TTL 段（46–51）和 Client async release 段（52–53）。
6. **新增错误码 `K_URMA_CONNECT_FAILED(1009)`**。
7. **`Cannot receive heartbeat from worker.`** 完整字符串末尾有句点；grep 用前缀匹配不影响。
8. **`fallback to TCP/IP payload`** 实际形态是 `, fallback to TCP/IP payload.`（带前导逗号与句点），宽松 grep 不受影响。
9. **`log_monitor_exporter` 仅支持 `"harddisk"`**，写 `"backend"` 会被 `ResMetricCollector::Init` reject。

---

### 附录 G · 文档维护约定

1. 错误码变化 → 先改 `include/datasystem/utils/status.h`，再同步 §1.2 / §5.1 / 附录 A。
2. 新增 `[PREFIX]` 标签 → 先在代码中落地并用 `rg '\[NEW_PREFIX\]' src/` 验证，再同步 §2 相应子节 + 附录 B。
3. 新增 metric → 追加在 `kv_metrics.cpp::KV_METRIC_DESCS` 末尾；同步附录 C 与 `KV_METRIC_END` 数字；§3 验收门槛随之更新。
4. `resource.log` 字段顺序以 `res_metrics.def` 为单一事实来源；附录 E 行号与之一一对应。
