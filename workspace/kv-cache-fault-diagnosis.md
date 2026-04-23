# KV Cache 通断类和时延类定位定界三板斧

---

# 一、通断类 — 连接/失败问题

**一、表象**

客户侧 KV Cache 请求成功率 < 99.9%，接口返回非 0 错误码

---

**二、故障排查**

**责任边界说明**：

| 边界 | 责任组织 | 说明 |
|---|---|---|
| 用户业务 | 客户业务 | 参数校验、Init、key 存在性 |
| OS | 客户业务运维/硬件 | 内存、磁盘、fd、网络、内核配置 |
| etcd 三方 | 客户运维 | etcd 集群和网络 |
| URMA | 分布式并行实验室/海思 | UB 硬件/驱动/UMDK |
| yuanrong-datasystem | 分布式并行实验室 | 数据系统进程内 |

---

步骤1：检查失败是否聚集在某个 Worker 节点

（1）如果是集中在个别 Worker 上，排查该 Worker 上的日志

（2）如果分布广泛，挑选报错节点排查

步骤2：排查用户业务问题

2.1 code ∈ {2, 3, 8} → 用户业务

（1）查看错误日志中的 respMsg 进行问题定界：

**表1**
| 错误码 | respMsg 片段 | 责任组织 | 常见问题排查指导 |
|---|---|---|---|
| `K_INVALID`(2) | `The objectKey is empty` | 客户业务 | 业务校验 |
| `K_INVALID`(2) | `dataSize should be bigger than zero` | 客户业务 | 业务校验 |
| `K_NOT_FOUND`(3) | `Can't find object` | 客户业务 | 业务自查 key |
| `K_NOT_READY`(8) | `ConnectOptions was not configured` | 客户业务 | 检查 Init |

步骤3：排查 code=5 (K_RUNTIME_ERROR)

3.1 code=5 需要根据错误信息细分

（1）查看具体错误信息

```bash
grep -E 'K_RUNTIME_ERROR|Get mmap entry failed|etcd is|urma' $LOG/datasystem_worker.INFO.log | tail -50
```

（2）根据错误信息定界：

**表7**
| 错误信息 | 责任边界 | 责任组织 | 常见问题排查指导 |
|---|---|---|---|
| `Get mmap entry failed` | OS | 客户业务运维 | `ulimit -l unlimited`；检查内存锁定限制 |
| `etcd is timeout/unavailable` | etcd 三方 | 客户运维 | `etcdctl endpoint status`；检查 etcd 集群和网络 |
| `urma ... payload ...` | URMA | 分布式并行实验室/海思 | 查 URMA 日志 |

3.2 如果错误信息为 `Get mmap entry failed` → OS（内存锁定限制）

（1）检查 mlock 限制

```bash
ulimit -l unlimited
cat /proc/<pid>/limits | grep 'Max locked memory'
```

（2）如仍失败，检查内存是否不足

```bash
free -h
dmesg | grep -i 'out of memory'
```

3.3 如果错误信息为 `etcd is timeout/unavailable` → etcd 三方

（1）检查 etcd 集群状态

```bash
etcdctl endpoint status -w table
systemctl status etcd
```

（2）检查到 etcd 的网络

```bash
ping <etcd_ip>
```

3.4 如果错误信息为 `urma ... payload ...` → URMA

（1）查看 URMA 相关日志

```bash
grep -E '\[URMA_' $LOG/*.INFO.log | tail -20
```

（2）如果 URMA 日志无异常，则进入步骤5

步骤4：排查 URMA 问题

4.1 code ∈ {1004, 1006, 1008, 1009, 1010} → URMA

（1）查看 URMA 日志进行问题定界：

