# KVCache 故障定位定界指南：三板斧手册

> **文档版本**：v2.0
>
> **面向读者**：功能测试 / 集成测试工程师 / 研发值班
>
> **目标**：看到现象 → 知道查哪类 → 知道下一步查什么表/日志

---

## 日志体系全景图

### 日志文件

| 序号 | 类型 | 路径 | 用途 |
|------|------|------|------|
| 1 | Worker运行日志 | `/logs/datasystem_worker.INFO.log` | ERROR/WARN/INFO文本日志 |
| 2 | Worker访问日志 | `/logs/access.log` | POSIX接口请求（需开启log_monitor） |
| 3 | **Worker资源日志** | `/logs/resource.log` | 周期聚合资源指标 |
| 4 | 第三方请求日志 | `/logs/request_out.log` | Worker访问ETCD/OBS记录 |
| 5 | Client运行日志 | `/path/client/ds_client_{pid}.INFO.log` | SDK运行日志 |
| 6 | **Client访问日志** | `/path/client/ds_client_access_{pid}.log` | SDK访问日志 |

### Metrics周期打印

```
开关：log_monitor=true（默认）
周期：log_monitor_interval_ms=10000ms（默认）
导出：log_monitor_exporter=harddisk（写入resource.log）
格式：
  Metrics Summary, version=v0, cycle=<N>, interval=<ms>ms
  Total:
  <metric_name>=<value>
  Compare with <ms>ms before:
  <metric_name>=+<delta>
```

---

## 速查总览：三步定界框架

```
现象（成功率↓ / P99↑ / 抖动）
 │
 ├─ 第一板斧：归类 → 看到哪一大类问题
 │    ├─ A类：用户层错误（参数/NotFound/未Init）
 │    ├─ B类：OS层-控制面（RPC/ZMQ/网络）
 │    ├─ C类：URMA层（UB设备/连接/CQ）
 │    └─ D类：组件层（Worker/etcd/内存）
 │
 ├─ 第二板斧：分流 → 下一步查什么
 │    ├─ 日志关键字
 │    ├─ Metrics指标
 │    └─ Access log字段
 │
 └─ 第三板斧：落点 → 定位到具体故障
      ├─ 表查询归类
      ├─ grep命令模板
      └─ 根因判断
```

---

## 零、故障处理路线图

```
 ┌─ 用户层(A) ─────────────────────────────────────────┐
 │  K_INVALID(2) / K_NOT_FOUND(3) / K_NOT_READY(8)     │
 │  → 查respMsg关键字 / 检查业务参数                     │
 └─────────────────────────────────────────────────────┘
 │
┌─ 成功率↓/P99↑ ─┼─ OS层-控制面(B) ─────────────────────────┐
│                │  K_RPC_*(1001/1002) / K_TRY_AGAIN(19)     │
│                │  → 查[TCP_*] / [ZMQ_*] / [RPC_*]结构化日志  │
│                │  关注: [TCP_CONNECT_FAILED] / [ZMQ_SEND_   │
│                │        FAILURE_TOTAL] / [RPC_RECV_TIMEOUT]  │
│                └────────────────────────────────────────────┘
│                              │
└──────────────┼─ URMA层(C) ─────────────────────────────────────┐
               │  K_URMA_*(1004/1006/1008/1010)                     │
               │  → 查[URMA_*]标签 + UB/TCP bytes                   │
               │  关注: [URMA_NEED_CONNECT] / [URMA_RECREATE_JFS]  │
               │  关注: fallback to TCP                              │
               └────────────────────────────────────────────────────┘
                              │
 ┌─ 组件层(D) ─────────────────────────────────────────┐
 │  K_CLIENT_WORKER_DISCONNECT(23)                      │
 │  K_SCALE_DOWN(31) / K_SCALING(32)                    │
 │  K_OUT_OF_MEMORY(6) / K_MASTER_TIMEOUT(25)          │
 │  → 查[HealthCheck]标签 / etcd状态 / 内存指标         │
 │  关注: [HealthCheck] Worker is exiting now           │
 │  关注: Cannot receive heartbeat / etcd is timeout   │
 └─────────────────────────────────────────────────────┘
```

**说明**：
- **A类(用户层)**：业务参数问题，直接看respMsg
- **B类(OS层-控制面)**：RPC/ZMQ/TCP网络问题，看结构化日志标签
- **C类(URMA层)**：UB/URMA硬件问题，看URMA标签和降级指标
- **D类(组件层)**：Worker心跳/etcd/内存问题，看HealthCheck和资源指标

