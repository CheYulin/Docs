# 故障定位定界速查卡 v2.0

## 快速归类决策（30秒定位）

```
返回StatusCode →
├─ 0 (K_OK) 但业务失败 → respMsg是否NOT_FOUND陷阱
├─ 2/3/8 → 用户层：参数/NotFound/未Init
├─ 1001/1002/19 → OS层-控制面：RPC超时/不可达
├─ 1004/1006/1008/1010 → URMA层：UB设备/连接/CQ
├─ 23/31/32 → 组件层：心跳断/Worker退出/扩缩容
└─ 5/6/7/13/20/25 → 组件层-Resources：内存/磁盘/IO/etcd
```

---

## 一、日志文件路径

```
Worker日志：
  /logs/datasystem_worker.INFO.log      ← 运行日志(ERROR/WARN/INFO)
  /logs/access.log                      ← POSIX接口访问日志
  /logs/resource.log                    ← 资源指标(周期输出)
  /logs/request_out.log                 ← ETCD/OBS第三方请求

Client日志：
  /path/client/ds_client_{pid}.INFO.log     ← SDK运行日志
  /path/client/ds_client_access_{pid}.log    ← SDK访问日志
```

---

## 二、日志关键字速查

### OS层-控制面关键字
```
[TCP_CONNECT_FAILED]        → TCP建连失败
[TCP_CONNECT_RESET]          → 连接被重置
[TCP_NETWORK_UNREACHABLE]    → 网络不可达
[TCP_CONN_WAIT_TIMEOUT]      → 建连等待超时
[SHM_FD_TRANSFER_FAILED]     → 共享内存fd传递失败
[RPC_RECV_TIMEOUT]           → RPC应答超时
[RPC_SERVICE_UNAVAILABLE]   → 服务不可用
[ZMQ_SEND_FAILURE_TOTAL]     → ZMQ发送失败
[ZMQ_RECEIVE_FAILURE_TOTAL]  → ZMQ接收失败
[ZMQ_RECV_TIMEOUT]           → ZMQ接收超时
```

### URMA层关键字
```
[URMA_NEED_CONNECT]          → URMA连接需重建
[URMA_RECREATE_JFS]          → JFS重建触发
[URMA_RECREATE_JFS_FAILED]   → JFS重建失败
[URMA_RECREATE_JFS_SKIP]     → 跳过JFS重建
[URMA_POLL_ERROR]            → CQ poll失败
[URMA_WAIT_TIMEOUT]          → URMA等待超时
fallback to TCP/IP payload   → UB降级TCP
```

### 组件层关键字
```
[HealthCheck] Worker is exiting now → Worker退出中
Cannot receive heartbeat from worker → 心跳超时
etcd is timeout                     → etcd超时
Disconnected from remote node       → 节点与etcd断开
meta_is_moving = true               → 扩缩容中
Get mmap entry failed               → mmap申请失败
```

---

## 三、Metrics指标速查

### ZMQ指标（控制面）
| Metric | 含义 | 故障信号 |
|--------|-----|---------|
| `zmq_send_failure_total` | 发送失败 | delta>0 |
| `zmq_receive_failure_total` | 接收失败 | delta>0 |
| `zmq_network_error_total` | 网络错误 | delta>0 |
| `zmq_last_error_number` | 最近错误号 | 非0=Gauge |
| `zmq_gateway_recreate_total` | 网关重建 | delta>0 |
| `zmq_event_disconnect_total` | 断开事件 | delta>0 |
| `zmq_event_handshake_failure_total` | 握手失败 | delta>0 |

### URMA指标（数据面）
| Metric | 含义 | 故障信号 |
|--------|-----|---------|
| `client_put_urma_write_total_bytes` | UB写字节 | 降级=0 |
| `client_put_tcp_write_total_bytes` | TCP写字节 | 降级↑ |
| `client_get_urma_read_total_bytes` | UB读字节 | 降级=0 |
| `client_get_tcp_read_total_bytes` | TCP读字节 | 降级↑ |
| `worker_urma_write_latency` | UB写延迟 | max飙升 |

### KV业务指标
| Metric | 含义 | 用途 |
|--------|-----|------|
| `client_put_request_total` | Put请求总数 | 计算成功率 |
| `client_put_error_total` | Put错误总数 | 计算成功率 |
| `client_get_request_total` | Get请求总数 | 计算成功率 |
| `client_get_error_total` | Get错误总数 | 计算成功率 |

### SHM Leak指标
| Metric | 类型 | 含义 |
|--------|------|------|
| `worker_shm_alloc_total` | Counter | 分配总次数 |
| `worker_shm_free_total` | Counter | 释放总次数 |
| `worker_shm_alloc_bytes` | Counter | 分配总字节 |
| `worker_shm_free_bytes` | Counter | 释放总字节 |
| `worker_shm_ref_table_bytes` | Gauge | ref_table钉住字节 |
| `worker_shm_unit_ref_count` | Gauge | ShmUnit钉住计数 |

### resource.log关键字段
| 顺序 | 指标 | 含义 | 故障信号 |
|------|------|------|---------|
| 1 | `SHARED_MEMORY` | 共享内存使用率 | 突增→异常 |
| 4 | `OBJECT_COUNT` | 对象个数 | 异常变化 |
| 5 | `OBJECT_SIZE` | 对象总大小 | 突增→异常 |
| 10 | `ETCD_QUEUE` | etcd写队列 | 堆积 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | etcd成功率 | 下降 |
| 22 | `OC_HIT_NUM` | 命中率 | mem/disk/l2/remote/miss |

