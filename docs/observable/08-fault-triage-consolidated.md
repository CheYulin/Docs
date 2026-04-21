# 08 · 故障定位定界手册（通断 × 时延 双轴）

> **本文是什么**：一份**自包含**的现场定位定界操作手册。看到现象 → 分类 → 定界 → 定位。
>
> **面向谁**：开发、运维、测试、值班。不要求先读任何其它文档。
>
> **凭什么准**：所有错误码、日志字符串、metric 名、gflag 默认值都以 `yuanrong-datasystem` 主干代码为 ground truth 验证过；源码锚点见附录 A/B/C/D。
>
> **两类故障**
>
> - **通断类（Availability）**：接口**返回失败** / 错误码非 0 / 功能不可用 / 进程挂 / 连接断。
> - **时延类（Latency）**：接口**返回成功**但**慢** / P99 飙升 / 吞吐下跌 / 抖动。
>
> **四大责任边界**（定界目标：判给谁）
>
> 1. **用户（User）**：业务侧误用 — 参数非法、对象不存在、未初始化、buffer 重用。
> 2. **DataSystem（DS）**：ds 自身进程（Worker / Master / SDK / ZMQ-RPC / etcd 交互 / 心跳 / SHM 管理）。
> 3. **URMA**：UB 硬件 / UMDK 驱动 / UB 链路。
> 4. **OS**：操作系统与环境 — TCP/IP 网络、iptables、路由、fd、mem、disk、ulimit。
>
> **手册使用顺序**：§0 一图流 → 按通断或时延跳到 §1 或 §2 → 先定界（§x.2）→ 再定位（§x.3）→ §3 模板出工单。

---

## 0. 一图流：分类 → 定界 → 定位

```
                      观察到现象
                           │
        ┌──────────────────┴───────────────────┐
        │                                      │
        ▼                                      ▼
  ① 通断（§1）                           ② 时延（§2）
  Status ≠ K_OK                          Status = K_OK
  / 连接断 / 进程挂                        / 但 latency↑ / 吞吐↓
        │                                      │
        ▼                                      ▼
   先定界（§1.2）                          先定界（§2.2）
   ┌───┬───┬────┬───┐                    ┌───┬───┬────┬───┐
   │ 用 │ DS │URMA│ OS │                    │ 用 │ DS │URMA│ OS │
   │户 │    │    │    │                    │户 │    │    │    │
   └─┬─┴─┬─┴─┬──┴─┬─┘                    └─┬─┴─┬─┴─┬──┴─┬─┘
     ▼   ▼   ▼    ▼                        ▼   ▼   ▼    ▼
                再定位（§1.3 / §2.3）
   按具体子场景落到 [日志前缀] × metric delta × 处置动作
                           │
                           ▼
                  §3 结论模板 / 贴工单
```

**四边界速记表**

| 边界 | 我判给你的触发特征 | 常见凭据 |
|------|-------------------|---------|
| **用户** | Status ∈ {2, 3, 8}，或 Status=0 但业务 respMsg 异常 | access log 的 `respMsg` |
| **DataSystem** | Status ∈ {1001,1002,19,23,25,29,31,32}；或 `[ZMQ_*]/[RPC_*]/[SOCK_*]` 打印；或 etcd / 心跳告警；或 SHM 钉住 | Worker / Client INFO log 结构化前缀、ZMQ metrics |
| **URMA** | Status ∈ {1004,1006,1008,1009,1010}；或 `[URMA_*]` / `fallback to TCP/IP payload` | `[URMA_*]` 日志族、`*_urma_*_bytes` |
| **OS** | Status ∈ {6,7,13,18}；或 `K_RUNTIME_ERROR(5)` 伴随 `Get mmap entry failed`；或 `[TCP_CONNECT_FAILED]` 且对端 Worker 存活 | `ulimit` / `ss` / `df` / `dmesg` / iptables |

> ⚠️ **`K_RPC_UNAVAILABLE(1002)` 是"桶码"**：相同 1002 可能由 DS（Worker crash / 队列清空）或 OS（iptables / 端口未开 / 路由断）引起，**必须看下一层 `[...]` 前缀才能定界**。
>
> ⚠️ **`K_OK(0) ≠ 一切正常`**：`KVClient::Get` 会把 `K_NOT_FOUND` 写成 `K_OK` 记录 access log（见附录 A），业务"查不到"时 **Status=0 + respMsg=NOT_FOUND**，要看 respMsg 判用户边界。

---

## 1. 通断类故障

### 1.1 典型表现

| 表现 | 一般分类线索 |
|------|-------------|
| `Put/Get/Create/Publish` 返回非 0 Status | 见 §1.2 决策树 |
| Status=0 但 `respMsg` 含 `NOT_FOUND / invalid / not ready` | 用户边界 |
| 客户端 `Cannot receive heartbeat from worker.` | DS 边界（Worker 挂 / 网络断） |
| `[HealthCheck] Worker is exiting now` | DS 边界（主动退出，由调度器拉起） |
| `etcd is timeout` / `etcd is unavailable` | DS 边界（etcd 子系统） |
| `Get mmap entry failed` / Status=5 | OS 边界（fd / mmap 限制） |
| `fallback to TCP/IP payload` 但功能成功 | 非通断（降级成功）→ 跳 §2 看时延 |

