# ZMQ RPC 延迟边界定界指南

> 目标：当 latency 异常时，快速定位是 **ZMQ 配置层**、**ZMQ 软件实现层** 还是 **OS/kernel 层** 的问题。
>
> 维护：本文件随代码一起演进。

---

## 一、延迟定界总图

```
应用层
│
│  ┌─────────────────────────────────────────────────────────────┐
│  │  ZMQ Context (ZMQ_IO_THREADS, ZMQ_MAX_SOCKETS)              │
│  │    ZmqStubConnMgr / ZmqMsgMgr (ZmqMsgQueue)                  │
│  │      ZmqFrontend (frontend socket)                          │
│  │        ZmqSocket → ZmqSocketRef → zmq_msg_send/recv()       │
│  └─────────────────────────────────────────────────────────────┘ │
│           │                              ▲
            ↓                              │
         [ ZMQ API 层 ]                   │
         zmq_msg_send()                   │
         zmq_msg_recv()                   │
            │                              │
            ↓                              │
         [ POSIX syscall 层 ]              │
         sendmsg() / recvmsg()             │
         epoll_wait() / futex()            │
            │                              │
            ↓                              │
         [ TCP Stack 层 ]                  │
         TCP send buffer / recv buffer     │
         Nagle (TCP_NODELAY)              │
         TCP congestion window             │
            │                              │
            ↓                              │
         [ NIC / Kernel Interrupt 层 ]      │
         DMA, kernel bypass (DPDK etc.)  │
         ──────────────────────────────────────────
```

---

## 二、三层定界速查表

### 症状 → 可能层 → 验证命令

| 症状 | 最可能层 | 验证命令 |
|------|---------|---------|
| e2e p50/p90 稳定偏高，但 p99 tail 正常 | ZMQ 配置（socket options, HWM） | `strace -c` 看 send/recv syscall 时间 |
| e2e p50 正常，p99 突然很高（毛刺） | OS 网络栈（TCP retransmit, NIC 中断） | `cat /proc/net/snmp` 看 RetransSegs |
| zmq_send_io_latency p99 很高 (>200 μs) | ZMQ → OS 边界（内核 socket 缓冲区满） | `ss -ti` 看 snd_wnd / rcv_space |
| epoll_wait 时间分布极差（stddev 很大） | ZMQ IO 线程内部（消息过多积压） | `bpftrace` 看 epoll_wait 时长分布 |
| futex 调用次数异常多 | ZMQ 内部锁竞争（多个 IO 线程争抢同一锁） | `strace -c` 看 futex 调用次数 |
| 建链第一次请求延迟高，后续正常 | ZMQ 连接建立（TCP handshake + ZMQ greeting） | 单次 RPC 延迟 warmup 曲线 |
| server_queue_wait 高 | 服务端 ZmqMsgQueue 积压（worker 线程不够） | ThreadPool 饱和度 metrics |
| client_queuing 高 | 客户端 outbound queue 积压 | ZMQ HWM 配置是否合理 |

---

## 三、ZMQ 可配置项详解

### 3.1 Context 级别（进程级别）

| 配置项 | 代码位置 | 建议值 | 对端影响 |
|--------|---------|--------|---------|
| `ZMQ_IO_THREADS` | `zmq_context.cpp:78` | 4（多核） | 每个 IO 线程独立 epoll，处理网络事件并发能力 |
| `ZMQ_MAX_SOCKETS` | `zmq_context.cpp:96` | 100000 | 允许的最大 socket 数 |

### 3.2 Socket 级别

#### 客户端 Socket（`ZmqSocketRef::Connect` 创建的 dealer socket）

