# 12.3 KVCache性能劣化

## 故障排查流程索引

```
P99时延升高
     │
     ├── 步骤1：确认聚集服务器（监控看板）
     │
     ├── 步骤2：确认劣化（max↑）
     │
     ├── 步骤3：URMA降级检查 ──→ 【URMA】联系URMA和底软团队
     │
     ├── 步骤4：规格超标检查 ──→ 【客户业务侧】扩容
     │
     ├── 步骤5：数据系统分段定位
     │        ├── ① Client SDK ──→ 【客户业务侧】
     │        ├── ② Client→Worker ──→ 步骤6自证清白
     │        ├── ③ 元数据访问（跨Worker）─→ 步骤6自证清白
     │        └── ④ 数据访问（跨Worker/UB）─→ 步骤6自证清白
     │
     ├── 步骤6：自证清白（ZMQ RPC）──→ 【KVC】或【客户运维侧】
     │
     ├── 步骤7：ZMQ/OS网络 ──→ 【客户运维侧】
     │
     └── 步骤8：SDK本地问题 ──→ 【客户业务侧】
```

## 一、故障现象

- 客户侧SDKP99时延上升x%
- 客户侧KVC Worker P99时延上升x%

## 二、故障排查

### 步骤1：确认P99时延上升是否聚集在某个服务器上

**操作**：查看监控看板，筛选异常P99时延的Pod IP分布

**判断**：
- 如果集中在个别服务器上 → 进入该异常服务器，通过步骤2排查
- 如果分布广泛 → 挑选报错服务器的日志进行排查

---

### 步骤2：确认时延劣化

**操作**：查看Metrics Summary，确认有实际流量且时延真的升高

```bash
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3
```

| 数据字段 | 名称 | 日志位置 | 结果 | 结论 | 解决措施 |
|----------|------|----------|------|------|----------|
| `Compare with` | Metrics Summary周期对比 | 运行日志-metrics | `count=+0` | 无流量，非时延问题 | 无需处理 |
| `Compare with` | Metrics Summary周期对比 | 运行日志-metrics | `max` ↑2-3× | 确认劣化 | 继续步骤3 |

---

### 步骤3：检查URMA是否降级到TCP

> **最优先检查项**。URMA降级到TCP会导致性能大幅下降。

**操作**：

```bash
# 检查降级日志
grep 'fallback to TCP/IP payload' $LOG/datasystem_worker.INFO.log

# 检查URMA/TCP字节统计
grep 'client_put_urma_write_total_bytes' $LOG/ds_client_*.INFO.log | tail -3
grep 'client_put_tcp_write_total_bytes' $LOG/ds_client_*.INFO.log | tail -3
grep 'client_get_urma_read_total_bytes' $LOG/ds_client_*.INFO.log | tail -3
grep 'client_get_tcp_read_total_bytes' $LOG/ds_client_*.INFO.log | tail -3
```

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|----------|----------|
| `fallback to TCP/IP payload` | URMA降级日志 | - | 运行日志-错误消息 | 频繁出现（>10次/分钟） | URMA降级到TCP | **URMA** | 联系URMA和底软团队 |
| `client_put_urma_write_total_bytes` | Client URMA写入字节 | bytes | 运行日志-metrics | delta=0 | URMA通道未使用 | **URMA** | 检查UB连接 |
| `client_put_tcp_write_total_bytes` | Client TCP写入字节 | bytes | 运行日志-metrics | delta>0 且 urma_delta=0 | TCP降级 | **URMA** | 联系URMA和底软团队 |
| `client_get_urma_read_total_bytes` | Client URMA读取字节 | bytes | 运行日志-metrics | delta=0 | URMA通道未使用 | **URMA** | 检查UB连接 |
| `client_get_tcp_read_total_bytes` | Client TCP读取字节 | bytes | 运行日志-metrics | delta>0 且 urma_delta=0 | TCP降级 | **URMA** | 联系URMA和底软团队 |

---

### 步骤4：检查规格/流量是否超标

> 业务流量大导致的性能劣化，非数据系统问题。

**操作**：