---

## 四、Access Log字段

```
code | handleName | microseconds | dataSize | reqMsg | respMsg
  ↑      ↑            ↑            ↑         ↑         ↑
错误码  接口名        耗时(μs)     数据大小   请求参数   响应信息
```

**注意陷阱**：
- **K_NOT_FOUND→0**：Get的NOT_FOUND在access log中显示为0
- **K_SCALING/K_SCALE_DOWN**：不是用户错误，SDK已处理

---

## 五、故障→验证对照表

| 故障 | 关键字/标签 | Metrics信号 | Access Log |
|-----|------------|------------|------------|
| ZMQ发送失败 | `[ZMQ_SEND_FAILURE_TOTAL]` | `zmq_send_failure_total`↑ | code=1002 |
| RPC超时 | `[RPC_RECV_TIMEOUT]` | `client_rpc_get_latency` max↑ | code=1001 |
| TCP建连失败 | `[TCP_CONNECT_FAILED]` | - | code=1002 |
| URMA需重连 | `[URMA_NEED_CONNECT]` | - | code=1006 |
| UB降级TCP | `fallback to TCP` | `tcp_xxx_bytes`↑ | - |
| JFS重建 | `[URMA_RECREATE_JFS]` | `worker_urma_write_latency` max↑ | - |
| etcd超时 | `etcd is timeout` | - | code=25 |
| Worker退出 | `[HealthCheck] exiting` | `worker_object_count`↓ | code=31 |
| 心跳超时 | `Cannot receive heartbeat` | - | code=23 |
| 内存泄漏 | `worker_shm_ref_table_bytes`涨 | OBJECT_COUNT↓但SIZE↑ | - |

---

## 六、常用grep命令

```bash
# 1. 查URMA标签
grep -E "\[URMA_" /logs/datasystem_worker.INFO.log

# 2. 查TCP/ZMQ/RPC标签
grep -E "\[(TCP|ZMQ|RPC|SOCK)_" /logs/datasystem_worker.INFO.log

# 3. 查Metrics delta
grep "Compare with" /logs/datasystem_worker.INFO.log | tail -3

# 4. 查错误码分布
grep "DS_KV_CLIENT_GET" /path/client/ds_client_access_{pid}.log | awk -F'|' '{print $1}' | sort | uniq -c

# 5. 查降级
grep "fallback to TCP" /logs/datasystem_worker.INFO.log

# 6. 查Worker退出
grep "HealthCheck.*exiting" /logs/datasystem_worker.INFO.log

# 7. 查etcd问题
grep "etcd is timeout" /logs/datasystem_worker.INFO.log

# 8. 查ZMQ失败
grep "zmq_.*_failure_total" /logs/datasystem_worker.INFO.log

# 9. 查SHM泄漏
grep "worker_shm_ref_table" /logs/datasystem_worker.INFO.log

# 10. 查resource.log资源
grep "SHARED_MEMORY\|ETCD_QUEUE\|OC_HIT_NUM" /logs/resource.log
```

---

## 七、SHM Leak判断

```
内存泄漏特征：
  - shm.memUsage 100s内从 3.58GB → 37.5GB
  - OBJECT_COUNT 从 438 → 37 (反向于OBJECT_SIZE)

判断公式：
  worker_shm_alloc_total > worker_shm_free_total
  + worker_shm_ref_table_bytes 持续涨
  + OBJECT_COUNT 持平
  = 元数据已删但物理shm仍被钉住
```

---

## 八、故障处理路线图

```
 ┌─ 用户层(A) ─────────────────────────────────────────┐
 │  K_INVALID(2) / K_NOT_FOUND(3) / K_NOT_READY(8)     │
 │  → 查respMsg关键字 / 检查业务参数                     │
 └─────────────────────────────────────────────────────┘
 │
┌─ 成功率↓/P99↑ ─┼─ OS层-控制面(B) ─────────────────────────┐
│                │  K_RPC_*(1001/1002) / K_TRY_AGAIN(19)     │
│                │  → 查[TCP_*] / [ZMQ_*] / [RPC_*]结构化日志  │
│                └────────────────────────────────────────────┘
│                              │
└──────────────┼─ URMA层(C) ─────────────────────────────────────┐
               │  K_URMA_*(1004/1006/1008/1010)                     │
               │  → 查[URMA_*]标签 + UB/TCP bytes                   │
               └────────────────────────────────────────────────────┘
                              │
 ┌─ 组件层(D) ─────────────────────────────────────────┐
 │  K_CLIENT_WORKER_DISCONNECT(23)                      │
 │  K_SCALE_DOWN(31) / K_SCALING(32)                    │
 │  K_OUT_OF_MEMORY(6) / K_MASTER_TIMEOUT(25)          │
 │  → 查[HealthCheck]标签 / etcd状态 / 内存指标         │
 └─────────────────────────────────────────────────────┘
```

**说明**：
- **A类(用户层)**：业务参数问题，直接看respMsg
- **B类(OS层-控制面)**：RPC/ZMQ/TCP网络问题，看结构化日志标签
- **C类(URMA层)**：UB/URMA硬件问题，看URMA标签和降级指标
- **D类(组件层)**：Worker心跳/etcd/内存问题，看HealthCheck和资源指标