### 1.2 通断故障的定界（三步，≤ 1 分钟）

> 目标：拿到**用户 / DS / URMA / OS** 四选一结论。

**Step 1：看 StatusCode 数值**（主判据）

```
Status →
├─ 0（K_OK）
│    └─ access log 的 respMsg 含 NOT_FOUND/invalid？
│          是 → 用户
│          否 → 非通断，跳 §2
│
├─ 2 / 3 / 8                                 → 用户
├─ 5（K_RUNTIME_ERROR）
│    ├─ Worker/Client 日志有 "Get mmap entry failed"  → OS（mmap/fd）
│    ├─ 有 "etcd is timeout"（Master 端）             → DS（etcd）
│    └─ 有 "urma ... payload ..."                    → URMA
├─ 6 / 7 / 13 / 18                           → OS（内存/IO/磁盘/fd）
├─ 19 / 23 / 25 / 29 / 31 / 32               → DS（可用性/扩缩容/心跳）
├─ 1001（RPC 超时）                           → 进入 Step 2
├─ 1002（RPC 不可达，桶码）                   → 进入 Step 2
└─ 1004 / 1006 / 1008 / 1009 / 1010          → URMA
```

**Step 2：Status 落在 1001/1002 时，看日志前缀分流**

| 最先出现的前缀 | 定界 | 原因 |
|---------------|------|------|
| `[TCP_CONNECT_FAILED]` + 对端 Worker 日志/心跳正常 | **OS** | 端口不通、iptables、路由 |
| `[TCP_CONNECT_FAILED]` + 对端 Worker 进程不在 | **DS** | Worker crash / 未拉起 |
| `[TCP_CONNECT_RESET]` / `[TCP_NETWORK_UNREACHABLE]` | **OS**（除非 Worker 重启） | 网络闪断 |
| `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | **DS** | 同机 Worker 未就绪 / UDS path 配置 |
| `[RPC_RECV_TIMEOUT]` + ZMQ fault counter 全 0 | **DS** | 对端**处理**慢，把 RPC 拖超时，非网络 |
| `[RPC_SERVICE_UNAVAILABLE]` | **DS** | 对端主动拒绝（状态不对 / shutting down） |
| `[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECEIVE_FAILURE_TOTAL]` + `zmq_last_error_number ∈ {EHOSTUNREACH, ENETDOWN, ...}` | **OS** | 网络栈真的挂了 |
| `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]` | **OS 或 DS** | 握手迟；看对端 Worker 是否存活再判 |
| `zmq_event_handshake_failure_total` delta > 0 | **DS**（安全/证书） | TLS / 认证配置 |

**Step 3：交叉验证（给出最终结论）**

- **ping / ss / iptables**：对端 IP 可达、端口 LISTEN、无 DROP/REJECT → 排除 OS。
- **对端 Worker INFO log 同时间窗有无受理日志**：有 → 对端活着，排除 DS 进程侧通断；没有则再看 `[HealthCheck] Worker is exiting now` 判 DS。
- **`worker_object_count` / access log 计数**：一边涨一边归零 → Worker 重启了。

### 1.3 通断故障的定位（按边界展开）

#### 1.3.1 用户边界

**定位依据**：Client Access Log（格式 `code | handleName | microseconds | dataSize | reqMsg | respMsg`）。

| respMsg 片段 | 含义 | 处置 |
|--------------|------|------|
| `The objectKey is empty` | key 为空 | 业务校验 |
| `dataSize should be bigger than zero` | size=0 | 业务校验 |
| `length not match` | keys/sizes 数组长度不等 | 业务校验 |
| `ConnectOptions was not configured` | 未配置连接参数 | 检查 `Init` |
| `Client object is already sealed` | buffer 重复 Publish | 业务逻辑 |
| `OBJECT_KEYS_MAX_SIZE_LIMIT` | 批次超限 | 拆 batch |
| `Can't find object` / `K_NOT_FOUND` | 对象不存在 | 业务自查 |

**速查**：

```bash
LOG=${log_dir:-/var/log/datasystem}
grep "DS_KV_CLIENT_GET" $LOG/ds_client_access_*.log \
  | awk -F'|' '{print $1}' | sort | uniq -c        # 错误码分布
grep '^2 |' $LOG/ds_client_access_*.log              # INVALID 类
grep -E "K_NOT_FOUND|Can.?t find object" $LOG/ds_client_*.INFO.log
```

#### 1.3.2 DataSystem 边界

**DS 边界下可再分 4 个子场景**：

##### (a) RPC 对端处理慢 / 队列被清（导致 1001/1002）

| 证据 | 判据 |
|------|------|
| `[RPC_RECV_TIMEOUT]` | Client 等应答超时 |
| `[RPC_SERVICE_UNAVAILABLE]` | 服务端主动回失败 |
| **所有 ZMQ fault counter = 0** | 不是网络，是对端自己慢/拒绝 |
| `resource.log` 的 `*_OC_SERVICE_THREAD_POOL` 中 `WAITING_TASK_NUM` 堆积 | 线程池被打满 |

**处置**：查 Worker CPU / 锁 / 慢 syscall；必要时扩 `oc_rpc_thread_num`。

##### (b) ZMQ/RPC 网关重建（连接抖动）