---

## 第一板斧：归类 — 按错误码判断大类

### 1.1 快速归类决策树

```
返回StatusCode →
 ├─ 是 0 (K_OK)？
 │    ├─ 是 → microseconds是否贴timeout / respMsg是否含NOT_FOUND
 │    └─ 否 → 继续判断
 │
 ├─ 是 2/3/8 (INVALID/NOT_FOUND/NOT_READY)？
 │    └─ → 用户层问题，检查业务参数/Init顺序
 │
 ├─ 是 1001/1002/19 (RPC超时/不可达)？
 │    └─ → OS层-控制面，查[TCP_*]/[ZMQ_*]日志标签
 │
 ├─ 是 1004/1006/1008/1010 (URMA族)？
 │    └─ → URMA层，查UB设备/驱动/CQ指标
 │
 ├─ 是 23/31/32 (心跳/扩缩容)？
 │    └─ → 组件层，查Worker状态/etcd
 │
 └─ 是 5/6/7/13/20/25 (OS资源/IO)？
      └─ → 组件层-Resources，查内存/磁盘/fd/etcd指标
```

### 1.2 错误码 → 故障域映射表

| 错误码 | 枚举名 | 故障域 | 优先怀疑方向 |
|-------|--------|-------|-------------|
| `0` | K_OK | ⚠️陷阱 | Get的NOT_FOUND被映射为0，需看respMsg |
| `2` | K_INVALID | **用户层** | 入参校验失败、参数非法 |
| `3` | K_NOT_FOUND | **用户层** | key不存在（非故障） |
| `5/7` | K_RUNTIME_ERROR | **组件层-Resources** | mmap失败、IO错误 |
| `6` | K_OUT_OF_MEMORY | **组件层-Resources** | 内存/shm池不足 |
| `8` | K_NOT_READY | **用户层** | 未Init或正在ShutDown |
| `13` | K_NO_SPACE | **组件层-Resources** | 磁盘空间满 |
| `19` | K_TRY_AGAIN | **OS层-控制面** | 服务端忙、瞬时可恢复 |
| `20` | K_FILE_LIMIT_REACHED | **组件层-Resources** | fd资源耗尽 |
| `23` | K_CLIENT_WORKER_DISCONNECT | **组件层** | 心跳断开/Worker退出 |
| `25` | K_MASTER_TIMEOUT | **组件层-Resources** | etcd不可用/节点超时 |
| `31` | K_SCALE_DOWN | **组件层** | Worker退出中（非用户错误） |
| `32` | K_SCALING | **组件层** | 扩缩容中（SDK已自动重试） |
| `1001` | K_RPC_DEADLINE_EXCEEDED | **OS层-控制面** | RPC超时（网络/对端/拥塞） |
| `1002` | K_RPC_UNAVAILABLE | **OS层-控制面** | RPC不可达（建连/传输失败） |
| `1004` | K_URMA_ERROR | **URMA层** | UB/URMA硬件或驱动路径 |
| `1006` | K_URMA_NEED_CONNECT | **URMA层** | URMA会话需重建 |
| `1008` | K_URMA_TRY_AGAIN | **URMA层** | URMA瞬时可恢复错误 |
| `1010` | K_URMA_WAIT_TIMEOUT | **URMA层** | URMA事件等待超时 |

---

## 第二板斧：分流 — 按大类查表

### 2.1 A类：用户层问题

#### 特征
- 错误码：K_INVALID(2), K_NOT_FOUND(3), K_NOT_READY(8)
- Client访问日志：respMsg含具体校验失败原因

#### Access log格式
```
code | handleName | microseconds | dataSize | reqMsg | respMsg
  ↑      ↑            ↑            ↑         ↑         ↑
 错误码  接口名        耗时(μs)     数据大小   请求参数   响应信息
```

#### respMsg关键字
| respMsg关键词 | 含义 | 处理建议 |
|-------------|------|---------|
| `The objectKey is empty` | key为空字符串 | 业务校验 |
| `dataSize should be bigger than zero` | size=0 | 业务校验 |
| `length not match` | keys/sizes长度不等 | 业务校验 |
| `ConnectOptions was not configured` | 未配置连接参数 | 检查Init配置 |
| `Client object is already sealed` | buffer重复Publish | 业务逻辑错误 |