```bash
# 请求量
grep 'client_put_request_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'client_get_request_total' $LOG/datasystem_worker.INFO.log | tail -3

# 连接数
grep 'ACTIVE_CLIENT_COUNT' $LOG/resource.log | tail -3

# 线程池负载
grep 'WAITING_TASK_NUM' $LOG/resource.log | tail -3
grep 'MAX_THREAD_NUM' $LOG/resource.log | tail -3
```

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|----------|----------|
| `client_put_request_total` | Client Put请求总数 | count | 运行日志-metrics | 超过设计规格 | 流量规格超标 | **客户业务侧** | 扩容或降业务量 |
| `client_get_request_total` | Client Get请求总数 | count | 运行日志-metrics | 超过设计规格 | 流量规格超标 | **客户业务侧** | 扩容或降业务量 |
| `ACTIVE_CLIENT_COUNT` | 活跃客户端数 | count | resource日志 | 超过设计上限 | 并发规格超标 | **客户业务侧** | 扩容或优化连接 |
| `WAITING_TASK_NUM` | 等待任务数 | count | resource日志 | 接近MAX_THREAD_NUM | 线程池打满 | **客户业务侧** | 扩容线程池或降业务量 |
| `WAITING_TASK_NUM` | 等待任务数 | count | resource日志 | 堆积但未达上限 | 数据系统问题 | **KVC** | 检查CPU/锁/线程池配置 |
| `MAX_THREAD_NUM` | 最大线程数 | count | resource日志 | 作为对比基准 | - | - | - |

---

### 步骤5：数据系统内部性能分段定位

> 数据系统内部将性能问题分为4段，逐段定位瓶颈所在。

**分段架构**：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         KVCache 性能分段                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐    ┌──────────────┐    ┌────────────┐    ┌────────────────┐  │
│  │ Client   │───▶│ Client→Worker│───▶│ 元数据访问  │───▶│   数据访问     │  │
│  │  SDK     │    │  (ZMQ RPC)   │    │  (Worker)  │    │ (URMA 或 TCP)  │  │
│  └──────────┘    └──────────────┘    └────────────┘    └────────────────┘  │
│       │                │                  │                   │             │
│       ▼                ▼                  ▼                   ▼             │
│  client_rpc_     zmq_client_        worker_rpc_          worker_urma_     │
│  get_latency     queuing_latency    create_meta_          write_latency     │
│  publish_latency stub_send_latency  query_meta_latency    tcp_write_latency │
│                                                                             │
│  耗时分段：                                                                   │
│  ① Client SDK耗时：client_rpc_get_latency / client_rpc_publish_latency (us) │
│  ② Client→Worker：zmq_client_queuing_latency + zmq_server_queue_wait_latency │
│  ③ 元数据访问：worker_rpc_create_meta_latency / worker_rpc_query_meta_latency (us) │
│  ④ 数据访问：worker_urma_write_latency / worker_tcp_write_latency (us)     │
│                                                                             │
│  自证清白：②④需通过ZMQ RPC指标区分KVC内部 vs 外部网络问题                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**操作**：查看日志平台中各分段时延

```bash
# ① Client SDK耗时
grep 'client_rpc_get_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'client_rpc_publish_latency' $LOG/datasystem_worker.INFO.log | tail -3

# ② Client→Worker（ZMQ RPC）
grep 'zmq_client_queuing_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_client_stub_send_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_server_queue_wait_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_server_exec_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_server_reply_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_rpc_e2e_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_rpc_network_latency' $LOG/datasystem_worker.INFO.log | tail -3

# ③ 元数据访问
grep 'worker_rpc_create_meta_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'worker_rpc_query_meta_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'worker_rpc_get_remote_object_latency' $LOG/datasystem_worker.INFO.log | tail -3

# ④ 数据访问
grep 'worker_urma_write_latency' $LOG/datasystem_worker.INFO.log | tail -3
grep 'worker_tcp_write_latency' $LOG/datasystem_worker.INFO.log | tail -3
```