| 证据 | 判据 |
|------|------|
| `zmq_gateway_recreate_total` delta > 0 | 发生重建 |
| `zmq_event_disconnect_total` delta > 0 | ZMQ 异步监测到断开（可能晚几秒） |
| 对端 Worker 存活且 `[HealthCheck] Worker is exiting now` 不在时间窗 | 不是 Worker 自主退出 |

**处置**：频率低可忽略（SDK 自重连）；频率高转 OS 边界查网络。

##### (c) etcd / 元数据路径

| 证据 | 判据 |
|------|------|
| Master log `etcd is timeout` | Master 看到 etcd 超时 |
| Worker log `etcd is unavailable` | Worker 看到 etcd 不可达 |
| `resource.log` `ETCD_QUEUE.CURRENT_SIZE` 堆积、`ETCD_REQUEST_SUCCESS_RATE` 下降 | etcd 成为瓶颈 |
| Status=25（`K_MASTER_TIMEOUT`） | 客户端侧看到 Master 超时 |

> ⚠️ **etcd 两种字符串并存**：Master 用 `etcd is timeout`（映射 `K_RUNTIME_ERROR`），Worker 用 `etcd is unavailable`（映射 `K_RPC_UNAVAILABLE`）。grep 必须**两个都加**。

**处置**：`systemctl status etcd`；集群查 raft leader；恢复后 1002/25 自愈。

##### (d) 心跳 / Worker 生命周期 / 扩缩容

| 证据 | 判据 |
|------|------|
| `Cannot receive heartbeat from worker.` + Status=23 | 心跳断 |
| `[HealthCheck] Worker is exiting now` | Worker 主动退出 |
| Status=31 / 32；RPC 回包字段 `meta_is_moving` | 扩缩容中，SDK 应自重试 |

**处置**：心跳断 → `kill -CONT <worker_pid>` 或检查 Worker 阻塞点；Worker 退出由 k8s 拉起；扩缩容期业务 SDK 自动重试通常即恢复。

##### (e) SHM 元数据异常（通断表现为 Status=5 `K_RUNTIME_ERROR`）

| 证据 | 判据 |
|------|------|
| `Get mmap entry failed` | 客户端 fd 无效 / mmap 表项未建 |
| 同时 `[SHM_FD_TRANSFER_FAILED]` | SDK 建立 shm fd 辅助通道失败 |

**处置**：先视为 OS 边界（`ulimit -l unlimited`），若仍复现查 SCM_RIGHTS 传 fd 路径（DS 实现问题）。

#### 1.3.3 URMA 边界

| 证据 | 含义 | 处置 |
|------|------|------|
| `[URMA_NEED_CONNECT]` 首次出现 + 对端 `instanceId` 变化 | 对端 Worker 重启 | 等 SDK 重连 |
| `[URMA_NEED_CONNECT]` 持续 + `instanceId` 未变 | UB 链路不稳 | 查 UB 端口 / 交换机 |
| `[URMA_RECREATE_JFS]` + `cqeStatus=9`（ACK TIMEOUT） | JFS 状态异常，自动重建 | 观察是否成功 |
| `[URMA_RECREATE_JFS_FAILED]` 连续 | 重建失败 | 交 URMA 团队查驱动 |
| `[URMA_POLL_ERROR]` | 驱动 / 硬件异常 | 查 UMDK 日志 |
| `[URMA_WAIT_TIMEOUT]` + Status=1010 | 等待 CQE 超时 | SDK 重试白名单内 |
| Status=1009（`K_URMA_CONNECT_FAILED`） | URMA 建连失败 | 查 UB 端口 `up/down` |

> 注意：**`fallback to TCP/IP payload` 不是通断**，是 URMA 层把请求改走 TCP 的**降级**；功能成功 → 归入时延类（§2.3.3）。

**速查**：

```bash
grep -E '\[URMA_' $LOG/datasystem_worker.INFO.log
grep -E '\[URMA_RECREATE_JFS(_FAILED|_SKIP)?\]' $LOG/datasystem_worker.INFO.log
```

#### 1.3.4 OS 边界

| 表现 | 判据 | 处置 |
|------|------|------|
| Status=6（OOM） | `dmesg \| grep -i 'Out of memory'`；`free -h` | 扩内存 / 调 cgroup |
| Status=13（磁盘满） | `df -h`；`resource.log` `SPILL_HARD_DISK` | 清理 / 扩容 |
| Status=18（fd 满） | `ls /proc/<pid>/fd \| wc -l` vs `ulimit -n` | `ulimit -n` 调大 |
| Status=5 + `Get mmap entry failed` | `ulimit -l` 锁定内存上限太低 | `ulimit -l unlimited` |
| `[TCP_CONNECT_FAILED]` + 对端 Worker 活 | `ss -tnlp` 看目的端口；`iptables -L -n` | 开端口 / 删规则 |
| `[TCP_CONNECT_RESET]` + 对端 Worker 无 crash | `dmesg`；`netstat -s \| grep reset` | 修网络 |
| `zmq_last_error_number = 101/110/111/113` | `errno`：NETUNREACH/ETIMEDOUT/ECONNREFUSED/EHOSTUNREACH | 对应 OS 排查 |

**常见 errno 速查**：

