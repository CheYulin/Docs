# 12.3 KVCache 性能劣化

## 故障排查流程索引

```
P99时延升高
     │
     ├── 步骤1：确认聚集服务器（监控看板）
     │
     ├── 步骤2：确认劣化（Metrics Summary）
     │     核心：看 max（count>0 时）是否 ↑2-3×
     │
     ├── 步骤3：URMA降级检查 ──→ 【URMA】fallback日志/URMA字节=0 → 联系URMA团队
     │
     ├── 步骤4：规格超标检查 ──→ 【客户业务侧】线程池打满/并发超标 → 扩容
     │
     ├── 步骤5：数据系统分段定位（思路：②/③/④均为Worker间通信）
     │        ├── ① Client SDK ──→ 【客户业务侧】Client端代码慢
     │        ├── ② Client→Worker ──→ ZMQ RPC段，详见附录A.1
     │        ├── ③ 元数据访问（Worker↔Worker）──→ 详见附录A.1
     │        └── ④ 数据访问（Worker↔Worker，URMA/TCP）──→ 详见附录A.1
     │     思路：②③④分段确认，哪个分段 max 最高就是瓶颈
     │
     ├── 步骤6：自证清白（ZMQ RPC）──→ network = e2e - exec，详见附录B
     │     思路：e2e高时，用公式拆出纯网络耗时，区分框架慢还是网络慢
     │
     ├── 步骤7：ZMQ/OS网络 ──→ 【客户运维侧】failure delta>0 → 网络/防火墙
     │
     └── 步骤8：SDK本地问题 ──→ 【客户业务侧】单请求P99高+系统正常 → 业务代码
```

## 一、故障现象

- 客户侧 SDK P99时延上升 x%
- 客户侧 KVC Worker P99时延上升 x%

## 二、故障排查

### 步骤1：确认P99时延聚集在哪个服务器

**操作**：查看监控看板，筛选异常P99时延的Pod IP分布

**判断**：
- 集中在个别服务器 → 进入该异常服务器，通过步骤2排查
- 分布广泛 → 挑选报错服务器的日志进行排查

---

### 步骤2：确认时延劣化

> **核心**：从 Metrics Summary 中找 P99/max 指标，确认 count>0 且 max 有明显上升。

**操作**：
```bash
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3
```

**判定**：

| 关键字段 | 含义 | 判定 |
|----------|------|------|
| `count` | 该周期内的请求数 | count=0 → 无流量，忽略 |
| `max` | P99最大耗时（微秒） | count>0 且 max ↑2-3× → 确认劣化 |

---

### 步骤3：检查URMA是否降级到TCP

> **最优先检查项**。URMA降级到TCP会导致性能大幅下降。

**操作**：
```bash
# 检查降级日志
grep 'fallback to TCP/IP payload' $LOG/datasystem_worker.INFO.log

# Client侧 URMA/TCP 字节
grep 'client_put_urma_write_total_bytes\|client_put_tcp_write_total_bytes' $LOG/ds_client_*.INFO.log | tail -3
grep 'client_get_urma_read_total_bytes\|client_get_tcp_read_total_bytes' $LOG/ds_client_*.INFO.log | tail -3

# Worker侧 URMA/TCP 字节
grep 'worker_put_urma_write_total_bytes\|worker_put_tcp_write_total_bytes' $LOG/datasystem_worker.INFO.log | tail -3
grep 'worker_get_urma_read_total_bytes\|worker_get_tcp_read_total_bytes' $LOG/datasystem_worker.INFO.log | tail -3
```

**判定**：

| 证据 | 结论 | 处置 |
|------|------|------|
| `fallback to TCP/IP payload` 频繁出现（>10次/分钟） | URMA降级到TCP | 联系URMA和底软团队 |
| `*_urma_*_bytes` delta=0 且 `*_tcp_*_bytes` delta>0 | TCP降级 | 联系URMA和底软团队 |
| `*_urma_*_bytes` delta>0 且 `*_tcp_*_bytes` delta=0 | URMA正常 | 继续步骤4 |

---

### 步骤4：检查规格/流量是否超标

> 业务流量大导致的性能劣化，非数据系统问题。

