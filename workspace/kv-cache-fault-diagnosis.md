# KV Cache 通断类和时延类定位定界三板斧

---

# 一、通断类 — 连接/失败问题

**一、表象**

客户侧 KV Cache 请求成功率 < 99.9%，接口返回非 0 错误码

---

**二、故障排查**

步骤1：检查失败是否聚集在某个 Worker 节点

（1）如果是集中在个别 Worker 上，排查该 Worker 上的日志

（2）如果分布广泛，挑选报错节点排查

步骤2：排查用户业务问题

2.1 code ∈ {2, 3, 8} → 用户业务问题

（1）查看错误日志中的 respMsg 进行问题定界：

**表1**
| respMsg 片段 | 含义 | 常见问题排查指导 |
|---|---|---|
| `The objectKey is empty` / `dataSize should be bigger than zero` | 参数非法 | 业务校验 |
| `ConnectOptions was not configured` | 未配置 Init | 检查 Init |
| `Client object is already seal` | buffer 重复 Publish | 业务逻辑 |
| `OBJECT_KEYS_MAX_SIZE_LIMIT` | 批次超限 | 拆 batch |
| `Can't find object` / `K_NOT_FOUND` | 对象不存在 | 业务自查 key |

步骤3：排查 URMA 问题

3.1 code ∈ {1004, 1006, 1008, 1009, 1010} → URMA

（1）查看 URMA 日志进行问题定界：

**表2**
| 证据 | 含义 | 常见问题排查指导 |
|---|---|---|
| `[URMA_NEED_CONNECT]` + `remoteInstanceId` 变化 | 对端 Worker 重启 | 等 SDK 自重连稳定 |
| `[URMA_NEED_CONNECT]` 持续 + `instanceId` 不变 | UB 链路不稳 | 查 UB 端口/交换机抖动 |
| `[URMA_RECREATE_JFS]` + 无 `JFS_FAILED` | JFS 异常自动重建 | 自愈成功，无需处置 |
| `[URMA_RECREATE_JFS_FAILED]` 连续 | JFS 重建失败 | 查 UMDK / 驱动日志 |
| `fallback to TCP/IP payload` | URMA 降级至 TCP | 间歇少量为 UB 抖，持续高频为 UB 端口 down |
| `[URMA_POLL_ERROR]` | 驱动/硬件问题 | `dmesg` 查驱动日志 |
| code=1009 (`K_URMA_CONNECT_FAILED`) | URMA 建连失败 | `ifconfig ub0` / `ubinfo` 查端口状态 |

（2）如果 URMA 日志无异常，则进入步骤4

步骤4：排查 OS 问题

4.1 code ∈ {6, 7, 13, 18} → OS（内存/IO/磁盘/fd）

（1）查看错误日志进行问题定界：

**表3**
| 错误码 | 含义 | 常见问题排查指导 |
|---|---|---|
| code=6 (`K_OUT_OF_MEMORY`) | 内存不足 | `dmesg | grep -i oom`；`free -h` |
| code=7 (`K_IO_ERROR`) | IO 错误 | `dmesg`；检查磁盘 |
| code=13 (`K_NO_SPACE`) | 磁盘满 | `df -h`；清理磁盘 |
| code=18 (`K_FILE_LIMIT_REACHED`) | fd 满 | `ulimit -n`；调大 fd 限制 |

4.2 code ∈ {1001, 1002} 且日志前缀为 OS 相关

（1）查看日志前缀进行问题定界：