```
11  EAGAIN            背压 / 非错
101 ENETUNREACH       路由不可达
104 ECONNRESET        对端 reset
110 ETIMEDOUT         TCP 超时
111 ECONNREFUSED      端口无监听
113 EHOSTUNREACH      主机不可达
```

---

## 2. 时延类故障

### 2.1 典型表现

| 表现 | 一般分类线索 |
|------|-------------|
| `client_rpc_get_latency` / `client_rpc_publish_latency` max 飙升 | 见 §2.2 |
| `worker_process_get_latency` / `worker_process_publish_latency` max 飙升 | Worker 侧慢 → DS |
| `worker_urma_write_latency` max 飙升 | URMA |
| `worker_tcp_write_latency` max 飙升 + UB 字节 delta=0 | 降级后被 TCP 拖慢 → URMA（UB 故障）或 OS（TCP 抖） |
| 吞吐下跌但无错误 | ZMQ 背压（`zmq_send_try_again_total` 涨）→ DS 消费侧慢 |
| Client 慢但 Worker 快 | 中间链路（OS 网络）或 SDK 本地 |

### 2.2 时延故障的定界（三步，≤ 3 分钟）

> 目标：同样输出 **用户 / DS / URMA / OS** 四选一。

**Step 1：是否真慢？**

- 看 `Metrics Summary` 的 `Compare with ... ms before` 段（下称 *delta 段*）；关注对应接口 Histogram 的 `max`（本周期 periodMax）。
- delta 段的 `max` 相比 baseline 翻 2~3 倍以上 → 确认慢。
- delta 段 `count=+0` 但 Total 段很大 → 无流量，非时延问题。

**Step 2：是 Client 链路慢还是 Worker 处理慢？**

| 对比 | 结论 |
|------|------|
| `client_rpc_get_latency` max 显著 > `worker_process_get_latency` max | 中间链路慢 → 进入 Step 3（可能 DS 框架 / URMA / OS 网络） |
| 两者同幅飙升 | Worker 业务自身慢 → **DS**；去看 Worker CPU / 线程池 / 锁 |
| Worker 快、Client 慢、且 `worker_to_client_total_bytes` delta 正常 | SDK 本地慢（反序列化 / 用户线程阻塞）→ **用户** 或 **DS 客户端** |

**Step 3：拆 Client ↔ Worker 的中间链路**

- `worker_urma_write_latency` max 飙 → **URMA**。
- `worker_tcp_write_latency` max 飙 + `*_urma_*_bytes` delta=0 + `fallback to TCP/IP payload` → **URMA**（UB 故障导致 TCP 降级）。
- `zmq_send_io_latency` / `zmq_receive_io_latency` max 飙 + ZMQ fault counter 全 0 → 再看 `zmq_rpc_serialize_latency / deserialize_latency`：
  - **序列化+反序列化占比 < 5%** → 网络或 Worker 对端处理慢，**不是 DS 框架**。
  - 占比 ≥ 5% → **DS** 框架侧（大 payload / protobuf 低效）。
- ping RTT 抖 / `tc qdisc` 有 netem 规则 / `nstat` 丢包 → **OS**。

**性能自证清白公式**

```
RPC 框架占比 = (zmq_rpc_serialize_latency + zmq_rpc_deserialize_latency)
             / (zmq_send_io_latency + zmq_receive_io_latency + 上两项)
```

`< 5%` → 瓶颈不在 ZMQ/protobuf 框架。

### 2.3 时延故障的定位（按边界展开）

#### 2.3.1 用户边界

- 过大 batch：`OBJECT_KEYS_MAX_SIZE_LIMIT` 附近的调用；减小 batch 或拆 key。
- SDK 调用线程被业务阻塞：SDK `StartMetricsThread` 的 metrics 仍然正常滚动，但业务线程 pstack 里卡在 app 代码 → 用户线程。
- 客户端 GC / 同步 IO：看 SDK 侧 pidstat，非 DS 问题。

#### 2.3.2 DataSystem 边界

##### (a) Worker 业务慢

| 证据 | 判据 |
|------|------|
| `worker_process_get_latency / publish_latency` max 飙 | Worker 业务路径慢 |
| `worker_rpc_create_meta_latency` max 飙 | 写元数据路径慢（etcd 或 Master 排队） |
| `resource.log` `*_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM` 堆积 | RPC 线程池打满 |
| `resource.log` `ETCD_QUEUE.CURRENT_SIZE` / `ETCD_REQUEST_SUCCESS_RATE` | etcd 侧瓶颈 |

**处置**：扩线程池；查锁 / 慢 syscall / L2 miss；etcd 端 `ETCDCTL_API=3 etcdctl endpoint status -w table`。

##### (b) DS 框架自身（序列化 / protobuf / ZMQ）

| 证据 | 判据 |
|------|------|
| `zmq_rpc_serialize_latency / deserialize_latency` 与 IO latency 比例 ≥ 5% | 框架占比偏高 |
| 请求 payload 异常大（`worker_to_client_total_bytes` / `worker_from_client_total_bytes`） | 数据面放大 |

**处置**：拆大对象 / 启用 URMA 零拷贝 / 用 Publish+Get 走 SHM。

##### (c) 跨 Worker Get 慢（远端对象）