**操作**：
```bash
# 请求量
grep 'client_put_request_total\|client_get_request_total' $LOG/datasystem_worker.INFO.log | tail -3

# 线程池负载
grep 'WAITING_TASK_NUM\|MAX_THREAD_NUM' $LOG/resource.log | tail -3

# 活跃客户端数
grep 'ACTIVE_CLIENT_COUNT' $LOG/resource.log | tail -3
```

**判定**：

| 证据 | 结论 | 处置 |
|------|------|------|
| `WAITING_TASK_NUM` 接近 `MAX_THREAD_NUM` | 线程池打满 | 扩容或降业务量 |
| `ACTIVE_CLIENT_COUNT` 超过设计上限 | 并发超标 | 扩容或优化连接 |
| 请求量超过设计规格 | 流量超标 | 扩容或降业务量 |
| `WAITING_TASK_NUM` 堆积但未达上限 | 数据系统问题 | 继续步骤5 |

---

### 步骤5：数据系统内部性能分段定位

> 数据系统内部将性能问题分为4段，各段责任归属不同。

**分段架构**：

```
┌─────────────────────────────────────────────────────────────────┐
│  ① Client SDK  │  ② Client→Worker  │  ③ 元数据访问  │  ④ 数据访问  │
│   (ZMQ RPC)    │    (ZMQ RPC)       │    (Worker)   │ (URMA/TCP)  │
└─────────────────────────────────────────────────────────────────┘
       ↓                 ↓                  ↓               ↓
  client_rpc_*      zmq_client_*       worker_rpc_*    worker_urma_*
  get_latency       queuing_latency    query_meta_*   write_latency
  publish_latency   stub_send_latency create_meta_*  tcp_write_latency
```

**判定规则**：哪个分段 max 最高，哪个就是瓶颈。

| 分段 | 耗时高归责 | 可能原因 | 详见 |
|------|-----------|---------|------|
| ① Client SDK | **客户业务侧** | 业务代码慢/prefetcher配置 | 步骤8 |
| ② Client→Worker | **KVC** 或 **客户运维侧** | 框架慢或网络慢 | 附录A.1 + 步骤6自证清白 |
| ③ 元数据访问 | **KVC** | 元数据服务慢/锁冲突 | 附录A.1 |
| ④ 数据访问 | **URMA** 或 **客户运维侧** | URMA慢/TCP降级/网络慢 | 步骤3 + 步骤6自证清白 |

> 跨 Worker 操作（③或④涉及远端）通过步骤6的 ZMQ RPC 指标判断是本端问题还是远端/网络问题，详见附录A.2。

---

### 步骤6：自证清白（ZMQ RPC）

> 当②或④耗时高时，通过 ZMQ RPC 指标区分 KVC 框架问题还是 OS/网络问题。

**E2E 耗时分解**：
```
E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY
                                           ↑
                                    ↑        ↑
                              这一段是       ↑
                            SERVER_EXEC    SERVER_REPLY已包含网络回程
```

**核心公式**：`zmq_rpc_network_latency = zmq_rpc_e2e_latency - zmq_server_exec_latency`

- `zmq_rpc_network_latency` = 纯网络传输耗时（请求发出 + 响应收回）
- 如果 `network_latency` 高但 `server_exec_latency` 正常 → **网络本身慢**，找客户运维侧

**操作**：
```bash
grep 'zmq_rpc_e2e_latency\|zmq_rpc_network_latency\|zmq_server_exec_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_client_queuing_latency\|zmq_client_stub_send_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_server_queue_wait_latency\|zmq_server_reply_latency' $LOG/datasystem_worker.INFO.log | tail -3
```

**判定**：

| 证据 | 结论 | 处置 |
|------|------|------|
| `zmq_server_exec_latency` 高 | Server业务慢 | 优化业务代码 |
| `zmq_client_queuing_latency` 高 | Client端框架慢 | 检查prefetcher |
| `zmq_server_queue_wait_latency` 高 | Server队列堆积 | 检查Server处理能力 |
| `zmq_rpc_network_latency` 高 + 框架正常 | 网络本身慢 | **客户运维侧**：检查网络设备和链路 |
| `zmq_rpc_e2e_latency` 高 + 各分段正常 | 整体负载高 | 扩容或降业务量 |