**表4**
| 日志前缀 | 含义 | 常见问题排查指导 |
|---|---|---|
| `[TCP_CONNECT_FAILED]` + 对端 Worker **活** | 端口不通/iptables/路由 | `ss -tnlp`；`iptables -L -n` |
| `[TCP_CONNECT_RESET]` / `[TCP_NETWORK_UNREACHABLE]` | 网络闪断 | `dmesg`；`netstat -s` |
| `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | 同机 UDS/SCM_RIGHTS 问题 | 检查路径/权限/fd 上限 |
| `[ZMQ_SEND_FAILURE_TOTAL]` + `zmq_last_error_number` | `zmq_msg_send/recv` 硬失败 | 按 errno 对照排查 |

（2）`zmq_last_error_number` → errno 对照：

**表5**
| N | 枚举 | 典型含义 |
|---|---|---|
| 11 | `EAGAIN` / `EWOULDBLOCK` | 背压（非错） |
| 101 | `ENETUNREACH` | 路由不可达 |
| 104 | `ECONNRESET` | 对端 reset |
| 110 | `ETIMEDOUT` | TCP 超时 |
| 111 | `ECONNREFUSED` | 端口无监听 |
| 113 | `EHOSTUNREACH` | 主机不可达 |

（3）如果 OS 日志无明确问题，则进入步骤5

步骤5：排查 etcd 三方问题

5.1 code=25 或 `etcd is timeout/unavailable`

（1）查看 etcd 日志进行问题定界：

**表6**
| 证据 | 含义 | 常见问题排查指导 |
|---|---|---|
| `etcd is timeout` / `etcd is unavailable` | etcd 集群或网络问题 | `etcdctl endpoint status`；`systemctl status etcd` |
| `ETCD_QUEUE` 堆积 | etcd 请求堆积 | 检查 etcd 集群健康状态 |
| `ETCD_REQUEST_SUCCESS_RATE` 下降 | etcd 可用性问题 | 检查 etcd 网络和磁盘 |

（2）如果 etcd 日志无异常，则进入步骤6

步骤6：定位 yuanrong-datasystem 问题

6.1 code ∈ {19, 23, 29, 31, 32} 或 code ∈ {1001, 1002} 且日志前缀为数据系统相关

（1）查看日志前缀进行问题定界：

**表7**
| 日志前缀 | 含义 | 常见问题排查指导 |
|---|---|---|
| `[RPC_RECV_TIMEOUT]` + ZMQ fault=0 | 对端处理慢 | `WAITING_TASK_NUM` 堆积；扩线程池 |
| `[RPC_SERVICE_UNAVAILABLE]` | 对端主动拒绝 | 检查对端状态 |
| `zmq_event_handshake_failure_total`↑ | TLS/认证配置问题 | 检查证书配置 |
| `[TCP_CONNECT_FAILED]` + 对端 Worker **不在** | 对端 Worker 重启/崩溃 | 检查对端进程 |
| `zmq_gateway_recreate_total`↑ | ZMQ 重建 | SDK 自重连，低频可忽略 |
| `Cannot receive heartbeat` (code=23) | 心跳超时 | 检查对端进程和网络 |
| `meta_is_moving` (code=31/32) | 扩缩容中 | SDK 自重试 |

（2）交叉验证：

- 对端 Worker 日志同时间窗有受理日志 → 对端活
- `worker_object_count` / access log 计数断崖 → 对端 Worker 重启

（3）资源指标：`WAITING_TASK_NUM` 堆积 → 查 CPU/锁；扩 `oc_rpc_thread_num`

---

**附录A：通断类错误码速查**

| 错误码 | 枚举 | 主责边界 |
|---|---|---|
| 0 | `K_OK` | 用户（Get 查不到时需看 respMsg） |
| 2 | `K_INVALID` | 用户 |
| 3 | `K_NOT_FOUND` | 用户 |
| 5 | `K_RUNTIME_ERROR` | OS/三方/URMA（按日志细分） |
| 6 | `K_OUT_OF_MEMORY` | OS |
| 7 | `K_IO_ERROR` | OS |
| 8 | `K_NOT_READY` | 用户 |
| 13 | `K_NO_SPACE` | OS |
| 18 | `K_FILE_LIMIT_REACHED` | OS |
| 19 | `K_TRY_AGAIN` | 数据系统/OS |
| 23 | `K_CLIENT_WORKER_DISCONNECT` | 数据系统/OS/机器 |
| 25 | `K_MASTER_TIMEOUT` | etcd 三方 |
| 29 | `K_SERVER_FD_CLOSED` | 数据系统 |
| 31 | `K_SCALE_DOWN` | 数据系统 |
| 32 | `K_SCALING` | 数据系统 |
| 1001 | `K_RPC_DEADLINE_EXCEEDED` | 数据系统/OS/三方 |
| 1002 | `K_RPC_UNAVAILABLE` | 数据系统/OS/三方 |
| 1004 | `K_URMA_ERROR` | URMA |
| 1006 | `K_URMA_NEED_CONNECT` | URMA |
| 1008 | `K_URMA_TRY_AGAIN` | URMA |
| 1009 | `K_URMA_CONNECT_FAILED` | URMA |
| 1010 | `K_URMA_WAIT_TIMEOUT` | URMA |

---

# 二、时延类 — 延迟问题

**一、表象**

KV Cache 请求 code 多为 0，但 P99 延迟显著升高、抖动

---

**二、故障排查**

步骤1：确认时延劣化

（1）检查 Metrics Summary delta 段，Histogram max 相对基线飙升（2-3×）

```bash
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3
```

（2）`count=+0` 则无流量，非时延问题

步骤2：排查用户/SDK 本地问题

（1）判断依据：`client_rpc_*_latency` max >> `worker_process_*_latency` max（Client 显著慢于 Worker）且 `worker_to_client_total_bytes` 正常（Worker 到 Client 数据传输正常）

→ 瓶颈在 Client 侧，问题定位到用户/SDK 本地

**表8**
| 观测现象 | 含义 | 常见问题排查指导 |
|---|---|---|
| `client_rpc_*_latency` max >> `worker_process_*_latency` max | Client 侧处理慢 | 用户业务代码反序列化/处理慢 |
| `worker_to_client_total_bytes` 正常 | Worker 到 Client 传输正常 | 排除网络和 Worker 问题 |
| 过大 batch | batch 接近 `OBJECT_KEYS_MAX_SIZE_LIMIT` | 拆 batch |
| SDK 调用线程被业务阻塞 | pstack 卡在 app 代码 | 检查业务代码 |
| 客户端 GC / 同步 IO | 运行时停顿 | 优化 GC；异步 IO |

（2）如果 Client 与 Worker 同幅慢或 Client 快于 Worker，则排除用户/SDK 问题，进入步骤3

步骤3：排查 URMA 问题

3.1 查看 URMA 相关指标

**表9**
| 证据 | 含义 | 常见问题排查指导 |
|---|---|---|
| `worker_urma_write_latency` max↑ | URMA 硬件/驱动慢 | `ifconfig ub0`；`ubinfo` |
| `urma_*` delta=0 + `tcp_*` 字节正常 + `fallback to TCP/IP payload` | URMA 降级至 TCP | 间歇少量为 UB 抖，持续高频为 UB 端口 down |
| `[URMA_NEED_CONNECT]` / `[URMA_RECREATE_JFS]` 间歇 | UB 链路不稳 | 查 UMDK / 驱动 |

（2）如果 URMA 指标正常，则进入步骤4

步骤4：排查 OS 网络问题

4.1 查看 OS 网络相关指标

**表10**
| 证据 | 含义 | 常见问题排查指导 |
|---|---|---|
| `ping` RTT 抖 | 网络链路抖动 | `ping -c 100 <peer>` |
| `tc qdisc` netem 残留 | netem 配置残留 | `tc qdisc show` |
| `nstat/ss -ti` 重传↑ | 网络丢包 | `nstat -az` |
| `zmq_send/receive_io_latency` max↑ + fault>0 | 网络栈问题 | `dmesg` |

（2）框架占比分析：

- `(serialize + deserialize) / (send_io + recv_io + serialize + deserialize)` < 5%
- 瓶颈不在 ZMQ/protobuf，中间网络或对端处理

（3）如果 OS 网络正常，则进入步骤5

步骤5：定位 yuanrong-datasystem 问题

5.1 Client vs Worker 拆解

（1）`client_rpc_*_latency` max 显著 > `worker_process_*_latency` max → 中间链路慢，进入步骤5.2

（2）两者同幅飙升 → 数据系统 Worker 业务慢

**表11**
| 子场景 | 证据 | 常见问题排查指导 |
|---|---|---|
| 线程池打满 | `WAITING_TASK_NUM` 堆积 | 扩线程池；查 CPU/锁 |
| 序列化慢 | 框架占比 ≥5% | 拆对象；启 URMA 零拷贝 |
| ZMQ 背压 | `zmq_send_try_again`↑ + fault=0 | 加消费线程；降峰限流 |

（3）`worker_rpc_get_remote_object_latency` max↑ → 跨 Worker Get，远端也慢则查远端业务

5.2 ZMQ RPC 队列时延细分（PR #686 新增 metrics）

> 通过 `MetaPb.ticks` 记录 8 个关键时间点，计算 7 个阶段延迟，实现**自证清白**

**Tick 时间线**：

```
CLIENT_ENQUEUE → CLIENT_TO_STUB → CLIENT_SEND → SERVER_RECV → SERVER_DEQUEUE → SERVER_EXEC_END → SERVER_SEND → CLIENT_RECV
    │              │                │             │              │               │              │
    ▼              ▼                ▼             ▼              ▼               ▼              ▼
 QUEUING      STUB_SEND      QUEUE_WAIT     EXEC          REPLY          E2E           NETWORK