| 证据 | 判据 |
|------|------|
| `worker_rpc_get_remote_object_latency` max 飙 | 远端拉取慢 |
| 远端 Worker `worker_process_get_latency` 同幅飙 | 远端业务慢 |
| 远端 Worker 正常 | 中间网络或 URMA → 转 §2.3.3 / §2.3.4 |

##### (d) ZMQ 背压（吞吐掉，不一定是 latency）

| 证据 | 判据 |
|------|------|
| `zmq_send_try_again_total` 持续涨，其它 fault counter 为 0 | HWM 背压 |
| `zmq_receive_try_again_total`（仅 blocking 模式）持续涨 | 接收端消费慢 |

**处置**：加消费端线程 / 降峰限流；不是错误。

#### 2.3.3 URMA 边界

| 证据 | 判据 | 处置 |
|------|------|------|
| `worker_urma_write_latency` max 飙 | UB 硬件 / 驱动慢 | 查 UMDK / UB 端口状态 |
| `client_*_urma_*_bytes` delta=0 + `client_*_tcp_*_bytes` delta 正常 | 已降级 TCP | 看 `fallback to TCP/IP payload` 频率；恢复 UB 就回 URMA 路径 |
| `fallback to TCP/IP payload` 频率 > 0 | 有降级 | UB 不稳；CPU 拷贝放大 |
| `[URMA_NEED_CONNECT]` / `[URMA_RECREATE_JFS]` 间歇 | 连接/队列不稳 | 影响尾延迟 |

**速查**：

```bash
grep -E '\[URMA_|fallback to TCP/IP payload' $LOG/*.INFO.log
# UB 端口
ibstat || ubinfo || ifconfig ub0
```

#### 2.3.4 OS 边界

| 证据 | 判据 | 处置 |
|------|------|------|
| ping 对端 RTT 抖 | `ping -i 0.2 <peer>` | 排 tc / 交换机 |
| `tc qdisc show dev eth0` 有 netem | 人工注入残留 | `tc qdisc del dev eth0 root netem` |
| `nstat / ss -ti` 重传率飙 | TCP 重传 | 查网卡 / 驱动 |
| iostat / vmstat 显示 IO wait / swap | 本机资源饱和 | 扩资源 / 隔离业务 |
| `resource.log` `SHARED_MEMORY` 接近 `TOTAL_LIMIT` | 内存压力传导到 GC/分配慢 | 扩 SHM 池 |
| `worker_shm_ref_table_bytes` gauge 持续涨 + `worker_object_count` 持平 | SHM 钉住（DS 实现问题，但表征是 OS 内存被吃光） | 见 §1.3.2(e) |

---

## 3. 结论模板（贴工单）

```
【故障类型】通断 / 时延（二选一，主因写第一）
【责任边界】用户 / DataSystem / URMA / OS（必须给出其一；跨界写主责+协查）
【错误码】<code> <枚举名> + rc.GetMsg()（时延类此行写 "N/A, Status=K_OK"）
【日志证据】
  - <SDK 日志一行，含 TraceID/时间 + objectKey>
  - <Worker 日志一行，同时间窗，带 [PREFIX] 前缀>
【Metrics delta】
  cycle=<N>, interval=<intervalMs>ms
  <Counter>=+<N>
  <Histogram> count=+<N>, max=<val>
【根因】<一句话>
【处置】<对应 §1.3 / §2.3 表中动作>
【闭环验证】<重跑或监控 X 分钟后哪些信号回到 baseline>
```

---

## 4. 实战示例

### 示例 1 · 通断 / DS：Get 返回 1002，对端 Worker 正常

```
Step1：Status=1002 → 进入日志前缀分流
Step2：先出现 [RPC_RECV_TIMEOUT]，所有 ZMQ fault counter delta=0
       → 对端处理慢型，定界 DS
Step3：resource.log 对端 WORKER_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM=128 堆积
【类型】通断 【边界】DataSystem（RPC 对端慢）
【处置】扩 oc_rpc_thread_num；查 Worker CPU / 锁
```

### 示例 2 · 通断 / OS：Get 返回 1002，iptables 注入

```
Step1：Status=1002
Step2：[ZMQ_SEND_FAILURE_TOTAL] + zmq_last_error_number=113 (EHOSTUNREACH)
Step3：iptables -L -n 发现 DROP 规则
【类型】通断 【边界】OS（iptables）
【处置】iptables -D ...；zmq_send_failure_total delta 归零即恢复
```

### 示例 3 · 通断 / URMA：Put 返回 1009

```
Step1：Status=1009 (K_URMA_CONNECT_FAILED) → URMA
Step3：[URMA_NEED_CONNECT] 高频 + [URMA_RECREATE_JFS_FAILED] 连续
       UB 端口 ifconfig ub0 DOWN
【类型】通断 【边界】URMA（UB 端口 DOWN）
【处置】ifconfig ub0 up；观察 [URMA_NEED_CONNECT] 消失
```

### 示例 4 · 通断 / 用户：Get 返回 0 但业务"查不到"

```
Step1：Status=0 → 看 respMsg
       access log 一行：0 | DS_KV_CLIENT_GET | ... | Can't find object
【类型】通断（业务不可见）【边界】用户（对象确实不存在）
【处置】业务排查 key 生成逻辑；注意 K_NOT_FOUND→K_OK 的 access log 记账陷阱
```

### 示例 5 · 时延 / URMA：Put avg 500us → 3000us，Status=0