**表7**
| 错误码 | 证据 | 责任组织 | 常见问题排查指导 |
|---|---|---|---|
| `K_URMA_ERROR`(1004) | `[URMA_POLL_ERROR]` | 海思 | 驱动/硬件问题；`dmesg` |
| `K_URMA_NEED_CONNECT`(1006) | `[URMA_NEED_CONNECT]` + `remoteInstanceId` 变化 | 分布式并行实验室 | 对端 Worker 重启；等 SDK 自重连 |
| `K_URMA_NEED_CONNECT`(1006) | `[URMA_NEED_CONNECT]` 持续 + `instanceId` 不变 | 海思 | UB 链路不稳；查 UB 端口/交换机 |
| `K_URMA_TRY_AGAIN`(1008) | `[URMA_RECREATE_JFS]` + 无 `JFS_FAILED` | 分布式并行实验室 | JFS 自愈成功；无需处置 |
| `K_URMA_TRY_AGAIN`(1008) | `[URMA_RECREATE_JFS_FAILED]` 连续 | 海思/分布式并行实验室 | 查 UMDK/驱动日志；联系海思 |
| `K_URMA_CONNECT_FAILED`(1009) | `[URMA_NEED_CONNECT]` 高频 + `ifconfig ub0 DOWN` | 海思 | UB 端口硬件；`ifconfig ub0 up` |
| `K_URMA_WAIT_TIMEOUT`(1010) | `[URMA_WAIT_TIMEOUT]` | 分布式并行实验室 | SDK 重试白名单自愈 |

（2）`fallback to TCP/IP payload` → URMA 降级至 TCP（间歇少量为 UB 抖，持续高频为 UB 端口 down）

（3）如果 URMA 日志无异常，则进入步骤5

步骤5：排查 OS 问题

5.1 code ∈ {6, 7, 13, 18} → OS

（1）查看错误日志进行问题定界：

**表7**
| 错误码 | 含义 | 责任组织 | 常见问题排查指导 |
|---|---|---|---|
| 
| `K_OUT_OF_MEMORY`(6) | 内存不足 | 客户业务运维/硬件 | `dmesg | grep -i oom`；`free -h`；检查物理内存 |
| `K_IO_ERROR`(7) | IO 错误 | 客户业务运维/硬件 | `dmesg`；检查磁盘/Smart 参数 |
| `K_NO_SPACE`(13) | 磁盘满 | 客户业务运维 | `df -h`；清理磁盘 |
| `K_FILE_LIMIT_REACHED`(18) | fd 满 | 客户业务运维 | `ulimit -n`；调大 fd 限制 |

4.2 code ∈ {1001, 1002} 且日志前缀为 OS 相关

（1）查看日志前缀进行问题定界：