| 配置项 | 代码位置 | 当前值 | 建议值 | 影响 |
|--------|---------|-------|--------|------|
| `ZMQ_LINGER` | `zmq_context.cpp:122` | `opt.linger_`=0 | 保持 0 | 关闭时不等重传，快速释放 |
| `ZMQ_SNDTIMEO` | `zmq_context.cpp:123` | `opt.timeout_` | 保持 | send 超时 |
| `ZMQ_RCVTIMEO` | `zmq_context.cpp:124` | `opt.timeout_` | 保持 | recv 超时 |
| `ZMQ_SNDHWM` | `zmq_socket.cpp:63` | `opt.hwm_` | 保持 | 发送端高水位线（队列积压阈值） |
| `ZMQ_RCVHWM` | `zmq_socket.cpp:64` | `opt.hwm_` | 保持 | 接收端高水位线 |
| `ZMQ_IMMEDIATE` | `zmq_context.cpp:125` | `opt.immediate_`=true | 保持 | true=队列不等待直发，减少延迟 |
| `ZMQ_TCP_NODELAY` | **未设置** | — | **建议 1** | 禁止 Nagle，**延迟降低 200-500 μs** |
| `ZMQ_TCP_KEEPALIVE` | **未设置** | — | 建议 1 | 检测死连接 |
| `ZMQ_PROBE_ROUTER` | `zmq_stub_conn.cpp:432` | true | 保持 | connect 后主动探测，提前发现对端存活 |

#### 服务端 Socket（`ZmqSocketRef::Bind` 创建的 socket）

| 配置项 | 代码位置 | 当前值 | 建议值 | 影响 |
|--------|---------|-------|--------|------|
| `ZMQ_BACKLOG` | `zmq_server_impl.cpp:376` | `ZMQ_SOCKET_BACKLOG`=1024 | 保持 | accept 队列长度 |
| `ZMQ_SNDHWM` | `zmq_server_impl.cpp:374` | 0（无限） | 保持 | — |
| `ZMQ_RCVHWM` | `zmq_server_impl.cpp:374` | 0（无限） | 保持 | — |

### 3.3 消息队列级别

| 配置项 | 代码位置 | 当前值 | 建议值 | 影响 |
|--------|---------|-------|--------|------|
| `RPC_HWM` (HWM for ZmqMsgQueue) | `zmq_constants.h:32` | 1000 | 保持 | inbound queue 容量 |
| `RPC_HWM_QUEUE` (outbound queue) | `zmq_constants.h:33` | 330 | 保持 | outbound queue 容量 |
| `RPC_POLL_TIME` (poll 间隔) | `zmq_constants.h:30` | **100ms** | 10ms | prefetch 线程每 100ms 才 poll，降到 10ms 减少延迟 |
| `MAX_CONN_THREADS` | `zmq_stub_conn.cpp:504` | **1** | 4 | 并发建链吞吐，受限时改大 |

---

## 四、OS 层可配置项（sysctl / ss）

### 4.1 TCP Buffer 大小

```bash
# 查看当前值
sysctl net.ipv4.tcp_rmem
sysctl net.ipv4.tcp_wmem
sysctl net.core.rmem_max
sysctl net.core.wmem_max

# 调大（临时）
sysctl -w net.ipv4.tcp_rmem="4096 87380 6291456"
sysctl -w net.ipv4.tcp_wmem="4096 65536 6291456"
```

**效果**：增大 `tcp_rmem/tcp_wmem` 可减少 kernel socket buffer 满导致的 blocking。

### 4.2 TCP 算法

```bash
# 查看当前拥塞控制算法
sysctl net.ipv4.tcp_congestion_control

# 推荐算法（低延迟场景）
sysctl -w net.ipv4.tcp_congestion_control=cubic   # 默认，吞吐量优先
sysctl -w net.ipv4.tcp_congestion_control=bbr    # BBR，延迟敏感场景
```

### 4.3 TCP Nodelay

```bash
# 系统级关闭 Nagle（影响所有 TCP 连接）
sysctl -w net.ipv4.tcp_nodelay=1

# 查看
sysctl net.ipv4.tcp_nodelay
```

> 注意：系统级 `tcp_nodelay=1` 相当于所有 socket 设置 `TCP_NODELAY`。在 ZMQ socket 侧单独设置 `ZMQ_TCP_NODELAY` 效果相同但更精准。

### 4.4 Socket 缓冲区

```bash
# 查看 socket 缓冲区大小
ss -ti

# 例如输出中看到：
#   rcv_space:14600 rcv_ssthresh:64076
# 表示 receive window 当前值 / 最大值
```