```
Step1：delta 段 client_rpc_publish_latency max 飙
Step2：worker_process_publish_latency 同幅飙 不成立；
       client_put_urma_write_total_bytes delta=0，client_put_tcp_write_total_bytes delta=+50MB
Step3：grep 'fallback to TCP/IP payload' 200/min
【类型】时延 【边界】URMA（UB 降级 TCP）
【处置】ifconfig ub0 / UMDK；恢复后 urma 字节 delta 回升
```

### 示例 6 · 时延 / DS：Get P99 飙，Status=0

```
Step1：client_rpc_get_latency max=50ms，baseline 2ms
Step2：ZMQ fault counter 全 0；worker_process_get_latency max=38ms（同幅飙）
Step3：resource.log WORKER_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM 堆积
【类型】时延 【边界】DataSystem（Worker 业务慢）
【处置】查 Worker CPU / 线程池 / 锁；必要时扩线程数
```

### 示例 7 · 时延 / OS：ZMQ 框架占比低，中间链路抖

```
Step1：client_rpc_get_latency max 飙，worker_process_get_latency 未变
Step2：zmq_send_io_latency max 飙；zmq_rpc_serialize+deserialize 占比 ~3%
Step3：ping 对端 RTT 抖动；tc qdisc 有 netem 延迟
【类型】时延 【边界】OS（网络）
【处置】tc qdisc del ...；或换网卡 / 换交换路径
```

### 示例 8 · 通断 / DS：SHM 钉住泄漏

```
Step1：无错误码，但 resource.log SHARED_MEMORY 从 3.58GB → 37.5GB
Step3：worker_shm_ref_table_bytes gauge 持续上涨
       worker_object_count gauge 持平
       worker_allocator_alloc_bytes_total delta > worker_allocator_free_bytes_total delta
【类型】通断（容量型，最终 OOM）【边界】DataSystem（SHM ref 未释放）
【处置】查 client DecRef；Worker 清理超时
```

---

## 5. 现场速查卡

### 5.1 错误码 → 边界一览

```
StatusCode                           边界   备注
0    K_OK                             用户?  看 respMsg；注意 NOT_FOUND→K_OK 陷阱
2    K_INVALID                        用户
3    K_NOT_FOUND                      用户
5    K_RUNTIME_ERROR                  OS/DS  看具体日志
6    K_OUT_OF_MEMORY                  OS
7    K_IO_ERROR                       OS
8    K_NOT_READY                      用户
13   K_NO_SPACE                       OS
18   K_FILE_LIMIT_REACHED             OS
19   K_TRY_AGAIN                      DS
20   K_DATA_INCONSISTENCY             DS
23   K_CLIENT_WORKER_DISCONNECT       DS
25   K_MASTER_TIMEOUT                 DS
29   K_SERVER_FD_CLOSED               DS
31   K_SCALE_DOWN                     DS
32   K_SCALING                        DS
1001 K_RPC_DEADLINE_EXCEEDED          DS/OS  分流见 §1.2 Step2
1002 K_RPC_UNAVAILABLE                DS/OS  同上（桶码）
1004 K_URMA_ERROR                     URMA
1006 K_URMA_NEED_CONNECT              URMA
1008 K_URMA_TRY_AGAIN                 URMA
1009 K_URMA_CONNECT_FAILED            URMA
1010 K_URMA_WAIT_TIMEOUT              URMA
```

### 5.2 一纸禅 grep

```bash
LOG=${log_dir:-/var/log/datasystem}

# 全部结构化日志前缀（通断定位主抓手）
grep -E '\[(TCP|UDS|ZMQ|RPC|SOCK|REMOTE|SHM_FD|URMA)_' \
  $LOG/datasystem_worker.INFO.log $LOG/ds_client_*.INFO.log

# Metrics delta 段（时延定界必看）
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3

# URMA 降级
grep 'fallback to TCP/IP payload' $LOG/*.INFO.log

# Worker 退出 / 心跳
grep -E '\[HealthCheck\] Worker is exiting now|Cannot receive heartbeat from worker' \
  $LOG/*.INFO.log

# etcd 两种字符串
grep -E 'etcd is (timeout|unavailable)' $LOG/datasystem_worker.INFO.log

# SHM 钉住
grep -E 'worker_shm_(ref_table_(bytes|size)|unit_(created|destroyed)_total|ref_(add|remove)_total)|worker_allocator_(alloc|free)_bytes_total' \
  $LOG/datasystem_worker.INFO.log

# resource.log 核心
grep -E 'SHARED_MEMORY|ETCD_QUEUE|ETCD_REQUEST_SUCCESS_RATE|OC_HIT_NUM|WAITING_TASK_NUM' \
  $LOG/resource.log

# Client 错误码分布
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log \
  | awk -F'|' '{print $1}' | sort | uniq -c
```

### 5.3 四边界各自的 OS/环境速查

```bash
# OS 资源
ulimit -a                               # fd/内存锁定
free -h; df -h
ls /proc/<pid>/fd | wc -l               # 实际 fd 数
ss -tnlp | grep <worker_port>           # 端口监听
iptables -L -n                           # 防火墙规则
tc qdisc show dev eth0                   # 网络 qdisc/netem
dmesg | tail -200                        # OOM / 驱动错

# URMA
ibstat 2>/dev/null || ubinfo 2>/dev/null
ifconfig ub0
ls /dev/ub*

# DS 进程
pgrep -af datasystem_worker
pidstat -p <worker_pid> 1
gstack <worker_pid>                      # 或 pstack
```