#### grep模板
```bash
# 查看用户层错误分布
grep "DS_KV_CLIENT_GET" /path/client/ds_client_access_{pid}.log | awk -F'|' '{print $1}' | sort | uniq -c

# 查找INVALID类错误
grep "^2 |" /path/client/ds_client_access_{pid}.log

# 查找NOT_FOUND
grep "K_NOT_FOUND" /path/client/ds_client_access_{pid}.log
```

---

### 2.2 B类：OS层-控制面问题

#### 特征
- 错误码：K_RPC_DEADLINE_EXCEEDED(1001), K_RPC_UNAVAILABLE(1002), K_TRY_AGAIN(19)
- access log：microseconds贴timeout / respMsg含网络关键字

#### 结构化日志标签

| 标签 | 源码位置 | 触发语义 |
|------|----------|---------|
| `[TCP_CONNECT_FAILED]` | `unix_sock_fd.cpp::ConnectTcp` | addrinfo遍历完无法connect() |
| `[TCP_CONNECT_RESET]` | `unix_sock_fd.cpp::ErrnoToStatus` | ECONNRESET / EPIPE |
| `[TCP_NETWORK_UNREACHABLE]` | `zmq_stub_conn.cpp::SendHeartBeats` | ZMQ_POLLOUT失败 |
| `[TCP_CONN_WAIT_TIMEOUT]` | `zmq_stub_conn.cpp::WaitForConnected` | 连接建立等待超时 |
| `[SHM_FD_TRANSFER_FAILED]` | `client_worker_common_api.cpp::Connect` | 传shm fd辅助连接失败 |
| `[RPC_RECV_TIMEOUT]` | `zmq_stub_impl.h::Recv` | client等应答超时 |
| `[RPC_SERVICE_UNAVAILABLE]` | `zmq_stub_conn.cpp::BackendToFrontend` | 服务端把错误回包 |
| `[ZMQ_SEND_FAILURE_TOTAL]` | `zmq_socket_ref.cpp::SendMsg` | zmq_msg_send硬失败 |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `zmq_socket_ref.cpp::RecvMsg` | zmq_msg_recv硬失败 |
| `[ZMQ_RECV_TIMEOUT]` | `zmq_socket.cpp::ZmqRecvMsg` | 阻塞recv超时 |

#### ZMQ Metrics指标

| Metric | 含义 | 故障信号 |
|--------|-----|---------|
| `zmq_send_failure_total` | 发送硬失败 | delta>0 |
| `zmq_receive_failure_total` | 接收硬失败 | delta>0 |
| `zmq_network_error_total` | 网络错误 | delta>0 |
| `zmq_last_error_number` | 最近错误号(Gauge) | 非0 |
| `zmq_gateway_recreate_total` | 网关重建 | delta>0 |
| `zmq_event_disconnect_total` | 断开事件 | delta>0 |
| `zmq_event_handshake_failure_total` | 握手失败 | delta>0 |

#### 定位定界表

| 标签/指标组合 | 根因判断 | 处理建议 |
|--------------|---------|---------|
| `[TCP_CONNECT_FAILED]` + `zmq_last_error_number=111` | 端口不可达 | 检查Worker进程/端口 |
| `[TCP_CONNECT_RESET]` + `zmq_network_error_total`↑ | 对端崩溃/网络闪断 | 检查对端Worker状态 |
| `[RPC_RECV_TIMEOUT]` + ZMQ fault counters=0 | 对端处理慢/队列满 | 查Worker负载/CPU |
| `[ZMQ_SEND_FAILURE_TOTAL]` | ZMQ发送失败 | iptables规则/网络闪断 |
| `zmq_gateway_recreate_total`↑ + `zmq_event_disconnect_total`↑ | 连接被重置 | 正常恢复 |

#### grep模板
```bash
# 查TCP建连失败
grep -E "\[TCP_CONNECT_FAILED\]|\[TCP_CONNECT_RESET\]" /logs/datasystem_worker.INFO.log

# 查RPC超时
grep -E "\[RPC_RECV_TIMEOUT\]|\[RPC_SERVICE_UNAVAILABLE\]" /logs/datasystem_worker.INFO.log

# 查ZMQ失败
grep -E "\[ZMQ_SEND_FAILURE_TOTAL\]|\[ZMQ_RECEIVE_FAILURE_TOTAL\]" /logs/datasystem_worker.INFO.log

# 查shm fd传递失败
grep "\[SHM_FD_TRANSFER_FAILED\]" /logs/datasystem_worker.INFO.log
```

---

### 2.3 C类：URMA层问题