**判断**：哪个分段max最高，哪个就是瓶颈；②和④需自证清白区分KVC vs 外部问题

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 分段 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|------|----------|----------|
| `client_rpc_get_latency` | Client RPC Get延迟 | us | 运行日志-metrics | P99高 | ① Client SDK | Client端慢 | **客户业务侧** | 检查业务代码 |
| `client_rpc_publish_latency` | Client RPC Publish延迟 | us | 运行日志-metrics | P99高 | ① Client SDK | Client端慢 | **客户业务侧** | 检查业务代码 |
| `zmq_client_queuing_latency` | Client队列等待 | us | 运行日志-metrics | 值高 | ② Client→Worker | Client框架慢 | **KVC** | 步骤6自证清白 |
| `zmq_client_stub_send_latency` | Client Stub发送 | us | 运行日志-metrics | 值高 | ② Client→Worker | Client框架慢 | **KVC** | 步骤6自证清白 |
| `zmq_server_queue_wait_latency` | Server队列等待 | us | 运行日志-metrics | 值高 | ② Client→Worker | Server框架慢 | **KVC** | 步骤6自证清白 |
| `zmq_server_exec_latency` | Server业务执行 | us | 运行日志-metrics | 值高 | ② Client→Worker | Server框架慢 | **KVC** | 步骤6自证清白 |
| `zmq_server_reply_latency` | Server回复入队 | us | 运行日志-metrics | 值高 | ② Client→Worker | Server框架慢 | **KVC** | 步骤6自证清白 |
| `worker_rpc_create_meta_latency` | 创建元数据延迟 | us | 运行日志-metrics | 值高 | ③ 元数据访问 | 元数据操作慢 | **KVC** | 步骤6自证清白 |
| `worker_rpc_query_meta_latency` | 查询元数据延迟 | us | 运行日志-metrics | 值高 | ③ 元数据访问 | 元数据操作慢 | **KVC** | 步骤6自证清白 |
| `worker_rpc_get_remote_object_latency` | 跨Worker获取延迟 | us | 运行日志-metrics | 值高 | ③/④ 跨Worker | 跨Worker慢 | **KVC** | 步骤6自证清白 |
| `worker_urma_write_latency` | URMA写入延迟 | us | 运行日志-metrics | 值高 | ④ 数据访问 | URMA慢 | **URMA** | 联系URMA团队 |
| `worker_tcp_write_latency` | TCP写入延迟 | us | 运行日志-metrics | 值高 | ④ 数据访问 | TCP降级慢 | **URMA** | 检查URMA状态 |

**跨Worker自证清白**：当③或④涉及跨Worker操作时，通过步骤6的ZMQ RPC指标判断是本端Worker问题还是远端Worker/网络问题

---

### 步骤6：自证清白（ZMQ RPC）

> 当②Client→Worker或③跨Worker或④跨Worker耗时高时，通过ZMQ RPC指标区分是KVC框架问题还是OS/网络问题。

**关键耗时分段（us）**：

```
Client  ───►  Server
  │              │
  │   CLIENT     │     SERVER
  │  QUEUING     │   QUEUE_WAIT
  │              │
  │   CLIENT     │     SERVER
  │ STUB_SEND    │     EXEC
  │              │
  │   NETWORK    │     REPLY
  │              │
  └──────►◄──────┘
       E2E = NETWORK + EXEC
```

**公式**：`zmq_rpc_network_latency = zmq_rpc_e2e_latency - zmq_server_exec_latency`

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|----------|----------|
| `zmq_client_queuing_latency` | Client队列等待 | us | 运行日志-metrics | 值高 | Client框架慢 | **KVC** | 检查Client端prefetcher |
| `zmq_client_stub_send_latency` | Client Stub发送 | us | 运行日志-metrics | 值高 | Client框架慢 | **KVC** | 检查ZmqFrontend线程 |
| `zmq_server_queue_wait_latency` | Server队列等待 | us | 运行日志-metrics | 值高 | Server框架慢 | **KVC** | 检查Server处理能力 |
| `zmq_server_exec_latency` | Server业务执行 | us | 运行日志-metrics | 值高 | Server业务慢 | **KVC** | 优化业务代码 |
| `zmq_server_reply_latency` | Server回复入队 | us | 运行日志-metrics | 值高 | Server回复慢 | **KVC** | 检查Server回复能力 |
| `zmq_rpc_e2e_latency` | 端到端延迟 | us | 运行日志-metrics | 值高 | 整体慢 | - | 分段定位 |
| `zmq_rpc_network_latency` | 网络延迟 | us | 运行日志-metrics | 值高+框架正常 | 网络本身慢 | **客户运维侧** | 检查网络设备和链路 |

