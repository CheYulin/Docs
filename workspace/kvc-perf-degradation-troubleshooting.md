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

| 结果 | 结论 |
|------|------|
| `count=+0` | 无流量，非时延问题 |
| `max` ↑2-3× | 确认劣化，继续步骤3 |

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

| 结果 | 结论 | 责任主体 |
|------|------|----------|
| `fallback to TCP/IP payload` 频繁出现 | URMA降级到TCP | **URMA**（联系URMA和底软团队） |
| `client_put_urma_write_total_bytes` delta=0 且 `client_put_tcp_write_total_bytes` delta>0 | URMA降级到TCP | **URMA**（联系URMA和底软团队） |
| `client_get_urma_read_total_bytes` delta=0 且 `client_get_tcp_read_total_bytes` delta>0 | URMA降级到TCP | **URMA**（联系URMA和底软团队） |

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

| 结果 | 结论 | 责任主体 |
|------|------|----------|
| QPS/并发超过设计规格 | 流量规格超标 | **客户业务侧**（需扩容） |
| `WAITING_TASK_NUM` 接近 `MAX_THREAD_NUM` | 线程池打满 | **客户业务侧**（需扩容） |
| `WAITING_TASK_NUM` 堆积但未达上限 | 数据系统问题 | **KVC** |

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

| 分段 | Metric | 责任主体 |
|------|--------|----------|
| ① Client SDK | `client_rpc_get_latency` / `client_rpc_publish_latency` 高 | 客户业务侧自查 |
| ② Client→Worker | `zmq_client_queuing_latency` / `zmq_client_stub_send_latency` / `zmq_server_queue_wait_latency` / `zmq_server_exec_latency` / `zmq_server_reply_latency` 高 | **KVC**（自证清白见步骤6） |
| ③ 元数据访问 | `worker_rpc_create_meta_latency` / `worker_rpc_query_meta_latency` 高 | **KVC**（跨Worker见步骤6自证清白） |
| ④ 数据访问 | `worker_urma_write_latency` / `worker_tcp_write_latency` 高 | **KVC**（跨Worker见步骤6自证清白） |

**跨Worker自证清白**：当③或④涉及跨Worker操作（如`worker_rpc_get_remote_object_latency`）时，通过步骤6的ZMQ RPC指标判断是本端Worker问题还是远端Worker/网络问题

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

| 分类 | Metric | 结论 | 责任主体 |
|------|--------|------|----------|
| Client框架高 | `zmq_client_queuing_latency` / `zmq_client_stub_send_latency` 高 | Client框架慢 | **KVC** |
| Worker框架高 | `zmq_server_queue_wait_latency` / `zmq_server_exec_latency` / `zmq_server_reply_latency` 高 | Server框架慢 | **KVC** |
| 网络高 + 框架正常 | `zmq_rpc_network_latency` 高且其他正常 | 网络本身慢 | **客户运维侧** |

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

| 结果 | 结论 | 责任主体 |
|------|------|----------|
| `zmq_send_failure_total` 有delta | ZMQ发送失败 | **客户运维侧** |
| `zmq_receive_failure_total` 有delta | ZMQ接收失败 | **客户运维侧** |
| ping RTT抖动 | 网络抖动 | **客户运维侧** |
| tc qdisc有netem残留 | 网络配置问题 | **客户运维侧** |
| nstat显示重传↑ | 网络丢包 | **客户运维侧** |

---

### 步骤8：用户/SDK本地问题

**操作**：查看SDK access log单请求时延

```bash
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
grep 'DS_KV_CLIENT_PUT' $LOG/ds_client_access_*.log | awk -F'|' '{print $3}' | sort -n | awk 'END{print "P99="$1}'
```

| 结果 | 结论 | 责任主体 |
|------|------|----------|
| 单请求时延高但系统指标正常 | 业务代码处理慢 | **客户业务侧** |

---

## 三、归责速查

| 责任主体 | 归属 | 判断依据 |
|----------|------|----------|
| **URMA** | 分布式并行实验室、海思 | `fallback to TCP/IP payload`频繁 / `client_put_urma_write_total_bytes`=0 |
| **KVC** | 分布式并行实验室 | 框架指标高 / `WAITING_TASK_NUM`堆积但未达上限 |
| **客户业务侧** | 客户业务 | 规格超标 / SDK access log单请求高 |
| **客户运维侧** | 客户运维 | `zmq_rpc_network_latency`高+框架正常 / `zmq_send_failure_total`有delta / ping抖 |

---

## 四、Metric速查

### 时延（us）

| Metric | 分段 |
|--------|------|
| `client_rpc_get_latency` | ① Client SDK |
| `client_rpc_publish_latency` | ① Client SDK |
| `client_rpc_create_latency` | ① Client SDK |
| `worker_process_get_latency` | ④ 数据访问（处理） |
| `worker_process_publish_latency` | ④ 数据访问（处理） |
| `worker_process_create_latency` | ④ 数据访问（处理） |
| `worker_rpc_create_meta_latency` | ③ 元数据访问 |
| `worker_rpc_query_meta_latency` | ③ 元数据访问 |
| `worker_rpc_get_remote_object_latency` | ③/④ 跨Worker |
| `worker_urma_write_latency` | ④ 数据访问-URMA |
| `worker_tcp_write_latency` | ④ 数据访问-TCP降级 |

### ZMQ RPC队列时延（us）

| Metric | 说明 |
|--------|------|
| `zmq_client_queuing_latency` | ② Client QUEUING |
| `zmq_client_stub_send_latency` | ② Client STUB_SEND |
| `zmq_server_queue_wait_latency` | ② SERVER QUEUE_WAIT |
| `zmq_server_exec_latency` | ② SERVER EXEC |
| `zmq_server_reply_latency` | ② SERVER REPLY |
| `zmq_rpc_e2e_latency` | ② 端到端 |
| `zmq_rpc_network_latency` | ② 网络延迟（E2E-EXEC） |

### 数据面字节（bytes）

| Metric | 说明 |
|--------|------|
| `client_put_urma_write_total_bytes` | Client URMA写入 |
| `client_put_tcp_write_total_bytes` | Client TCP写入 |
| `client_get_urma_read_total_bytes` | Client URMA读取 |
| `client_get_tcp_read_total_bytes` | Client TCP读取 |