#### 特征
- 错误码：K_URMA_ERROR(1004), K_URMA_NEED_CONNECT(1006), K_URMA_TRY_AGAIN(1008), K_URMA_WAIT_TIMEOUT(1010)
- 日志含URMA关键字 / UB降级TCP

#### 结构化日志标签

| 标签 | 源码位置 | 触发语义 |
|------|----------|---------|
| `[URMA_NEED_CONNECT]` | `urma_manager.cpp::CheckUrmaConnectionStable` | 连接不存在/实例不匹配 |
| `[URMA_RECREATE_JFS]` | `urma_manager.cpp::HandleUrmaEvent` | JFS重建触发(cqeStatus=9) |
| `[URMA_RECREATE_JFS_FAILED]` | `urma_manager.cpp::HandleUrmaEvent` | JFS重建失败 |
| `[URMA_RECREATE_JFS_SKIP]` | `urma_manager.cpp` | connection已过期跳过重建 |
| `[URMA_POLL_ERROR]` | `urma_manager.cpp::ServerEventHandleThreadMain` | PollJfcWait报错 |
| `[URMA_WAIT_TIMEOUT]` | `urma_manager.cpp::WaitToFinish` | URMA事件等待超时 |

#### URMA Metrics指标

| Metric | 含义 | 故障信号 |
|--------|-----|---------|
| `client_put_urma_write_total_bytes` | UB写字节 | 降级时为0 |
| `client_put_tcp_write_total_bytes` | TCP写字节（降级） | 降级时↑ |
| `client_get_urma_read_total_bytes` | UB读字节 | 降级时为0 |
| `client_get_tcp_read_total_bytes` | TCP读字节（降级） | 降级时↑ |
| `worker_urma_write_latency` | UB写延迟 | max飙升 |

#### 降级判断
- 日志：`fallback to TCP/IP payload`
- `tcp_xxx_bytes`↑ 且 `urma_xxx_bytes`不涨

#### 定位定界表

| 标签/指标组合 | 根因判断 | 处理建议 |
|--------------|---------|---------|
| `[URMA_NEED_CONNECT]` + `remoteInstanceId`变化 | 远端Worker重启 | 正常恢复 |
| `[URMA_NEED_CONNECT]` 持续出现 | 连接不稳定 | 检查UB设备 |
| `[URMA_RECREATE_JFS]` + `cqeStatus=9` | JFS状态异常 | 自动重建 |
| `fallback to TCP/IP payload` 突增 | UB设备/链路故障 | 检查UB端口 |
| `worker_urma_write_latency` max飙升 | UB设备延迟 | 查硬件问题 |

#### grep模板
```bash
# 查URMA连接问题
grep -E "\[URMA_NEED_CONNECT\]" /logs/datasystem_worker.INFO.log

# 查JFS重建
grep -E "\[URMA_RECREATE_JFS\]" /logs/datasystem_worker.INFO.log

# 查UB降级
grep "fallback to TCP/IP payload" /logs/datasystem_worker.INFO.log
```

---

### 2.4 D类：组件层问题

#### 特征
- 错误码：K_SCALE_DOWN(31), K_SCALING(32), K_CLIENT_WORKER_DISCONNECT(23), K_OUT_OF_MEMORY(6), K_MASTER_TIMEOUT(25)
- 日志含HealthCheck关键字 / etcd超时 / 内存指标异常

#### 日志关键字

```
[HealthCheck] Worker is exiting now     → Worker退出中
Cannot receive heartbeat from worker   → 心跳超时
etcd is timeout                       → etcd超时
Disconnected from remote node         → 节点与etcd断开
meta_is_moving = true                 → 扩缩容中
Get mmap entry failed                 → mmap申请失败
```

#### resource.log关键指标

| 顺序 | 指标 | 含义 | 故障信号 |
|------|------|------|---------|
| 1 | `SHARED_MEMORY` | 共享内存使用率 | 突增→异常 |
| 4 | `OBJECT_COUNT` | 对象个数 | 异常变化 |
| 5 | `OBJECT_SIZE` | 对象总大小 | 突增→内存异常 |
| 10 | `ETCD_QUEUE` | etcd写队列 | 堆积→控制面受阻 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | etcd成功率 | 下降→etcd问题 |
| 22 | `OC_HIT_NUM` | 缓存命中率 | miss突增 |

#### SHM内存泄漏判断
```
特征：
  - shm.memUsage 100s内从 3.58GB → 37.5GB
  - OBJECT_COUNT 从 438 → 37 (反向于OBJECT_SIZE)

判断公式：
  worker_shm_alloc_total > worker_shm_free_total
  + worker_shm_ref_table_bytes 持续涨
  + OBJECT_COUNT 持平
  = 物理shm仍被钉住
```