---

### 步骤7：ZMQ/OS网络故障检查

**操作**：

```bash
# ZMQ故障
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_receive_failure_total' $LOG/datasystem_worker.INFO.log | tail -3

# OS网络
ping -c 100 <peer_ip>
tc qdisc show dev eth0
nstat -az
```

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|----------|----------|
| `zmq_send_failure_total` | ZMQ发送失败次数 | count | 运行日志-metrics | delta>0 | ZMQ发送失败 | **客户运维侧** | 检查网络和防火墙 |
| `zmq_receive_failure_total` | ZMQ接收失败次数 | count | 运行日志-metrics | delta>0 | ZMQ接收失败 | **客户运维侧** | 检查网络和防火墙 |
| `zmq_send_try_again_total` | ZMQ发送重试次数 | count | 运行日志-metrics | delta>0且failure=0 | 背压非故障 | - | 正常现象 |
| ping RTT | 网络延迟 | ms | OS命令 | 抖动 | 网络抖动 | **客户运维侧** | 检查网络设备 |
| tc qdisc | 队列规则 | - | OS命令 | 有netem残留 | 网络配置问题 | **客户运维侧** | 清理tc配置 |
| nstat重传 | TCP重传 | count | OS命令 | 重传↑ | 网络丢包 | **客户运维侧** | 检查网络链路 |

---

### 步骤8：用户/SDK本地问题

**操作**：查看SDK access log单请求时延

```bash
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
grep 'DS_KV_CLIENT_PUT' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
```

| 数据字段 | 名称 | 单位 | 日志位置 | 判定方法 | 结论 | 责任主体 | 解决措施 |
|----------|------|------|----------|----------|------|----------|----------|
| `DS_KV_CLIENT_GET` | SDK Get请求日志 | - | 运行日志-错误消息 | 单请求P99高但系统正常 | 业务代码慢 | **客户业务侧** | 优化业务代码 |
| `DS_KV_CLIENT_PUT` | SDK Put请求日志 | - | 运行日志-错误消息 | 单请求P99高但系统正常 | 业务代码慢 | **客户业务侧** | 优化业务代码 |

---

## 三、归责速查

| 责任主体 | 归属 | 判断依据 |
|----------|------|----------|
| **URMA** | 分布式并行实验室、海思 | `fallback to TCP/IP payload`频繁 / `client_put_urma_write_total_bytes`=0 |
| **KVC** | 分布式并行实验室 | 框架指标高 / `WAITING_TASK_NUM`堆积但未达上限 |
| **客户业务侧** | 客户业务 | 规格超标 / SDK access log单请求高 |
| **客户运维侧** | 客户运维 | `zmq_rpc_network_latency`高+框架正常 / `zmq_send_failure_total`有delta / ping抖 |

---

## 四、日志位置速查

| 日志类型 | 文件位置 | 说明 |
|----------|----------|------|
| 运行日志-metrics | `datasystem_worker.INFO.log` | Metrics Summary指标输出 |
| resource日志 | `resource.log` | 资源监控（线程池、客户端数等） |
| 运行日志-错误消息 | `datasystem_worker.INFO.log` | 结构化错误日志和降级日志 |

---

## 五、Metric速查