### 5.4 处置措施速查

| 故障 | 恢复 | 验证信号 |
|------|------|---------|
| ZMQ 发送失败（iptables 注入） | `iptables -D OUTPUT -p tcp --dport X -j DROP` | `zmq_send_failure_total` delta 归零 |
| RPC 超时（tc 注入） | `tc qdisc del dev eth0 root netem` | latency 回 baseline |
| TCP 建连失败 | 开端口 / 删 iptables / 拉起 Worker | `[TCP_CONNECT_FAILED]` 消失 |
| URMA 需重连 | SDK 自动重连 | `[URMA_NEED_CONNECT]` 消失 |
| UB 降级 | `ifconfig ub0 up`；修 UMDK | `client_*_urma_*_bytes` delta>0 |
| Worker 退出 | k8s 拉起 | 新 pid 建连 |
| 心跳超时（手工 STOP） | `kill -CONT <worker_pid>` | 心跳恢复 |
| etcd 超时 | `systemctl start etcd` | `etcd is ...` 消失 |
| mmap 失败 | `ulimit -l unlimited` | `Get mmap entry failed` 消失 |
| fd 耗尽 | `ulimit -n` 调大 | Status=18 消失 |
| SHM 钉住 | 查 DecRef；必要时重启 Worker | `worker_shm_ref_table_bytes` 回稳 |

---

## 附录

### 附录 A · 错误码代码锚点

枚举定义 `include/datasystem/utils/status.h`：

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

NOT_FOUND→K_OK 记账陷阱：

```187:189:src/datasystem/client/kv_cache/kv_client.cpp
    StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode();
    accessPoint.Record(code, std::to_string(dataSize), reqParam, rc.GetMsg());
```

---

### 附录 B · 日志前缀 → 源码锚点

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
| `[URMA_NEED_CONNECT]` | `urma_manager.cpp`（多处）+ `worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker` (~947) |
| `[URMA_RECREATE_JFS]` | `urma_manager.cpp::HandleUrmaEvent` (~772) + `urma_resource.cpp::MarkAndRecreate` (~392,~407) |
| `[URMA_RECREATE_JFS_FAILED]` | `urma_manager.cpp` (~779) |
| `[URMA_RECREATE_JFS_SKIP]` | `urma_manager.cpp` (~784) + `urma_resource.cpp` (~370,~386,~398) |
| `[URMA_POLL_ERROR]` | `urma_manager.cpp::ServerEventHandleThreadMain` (~625) |
| `[URMA_WAIT_TIMEOUT]` | `urma_manager.cpp::WaitToFinish` (~732) |
| `[HealthCheck] Worker is exiting now` | `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` (~371) |
| `Cannot receive heartbeat from worker.` | `src/datasystem/client/listen_worker.cpp` (~114) |
| `etcd is timeout` | `src/datasystem/master/replica_manager.cpp` (~1190) |
| `etcd is unavailable` | `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` (~1631) |
| `Get mmap entry failed` | `src/datasystem/client/object_cache/object_client_impl.cpp`（多处） |
| `fallback to TCP/IP payload` | `src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp` (~117,~131) |

---

### 附录 C · Metrics 完整清单（54 条）

定义于 `src/datasystem/common/metrics/kv_metrics.{h,cpp}`（`KvMetricId` 枚举 + `KV_METRIC_DESCS`），`static_assert` 保证 `KV_METRIC_END = 54`。

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

---

### 附录 D · 路径与关键 gflag

#### D.1 日志路径来源

| 文件 | 代码出处 |
|------|---------|
| `${log_dir}` | gflag `--log_dir`（`common/util/gflag/common_gflag_define.cpp:28`） |
| `${log_dir}/access.log` | `include/datasystem/common/constants.h:29` |
| `${log_dir}/ds_client_access_<pid>.log` | `common/log/access_recorder.cpp:112-125`；可用 `DATASYSTEM_CLIENT_ACCESS_LOG_NAME` 覆盖 |
| `${log_dir}/resource.log` | `common/metrics/res_metric_collector.cpp:61-62` |
| `${log_dir}/datasystem_worker.INFO.log` | glog 默认命名 |
| `${log_dir}/ds_client_<pid>.INFO.log` | glog 默认命名（SDK） |
| `${log_dir}/request_out.log` | Worker 访问 etcd / OBS 子系统 |

#### D.2 gflag 默认值

| gflag | 默认 | 语义 |
|-------|------|------|
| `log_monitor` | `true` | Summary 总开关；关掉后 `Tick/PrintSummary` 空操作，内部累加仍继续 |
| `log_monitor_interval_ms` | `10000` | Summary 实际打印周期（非 `Tick` 粒度） |
| `log_monitor_exporter` | `"harddisk"` | **代码仅接受 `"harddisk"`**；其它值（含帮助文本的 `"backend"`）被 `ResMetricCollector::Init` reject 为 `K_INVALID` |
| `log_dir` | `$GOOGLE_LOG_DIR` / glog 默认 | 控制所有日志路径 |

#### D.3 Metrics Summary 格式源码