#### 定位定界表

| 标签/指标组合 | 根因判断 | 处理建议 |
|--------------|---------|---------|
| `[HealthCheck] Worker is exiting now` | Worker主动退出 | k8s自动拉起 |
| `Cannot receive heartbeat from worker` | 心跳超时 | 检查Worker状态 |
| `SHARED_MEMORY`突增 + `worker_shm_ref_table_bytes`涨 | 内存泄漏 | 检查ref_table钉住 |
| `etcd is timeout` 持续 | etcd集群故障 | 紧急介入 |
| `OBJECT_COUNT` 突降 | Worker重启/数据丢失 | 检查稳定性 |

#### grep模板
```bash
# 查Worker退出
grep -E "\[HealthCheck\] Worker is exiting now|Cannot receive heartbeat" /logs/datasystem_worker.INFO.log

# 查etcd问题
grep -E "etcd is timeout|Disconnected from remote node" /logs/datasystem_worker.INFO.log

# 查扩缩容
grep -E "meta_is_moving|Scale down|K_SCALING" /logs/datasystem_worker.INFO.log

# 查内存指标
grep -E "worker_shm_(alloc|free|ref_table)" /logs/datasystem_worker.INFO.log

# 查resource.log内存
grep "SHARED_MEMORY" /logs/resource.log
```

---

## 第三板斧：落点 — Metrics + 日志交叉验证

### 3.1 Metrics Summary解读顺序

```
1. 先看cycle是否连续
   Metrics Summary, version=v0, cycle=123, interval=10000ms

2. 再看Compare with delta段
   client_get_request_total=+500, client_get_error_total=+5
   (↑有请求, ↑有5个错误)

3. 最后看Histogram的max
   client_rpc_get_latency,count=+500,avg=800us,max=50000us
```

### 3.2 P99劣化定位查表

| 现象 | 主查指标 | 次查指标 | 定界结论 |
|-----|---------|---------|---------|
| Get P99↑ | `client_rpc_get_latency` max | `worker_process_get_latency` | client侧慢/链路问题 |
| Get P99↑ + ZMQ counters=0 | `zmq_receive_io_latency` max | `zmq_send_io_latency` | 对端慢，非网络 |
| Publish P99↑ | `client_rpc_publish_latency` max | `worker_process_publish_latency` | 元数据/etcd问题 |
| UB P99↑ + 降级TCP | `worker_urma_write_latency` max | `client_get_tcp_read_total_bytes` | UB设备故障 |

### 3.3 成功率劣化定位查表

| 现象 | 主查指标 | 次查日志 | 定界结论 |
|-----|---------|---------|---------|
| Get错误率↑ | `client_get_error_total` / `client_get_request_total` | `[RPC_RECV_TIMEOUT]` | RPC超时 |
| Put错误率↑ | `client_put_error_total` / `client_put_request_total` | `[ZMQ_SEND_FAILURE_TOTAL]` | ZMQ发送失败 |
| URMA错误↑ | `client_get_urma_read_total_bytes`=0 | `[URMA_NEED_CONNECT]` | UB连接问题 |
| 降级TCP↑ | `client_get_tcp_read_total_bytes`↑ | `fallback to TCP/IP payload` | UB设备问题 |
| etcd超时↑ | `worker_rpc_create_meta_latency` max | `etcd is timeout` | etcd集群问题 |

---

## 附录A：故障构造与验收指南

### A.1 故障注入方法矩阵

| 故障类型 | 注入方法 | 验证指标 | 预期日志 |
|---------|---------|---------|---------|
| **ZMQ发送失败** | iptables drop / kill Worker | `zmq_send_failure_total`↑ | `[ZMQ_SEND_FAILURE_TOTAL]` |
| **RPC超时** | tc delay + timeout配置 | `client_rpc_get_latency` max↑ | `[RPC_RECV_TIMEOUT]` |
| **URMA连接断** | kill远端Worker | `zmq_gateway_recreate_total`↑ | `[URMA_NEED_CONNECT]` |
| **UB降级TCP** | ifconfig ub0 down | TCP bytes↑, URMA bytes=0 | `fallback to TCP/IP payload` |
| **JFS重建** | 触发cqeStatus=9 | `worker_urma_write_latency` max↑ | `[URMA_RECREATE_JFS]` |
| **etcd超时** | systemctl stop etcd | `K_MASTER_TIMEOUT` | `etcd is timeout` |
| **内存泄漏** | 模拟ref_table钉住 | `worker_shm_ref_table_bytes`涨 | - |
| **Worker退出** | kill -9 Worker | `worker_object_count`↓ | `[HealthCheck] exiting` |