---

### 步骤7：ZMQ/OS网络故障检查

**操作**：
```bash
# ZMQ故障
grep 'zmq_send_failure_total\|zmq_receive_failure_total' $LOG/datasystem_worker.INFO.log | tail -3

# OS网络
ping -c 100 <peer_ip>
tc qdisc show dev eth0
nstat -az
```

**判定**：

| 证据 | 结论 | 处置 |
|------|------|------|
| `zmq_send/receive_failure_total` delta>0 | ZMQ发送/接收失败 | **客户运维侧**：检查网络和防火墙 |
| `zmq_send_try_again_total` delta>0 但 failure=0 | 背压（非故障） | 正常现象 |
| ping 抖动 | 网络抖动 | **客户运维侧**：检查网络设备 |
| `tc qdisc` 有 netem 残留 | 网络配置问题 | **客户运维侧**：清理tc配置 |
| nstat TCP重传 ↑ | 网络丢包 | **客户运维侧**：检查网络链路 |

---

### 步骤8：用户/SDK本地问题

**操作**：
```bash
# 从 access log 计算单请求 P99
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
grep 'DS_KV_CLIENT_PUT' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
```

**判定**：单请求P99高但系统指标正常 → 业务代码问题。

---

## 三、归责速查

| 责任主体 | 归属 | 判断依据 |
|----------|------|----------|
| **URMA** | 分布式并行实验室、海思 | `fallback to TCP` 频繁 / URMA字节=0 + TCP字节>0 |
| **KVC** | 分布式并行实验室 | 框架指标高 / `WAITING_TASK_NUM` 堆积但未达上限 |
| **客户业务侧** | 客户业务 | 规格超标 / SDK access log 单请求高 |
| **客户运维侧** | 客户运维 | `zmq_rpc_network_latency` 高+框架正常 / `zmq_*_failure_total` delta>0 / ping抖 |

---

## 附录A：分段定位详解

### A.1 四段耗时含义

| 分段 | 指标 | 正常范围 | 耗时高时归责 |
|------|------|---------|------------|
| ① Client SDK | `client_rpc_get_latency` / `client_rpc_publish_latency` | < 1ms | **客户业务侧**：业务代码/prefetcher |
| ② Client→Worker | `zmq_client_queuing_latency` + `zmq_server_queue_wait_latency` | < 500μs | 自证清白后归 **KVC** 或 **客户运维侧** |
| ③ 元数据访问 | `worker_rpc_create_meta_latency` / `worker_rpc_query_meta_latency` | < 100μs | **KVC**：元数据服务/锁冲突 |
| ④ 数据访问 | `worker_urma_write_latency` / `worker_tcp_write_latency` | URMA<10μs，TCP<100μs | 自证清白后归 **URMA** 或 **客户运维侧** |

### A.2 跨Worker自证清白

当③或④涉及跨 Worker 操作时，通过以下公式区分本端 Worker 问题还是远端 Worker/网络问题：

```
远端贡献 = zmq_rpc_get_remote_object_latency - (本地Worker处理时延 + 网络时延)
```

- 远端贡献占比 > 50% → 远端 Worker 或网络问题
- 本端占比高 → 本端 Worker 问题

**操作**：
```bash
grep 'worker_rpc_get_remote_object_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_rpc_network_latency' $LOG/datasystem_worker.INFO.log | tail -3
```

---

## 附录B：Metrics 完整参考

### B.1 业务时延类（单位：μs）