### 业务时延（us）

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `client_rpc_get_latency` | Client RPC Get延迟 | us | SDK发起Get到收到响应时间 | P99高表示Client端慢 | 检查业务代码 |
| `client_rpc_publish_latency` | Client RPC Publish延迟 | us | SDK发起Publish到收到响应时间 | P99高表示Client端慢 | 检查业务代码 |
| `client_rpc_create_latency` | Client RPC Create延迟 | us | SDK发起Create到收到响应时间 | P99高表示Client端慢 | 检查业务代码 |
| `worker_process_get_latency` | Worker处理Get延迟 | us | Worker实际处理Get的时间 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_process_publish_latency` | Worker处理Publish延迟 | us | Worker实际处理Publish的时间 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_process_create_latency` | Worker处理Create延迟 | us | Worker实际处理Create的时间 | 值高表示Worker业务慢 | 检查Worker端 |
| `worker_rpc_create_meta_latency` | 创建元数据延迟 | us | Worker创建元数据的时间 | 值高表示元数据操作慢 | 检查元数据服务 |
| `worker_rpc_query_meta_latency` | 查询元数据延迟 | us | Worker查询元数据的时间 | 值高表示元数据操作慢 | 检查元数据服务 |
| `worker_rpc_get_remote_object_latency` | 跨Worker获取延迟 | us | 跨Worker获取对象的时间 | 值高表示跨Worker或网络慢 | 自证清白定位 |
| `worker_urma_write_latency` | URMA写入延迟 | us | Worker通过URMA写入数据时间 | 值高表示URMA慢 | 联系URMA团队 |
| `worker_tcp_write_latency` | TCP写入延迟 | us | Worker通过TCP写入数据时间 | 值高表示TCP降级慢 | 检查URMA状态 |

### 数据面字节（bytes）

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `client_put_urma_write_total_bytes` | URMA写入字节 | bytes | Client通过URMA写入的总字节数 | delta=0表示URMA通道未使用 | 检查URMA连接 |
| `client_put_tcp_write_total_bytes` | TCP写入字节 | bytes | Client通过TCP写入的总字节数 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |
| `client_get_urma_read_total_bytes` | URMA读取字节 | bytes | Client通过URMA读取的总字节数 | delta=0表示URMA通道未使用 | 检查URMA连接 |
| `client_get_tcp_read_total_bytes` | TCP读取字节 | bytes | Client通过TCP读取的总字节数 | delta>0且urma_delta=0表示降级 | 联系URMA团队 |

### ZMQ RPC队列时延（us）

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `zmq_client_queuing_latency` | Client队列等待 | us | Client到Stub队列等待时间 | 值高表示MsgQue堆积 | 检查Client端prefetcher |
| `zmq_client_stub_send_latency` | Client Stub发送 | us | Stub到Socket发送时间 | 值高表示ZmqFrontend繁忙 | 检查ZmqFrontend线程 |
| `zmq_server_queue_wait_latency` | Server队列等待 | us | Server接收后到执行前等待 | 值高表示Server请求队列堆积 | 检查Server处理能力 |
| `zmq_server_exec_latency` | Server业务执行 | us | Server实际业务处理时间 | 值高表示业务逻辑慢 | 优化业务代码 |
| `zmq_server_reply_latency` | Server回复入队 | us | Server执行完到回复入队时间 | 值高表示回复队列堆积 | 检查Server回复能力 |
| `zmq_rpc_e2e_latency` | 端到端延迟 | us | Client发出到收到响应总时间 | P99高表示整体慢 | 分段定位瓶颈 |
| `zmq_rpc_network_latency` | 网络延迟 | us | E2E减去Server执行时间 | 值高+框架正常表示网络慢 | 检查网络设备和链路 |

### ZMQ故障监控

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `zmq_send_failure_total` | ZMQ发送失败次数 | count | ZMQ发送失败累计次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_receive_failure_total` | ZMQ接收失败次数 | count | ZMQ接收失败累计次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_send_try_again_total` | ZMQ发送重试次数 | count | ZMQ发送重试累计次数 | delta>0且failure=0为背压非故障 | 正常现象 |

### 资源监控（resource.log）

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `ACTIVE_CLIENT_COUNT` | 活跃客户端数 | count | 当前连接的客户端数量 | 超过设计上限 | 扩容或优化连接管理 |
| `WAITING_TASK_NUM` | 等待任务数 | count | 线程池排队任务数 | 接近MAX_THREAD_NUM表示打满 | 扩容线程池或减少业务量 |
| `MAX_THREAD_NUM` | 最大线程数 | count | 线程池配置的最大线程数 | 作为WAITING_TASK_NUM的对比基准 | - |
| `WORKER_OC_SERVICE_THREAD_POOL` | RPC线程池 | - | RPC服务线程池状态 | WAITING_TASK_NUM堆积 | 扩线程池或查CPU/锁 |