---

## 五、ZMQ 内部实现关键路径与耗时归属

### 5.1 客户端发送路径（完整）

```
应用调用 stub->SimpleGreetingAsyncWrite()
  │  TICK_CLIENT_ENQUEUE  ← 高精度时间戳记录在此
  │  RecordTick(meta, "CLIENT_ENQUEUE")
  ↓
ZmqMsgQueue::SendMsg()  →  client_queuing_latency 开始
  │  （无锁 enqueue 到 MsgQueMgr outbound queue）
  ↓
ZmqMsgMgr::Outbound()   ←  ZmqStubConnMgr::Outbound()
  │  TICK_CLIENT_TO_STUB
  │  RecordTick(meta, "CLIENT_TO_STUB")
  ↓
ZmqFrontend::SendMsg()  →  msgQue_->Send()（容量 RPC_HWM=1000）
  │  eventfd_write(efd_, 1)  唤醒 frontend 线程
  ↓
ZmqFrontend::WorkerEntry() [独立线程]
  │  epoll_wait() 等待 frontend socket 或 efd_ 就绪
  │  处理时间 = epoll_wait 返回延迟 + 消息 dequeue 时间
  ↓
frontend socket (dealer) →  ZmqSocketRef::SendMsg()
  │  METRIC_TIMER(ZMQ_SEND_IO_LATENCY)
  ↓
  zmq_msg_send()   ←  syscall，进入 kernel
  │  = sendmsg()   ←  ZMQ 内部已捕获到 ZMQ_SEND_IO_LATENCY
  ↓
[ OS TCP Stack ]
  │  TCP send buffer (net.ipv4.tcp_wmem)
  │  Nagle 算法（若未设置 TCP_NODELAY）
  │  TCP congestion window
  ↓
[ NIC / Wire ]
──────────────────────────────────────────

服务端接收路径（完整）
──────────────────────────────────────────
[ NIC / Wire ]
  ↓
[ OS TCP Stack ]
  ↓
zmq_msg_recv()  ←  syscall
  │  = recvmsg()
  ↓
METRIC_TIMER(ZMQ_RECEIVE_IO_LATENCY)
  ↓
ZmqSocketRef::RecvMsg()
  │  TICK_SERVER_RECV
  ↓
ZmqServerImpl::RouteToService()
  │  内部 enqueue → ZmqMsgQueue（server side）
  │  TICK_SERVER_DEQUEUE
  ↓
ZmqService worker thread pool
  │  ZmqServerStreamBase::HandleUnaryCall()
  │  TICK_SERVER_EXEC_END
  ↓
DemoServiceImpl::SimpleGreeting()  ←  用户业务逻辑
  │  平均 1.9 μs
  ↓
序列化回复 (protobuf)
  │  TICK_SERVER_SEND
  ↓
ZmqSocketRef::SendMsg() → zmq_msg_send() → kernel
  │  METRIC_TIMER(ZMQ_SEND_IO_LATENCY)
  ↓
客户端 recv: zmq_msg_recv() → TICK_CLIENT_RECV
```

### 5.2 耗时归属判定

| 耗时区间 | 测量指标 | 定界 |
|---------|---------|------|
| client enqueue → MsgQueMgr enqueue | `zmq_client_queuing_latency` | ZMQ 内部队列（无 syscall） |
| MsgQueMgr → frontend socket send | `zmq_send_io_latency`（含 zmq_msg_send） | ZMQ → OS 边界 |
| kernel send buffer → wire | — | OS TCP stack（用 `tcp_profile.sh`） |
| wire → kernel recv buffer | — | OS TCP stack（用 `tcp_profile.sh`） |
| kernel recv → zmq_msg_recv 返回 | `zmq_receive_io_latency` | OS → ZMQ 边界 |
| server dequeue → worker thread 唤醒 | `zmq_server_queue_wait_latency` | ZMQ 内部队列 + OS futex/epoll |
| worker thread 处理 | `zmq_server_exec_latency` | 用户业务逻辑 |
| server reply send | `zmq_server_reply_latency` | ZMQ → OS 边界（序列化+socket send） |