### A.2 验收Checklist

**基础观测能力**：
- [ ] Worker日志有 `Metrics Summary, version=v0, cycle=...`
- [ ] Client日志有 `Metrics Summary, version=v0, cycle=...`
- [ ] resource.log有资源指标输出

**故障注入验证**：
- [ ] ZMQ故障：`zmq_send_failure_total` delta > 0
- [ ] URMA故障：`[URMA_NEED_CONNECT]` 或 `[URMA_RECREATE_JFS]` 出现
- [ ] 降级TCP：`client_get_tcp_read_total_bytes`↑ 且 `urma`不涨

---

## 附录B：快速参考

### B.1 错误码速查
```
0    = K_OK (注意NOT_FOUND陷阱)
2    = K_INVALID (用户参数)
3    = K_NOT_FOUND (不存在)
5/7  = K_RUNTIME_ERROR (mmap/IO)
6    = K_OUT_OF_MEMORY (内存不足)
8    = K_NOT_READY (未Init)
13   = K_NO_SPACE (磁盘满)
19   = K_TRY_AGAIN (重试)
20   = K_FILE_LIMIT (fd满)
23   = K_CLIENT_WORKER_DISCONNECT (心跳断)
25   = K_MASTER_TIMEOUT (etcd超时)
31   = K_SCALE_DOWN (Worker退出)
32   = K_SCALING (扩缩容)
1001 = K_RPC_DEADLINE_EXCEEDED (RPC超时)
1002 = K_RPC_UNAVAILABLE (RPC不可达)
1004 = K_URMA_ERROR (UB错误)
1006 = K_URMA_NEED_CONNECT (UB需重连)
1008 = K_URMA_TRY_AGAIN (UB重试)
1010 = K_URMA_WAIT_TIMEOUT (UB等待超时)
```

### B.2 grep一纸禅
```bash
# 查所有URMA标签
grep -E "\[URMA_" /logs/datasystem_worker.INFO.log

# 查所有TCP/ZMQ/RPC标签
grep -E "\[(TCP|ZMQ|RPC|SOCK)_" /logs/datasystem_worker.INFO.log

# 查Metrics delta
grep "Compare with" /logs/datasystem_worker.INFO.log | tail -3

# 查降级
grep "fallback to TCP" /logs/datasystem_worker.INFO.log

# 查Worker退出
grep "HealthCheck.*exiting" /logs/datasystem_worker.INFO.log

# 查etcd问题
grep "etcd is timeout" /logs/datasystem_worker.INFO.log

# 查SHM相关指标
grep "worker_shm_ref_table" /logs/datasystem_worker.INFO.log

# 查resource.log
grep "SHARED_MEMORY\|ETCD_QUEUE\|OC_HIT_NUM" /logs/resource.log
```

### B.3 日志文件速查
```
Worker日志：
  /logs/datasystem_worker.INFO.log      ← 运行日志
  /logs/access.log                      ← POSIX访问日志
  /logs/resource.log                    ← 资源指标
  /logs/request_out.log                 ← 第三方请求(ETCD/OBS)

Client日志：
  /path/client/ds_client_{pid}.INFO.log     ← SDK运行日志
  /path/client/ds_client_access_{pid}.log   ← SDK访问日志
```

### B.4 resource.log关键字段
```
顺序|指标|含义
1|SHARED_MEMORY|共享内存使用率
3|ACTIVE_CLIENT_COUNT|已建连客户端数
4|OBJECT_COUNT|对象个数
5|OBJECT_SIZE|对象总大小
6|WORKER_OC_SERVICE_THREAD_POOL|RPC线程池
7|WORKER_WORKER_OC_SERVICE_THREAD_POOL|Worker间RPC池
8|MASTER_WORKER_OC_SERVICE_THREAD_POOL|Master-Worker RPC池
9|MASTER_OC_SERVICE_THREAD_POOL|Master OC处理池
10|ETCD_QUEUE|etcd写队列
11|ETCD_REQUEST_SUCCESS_RATE|etcd成功率
12|OBS_REQUEST_SUCCESS_RATE|OBS成功率
13|MASTER_ASYNC_TASKS_THREAD_POOL|Master异步任务池
22|OC_HIT_NUM|缓存命中率(mem/disk/l2/remote/miss)
```