```167:169:src/datasystem/common/metrics/metrics.cpp
    os << "Metrics Summary, version=" << VERSION << ", cycle=" << ++g_cycle
       << ", interval=" << intervalMs << "ms\n\n";
    os << "Total:\n" << total.str() << "\nCompare with "
       << intervalMs << "ms before:\n" << delta.str();
```

`VERSION = "v0"`（`metrics.cpp:33`）。

#### D.4 两种进程如何启 Metrics

| 进程 | `InitKvMetrics` 位置 | `Tick` 驱动 |
|------|---------------------|-------------|
| **Worker** | `worker/worker_oc_server.cpp::WorkerOCServer::Start`（`ReadinessProbe()` 之后） | `worker/worker_main.cpp` 主循环每秒 `metrics::Tick()` |
| **Client (SDK)** | `client/kv_cache/kv_client.cpp::Init/InitEmbedded`；`client/object_cache/object_client.cpp::Init` | `client/object_cache/object_client_impl.cpp::StartMetricsThread` 每 1s |

---

### 附录 E · `resource.log` 完整字段（22 项）

定义于 `src/datasystem/common/metrics/res_metrics.def`，按序输出。

| # | 字段 | 关键子项 |
|---|------|---------|
| 1 | `SHARED_MEMORY` | MEMORY_USAGE / PHYSICAL_MEMORY_USAGE / TOTAL_LIMIT / WORKER_SHARE_MEMORY_USAGE / SC_MEMORY_USAGE / SC_MEMORY_LIMIT |
| 2 | `SPILL_HARD_DISK` | SPACE_USAGE / PHYSICAL_SPACE_USAGE / TOTAL_LIMIT |
| 3 | `ACTIVE_CLIENT_COUNT` | — |
| 4 | `OBJECT_COUNT` | — |
| 5 | `OBJECT_SIZE` | — |
| 6 | `WORKER_OC_SERVICE_THREAD_POOL` | IDLE_NUM / CURRENT_TOTAL_NUM / MAX_THREAD_NUM / WAITING_TASK_NUM / THREAD_POOL_USAGE |
| 7 | `WORKER_WORKER_OC_SERVICE_THREAD_POOL` | 同上 |
| 8 | `MASTER_WORKER_OC_SERVICE_THREAD_POOL` | 同上 |
| 9 | `MASTER_OC_SERVICE_THREAD_POOL` | 同上 |
| 10 | `ETCD_QUEUE` | CURRENT_SIZE / TOTAL_LIMIT / ETCD_QUEUE_USAGE |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | SUCCESS_RATE |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | SUCCESS_RATE |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | 线程池五元组 |
| 14 | `STREAM_COUNT` | — |
| 15 | `WORKER_SC_SERVICE_THREAD_POOL` | 线程池五元组 |
| 16 | `WORKER_WORKER_SC_SERVICE_THREAD_POOL` | 同上 |
| 17 | `MASTER_WORKER_SC_SERVICE_THREAD_POOL` | 同上 |
| 18 | `MASTER_SC_SERVICE_THREAD_POOL` | 同上 |
| 19 | `STREAM_REMOTE_SEND_SUCCESS_RATE` | SUCCESS_RATE |
| 20 | `SHARED_DISK` | USAGE / PHYSICAL_USAGE / TOTAL_LIMIT / USAGE_RATE |
| 21 | `SC_LOCAL_CACHE` | USAGE / RESERVED_USAGE / TOTAL_LIMIT / USAGE_RATE |
| 22 | `OC_HIT_NUM` | MEM_HIT_NUM / DISK_HIT_NUM / L2_HIT_NUM / REMOTE_HIT_NUM / MISS_NUM |

---

### 附录 F · 对旧版文档的修正项

1. `[TCP_CONN_WAIT_TIMEOUT]` 在代码里不存在 → 用 `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]`。
2. `K_FILE_LIMIT_REACHED = 18`（不是 20，20 是 `K_DATA_INCONSISTENCY`）。
3. etcd 两种字符串并存：Master `etcd is timeout`；Worker `etcd is unavailable`。
4. SHM 泄漏旧 metric 名大多不存在；正确名以附录 C(ID 36–45) 为准。
5. Metrics 总数 **54**（`KV_METRIC_END=54`），不是 36。
6. 新增错误码 `K_URMA_CONNECT_FAILED = 1009`。
7. `Cannot receive heartbeat from worker.` 完整带句点。
8. `fallback to TCP/IP payload` 在代码中形如 `, fallback to TCP/IP payload.`。
9. `log_monitor_exporter` 仅支持 `"harddisk"`（帮助文本提及的 `"backend"` 会被 reject）。

---

### 附录 G · 维护约定

1. 错误码变化 → 先改 `include/datasystem/utils/status.h`，再同步 §1.2 / §5.1 / 附录 A。
2. 新增 `[PREFIX]` 标签 → 先落地代码、`rg '\[NEW_PREFIX\]' src/` 验证存在，再同步 §1.2 / §1.3 / §2.3 / 附录 B。
3. 新增 metric → 追加到 `kv_metrics.cpp::KV_METRIC_DESCS` 末尾；更新附录 C 与 `KV_METRIC_END`。
4. `resource.log` 字段顺序以 `res_metrics.def` 为单一事实源；附录 E 与之一一对应。