```

**表12：7 个新增 Latency Metrics**
| Metric | 含义 | 计算公式 | 瓶颈定位 |
|---|---|---|---|
| `ZMQ_CLIENT_QUEUING_LATENCY` | Client 队列等待 | `CLIENT_TO_STUB - CLIENT_ENQUEUE` | MsgQue 堆积 |
| `ZMQ_CLIENT_STUB_SEND_LATENCY` | Client Stub 发送 | `CLIENT_SEND - CLIENT_TO_STUB` | ZmqFrontend 繁忙 |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | Server 队列等待 | `SERVER_DEQUEUE - SERVER_RECV` | Server 队列堆积 |
| `ZMQ_SERVER_EXEC_LATENCY` | Server 业务执行 | `SERVER_EXEC_END - SERVER_DEQUEUE` | 业务逻辑 |
| `ZMQ_SERVER_REPLY_LATENCY` | Server 回复延迟 | `SERVER_SEND - SERVER_EXEC_END` | Server 回复入队 |
| `ZMQ_RPC_E2E_LATENCY` | 端到端延迟 | `CLIENT_RECV - CLIENT_ENQUEUE` | 全流程 |
| `ZMQ_RPC_NETWORK_LATENCY` | 网络延迟 | `E2E - SERVER_EXEC` | OS 网络栈/硬件 |

**核心等式**：`NETWORK = E2E - SERVER_EXEC`

（1）如果 `NETWORK` 高但 `SERVER_EXEC` 正常 → OS 网络问题（回步骤4）

（2）如果 `CLIENT_QUEUING` / `CLIENT_STUB_SEND` 高 → 数据系统 Client 问题

（3）如果 `SERVER_QUEUE_WAIT` / `SERVER_REPLY` 高 → 数据系统 Server 问题

（4）如果 `SERVER_EXEC` 高 → 数据系统 Server 业务逻辑问题

---

**附录B：时延类 Metrics 速查**

| Metric | 类型 | 单位 | 说明 |
|---|---|---|---|
| `client_rpc_create_latency` | Histogram | us | Client RPC 创建 |
| `client_rpc_publish_latency` | Histogram | us | Client RPC 发布 |
| `client_rpc_get_latency` | Histogram | us | Client RPC 获取 |
| `worker_process_create_latency` | Histogram | us | Worker 处理创建 |
| `worker_process_publish_latency` | Histogram | us | Worker 处理发布 |
| `worker_process_get_latency` | Histogram | us | Worker 处理获取 |
| `worker_urma_write_latency` | Histogram | us | URMA 写入 |
| `worker_tcp_write_latency` | Histogram | us | TCP 写入 |
| `zmq_send_io_latency` | Histogram | us | ZMQ 发送 IO |
| `zmq_receive_io_latency` | Histogram | us | ZMQ 接收 IO |
| `zmq_rpc_serialize_latency` | Histogram | us | ZMQ 序列化 |
| `zmq_rpc_deserialize_latency` | Histogram | us | ZMQ 反序列化 |

**降级判据**：`urma_*` delta=0 + `tcp_*` delta↑ + `fallback to TCP/IP payload`

**框架占比** = `(serialize + deserialize) / (send_io + recv_io + serialize + deserialize)`，≥5% 为数据系统框架问题

---

**附录C：resource.log 核心字段**

| 字段 | 含义 | 用途 |
|---|---|---|
| `SHARED_MEMORY` | 共享内存使用 | 接近 TOTAL_LIMIT 需排查 |
| `WAITING_TASK_NUM` | 线程池等待任务数 | 堆积为数据系统问题 |
| `ETCD_QUEUE` | etcd 请求队列 | 堆积为 etcd 问题 |
| `ETCD_REQUEST_SUCCESS_RATE` | etcd 请求成功率 | 下降为 etcd 问题 |
| `OC_HIT_NUM` | 缓存命中统计 | 分析缓存效果 |