| 指标 | 名称 | 判定方法 | 解决措施 |
|------|------|---------|---------|
| `client_rpc_get_latency` | Client RPC Get延迟 | P99高表示Client端慢 | 检查业务代码 |
| `client_rpc_publish_latency` | Client RPC Publish延迟 | P99高表示Client端慢 | 检查业务代码 |
| `client_rpc_create_latency` | Client RPC Create延迟 | P99高表示Client端慢 | 检查业务代码 |
| `worker_process_get_latency` | Worker处理Get延迟 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_process_publish_latency` | Worker处理Publish延迟 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_process_create_latency` | Worker处理Create延迟 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_rpc_create_meta_latency` | 创建元数据延迟 | 值高表示元数据操作慢 | 检查元数据服务 |
| `worker_rpc_query_meta_latency` | 查询元数据延迟 | 值高表示元数据操作慢 | 检查元数据服务 |
| `worker_rpc_get_remote_object_latency` | 跨Worker获取延迟 | 值高表示跨Worker或网络慢 | 自证清白定位 |
| `worker_urma_write_latency` | URMA写入延迟 | 值高表示URMA慢 | 联系URMA团队 |
| `worker_tcp_write_latency` | TCP写入延迟 | 值高表示TCP降级慢 | 检查URMA状态 |

### B.2 ZMQ RPC队列时延类（单位：μs）

| 指标 | 名称 | 判定方法 | 解决措施 |
|------|------|---------|---------|
| `zmq_client_queuing_latency` | Client队列等待 | 值高表示MsgQue堆积 | 检查Client端prefetcher |
| `zmq_client_stub_send_latency` | Client Stub发送 | 值高表示ZmqFrontend繁忙 | 检查ZmqFrontend线程 |
| `zmq_server_queue_wait_latency` | Server队列等待 | 值高表示Server请求队列堆积 | 检查Server处理能力 |
| `zmq_server_exec_latency` | Server业务执行 | 值高表示业务逻辑慢 | 优化业务代码 |
| `zmq_server_reply_latency` | Server回复入队 | 值高表示回复队列堆积 | 检查Server回复能力 |
| `zmq_rpc_e2e_latency` | 端到端延迟 | P99高表示整体慢 | 分段定位瓶颈 |
| `zmq_rpc_network_latency` | 网络延迟 | 值高+框架正常表示网络慢 | 检查网络设备和链路 |

### B.3 数据面字节类（单位：bytes）

| 指标 | 名称 | 判定方法 | 解决措施 |
|------|------|---------|---------|
| `client_put_urma_write_total_bytes` | Client URMA写入字节 | delta=0表示URMA通道未使用 | 检查URMA连接 |
| `client_put_tcp_write_total_bytes` | Client TCP写入字节 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |
| `client_get_urma_read_total_bytes` | Client URMA读取字节 | delta=0表示URMA通道未使用 | 检查URMA连接 |
| `client_get_tcp_read_total_bytes` | Client TCP读取字节 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |
| `worker_put_urma_write_total_bytes` | Worker URMA写入字节 | delta=0表示URMA通道未使用 | 检查UB连接 |
| `worker_put_tcp_write_total_bytes` | Worker TCP写入字节 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |
| `worker_get_urma_read_total_bytes` | Worker URMA读取字节 | delta=0表示URMA通道未使用 | 检查UB连接 |
| `worker_get_tcp_read_total_bytes` | Worker TCP读取字节 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |

### B.4 ZMQ故障监控 + resource监控

| 指标 | 名称 | 判定方法 | 解决措施 |
|------|------|---------|---------|
| `zmq_send_failure_total` | ZMQ发送失败次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_receive_failure_total` | ZMQ接收失败次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_send_try_again_total` | ZMQ发送重试次数 | delta>0且failure=0为背压非故障 | 正常现象 |
| `ACTIVE_CLIENT_COUNT` | 活跃客户端数 | 超过设计上限 | 扩容或优化连接管理 |
| `WAITING_TASK_NUM` | 等待任务数 | 接近MAX_THREAD_NUM表示打满 | 扩容线程池或减少业务量 |
| `MAX_THREAD_NUM` | 最大线程数 | 作为WAITING_TASK_NUM的对比基准 | — |

---

## 附录C：日志位置速查

| 日志类型 | 文件位置 | 说明 |
|----------|----------|------|
| 运行日志-metrics | `datasystem_worker.INFO.log` | Metrics Summary 指标输出 |
| resource日志 | `resource.log` | 资源监控（线程池、客户端数等） |
| 运行日志-错误消息 | `datasystem_worker.INFO.log` | 结构化错误日志和降级日志 |