**表7**
| 日志前缀 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| `[TCP_CONNECT_FAILED]` + 对端 Worker **活** | 客户业务运维/网络 | 端口不通/iptables/路由 |
| `[TCP_CONNECT_RESET]` / `[TCP_NETWORK_UNREACHABLE]` | 客户业务运维/网络 | 网络闪断；`dmesg` |
| `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | 客户业务运维 | UDS 路径/权限/fd 上限 |
| `[ZMQ_SEND_FAILURE_TOTAL]` + `zmq_last_error_number` | 客户业务运维/网络 | 按 errno 对照排查 |

（2）`zmq_last_error_number` → errno 对照：

**表7**
| N | 枚举 | 典型含义 |
|---|---|---|
| 11 | `EAGAIN` / `EWOULDBLOCK` | 背压（非错） |
| 101 | `ENETUNREACH` | 路由不可达 |
| 104 | `ECONNRESET` | 对端 reset |
| 110 | `ETIMEDOUT` | TCP 超时 |
| 111 | `ECONNREFUSED` | 端口无监听 |
| 113 | `EHOSTUNREACH` | 主机不可达 |

（3）如果 OS 日志无明确问题，则进入步骤5

步骤6：排查 etcd 三方问题

5.1 code=25 或 `etcd is timeout/unavailable`

（1）查看 etcd 日志进行问题定界：

**表7**
| 证据 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| `etcd is timeout` / `etcd is unavailable` | 客户运维 | etcd 集群或网络；`etcdctl endpoint status` |
| `ETCD_QUEUE` 堆积 | 客户运维 | 检查 etcd 集群健康状态 |
| `ETCD_REQUEST_SUCCESS_RATE` 下降 | 客户运维 | 检查 etcd 网络和磁盘 |

（2）如果 etcd 日志无异常，则进入步骤7

步骤7：定位 yuanrong-datasystem 问题

6.1 code ∈ {19, 20, 23, 29, 31, 32} 或 code ∈ {1001, 1002} 且日志前缀为数据系统相关

（1）查看日志前缀进行问题定界：

**表7**
| 错误码 | 日志前缀 | 责任组织 | 常见问题排查指导 |
|---|---|---|---|
| `K_TRY_AGAIN`(19) | `[RPC_RECV_TIMEOUT]` + fault=0 | 分布式并行实验室 | 对端处理慢；`WAITING_TASK_NUM` 堆积 |
| `K_TRY_AGAIN`(19) | `[ZMQ_SEND_FAILURE_TOTAL]` + 对端活 | 客户业务运维 | 网络问题 |
| `K_DATA_INCONSISTENCY`(20) | 元数据与实际数据不一致 | 分布式并行实验室 | 检查 Worker 进程 bug；查看 CoreDump |
| `K_CLIENT_WORKER_DISCONNECT`(23) | `[TCP_CONNECT_FAILED]` + 对端不在 | 分布式并行实验室 | 对端 Worker 重启/崩溃 |
| `K_CLIENT_WORKER_DISCONNECT`(23) | `Cannot receive heartbeat` | 分布式并行实验室/客户运维 | 检查对端进程和网络 |
| `K_SERVER_FD_CLOSED`(29) | `[HealthCheck] Worker is exiting` | 分布式并行实验室 | Worker 主动退出 |
| `K_SCALE_DOWN`(31) / `K_SCALING`(32) | `meta_is_moving` | 分布式并行实验室 | 扩缩容中；SDK 自重试 |
| `K_RPC_DEADLINE_EXCEEDED`(1001) | `[RPC_SERVICE_UNAVAILABLE]` | 分布式并行实验室 | 对端拒绝；检查对端状态 |
| `K_RPC_DEADLINE_EXCEEDED`(1001) | `[RPC_RECV_TIMEOUT]` + fault=0 | 分布式并行实验室 | 对端处理慢；`WAITING_TASK_NUM` 堆积 |
| `K_RPC_UNAVAILABLE`(1002) | `[TCP_CONNECT_FAILED]` + 对端不在 | 分布式并行实验室 | 对端 Worker 重启/崩溃 |
| `K_RPC_UNAVAILABLE`(1002) | `[TCP_CONNECT_FAILED]` + 对端活 | 客户业务运维/网络 | 端口不通/iptables/路由 |
| `K_RPC_UNAVAILABLE`(1002) | `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | 客户业务运维 | UDS 路径/权限/fd 上限 |
| `K_RPC_UNAVAILABLE`(1002) | `[ZMQ_SEND_FAILURE_TOTAL]` + `zmq_last_error_number` | 客户业务运维/网络 | 按 errno 对照排查 |
| `K_RPC_UNAVAILABLE`(1002) | `zmq_event_handshake_failure_total`↑ | 分布式并行实验室 | TLS/认证配置问题 |
| `K_RPC_UNAVAILABLE`(1002) | `etcd is timeout/unavailable` | 客户运维 | etcd 问题 |

（2）code=19 详细排查

（2.1）如果是 `[RPC_RECV_TIMEOUT]` + fault=0：

```bash
# 检查对端线程池是否打满
grep 'WAITING_TASK_NUM' $LOG/resource.log
```

→ `WAITING_TASK_NUM` 堆积 → 扩线程池；查 CPU/锁

（2.2）如果是 `[ZMQ_SEND_FAILURE_TOTAL]` + 对端活：

```bash
# 检查网络连接
ping <peer_ip>
ss -tnlp | grep <port>
```

（3）code=20 详细排查

```bash
# 检查 Worker 进程是否异常退出过
grep -E 'Worker is exiting|Segmentation fault' $LOG/datasystem_worker.INFO.log

# 检查 object count 和 size 是否匹配
grep -E 'worker_object_count|OBJECT_SIZE' $LOG/resource.log

# 检查副本间数据一致性
grep -E 'replica|inconsistent' $LOG/datasystem_worker.INFO.log

# 检查网络是否有丢包/乱序
nstat -az
ip -s link
```

（4）code=1001 详细排查

（4.1）如果是 `[RPC_SERVICE_UNAVAILABLE]`：

```bash
# 检查对端 Worker 是否在运行
pgrep -af datasystem_worker
ss -tnlp | grep <worker_port>

# 检查对端是否正在扩缩容
grep -E 'meta_is_moving|SCALING' $LOG/datasystem_worker.INFO.log
```

（4.2）如果是 `[RPC_RECV_TIMEOUT]`：

```bash
# 检查对端线程池是否打满
grep 'WAITING_TASK_NUM' $LOG/resource.log

# 检查对端 CPU/内存是否正常
top -bn1 | head -20
```