---

## 六、关键配置修改对照表

### 改什么 → 看什么

| 修改 | 验证指标 | 验证方法 |
|------|---------|---------|
| `ZMQ_TCP_NODELAY=1` | `zmq_send_io_latency` p50/p99 | REPL histogram 对比 |
| `MAX_CONN_THREADS=4` | 并发建链场景的首次 RPC 延迟 | 多 client 并发压测 |
| `ZMQ_IO_THREADS=4` | context-switches 下降 | `perf stat -a -e context-switches` |
| `RPC_POLL_TIME=10ms` | `zmq_client_queuing_latency` p99 | REPL histogram 对比 |
| `ZMQ_SNDHWM/RCVHWM` | 队列积压时延迟 | 高负载压测 |
| `tcp_wmem/rmem` 增大 | `ss -ti` 中 snd_cwnd/rcv_space | tcp_profile.sh 输出 |

---

## 七、Profiling 脚本与层的对应关系

| 脚本 | 探测层 | 关键指标 |
|------|--------|---------|
| `repl_pipeline.sh` | ZMQ 应用层 | 8 个 histogram（见上表） |
| `perf_profile.sh` | ZMQ 软件实现层（CPU） | 热函数火焰图 |
| `syscall_profile.sh` | ZMQ → OS 边界 + OS syscall | futex/epoll_wait/sendmsg 时间占比 |
| `tcp_profile.sh` | OS TCP Stack | RetransSegs, RTT, snd_cwnd |
| `bpftrace`（手动） | OS kernel 深层 | epoll_wait 时长分布，futex 锁竞争 |

---

## 八、建议优先修改的配置文件

### 8.1 `zmq_socket_ref.cpp` — `Connect()` 添加 TCP_NODELAY

```cpp
// 文件：src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp
// 位置：ZmqSocketRef::Connect() 函数，在 zmq_connect() 调用之后

Status ZmqSocketRef::Connect(const std::string &endPoint, bool isIPv6)
{
    // ... 现有 IPv6 设置代码 ...
    rc = zmq_connect(sock_, endPoint.data());
    if (rc == -1) {
        return ZmqErrnoToStatus(errno, FormatString("ZMQ connect to %s unsuccessful", endPoint));
    }
    // ===== 新增：TCP_NODELAY 优化 =====
    int nodelay = 1;
    int s = zmq_setsockopt(sock_, ZMQ_TCP_NODELAY, &nodelay, sizeof(nodelay));
    if (s != 0) {
        LOG(WARNING) << "ZMQ_TCP_NODELAY failed: " << zmq_strerror(errno);
    }
    // ===================================
    return Status::OK();
}
```

### 8.2 `zmq_stub_conn.cpp` — `MAX_CONN_THREADS`

```cpp
// 文件：src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp
// 位置：ZmqSockConnHelper::StartThreads() 函数

static constexpr int MAX_CONN_THREADS = 4;  // 原来是 1，并发建链吞吐 +4x
```

### 8.3 `rpc_constants.h` — `RPC_POLL_TIME`

```cpp
// 文件：src/datasystem/common/rpc/rpc_constants.h

// 原来：static constexpr int RPC_POLL_TIME = 100;  // 100ms
// 建议：static constexpr int RPC_POLL_TIME = 10;   // 10ms，prefetch 延迟从 100ms 降到 10ms
```

---

## 九、验证步骤（改完后必做）

```bash
# 1. 重新编译（release + perf profile）
cd profiling/
DURATION=15 bash build_profiling_pipeline.sh

# 2. 对比 REPL histogram（重点看 zmq_send_io_latency 和 zmq_rpc_e2e_latency）
# 预期：zmq_send_io_latency p50 应下降

# 3. 对比 syscall profile（strace -c）
# 预期：sendmsg 时间分布改善

# 4. 检查 TCP retransmits
grep RetransSegs results/profiling_*/tcp_profile_report.txt
# 预期：无新增 retransmit
```