（5）code=1002 详细排查

（5.1）如果是 TCP/UDS/ZMQ 问题：

```bash
# 检查网络连接
ping <peer_ip>
ss -tnlp | grep <port>

# 检查 iptables 规则
iptables -L -n

# 检查 ZMQ errno
grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log
```

（5.2）如果是 etcd 问题：

```bash
etcdctl endpoint status -w table
systemctl status etcd
```

（5.3）如果是 TLS/认证问题：

```bash
# 检查证书配置
grep -E 'handshake|TLS|Cert' $LOG/datasystem_worker.INFO.log

# 检查 zmq_event_handshake_failure_total
grep 'zmq_event_handshake_failure_total' $LOG/datasystem_worker.INFO.log
```

（5.4）交叉验证：

```bash
# 检查对端是否存活
ping <peer_ip>
ssh <peer_ip> "pgrep -af datasystem_worker"

# 检查对端 Worker 日志
grep -E 'Worker is exiting|Cannot receive heartbeat' $LOG/datasystem_worker.INFO.log
```

（6）交叉验证：
- 对端 Worker 日志同时间窗有受理日志 → 对端活
- `worker_object_count` / access log 计数断崖 → 对端 Worker 重启

（7）资源指标：`WAITING_TASK_NUM` 堆积 → 查 CPU/锁；扩 `oc_rpc_thread_num`

---

**多方故障定界到具体组织的排查步骤**

当故障涉及多个组织时，按以下顺序交叉验证：

1. **先确认硬件是否存活**：
   - OS 问题：检查物理机器 `ping/ssh` 是否可达
   - URMA 问题：检查 UB 端口 `ifconfig ub0` 是否 UP

2. **对比时间窗口**：
   - 多方日志同一时间出现异常 → 根因在最先出现的那个
   - 查看 `grep -E '\[HealthCheck\]|etcd is|URMA' $LOG/*.INFO.log | head -20` 确认先后顺序

3. **因果关系判定**：

**表7-续：多方因果判定**
| 现象 | 可能的根因 | 定界方法 |
|---|---|---|
| Worker 退出 + URMA 重建 | Worker 触发 UB 异常？还是 UB 异常导致 Worker 退出？ | 查看 Worker 退出原因（OOM/被 kill/编排）；UB 日志是否在 Worker 退出之后 |
| etcd timeout + Worker 断连 | etcd 导致 Worker 选主失败？还是 Worker 导致 etcd 压力？ | 查看 `ETCD_REQUEST_SUCCESS_RATE` 下降是局部还是全局；`ETCD_QUEUE` 堆积方向 |
| OS 网络闪断 + ZMQ 重建 | 底层网络导致 ZMQ 断开？ | 查看 `dmesg` 是否有网卡/驱动报错；`ip -s link` 是否有丢包 |

4. **组织归属判定**：
   - **客户业务运维**：OS 侧配置（iptables/tc/ulimit）、物理硬件（内存/磁盘/网卡）
   - **客户运维**：etcd 集群配置和网络
   - **海思**：UB 硬件、驱动、固件问题（`dmesg` 有 UB 驱动报错、`ifconfig ub0` 显示端口 down）
   - **分布式并行实验室**：数据系统软件逻辑、ZMQ 框架、URMA SDK、线程池配置

---

**附录A：通断类错误码速查**

| 错误码 | 枚举 | 主责边界 | 责任组织 |
|---|---|---|---|
| 0 | `K_OK` | 用户 | 客户业务（Get 查不到时需看 respMsg） |
| 2 | `K_INVALID` | 用户 | 客户业务 |
| 3 | `K_NOT_FOUND` | 用户 | 客户业务 |
| 5 | `K_RUNTIME_ERROR` | OS/三方/URMA | 按日志细分 |
| 6 | `K_OUT_OF_MEMORY` | OS | 客户业务运维/硬件 |
| 7 | `K_IO_ERROR` | OS | 客户业务运维/硬件 |
| 8 | `K_NOT_READY` | 用户 | 客户业务 |
| 13 | `K_NO_SPACE` | OS | 客户业务运维 |
| 18 | `K_FILE_LIMIT_REACHED` | OS | 客户业务运维 |
| 19 | `K_TRY_AGAIN` | 数据系统/OS | 分布式并行实验室/客户业务运维 |
| 20 | `K_DATA_INCONSISTENCY` | 数据系统 | 分布式并行实验室 |
| 23 | `K_CLIENT_WORKER_DISCONNECT` | 数据系统/OS/机器 | 分布式并行实验室/客户业务运维 |
| 25 | `K_MASTER_TIMEOUT` | etcd 三方 | 客户运维 |
| 29 | `K_SERVER_FD_CLOSED` | 数据系统 | 分布式并行实验室 |
| 31 | `K_SCALE_DOWN` | 数据系统 | 分布式并行实验室 |
| 32 | `K_SCALING` | 数据系统 | 分布式并行实验室 |
| 1001 | `K_RPC_DEADLINE_EXCEEDED` | 数据系统/OS/三方 | 按日志前缀分 |
| 1002 | `K_RPC_UNAVAILABLE` | 数据系统/OS/三方 | 按日志前缀分 |
| 1004 | `K_URMA_ERROR` | URMA | 海思 |
| 1006 | `K_URMA_NEED_CONNECT` | URMA | 分布式并行实验室/海思 |
| 1008 | `K_URMA_TRY_AGAIN` | URMA | 分布式并行实验室/海思 |
| 1009 | `K_URMA_CONNECT_FAILED` | URMA | 海思 |
| 1010 | `K_URMA_WAIT_TIMEOUT` | URMA | 分布式并行实验室 |

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
| 观测现象 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| `client_rpc_*_latency` max >> `worker_process_*_latency` max | 客户业务 | 用户业务代码反序列化/处理慢 |
| 过大 batch | 客户业务 | batch 接近 `OBJECT_KEYS_MAX_SIZE_LIMIT`；拆 batch |
| SDK 调用线程被业务阻塞 | 客户业务 | pstack 卡在 app 代码；检查业务代码 |
| 客户端 GC / 同步 IO | 客户业务 | 优化 GC；异步 IO |

（2）如果 Client 与 Worker 同幅慢或 Client 快于 Worker，则排除用户/SDK 问题，进入步骤3

步骤3：排查 URMA 问题

3.1 查看 URMA 相关指标

**表9**
| 证据 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| `worker_urma_write_latency` max↑ | 海思 | UB 硬件/驱动慢；`ifconfig ub0` |
| `urma_*` delta=0 + `tcp_*` 字节正常 + `fallback to TCP/IP payload` | 海思 | UB 降级至 TCP；间歇少量为 UB 抖，持续高频为 UB 端口 down |
| `[URMA_NEED_CONNECT]` / `[URMA_RECREATE_JFS]` 间歇 | 海思/分布式并行实验室 | 查 UMDK / 驱动；`ibstat` |

（2）如果 URMA 指标正常，则进入步骤5

步骤4：排查 OS 网络问题

4.1 查看 OS 网络相关指标

**表10**
| 证据 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| `ping` RTT 抖 | 客户业务运维/网络 | 网络链路抖动；`ping -c 100 <peer>` |
| `tc qdisc` netem 残留 | 客户业务运维 | netem 配置残留；`tc qdisc show` |
| `nstat/ss -ti` 重传↑ | 客户业务运维/网络 | 网络丢包；`nstat -az` |
| `zmq_send/receive_io_latency` max↑ + fault>0 | 客户业务运维/网络 | 网络栈问题；`dmesg` |

（2）框架占比分析：

- `(serialize + deserialize) / (send_io + recv_io + serialize + deserialize)` < 5%
- 瓶颈不在 ZMQ/protobuf，中间网络或对端处理

（3）如果 OS 网络正常，则进入步骤5

步骤5：定位 yuanrong-datasystem 问题

5.1 Client vs Worker 拆解

（1）`client_rpc_*_latency` max 显著 > `worker_process_*_latency` max → 中间链路慢，进入步骤5.2

（2）两者同幅飙升 → 数据系统 Worker 业务慢

**表11**
| 子场景 | 责任组织 | 常见问题排查指导 |
|---|---|---|
| 线程池打满 | 分布式并行实验室 | `WAITING_TASK_NUM` 堆积；扩线程池；查 CPU/锁 |
| 序列化慢 | 分布式并行实验室 | 框架占比 ≥5%；拆对象；启 URMA 零拷贝 |
| ZMQ 背压 | 分布式并行实验室 | `zmq_send_try_again`↑ + fault=0；加消费线程；降峰限流 |

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
| Metric | 含义 | 计算公式 | 瓶颈定位 | 责任组织 |
|---|---|---|---|---|
| `ZMQ_CLIENT_QUEUING_LATENCY` | Client 队列等待 | `CLIENT_TO_STUB - CLIENT_ENQUEUE` | MsgQue 堆积 | 分布式并行实验室 |
| `ZMQ_CLIENT_STUB_SEND_LATENCY` | Client Stub 发送 | `CLIENT_SEND - CLIENT_TO_STUB` | ZmqFrontend 繁忙 | 分布式并行实验室 |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | Server 队列等待 | `SERVER_DEQUEUE - SERVER_RECV` | Server 队列堆积 | 分布式并行实验室 |
| `ZMQ_SERVER_EXEC_LATENCY` | Server 业务执行 | `SERVER_EXEC_END - SERVER_DEQUEUE` | 业务逻辑 | 分布式并行实验室 |
| `ZMQ_SERVER_REPLY_LATENCY` | Server 回复延迟 | `SERVER_SEND - SERVER_EXEC_END` | Server 回复入队 | 分布式并行实验室 |
| `ZMQ_RPC_E2E_LATENCY` | 端到端延迟 | `CLIENT_RECV - CLIENT_ENQUEUE` | 全流程 | — |
| `ZMQ_RPC_NETWORK_LATENCY` | 网络延迟 | `E2E - SERVER_EXEC` | OS 网络栈/硬件 | 客户业务运维/网络 |

**核心等式**：`NETWORK = E2E - SERVER_EXEC`

（1）如果 `NETWORK` 高但 `SERVER_EXEC` 正常 → OS 网络问题（回步骤4）

（2）如果 `CLIENT_QUEUING` / `CLIENT_STUB_SEND` 高 → 分布式并行实验室（Client 软件问题）

（3）如果 `SERVER_QUEUE_WAIT` / `SERVER_REPLY` 高 → 分布式并行实验室（Server 软件问题）

（4）如果 `SERVER_EXEC` 高 → 分布式并行实验室（Server 业务逻辑问题）

---

**附录B：时延类 Metrics 速查**

| Metric | 类型 | 单位 | 责任组织 |
|---|---|---|---|
| `client_rpc_create_latency` | Histogram | us | 分布式并行实验室（Client SDK） |
| `client_rpc_publish_latency` | Histogram | us | 分布式并行实验室（Client SDK） |
| `client_rpc_get_latency` | Histogram | us | 分布式并行实验室（Client SDK） |
| `worker_process_create_latency` | Histogram | us | 分布式并行实验室（Server） |
| `worker_process_publish_latency` | Histogram | us | 分布式并行实验室（Server） |
| `worker_process_get_latency` | Histogram | us | 分布式并行实验室（Server） |
| `worker_urma_write_latency` | Histogram | us | 海思（UB 硬件/驱动） |
| `worker_tcp_write_latency` | Histogram | us | 客户业务运维/网络 |
| `zmq_send_io_latency` | Histogram | us | 客户业务运维/网络 |
| `zmq_receive_io_latency` | Histogram | us | 客户业务运维/网络 |
| `zmq_rpc_serialize_latency` | Histogram | us | 分布式并行实验室 |
| `zmq_rpc_deserialize_latency` | Histogram | us | 分布式并行实验室 |

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

---

**附录D：多方故障定界速查**

| 现象 | 责任组织 | 定界证据 |
|---|---|---|
| UB 端口 DOWN | 海思 | `ifconfig ub0 DOWN`；`ubinfo` 无设备 |
| UB 驱动报错 | 海思 | `dmesg | grep ub` |
| UB 降级 TCP | 海思 | `fallback to TCP/IP payload` 持续高频 |
| JFS 重建失败 | 海思/分布式并行实验室 | `[URMA_RECREATE_JFS_FAILED]` 连续 |
| etcd 超时 | 客户运维 | `etcdctl endpoint status` 不健康 |
| 网络丢包/错包 | 客户业务运维/网络 | `nstat -az`；`ip -s link` |
| OS 内核参数异常 | 客户业务运维 | `sysctl -a` 检查网络栈参数 |
| ZMQ 框架慢 | 分布式并行实验室 | 框架占比 ≥5% |
| 线程池打满 | 分布式并行实验室 | `WAITING_TASK_NUM` 持续堆积 |
