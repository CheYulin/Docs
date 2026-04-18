# ZMQ 重连机制与 IF Down 场景深度分析

## 1. ZMQ 默认重连配置

| 配置项 | 默认值 | 说明 | 源码位置 |
|--------|--------|------|----------|
| `ZMQ_RECONNECT_IVL` | **100ms** | 首次重连间隔 | `options.cpp:188` |
| `ZMQ_RECONNECT_IVL_MAX` | **0** (禁用指数退避上界) | =0时: interval = prev + jitter[0, reconnect_ivl) | `options.hpp:103` |
| `ZMQ_TCP_KEEPALIVE` | **-1** (不改动系统默认) | 不主动设置 SO_KEEPALIVE | `options.cpp:201` |
| `ZMQ_TCP_KEEPALIVE_IDLE` | **-1** | 不设置 | `options.cpp:202` |
| `ZMQ_TCP_KEEPALIVE_CNT` | **-1** | 不设置 | `options.cpp:203` |
| `ZMQ_TCP_KEEPALIVE_INTVL` | **-1** | 不设置 | `options.cpp:204` |
| `ZMQ_HEARTBEAT_IVL` | **0** (禁用) | ZMTP PING/PONG 心跳间隔 | `options.cpp:215` |
| `ZMQ_HEARTBEAT_TIMEOUT` | **-1** (跟随 IVL) | PONG 超时 | `options.cpp:216` |
| `ZMQ_HEARTBEAT_TTL` | **0** | 通知对端 TTL | `options.cpp:214` |
| `ZMQ_HANDSHAKE_IVL` | **30000ms** | ZMTP 握手超时 | `options.cpp:212` |
| `ZMQ_SNDHWM / ZMQ_RCVHWM` | **1000** | 消息高水位 | `options.cpp:167-172` |
| `ZMQ_LINGER` | **-1** (无限等待) | close 时等待发送 | `options.cpp:176` |
| `ZMQ_CONNECT_TIMEOUT` | **0** (使用 OS 默认) | TCP connect 超时 | `options.cpp:185` |

### 数据系统 RPC 框架实际配置

| 配置项 | 实际设置值 | 位置 |
|--------|-----------|------|
| `ZMQ_LINGER` | **0** (立即丢弃) | `zmq_context.cpp:123` |
| `ZMQ_SNDTIMEO` | **60000ms** (Server) / **3000ms** (Client DEALER) | `rpc_constants.h:27,46` |
| `ZMQ_RCVTIMEO` | **60000ms** / **3000ms** | 同上 |
| `ZMQ_SNDHWM` | **0** (无限) | Server & Client 都设为 0 |
| `ZMQ_RCVHWM` | **0** (无限) | 同上 |
| `ZMQ_IMMEDIATE` | **1** (true) | `zmq_context.cpp:126` |
| `ZMQ_PROBE_ROUTER` | **1** (true) | Client DEALER 特有 |
| `ZMQ_BACKLOG` | **1024** | Server ROUTER |
| `ZMQ_RECONNECT_IVL` | **未设置 → 100ms** | 使用 libzmq 默认 |
| `ZMQ_RECONNECT_IVL_MAX` | **未设置 → 0** | 使用 libzmq 默认 |
| `ZMQ_TCP_KEEPALIVE` | **未设置 → -1** | 不启用 TCP keepalive |
| `ZMQ_HEARTBEAT_IVL` | **未设置 → 0** | 不启用 ZMTP 心跳 |

> **关键发现**: 数据系统 RPC 框架 **未配置** ZMQ 的 TCP keepalive、ZMTP 心跳、重连间隔。完全依赖 libzmq 默认值。

---

## 2. ZMQ 怎么知道 TCP 链路异常？故障检测时间

### 检测机制层次

```
┌─────────────────────────────────────────────────────┐
│ 应用层 ZMQ 心跳 (ZMTP PING/PONG)  ← 当前未启用!   │
├─────────────────────────────────────────────────────┤
│ TCP Keepalive (SO_KEEPALIVE)       ← 当前未启用!   │
├─────────────────────────────────────────────────────┤
│ TCP Read/Write 错误               ← 唯一的检测手段  │
│   - recv() 返回 0 (FIN)                            │
│   - recv()/send() 返回 ECONNRESET/EPIPE/ETIMEDOUT  │
└─────────────────────────────────────────────────────┘
```

### 检测路径详解

#### 路径 A: Read 侧 (主要检测)
```
recv() 返回 0 → tcp_read() → stream_engine_base::in_event_internal()
  → error(connection_error) → session_base::engine_error()
  → clean_pipes() + reconnect()
```

#### 路径 B: Write 侧 (不够可靠)
```
send() 返回 EPIPE/ECONNRESET → tcp_write() → stream_engine_base::out_event()
  → 仅 reset_pollout()，不拆连接！
  → 必须等 read 侧发现错误才会真正拆连接
```

#### 路径 C: TCP Keepalive (当前未启用)
- 默认 `tcp_keepalive = -1`，ZMQ 不设置 `SO_KEEPALIVE`
- Linux 默认 keepalive: idle=7200s, interval=75s, count=9 → 检测需要 **~7200 + 75*9 = 7875s**
- 即使 OS 开了 keepalive，默认参数也无实际意义

#### 路径 D: ZMTP 心跳 (当前未启用)
- `heartbeat_interval = 0`，不发送 PING
- 如果启用: 每 `heartbeat_interval` ms 发送 PING，`heartbeat_timeout` ms 内没收到 PONG 则 `error(timeout_error)`

### IF Down 场景的故障检测时间

**IF Down = 网卡链路层断开，TCP 连接不会收到 FIN/RST**

| 检测手段 | 当前是否启用 | 检测时间 |
|----------|-------------|----------|
| 对端 FIN/RST | IF Down 时无法发送 | **不适用** |
| TCP write 失败 | 需要有数据发送 | 取决于 TCP 重传超时 (Linux 默认 ~15-20min) |
| TCP Keepalive | **未启用** | 不适用 |
| ZMTP Heartbeat | **未启用** | 不适用 |
| 应用层 RPC 超时 | 是 (60s/3s) | **60s (Server) / 3s (Client)** |
| 应用层 liveness | 是 | heartbeatInterval * K_LIVENESS (120次) |

> **结论**: 在当前配置下，IF Down 的检测几乎完全依赖 **应用层 RPC 超时** 和 **TCP 重传超时**。Client 端 3s 的 SNDTIMEO/RCVTIMEO 会首先触发。

---

## 3. ZMQ 应对 1s IF Down 的时间线

```
时间线 (ms)    事件
────────────────────────────────────────────────────────────────
  0            IF Down 发生，TCP 链路断开
               ZMQ 不知情，socket 状态看起来正常
               
  0~1000       ┌─ IF Down 期间 ──────────────────────────┐
               │                                          │
               │ [如果有数据正在传输]                      │
               │   TCP 层: 数据包丢失，开始重传            │
               │   TCP RTO: 初始~200ms, 指数退避          │
               │   第1次重传: ~200ms                       │
               │   第2次重传: ~400-600ms                   │
               │                                          │
               │ [如果没有数据传输]                        │
               │   ZMQ 完全不知情，pipe 缓冲区正常         │
               │   send() 照常成功（放入 ZMQ 内部队列）    │
               │                                          │
               └──────────────────────────────────────────┘
               
 1000          IF Up 恢复
               
 1000~1200     TCP 层: 重传的数据包被确认（或下一次重传成功）
               已缓冲的数据继续发送
               TCP 连接 **未断开**，sequence number 连续
               
 ~1200         数据传输恢复正常
               ZMQ 全程不知道发生了 IF Down
               **没有触发重连**

═══════════════════════════════════════════════════════════════
结论: 1s IF Down → TCP 未断 → ZMQ 不感知 → 不重连 → 数据无丢失
═══════════════════════════════════════════════════════════════
```

### 关键逻辑: TCP 重传超时 vs IF Down 持续时间

```
Linux TCP 重传行为:
  RTO 初始值: ~200ms (取决于 RTT)
  重传次数上限: net.ipv4.tcp_retries2 = 15 (默认)
  总超时: 约 13-30 分钟 (指数退避累计)

  重传时间表 (大致):
  ┌──────────────┬────────┐
  │ 重传次数      │ 累计时间 │
  ├──────────────┼────────┤
  │ 1            │ ~200ms  │
  │ 2            │ ~600ms  │
  │ 3            │ ~1.4s   │
  │ 4            │ ~3s     │
  │ 5            │ ~6.2s   │
  │ 6            │ ~12.6s  │
  │ ...          │ ...     │
  │ 15           │ ~15min  │
  └──────────────┴────────┘

IF Down < ~15min → TCP 连接存活 → ZMQ 无感 → 不重连
IF Down > TCP重传总超时 → TCP RST → ZMQ recv()=0 → 重连
```

---

## 4. 2.5s 周期注入 0.5s IF Down 的表现

### 场景参数
- 周期: 2.5s
- IF Down 持续: 0.5s
- IF Up 持续: 2.0s
- 实际观测故障时间: 0.7~0.8ms

```
时间线:
  0.0s ─── IF Down ───  0.5s ─── IF Up ─── 2.5s ─── IF Down ─── 3.0s ─── ...

每个 IF Down 窗口 (0.5s = 500ms):
┌──────────────────────────────────────────────────────────────┐
│ TCP RTO ~200ms，0.5s 内最多重传 1-2 次                       │
│ IF Up 恢复后，重传包到达 → TCP 连接保持                      │
│ 观测: 延迟抖动 ~200-500ms，吞吐量短暂降低                   │
│ ZMQ: 不触发重连，不丢消息                                    │
└──────────────────────────────────────────────────────────────┘
```

### 预期表现

| 指标 | 预期 |
|------|------|
| TCP 连接是否断开 | **否** (0.5s 远小于 TCP 重传超时) |
| ZMQ 是否触发重连 | **否** |
| 消息是否丢失 | **否** (TCP 可靠传输保证) |
| RPC 是否超时 | **可能** (如果恰好在 IF Down 期间等待 response, 累计延迟可能导致应用超时) |
| 延迟增加 | **是**, 每次 IF Down 增加 ~200-500ms 延迟 |
| 吞吐量影响 | 瞬时降低, TCP 拥塞窗口可能收缩 |

### 实际观测 0.7~0.8ms 故障时间的解释

0.7~0.8ms 非常短，远小于 TCP RTO (~200ms)。这个时间尺度上:
- TCP 的重传还没有触发
- 可能是 **链路层恢复** 的时间（网卡 link state 变化的 carrier detect 时间）
- 在这个尺度上，**可能丢失了 1-2 个 TCP segment**，但 TCP 的快速重传 (3 个 duplicate ACK) 或 RTO 会恢复
- 对 ZMQ 和上层应用 **几乎无感知**

---

## 5. ZMQ 重连后是否会丢包？

### 核心结论: **会丢消息！**

ZMQ 虽然看起来像可靠消息队列，但 **在 TCP 连接断开重连时，消息可能丢失**。

### 丢失场景分析

#### 场景 1: 已发出但未确认的消息 (TCP 缓冲区中)

```
Client                          Network                        Server
  │                               │                               │
  │── zmq_send(request) ──→      │                               │
  │   (进入 TCP send buffer)      │                               │
  │                               │←── IF Down ──                │
  │                               │   TCP buffer 中的数据         │
  │                               │   在重传超时后丢失            │
  │                               │                               │
  │   TCP连接最终断开              │                               │
  │   ZMQ engine_error             │                               │
  │   clean_pipes() + reconnect   │                               │
  │                               │                               │
  │   *** request 丢失 ***        │                               │
```

**TCP send buffer 里的数据**: TCP 连接断开时，尚在 send buffer 中未被对端 ACK 的数据 **全部丢失**。ZMQ 的 `clean_pipes()` 只回滚 **ZMQ pipe 里的未完成多帧消息**，已经交给 TCP 的数据不会被回滚。

#### 场景 2: Server 发出 response, Client TCP 断开

```
Server                          Network                        Client
  │                               │                               │
  │── zmq_send(response) ──→     │                               │
  │   response 进入 Server 的     │                               │
  │   ROUTER socket 的发送队列    │                               │
  │                               │←── Client TCP 断开 ──        │
  │                               │                               │
  │   ROUTER: 目标 peer 断开      │                               │
  │   该 peer 的消息被丢弃        │                               │
  │                               │                               │
  │   *** response 丢失 ***       │                               │
```

**ROUTER socket 行为**: 当 ROUTER 发送到一个已断开的 peer 时，`EHOSTUNREACH` → 消息直接丢弃（ROUTER 默认行为）。

#### 场景 3: ZMQ 内部 pipe 中的消息

```
重连后:
- Client 创建新的 DEALER socket
- 新 socket 有新的 routing-id (UUID)
- Server ROUTER 视其为新 peer
- 旧连接的 pipe 中缓冲的消息:
  - 入站消息: clean_pipes() 丢弃不完整的多帧
  - 出站消息: rollback() 回滚不完整多帧
  - 完整消息: 随 pipe terminate 被丢弃
```

### RPC Request/Response 丢失矩阵

> **关键前提**: IF Down 时 TCP 不会自己主动断开。TCP 只会默默重传，直到重传次数
> 耗尽 (约 15-30min)。实际中 TCP 连接是被 **上层主动 close(fd)** 杀死的——要么是
> RPC 框架 liveness=0 重建 DEALER (约 12s)，要么是 libzmq heartbeat 超时触发内部
> 重连 (如果配了, 约 1.5s)。下面按"谁杀死了连接"来区分。

```
┌───────────────────────┬────────────────┬──────────────────────┬──────────────────────┐
│ 消息所在阶段           │ IF 短暂中断    │ libzmq 内部重连      │ RPC框架重建DEALER    │
│                       │ TCP 未被杀     │ (heartbeat超时,      │ (liveness=0,         │
│                       │ (IF < 数秒)    │  ~1.5s, 只换fd)     │  ~12s, 整个socket重建)│
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Request 在 ZMQ pipe   │ ✅ 不丢        │ ✅ 不丢              │ ❌ 丢失              │
│ (zmq_send 已返回)     │ TCP重传兜底    │ pipe 保留,           │ linger=0,            │
│                       │                │ 新连接上重发         │ pipe 立即丢弃        │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Request 在 TCP        │ ✅ 不丢        │ ❌ 丢失              │ ❌ 丢失              │
│ send buffer           │ TCP重传兜底    │ close(old_fd),       │ close(old_fd),       │
│                       │                │ 内核丢弃未确认数据   │ 内核丢弃未确认数据   │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Request 在网络中      │ ✅ 不丢        │ ❌ 丢失              │ ❌ 丢失              │
│ (in-flight)           │ TCP重传兜底    │ 旧TCP会话已死        │ 旧TCP会话已死        │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Request 已达 Server   │ ✅ 不丢        │ ✅ 不丢              │ ✅ 不丢              │
│ (Server 正在处理)     │                │ 但 response 可能丢   │ 但 response 可能丢   │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Response 在 Server    │ ✅ 不丢        │ ❌ 丢失              │ ❌ 丢失              │
│ ROUTER pipe/TCP buf   │ TCP重传兜底    │ 旧 peer pipe 清理    │ ROUTER 丢弃旧 peer   │
│                       │                │ 但同 routing-id,     │ 新 routing-id,       │
│                       │                │ 新连接可重新关联     │ 旧 response 无接收者 │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Response 在网络中     │ ✅ 不丢        │ ❌ 丢失              │ ❌ 丢失              │
│ (in-flight)           │ TCP重传兜底    │ 旧TCP会话已死        │ 旧TCP会话已死        │
├───────────────────────┼────────────────┼──────────────────────┼──────────────────────┤
│ Response 已到 Client  │ ✅ 不丢        │ ✅ 不丢              │ ✅ 不丢              │
│ ZMQ pipe / MsgQue     │ 已在应用层     │ 已在应用层           │ 已在应用层           │
└───────────────────────┴────────────────┴──────────────────────┴──────────────────────┘

核心逻辑: IF Down 时 TCP 自身不会断开 (只是默默重传)。
数据丢失只在 close(fd) 时发生——这是上层 (ZMQ/应用) 主动做的决定。
```

### 判断是否触发TCP断开的关键

**0.5s IF Down**: TCP **不断开** → 不丢包
**长时间 IF Down (>15min)**: TCP 断开 → 丢包

**中间地带** 取决于:
1. TCP RTO 和重传次数 (`tcp_retries2=15`, 约15-30min)
2. 是否有 TCP keepalive 缩短检测时间 (当前未启用)
3. 是否有 ZMTP heartbeat 缩短检测时间 (当前未启用)
4. 应用层超时 (Client 3s, Server 60s) → 应用层可能先超时放弃

---

## 6. 数据系统 RPC 框架的保护机制

### 6.1 应用层 Liveness 检测

```cpp
// zmq_stub_conn.cpp:332-383 - WorkerEntry 主循环
// 每次 idle (K_NOT_FOUND) 时 liveness_--
// 收到 response 时 ResetLiveness()
// liveness_ == 0 时: 销毁 DEALER, 重建连接

K_LIVENESS = 120  // zmq_constants.h:38
heartbeatInterval = 动态计算 (基于 timeoutMs)
```

这是 **Client 侧的应用层心跳**，不依赖 ZMQ ZMTP 心跳。

### 6.2 GetStreamPeer 重试

```cpp
// zmq_stub_impl.cpp - GetStreamPeer
// 循环直到 retryTimeout (默认60s)
// K_RPC_UNAVAILABLE 或 K_TRY_AGAIN 时重试
// 每次重试 sleep 100ms
// 错误时重建 MsgQue
```

### 6.3 EAGAIN 处理

```cpp
// zmq_stub_conn.cpp:348-351
if (rc.GetCode() == K_TRY_AGAIN) {
    // force liveness to 0 → 触发 DEALER 重建
    liveness_ = 0;
}
```

### 6.4 ZMQ_IMMEDIATE = true

```cpp
// zmq_context.cpp:126
// ZMQ_IMMEDIATE=1: 只在连接真正建立后才路由消息到该 peer
// 避免向未完成连接的 peer 发送消息
```

这很关键！`ZMQ_IMMEDIATE=true` 意味着:
- 在 DEALER 连接未完成时，`zmq_send()` 会阻塞/返回 EAGAIN
- 不会把消息扔进一个还没建链的 pipe

---

## 7. 自动建链开销

### TCP 连接建立
- **3-way handshake**: 1.5 RTT (~0.1-1ms 局域网)
- ~50-100μs CPU (socket 创建 + 系统调用)

### ZMTP 握手
- **ZMTP greeting exchange**: 64 bytes 互发, 1 RTT
- **Mechanism handshake**:
  - NULL (无认证): 0-1 RTT, 几十字节
  - CURVE (当前使用): 4 RTT + 加密计算 (~1-5ms)
- **Properties exchange**: 1 RTT

### 总建链开销

| 阶段 | 延迟 (局域网) | 说明 |
|------|-------------|------|
| TCP 3-way handshake | ~0.2ms | |
| ZMTP greeting | ~0.1ms | 64字节交换 |
| NULL mechanism | ~0.1ms | 如果不用 CURVE |
| CURVE mechanism | ~2-5ms | 4次 box/unbox |
| Properties | ~0.1ms | |
| **总计 (NULL)** | **~0.5ms** | |
| **总计 (CURVE)** | **~3-6ms** | |

加上 ZMQ 的 reconnect_ivl (默认 100ms wait):

```
实际重连延迟 = reconnect_ivl (100ms) + TCP建链 + ZMTP握手
             ≈ 100ms + 0.5ms (NULL) 或 100ms + 5ms (CURVE)
             ≈ 100-105ms
```

---

## 8. 综合建议

### 8.1 当前风险

1. **无主动故障检测**: TCP keepalive 和 ZMTP heartbeat 都未启用
2. **长 IF Down 无法快速感知**: 依赖 TCP 重传超时 (~15min) 或应用层超时 (3-60s)
3. **ROUTER → 断开 peer 的 response 丢失**: 无重试机制

### 8.2 推荐配置

```cpp
// 在 ZmqSocket 创建后或 zmq_context.cpp 中添加:

// 启用 ZMTP 心跳 (推荐)
sock.setsockopt(ZMQ_HEARTBEAT_IVL, 500);    // 每500ms发PING
sock.setsockopt(ZMQ_HEARTBEAT_TIMEOUT, 1500); // 1.5s无PONG判死
sock.setsockopt(ZMQ_HEARTBEAT_TTL, 1500);    // 通知对端1.5s TTL

// 启用 TCP Keepalive (辅助)
sock.setsockopt(ZMQ_TCP_KEEPALIVE, 1);
sock.setsockopt(ZMQ_TCP_KEEPALIVE_IDLE, 10);   // 10s空闲后开始探测
sock.setsockopt(ZMQ_TCP_KEEPALIVE_CNT, 3);     // 3次探测
sock.setsockopt(ZMQ_TCP_KEEPALIVE_INTVL, 5);   // 5s探测间隔
// → 最慢 10+3*5=25s 检测到断链

// 重连间隔
sock.setsockopt(ZMQ_RECONNECT_IVL, 100);       // 100ms (默认已是)
sock.setsockopt(ZMQ_RECONNECT_IVL_MAX, 5000);  // 5s 上界, 启用指数退避
```

### 8.3 针对 2.5s/0.5s IF Down 场景

| 方面 | 当前表现 | 启用心跳后 |
|------|---------|-----------|
| TCP 连接 | 不断开 | 不断开 |
| 消息丢失 | 不丢失 | 不丢失 |
| 延迟抖动 | ~200-500ms | ~200-500ms |
| 故障感知 | 不感知 | PING 可能超时触发误断 |

> **注意**: 如果配置了 `HEARTBEAT_TIMEOUT=1500ms`，在 2.5s 周期的 0.5s IF Down 下，心跳大概率不会超时（因为窗口仅 0.5s，而 timeout 是 1.5s 且最近的 PONG/数据会重置计时器）。但如果心跳恰好在 IF Down 期间到期且网络恢复后数据又堆积，可能有少量误判。建议 heartbeat_timeout > IF Down 最大持续时间。

### 8.4 RPC 丢失防护

对于 **request 丢失**:
- 当前 RPC 框架的 `GetStreamPeer` 有重试机制，可以覆盖
- 但前提是 `zmq_send` 返回了错误，如果消息已经进入 TCP buffer 后 TCP 断开，RPC 框架无法感知

对于 **response 丢失**:
- 这是更隐蔽的问题: Server 已处理，response 丢在网络/ROUTER 里
- Client 侧表现为 **RPC 超时** (K_RPC_UNAVAILABLE)
- 上层需要 **幂等性** 设计来安全重试

---

## 9. 跨节点 TCP Socket 重建与消息丢失深度分析

### 9.1 ZMQ 内部数据流的 6 个阶段

一条消息从 `zmq_send` 到 `zmq_recv`，经过以下 6 个阶段：

```
zmq_send(msg)
    │
    ▼
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│ ① ZMQ    │→│ ② ZMQ    │→│ ③ 内核    │→│ ④ 网络   │→│ ⑤ 对端   │→│ ⑥ 对端   │
│ pipe     │  │ engine   │  │ TCP send  │  │ 线路上   │  │ TCP recv │  │ ZMQ pipe │
│ (用户态) │  │ write()  │  │ buffer    │  │ (in-     │  │ buffer   │  │ (用户态) │
│ 消息队列 │  │ 序列化   │  │ (内核态)  │  │ flight)  │  │ (内核态) │  │ 消息队列 │
└──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
                                                                           │
                                                                           ▼
                                                                     zmq_recv(msg)
```

### 9.2 两级重建机制的差异

跨节点场景下有两种不同级别的 TCP socket 重建：

#### Level 1: libzmq 内部重连 (同一个 ZMQ socket 对象)

发生在 libzmq 自己检测到连接断开时（`recv()=0`, TCP 超时等）。ZMQ 的 `session_base::reconnect()` 关闭旧 fd，启动新 TCP 连接，但 **ZMQ socket 对象和 pipe 不销毁**。

```
触发路径:
  stream_engine_base::error(connection_error)
  → session_base::engine_error()
  → clean_pipes()  // 回滚不完整多帧，不销毁 pipe
  → reconnect()    // 新建 tcp_connecter, pipe 保留
  → 100ms 后 TCP SYN → ZMTP 握手 → 新 engine 挂到旧 session
```

| 阶段 | 位置 | 命运 | 原因 |
|------|------|------|------|
| ① | ZMQ pipe (用户态队列) | **存活** | pipe 没被销毁，新连接建立后继续发送 |
| ② | engine 正在写 | **部分回滚** | 不完整多帧被 `rollback()` |
| ③ | 内核 TCP send buffer | **丢失** | `close(fd1)` → 内核丢弃 send buffer |
| ④ | 网络线路上 | **丢失** | 旧 TCP 连接已死，对端不接受 |
| ⑤ | 对端 TCP recv buffer | **安全** | 已到达对端内核，与旧连接断开无关 |
| ⑥ | 对端 ZMQ pipe | **安全** | 已在应用层 |

#### Level 2: RPC 框架重建 DEALER (数据系统实际走的路径)

发生在 `WorkerEntry` 的 `liveness==0` 时，**关闭旧 DEALER socket 整体，创建全新 DEALER**：

```
触发路径 (zmq_stub_conn.cpp:332-384):
  WorkerEntry 主循环:
    HandleEvent() → poll idle → liveness_--
    ... 120 次 idle (每次 ~100ms) ...
    liveness_ == 0
    → frontend_->Close()   // zmq_close, ZMQ_LINGER=0, 立即丢弃所有 pending
    → InitFrontend()       // 创建全新 DEALER, 新 UUID routing-id
    → frontend_->Connect() // 新 TCP 连接
```

| 阶段 | 位置 | 命运 | 原因 |
|------|------|------|------|
| ① | ZMQ pipe (用户态队列) | **丢失** | `ZMQ_LINGER=0`, `zmq_close` 立即丢弃 |
| ② | engine 正在写 | **丢失** | 同上 |
| ③ | 内核 TCP send buffer | **丢失** | `close(fd1)` → 内核丢弃 + 发 RST |
| ④ | 网络线路上 | **丢失** | 旧 TCP 连接已死 |
| ⑤ | 对端 TCP recv buffer | **安全** | 已到达对端内核 |
| ⑥ | 对端 ZMQ pipe | **安全** | 已在应用层 |

> **关键区别**: Level 1 中 ZMQ pipe 里的完整消息能在新连接上重发；Level 2 中因为 `linger=0` + 整个 socket 销毁，pipe 中的消息也全部丢弃。

### 9.3 `close(fd)` 是丢失的根本分界线

```
              ZMQ 用户态                  │  内核态
                                          │
  ┌─────────┐    ┌──────────┐             │  ┌──────────────────┐
  │  pipe   │───→│ engine   │── write() ─→│─→│ TCP send buffer  │
  │ msg_1   │    │          │             │  │ [msg_3][msg_4]   │
  │ msg_2   │    │          │             │  │  未被ACK的数据    │
  └─────────┘    └──────────┘             │  └──────────────────┘
                                          │          │
                      close(fd1) ─────────│──────────┘
                      这一刀切在这里        │   内核: 丢弃 buffer, 发 RST
                                          │
                                          │  ┌──────────────────┐
           新 fd2 ────────────────────────│─→│ 新 TCP send buf  │
           新 TCP 连接                     │  │ (空的)           │
                                          │  └──────────────────┘
```

- `close(fd1)` + `SO_LINGER=0` (ZMQ 设置了 `ZMQ_LINGER=0`): 内核 **不等待** send buffer 发送完毕，直接丢弃并发 RST
- 这与 TCP 的 `SO_LINGER` 不同，ZMQ 的 `ZMQ_LINGER` 控制的是 `zmq_close` 时等多久让内部 pipe 排空，pipe 排空后底层 fd 的 `close()` 行为取决于内核

### 9.4 网络中是否有垃圾消息？

**没有垃圾消息**。三层保障：

**TCP 层保证 — 连接隔离**:
```
旧连接: client_ip:port_A → server_ip:port_S  (四元组 A)
新连接: client_ip:port_B → server_ip:port_S  (四元组 B)

端口不同 → 完全独立的 TCP 会话
旧连接的 seq/ack 不可能串到新连接
旧连接的 RST 不影响新连接
```

**TCP RST 清理机制**:
```
Client close(fd1) → 发 RST
  → Server 收到 RST → 丢弃旧连接上所有待发数据
  → 之后旧连接上任何方向的数据都被 TCP 拒绝
  → 不会有残留数据被应用层收到
```

**ZMTP 协议层保证 — 握手校验**:
```
每条新 TCP 连接必须完成 ZMTP 握手:
  1. Greeting: 0xFF + 8字节 + 0x7F + version + mechanism
  2. Mechanism handshake (NULL/CURVE 认证)
  3. Properties exchange (routing-id 等)

如果有残留的旧数据流混入 → 无法通过 ZMTP greeting 校验
→ handshake 失败 → 连接拒绝
→ 不产生应用层垃圾消息
```

**唯一的"浪费"流量**:
```
Server 不知道 Client 已重建 → 在旧连接上发 response
→ 数据在网络上传输了（浪费带宽）
→ 到达 Client 后被 TCP RST 拒绝
→ 不被任何 ZMQ socket 接收，不影响应用逻辑
→ 不是"垃圾消息"，只是无效流量
```

### 9.5 Server 视角：旧连接和新连接的 peer 身份

```
         时间轴
           │
  ─────────┤ Client DEALER (routing-id = UUID-A) 连接
           │ Server ROUTER 内部: peer_map[UUID-A] → pipe_1 → fd_1
           │
  ─────────┤ IF Down
           │
  ─────────┤ Client liveness=0, close 旧 DEALER, 创建新 DEALER
           │ Client 新 routing-id = UUID-B
           │ Client TCP SYN (fd_2)
           │
  ─────────┤ Server 收到新连接
           │ ZMTP 握手, 得到 routing-id = UUID-B
           │ Server ROUTER 内部: peer_map[UUID-B] → pipe_2 → fd_2
           │
           │ 此时 Server 同时持有:
           │   peer_map[UUID-A] → pipe_1 → fd_1 (半死: 还没超时)
           │   peer_map[UUID-B] → pipe_2 → fd_2 (活跃)
           │
  ─────────┤ 如果 Server 有 response 要回给旧请求:
           │   → 发到 UUID-A 的 pipe_1 → fd_1 (已断或半断)
           │   → 最终丢失 ★
           │
  ─────────┤ Server 旧连接 fd_1 最终超时或收到 RST
           │ peer_map[UUID-A] 清理
           │
```

> **最隐蔽的丢失场景**: Server 在 t3 处理完请求, `zmq_send(response)` 成功返回（进入 ROUTER pipe），但此时 Client 已经重建了新 DEALER。Response 发到旧 UUID-A 的 pipe，最终随旧连接断开而丢失。Server 认为"发送成功"，Client 等到 RPC 超时。如果上层无幂等设计，重试可能导致数据不一致。

### 9.6 完整跨节点故障时间线

```
 0s              3s              6s              9s             12s
  │               │               │               │               │
  │ IF Down       │               │               │               │
  │ ←───────────→ │               │               │               │
  │   (持续数秒)  │               │               │               │
  │               │               │               │               │
Client:           │               │               │               │
  │ ZMQ 不知情    │ poll idle     │ idle...       │ liveness=0    │
  │ send→TCP buf  │ liveness--   │ liveness--    │ Close旧DEALER │
  │ (TCP在重传)   │               │               │ (linger=0)    │
  │               │               │               │ →pipe丢弃     │
  │               │               │               │ →close(fd1)   │
  │               │               │               │ →RST发出      │
  │               │               │               │               │
  │               │               │               │ New DEALER    │
  │               │               │               │ UUID-B        │
  │               │               │               │ TCP SYN(fd2)  │
  │               │               │               │ ZMTP握手      │
  │               │               │               │ ~100ms        │
  │               │               │               │ 连接恢复      │
  │               │               │               │               │
Server:           │               │               │               │
  │ 不知Client断  │ 可能在处理    │ zmq_send(resp)│ 收到RST或     │
  │               │ 旧请求        │ →旧pipe(UUID-A)│ 新连接(UUID-B)│
  │               │               │ →fd1 TCP buf  │ 旧peer清理    │
  │               │               │ →最终丢失 ★   │               │
  │               │               │               │               │

丢失的数据:
  → 阶段③: fd1 TCP send buffer 中未确认的 request 数据
  → 阶段④: 网络中 in-flight 的 request/response
  → 阶段①: ZMQ pipe 中排队的消息 (linger=0, 立即丢弃)
  → Server 发到旧 UUID-A 的 response
```

---

## 10. libzmq 内部重连 vs RPC 框架重建 DEALER —— 两级重连机制详解

### 10.1 ZMQ socket 内部架构

理解"两级重连"需要先看 ZMQ 一个 socket 内部的分层结构：

```
应用代码只看到这一层:
┌────────────────────────────────┐
│      zmq_socket (DEALER)       │  ← zmq_send/recv 操作的对象
└───────────────┬────────────────┘
                │
                │  以下全部是 libzmq 内部自动管理, 应用不可见:
                │
┌───────────────▼────────────────┐
│           session               │  ← 逻辑会话, 管理 pipe + 重连策略
│                                 │
│  ┌───────────────────────────┐ │
│  │    pipe (用户态消息队列)    │ │  ← zmq_send 的消息先到这里排队
│  └────────────┬──────────────┘ │
│               │                 │
│  ┌────────────▼──────────────┐ │
│  │  engine (ZMTP 协议引擎)   │ │  ← 负责 ZMTP 分帧、握手、心跳
│  │  ┌────────────────────┐   │ │
│  │  │   TCP fd (fd1)     │   │ │  ← 真正的 TCP socket, 系统调用层
│  │  └────────────────────┘   │ │
│  └───────────────────────────┘ │
└────────────────────────────────┘
```

### 10.2 两级重连的对比

#### Level 1: libzmq 内部重连 (只换 engine + fd)

```
触发条件: libzmq 自己检测到 TCP 断开
  - recv() 返回 0 (FIN) 或错误码
  - ZMTP heartbeat 超时 (如果配置了)
  - TCP keepalive 探测失败 (如果配置了)

代码路径:
  stream_engine_base::error()
  → session_base::engine_error()
  → clean_pipes()     // 回滚不完整多帧, 但不销毁 pipe
  → reconnect()       // 新建 tcp_connecter, pipe 保留
  → wait 100ms (reconnect_ivl)
  → TCP SYN → ZMTP 握手 → 新 engine 挂到同一个 session

结果:
  zmq_socket  → 同一个 ✅
  session     → 同一个 ✅
  pipe        → 同一个 ✅ (里面排队的完整消息保留!)
  routing-id  → 不变 (UUID-A) ✅ (Server 能识别是同一个 peer)
  engine      → 旧的销毁, 新建
  TCP fd      → 旧 fd 关闭, 新 fd 建立
```

#### Level 2: RPC 框架重建 DEALER (整个 zmq_socket 销毁重建)

```
触发条件: 应用层代码主动触发
  - WorkerEntry 中 liveness=0 (约 12s 无响应)
  - HandleEvent 返回 K_TRY_AGAIN (EAGAIN 直接置 liveness=0)

代码路径 (zmq_stub_conn.cpp:367-384):
  liveness_ == 0
  → InitFrontend() 创建新 DEALER
  → swap(frontend_, newSocket) → 旧 socket 析构
  → zmq_close() + ZMQ_LINGER=0 → pipe 中所有消息立即丢弃
  → close(old_fd) → TCP send buffer 丢弃

结果:
  zmq_socket  → 旧的销毁, 新建
  session     → 旧的销毁, 新建
  pipe        → 旧的销毁 (消息丢弃), 新建空 pipe
  routing-id  → 变了 (UUID-A → UUID-B), Server 视为全新 peer
  engine      → 旧的销毁, 新建
  TCP fd      → 旧 fd 关闭, 新 fd 建立
```

#### 类比

```
libzmq 内部重连 ≈ 手机 Wi-Fi 断了自动重连同一个热点
  → 手机还是那个手机 (zmq_socket)
  → APP 还在运行 (session + pipe)
  → 只是底层换了个 Wi-Fi 连接 (engine + fd)
  → 排队没发的消息, 重连后自动发出

RPC框架重建 ≈ 卸载 APP 重装
  → 新的 APP 实例 (新 zmq_socket)
  → 聊天记录丢了 (pipe 清空)
  → 要重新登录 (新 routing-id)
  → 对方看到你是一个"新用户"
```

### 10.3 各阶段数据命运对比

| 数据位置 | libzmq 内部重连 | RPC 框架重建 DEALER |
|---------|----------------|-------------------|
| ① ZMQ pipe 中完整消息 | **存活**, 新连接上重发 | **丢弃** (linger=0) |
| ② pipe 中不完整多帧 | **rollback** 丢弃 | **丢弃** |
| ③ 内核 TCP send buffer | **丢失** (close old fd) | **丢失** |
| ④ 网络 in-flight | **丢失** | **丢失** |
| ⑤ 对端 TCP recv buffer | **安全** | **安全** |
| ⑥ 对端 ZMQ pipe | **安全** | **安全** |
| Server 回 response (旧连接) | **旧 pipe 清理, 丢失** | **丢失** |
| Server 回 response (新连接) | **同 routing-id, 能路由** | **新 UUID, 收不到旧的** |

### 10.4 IF Down 时哪级重连先触发？

当前配置下 (无 heartbeat, 无 TCP keepalive):

```
IF Down 发生
  │
  │ libzmq 能检测到吗?
  │   recv() 返回 0? → 不会, 对端发不出 FIN
  │   TCP keepalive?  → 未配置
  │   ZMTP heartbeat? → 未配置
  │   → libzmq 不知道连接断了, 内部重连不触发!
  │
  │ RPC 框架能检测到吗?
  │   WorkerEntry poll → 没有 POLLIN → idle
  │   liveness-- 每 100ms 一次
  │   120 次后 → liveness=0 → 重建 DEALER
  │   → 约 12s 后触发
  │
  ▼
  结论: 当前只走 Level 2 (RPC框架重建), Level 1 轮不到
```

如果配了 ZMTP heartbeat (`ZMQ_HEARTBEAT_IVL=500, TIMEOUT=1500`):

```
IF Down 发生
  │
  │ libzmq:
  │   PING 发出 → TCP buf → 网络不通
  │   1.5s 后 heartbeat timeout
  │   → error(timeout_error) → 内部重连触发! (Level 1)
  │   → pipe 保留, routing-id 不变
  │
  │ RPC 框架:
  │   liveness 还剩 ~105 (才减了 15 次)
  │   → Level 2 还没触发
  │
  ▼
  结论: 配了 heartbeat 后, Level 1 先触发 (~1.5s), Level 2 不触发
        这是更优的行为: pipe 消息不丢, 身份不变
```

### 10.5 配了 heartbeat 后的 IF Down 完整时间线

```
 0s            1.5s          2s           5s           8s
  │              │            │            │            │
  │ IF Down      │            │ IF Up      │            │
  │              │            │            │            │
  │ ZMQ 按计划   │ 1.5s!      │            │            │
  │ 发 PING      │ heartbeat  │            │            │
  │ → TCP buf    │ timeout!   │            │            │
  │ → 网络不通   │            │            │            │
  │              │ Level 1:   │            │            │
  │              │ engine_    │            │            │
  │              │ error()    │            │            │
  │              │ close(fd1) │            │            │
  │              │ ┌─────────────────────┐ │            │
  │              │ │ ③ TCP buf: 丢失     │ │            │
  │              │ │ ① pipe: 保留!       │ │            │
  │              │ │ routing-id: 不变!   │ │            │
  │              │ └─────────────────────┘ │            │
  │              │                         │            │
  │              │ reconnect()             │            │
  │              │ wait 100ms              │            │
  │              │ TCP SYN → 失败(IF Down) │            │
  │              │ wait ~200ms             │            │
  │              │ TCP SYN → 失败          │ IF Up!     │
  │              │ ...重试...              │            │
  │              │                         │ TCP SYN ✅ │
  │              │                         │ ZMTP握手   │
  │              │                         │            │
  │              │                         │ pipe 中的  │
  │              │                         │ 消息通过   │
  │              │                         │ fd2 发出 ✅│
  │              │                         │            │
  │              │                         │ Server:    │
  │              │                         │ 同UUID-A   │
  │              │                         │ 重新关联   │

  RPC 框架层: liveness 减了几次但远没到 0, Level 2 不触发
  应用层: 如果 RPC 超时 (3s) 在网络恢复前到期, 调用方已返回错误
         pipe 中的 request 后来发出去了, 但 response 回来时
         MsgQue 可能已关闭 (id 不匹配被丢弃)
```

### 10.6 两级重连的设计意义

```
为什么需要两级?

Level 1 (libzmq 内部): 处理 "TCP 断了但业务还在" 的场景
  → 快速恢复底层连接, 上层无感
  → pipe 消息保留, 身份不变
  → 适合短暂网络抖动

Level 2 (RPC 框架): 处理 "Level 1 连不上 / 对端长时间无响应" 的场景
  → 彻底重来, 清理所有状态
  → 避免僵尸连接永远挂着
  → 适合对端真的挂了的情况

理想分工:
  短故障 (秒级): TCP 重传兜底, 无重连
  中故障 (1-10s): Level 1 内部重连, pipe 保留
  长故障 (>12s):  Level 2 重建, 彻底放弃旧状态

当前问题: Level 1 因为没配 heartbeat 而失效
  → 短/中故障靠 TCP 重传
  → 长故障直接跳到 Level 2 (更暴力)
  → 缺少中间的 "温和重连" 层

配了 heartbeat 后: Level 1 激活
  → 中故障时: 内部重连, pipe 保留, 身份不变
  → 恢复质量更高
```

---

## 11. close(fd) 的精确触发条件 (源码级)

### 11.1 close(fd) 在哪里执行

TCP fd 的 close 只在 **engine 析构函数** 中执行，不在其他地方：

```
所有 close(fd) 路径:
  error()     → unplug() → delete this → ~stream_engine_base_t() → close(_s)
  terminate() → unplug() → delete this → ~stream_engine_base_t() → close(_s)

所以关键问题是: 什么条件触发 error()?
```

### 11.2 触发 error() 的 5 个条件

#### 条件 1: TCP read 返回 0 或硬错误 (对端 FIN/RST)

```
recv() 返回 0 (对端发了 FIN, 正常关闭)
  → tcp_read() 返回 0
  → stream_engine_base::read() 映射为 return -1, errno=EPIPE
  → in_event_internal(): errno != EAGAIN
  → error(connection_error)  ← 触发!

recv() 返回 -1, errno=ECONNRESET (对端发了 RST)
  → 同上路径 → error(connection_error)  ← 触发!

recv() 返回 -1, errno=ETIMEDOUT (TCP 重传耗尽, ~15-30min)
  → 同上路径 → error(connection_error)  ← 触发!

recv() 返回 -1, errno=EAGAIN (暂无数据)
  → 不触发, 返回等下次 poll
```

IF Down 时能触发? **不能** — 对端发不出 FIN/RST, recv() 不出错

#### 条件 2: ZMTP heartbeat_timeout 到期 (发了 PING, 没收到 PONG)

```
heartbeat_ivl 定时器到期
  → 发送 ZMTP PING 帧
  → 启动 heartbeat_timeout 定时器

heartbeat_timeout 定时器到期 (在 timeout ms 内没收到完整消息)
  → timer_event(heartbeat_timeout_timer_id)
  → error(timeout_error)  ← 触发!

取消条件: decode_and_push() 成功处理了任意一条完整 ZMTP 消息
  → cancel_timer(heartbeat_timeout_timer_id)
  → 不触发

注意: 只有完整消息能重置计时器, 原始 TCP 字节 (未解码) 不行
```

IF Down 时能触发? **能, 但当前未配置** — 配了则在 timeout ms 后触发

#### 条件 3: heartbeat_ttl 到期 (对端声明的存活时限到期)

```
收到对端 PING, 其中携带 TTL 值
  → 启动 heartbeat_ttl 定时器 (TTL * 100 ms)

TTL 定时器到期
  → timer_event(heartbeat_ttl_timer_id)
  → error(timeout_error)  ← 触发!

取消条件: 同上, decode_and_push() 处理完整消息时取消
```

IF Down 时能触发? **能, 但当前未配置**

#### 条件 4: ZMTP 握手超时 (handshake_ivl, 默认 30s)

```
新 TCP 连接建立后, 启动 handshake 定时器 (默认 30000ms)

30s 内 ZMTP 握手未完成 (greeting + mechanism + properties)
  → timer_event(handshake_timer_id)
  → error(timeout_error)  ← 触发!
```

IF Down 时能触发? **只在重连建新连接时** — 已建好的连接不涉及

#### 条件 5: 协议解析错误

```
in_event_internal() 中 decode/process 返回 -1, errno != EAGAIN
  → error(protocol_error)  ← 触发!

例如: 畸形 ZMTP 帧, 版本不匹配, ZAP 认证失败
```

IF Down 时能触发? **不能** — 收不到数据就没有解析

### 11.3 关键发现: TCP write 错误不触发 close!

```
send() 返回 -1 (EPIPE / ECONNRESET / ENOTCONN)
  → tcp_write() 返回 -1
  → out_event(): nbytes == -1
  → 仅 reset_pollout()  ← 停止监听可写事件
  → 不调用 error()!
  → 不 close(fd)!

ZMQ 设计: write 失败只暂停发送, 等 read 侧检测到错误再统一处理
即使 TCP send buffer 满 + 重传失败, 也不会从 write 侧触发 close
```

### 11.4 IF Down 时的完整决策树

```
IF Down 发生
│
├─ 条件1: recv() 会返回错误吗?
│    对端发不出 FIN/RST → recv() 不出错
│    POLLIN 不就绪时 recv() 根本不被调用
│    ❌ 不触发
│
├─ 条件2: heartbeat timeout?
│    当前未配置 → ❌ 不触发
│    如果配了 ZMQ_HEARTBEAT_TIMEOUT=1500 → ✅ 1.5s 后触发 close(fd)
│
├─ 条件3: heartbeat TTL?
│    当前未配置 → ❌ 不触发
│
├─ 条件4: 握手超时?
│    只在新连接时 → ❌ 不适用 (已建好的连接)
│
├─ 条件5: 协议错误?
│    收不到数据就无解析 → ❌ 不触发
│
├─ TCP write 失败?
│    可能发生 (send buffer 满 + 重传超时 → EPIPE)
│    但 write 失败不触发 close! → ❌ 不触发
│
├─ TCP keepalive? (间接触发条件1)
│    当前未配置 → ❌ 不触发
│    如果配了 (idle=10, cnt=3, intvl=5):
│    → 25s 后内核给 socket 标记 ETIMEDOUT
│    → 下次 recv() 被调用时返回 -1 → ✅ 条件1 触发
│
└─ 应用层 liveness=0? (不是 libzmq 的 close)
     约 12s 后触发
     这是 RPC 框架调用 zmq_close() → 整个 DEALER 销毁
     ✅ 触发, 但属于 Level 2 重建, 不是 Level 1 内部重连
```

### 11.5 结论

```
当前配置下 IF Down 的唯一 close 来源:
  ┌─────────────────────────────────────────────────┐
  │ RPC 框架 liveness=0 (~12s) → zmq_close()       │
  │ 这是 Level 2 重建, pipe 全丢, 身份重置          │
  │ libzmq 内部 Level 1 重连: 完全不会触发          │
  └─────────────────────────────────────────────────┘

配了 heartbeat 后:
  ┌─────────────────────────────────────────────────┐
  │ libzmq heartbeat_timeout (~1.5s) → close(fd)   │
  │ 这是 Level 1 内部重连, pipe 保留, 身份不变      │
  │ 如果 Level 1 能恢复, Level 2 不会被触发         │
  └─────────────────────────────────────────────────┘

配了 TCP keepalive 后:
  ┌─────────────────────────────────────────────────┐
  │ keepalive 探测失败 (~25s) → recv() ETIMEDOUT    │
  │ → 条件1 触发 → Level 1 内部重连                 │
  └─────────────────────────────────────────────────┘

设计要点: close(fd) 不是 TCP 自己的决定, 是上层 (ZMQ/应用) 基于
超时策略主动做的。TCP 本身在 IF Down 时只会默默重传, 永远不会主动
放弃一个连接 (直到 tcp_retries2 耗尽, 约 15-30min)。
```

---

## 12. SO_LINGER vs ZMQ_LINGER 对比

两个 LINGER 工作在不同层次，控制的是 close 时等不等数据发完，但作用域完全不同。

### 12.1 SO_LINGER (TCP/内核层)

控制 `close(fd)` 时内核对 TCP send buffer 中未发送数据的处理。

```
三种模式:
┌─────────────────┬────────────────────────────────────────────┐
│ 配置             │ close(fd) 行为                             │
├─────────────────┼────────────────────────────────────────────┤
│ l_onoff = 0     │ 默认行为:                                  │
│ (默认)          │   close() 立即返回                          │
│                 │   内核在后台继续发送 send buffer 中的数据    │
│                 │   发完后正常 FIN 四次挥手                    │
│                 │   数据不丢失 (除非对端先断)                  │
├─────────────────┼────────────────────────────────────────────┤
│ l_onoff = 1     │ 优雅关闭 (有超时):                          │
│ l_linger > 0    │   close() 阻塞最多 l_linger 秒             │
│                 │   等 send buffer 排空 + 收到对端 FIN        │
│                 │   超时 → 丢弃剩余数据, 发 RST              │
├─────────────────┼────────────────────────────────────────────┤
│ l_onoff = 1     │ 硬关闭 (立即):                              │
│ l_linger = 0    │   close() 立即返回                          │
│                 │   内核丢弃 send buffer 全部数据              │
│                 │   直接发 RST (不走 FIN 四次挥手)             │
└─────────────────┴────────────────────────────────────────────┘
```

### 12.2 ZMQ_LINGER (ZMQ/用户态层)

控制 `zmq_close(socket)` 时 ZMQ 用户态 pipe 中排队消息的处理。

```
三种模式:
┌─────────────────┬────────────────────────────────────────────┐
│ 配置             │ zmq_close() 行为                           │
├─────────────────┼────────────────────────────────────────────┤
│ ZMQ_LINGER = -1 │ 默认: 无限等待                              │
│ (libzmq 默认)   │   zmq_close() 阻塞直到 pipe 中所有消息     │
│                 │   都交给 TCP send buffer                    │
│                 │   可能永远阻塞 (如果对端不收)               │
├─────────────────┼────────────────────────────────────────────┤
│ ZMQ_LINGER > 0  │ 有超时 (毫秒):                              │
│                 │   zmq_close() 等最多 N 毫秒                │
│                 │   尽量把 pipe 中消息排到 TCP                │
│                 │   超时后丢弃剩余消息, 关闭底层 fd           │
├─────────────────┼────────────────────────────────────────────┤
│ ZMQ_LINGER = 0  │ 立即丢弃 (你们的配置):                      │
│                 │   zmq_close() 立即返回                     │
│                 │   pipe 中所有排队消息立即丢弃               │
│                 │   底层 fd 立即 close()                      │
└─────────────────┴────────────────────────────────────────────┘
```

### 12.3 两者的作用域

```
zmq_send(msg)
    │
    ▼
┌──────────────┐          ┌──────────────┐
│  ZMQ pipe    │          │  TCP send    │
│  (用户态)    │──write──→│  buffer      │──网络──→ 对端
│              │          │  (内核态)    │
└──────────────┘          └──────────────┘
       │                         │
  ZMQ_LINGER                SO_LINGER
  控制这里的数据              控制这里的数据
```

### 12.4 ZMQ_LINGER=0 在当前架构下是正确的

zmq_close() 被调用的场景只有三个：

| 场景 | 代码位置 | 说明 |
|------|---------|------|
| liveness=0 重建 DEALER | `zmq_stub_conn.cpp:378` swap 后旧 socket 析构 | 故障恢复路径 |
| WorkerEntry 退出 | `zmq_stub_conn.cpp:320` Raii guard | shutdown |
| Server/Context shutdown | `zmq_server_impl.cpp:98` | shutdown |

linger=0 为什么是对的：

```
liveness=0 触发时, 连接已"判死" (~12s 无响应):
  1. pipe 里的数据发到旧连接也没用 (对端可能早断了)
  2. 新 DEALER 有新 routing-id, 旧消息的 response 回旧身份, 新 socket 收不到
  3. 等 pipe 排空 = 浪费时间 + 阻塞 WorkerEntry + 延迟故障恢复
  4. shutdown 时不阻塞, 进程快速退出

改大 linger 的后果:
  ZMQ_LINGER=5000 → zmq_close() 阻塞 5 秒
    → WorkerEntry 被阻塞 → 新 DEALER 建立延迟
    → 故障恢复从 ~12s 变成 ~17s
    → 且数据仍然发不出去 (网络不通) → 白等
```

---

## 13. ZMQ 为什么 close(fd) 而不是等 TCP 恢复

### 13.1 根本矛盾

```
TCP 的态度: "我重传 15-30 分钟再放弃"
应用的态度: "3 秒没响应我就等不了了"

时间尺度差三个数量级, 应用不可能等 TCP
```

### 13.2 ZMQ 架构限制: session 与 engine 1:1

```
ZMQ 内部:
  session ──→ engine ──→ fd

一个 session 只能绑一个 engine (一个 TCP 连接)
不支持同时持有新旧两个连接:
  session ──→ engine_old(fd1)  ← 等恢复
         └──→ engine_new(fd2)  ← 同时建新的  ← 不支持!

要建新连接, 必须先销毁旧 engine = close(旧 fd)
```

理想方案 (ZMQ 不支持)：
```
保留旧 fd, 同时建新 fd, 设宽限期:
  fd1 恢复了 → 好, 数据不丢, 关 fd2
  fd1 超时   → 关 fd1, 切 fd2

这需要 session 支持双 engine + 消息去重
→ ZMQ 作为轻量传输层不做这个
→ 这是 QUIC 或应用层协议的工作
```

### 13.3 正确策略: 避免不该 close 的时候 close

```
既然 close(fd) 是破坏性的, 最好的策略是让超时 > IF Down 持续时间:

你的场景: 2.5s 周期, 0.5s IF Down

┌──────────────────────────┬──────────┬──────────────────────────┐
│ 超时配置                  │ 推荐值   │ 原因                      │
├──────────────────────────┼──────────┼──────────────────────────┤
│ ZMQ_HEARTBEAT_TIMEOUT    │ 不配置   │ 0.5s IF Down 让 TCP      │
│ (或 > 2s)                │ 或 3000  │ 自己重传就够了            │
├──────────────────────────┼──────────┼──────────────────────────┤
│ liveness 超时            │ ~12-120s │ 0.5s IF Down 远不会      │
│ (heartbeatInterval*max)  │ (不改)   │ 耗尽 liveness            │
├──────────────────────────┼──────────┼──────────────────────────┤
│ RPC timeout              │ 3-60s    │ 当前值已足够              │
└──────────────────────────┴──────────┴──────────────────────────┘

结果: 0.5s IF Down 全程无 close(fd) → TCP 重传兜底 → 零丢包
```

---

## 14. RPC 框架 WorkerEntry 主循环详解

### 14.1 架构总览

```
业务线程 (KV Client)
    │ 调用 RPC: Put(key, value)
    ▼
┌──────────────────────────────────────────────────┐
│  ZmqFrontend (专用后台线程)                       │
│                                                   │
│  ┌─────────┐        ┌──────────────┐             │
│  │ msgQue_ │ ←───── │ 业务线程     │ request入队 │
│  │ (内部   │        │ SendMsg()    │             │
│  │  队列)  │        └──────────────┘             │
│  └────┬────┘                                     │
│       │ eventfd 通知                              │
│       ▼                                          │
│  ┌──────────────┐                                │
│  │ DEALER socket │ ←TCP→ Server ROUTER socket    │
│  │ (frontend_)   │                               │
│  └──────────────┘                                │
│                                                   │
│  主循环: WorkerEntry()                            │
│    while(!interrupt) {                            │
│       HandleEvent()  // poll + 收发               │
│       liveness 管理  // 健康检查                   │
│    }                                              │
└──────────────────────────────────────────────────┘
```

### 14.2 HandleEvent: 每次循环干什么

```
HandleEvent(timeout):
  poll(zmq_fd, eventfd, timeout_ms)
  同时监听:
    zmq_fd:  DEALER socket 有数据可收? (Server 发来 response)
    eventfd: 内部队列有新 request 要发?

  zmq_fd 可读 → ZmqSocketToBackend():
    从 DEALER 收 response → ResetLiveness() → 转发给业务线程
    
  eventfd 可读 → BackendToFrontend():
    从内部队列取 request → 通过 DEALER 发出

  都没有 → 返回 K_NOT_FOUND (idle)
```

### 14.3 liveness 递减的精确逻辑

```cpp
// zmq_stub_conn.cpp:334-386 简化后的逻辑:
while (!interrupt_) {
    rc = HandleEvent(timeout);

    if (rc == K_NOT_FOUND) {          // idle: 没有任何事件
        timeout = 100;                // 下次 poll 等 100ms
        if (t < heartbeatInterval_)   // 还没到心跳间隔
            continue;                 // → 跳回开头, 不减 liveness!
    } else {
        timeout = 0;
        if (rc == K_TRY_AGAIN) {      // EAGAIN: 直接判死
            liveness_ = 0;            // → 立即跳到重建
        } else {
            continue;                 // 正常收到数据, 跳回开头
        }
    }

    // 只有累计 idle >= heartbeatInterval_ 才到这里
    if (liveness_ > 0) liveness_--;
    SendHeartBeats();                 // 发应用层心跳
    t.Reset();

    if (liveness_ == 0) {             // 判死 → 重建 DEALER
        InitFrontend(new_socket);
        swap(frontend_, new_socket);  // 旧 socket 析构 → close(fd)
    }
}
```

关键：**不是每 100ms 减一次！**

```
每次循环:
  idle → 检查 t < heartbeatInterval_ → 不到就 continue, 不减 liveness
  
  只有累计 idle 时间 >= heartbeatInterval_ (默认 1000ms) 才:
    liveness_--, SendHeartBeats(), t.Reset()
    
实际递减频率 = 每 heartbeatInterval_ ms 减一次
```

### 14.4 从 IF Down 到 close 的时间计算

```
默认配置:
  heartbeatInterval_ = 1000ms (K_ONE_SECOND)
  maxLiveness_ = 120 (K_LIVENESS)
  → close 时间 = 1000ms × 120 = 120s (2分钟)

如果被 UpdateLiveness() 动态调整过:
  UpdateLiveness(timeoutMs):
    interval = max(200ms, min(timeoutMs/4, 30000ms))
    newLiveness = max(timeoutMs*0.9/interval, 3)
    
  例如 timeoutMs=3000ms:
    interval = max(200, min(750, 30000)) = 750ms
    liveness = max(2700/750, 3) = max(3.6, 3) = 3
    → close 时间 = 750ms × 3 ≈ 2.25s

快速通道: HandleEvent 返回 K_TRY_AGAIN
  → liveness 直接置 0 → 立即重建, 不用等
```

### 14.5 应用层心跳 vs ZMTP 心跳

```
应用层心跳 (RPC框架, 当前在用):           ZMTP 心跳 (ZMQ协议层, 当前未用):
────────────────────────────              ────────────────────────────
发送: 普通 MetaPb RPC 消息                发送: ZMTP PING 帧 (协议内部)
  method_index = ZMQ_HEARTBEAT_METHOD       不经过 pipe, engine 直接发
经过: pipe → engine → TCP                 经过: engine → TCP

处理: Server ROUTER 收到                  处理: 对端 engine 内部处理
  → 回一条 response                         → 自动回 PONG
  → 走正常 RPC 回路                         → 不经过应用层

超时: liveness 递减到 0                   超时: heartbeat_timeout_timer 到期
  → RPC 框架 zmq_close()                   → libzmq error(timeout_error)
  → Level 2 重建 (pipe 全丢)               → Level 1 内部重连 (pipe 保留)
  → 新 routing-id                          → routing-id 不变
```

---

## 15. 故障注入方式对比与分析

### 15.1 三种 IF Down 注入方式

```bash
# 方式 1: ip link down/up (真 IF Down, 链路层)
while true; do
  ip link set eth0 down; sleep 0.5
  ip link set eth0 up;   sleep 2.0
done

# 方式 2: tc netem 100% 丢包 (网络层模拟)
while true; do
  tc qdisc add dev eth0 root netem loss 100%; sleep 0.5
  tc qdisc del dev eth0 root;                 sleep 2.0
done

# 方式 3: iptables DROP (网络层过滤)
while true; do
  iptables -A INPUT -i eth0 -j DROP
  iptables -A OUTPUT -o eth0 -j DROP; sleep 0.5
  iptables -F;                        sleep 2.0
done
```

### 15.2 不同方式的本质区别

```
┌─────────────────┬──────────────┬──────────────┬──────────────┐
│                 │ ip link down │ tc netem     │ iptables     │
│                 │ (真IF Down)  │ loss 100%    │ DROP         │
├─────────────────┼──────────────┼──────────────┼──────────────┤
│ 作用层          │ 链路层 (L2)  │ 网络层 (L3)  │ 网络层 (L3)  │
│ 网卡 carrier    │ 消失         │ 保持         │ 保持         │
│ ARP 表          │ 可能失效     │ 保持         │ 保持         │
│ TCP 连接状态    │ 内核可能     │ 不感知       │ 不感知       │
│                 │ 立即通知应用 │ 只是丢包     │ 只是丢包     │
│ 恢复后行为      │ 需要重新     │ 立即恢复     │ 立即恢复     │
│                 │ ARP/路由     │              │              │
│ 对 TCP socket   │ send 可能返回│ 无直接影响   │ 无直接影响   │
│ 的直接影响      │ ENETDOWN     │ TCP 默默重传 │ TCP 默默重传 │
└─────────────────┴──────────────┴──────────────┴──────────────┘
```

### 15.3 ip link down (真 IF Down) 的精确行为

```
ip link set eth0 down 执行时:
│
├─ 内核: IFF_UP 标志清除, carrier 丢失
├─ 该网卡上所有路由: 标记为不可达
├─ 已有的 TCP socket:
│   ├─ 正在 send(): 返回 ENETDOWN (-1, errno=100)
│   ├─ 正在 recv(): 不会立即返回错误 (recv 只在有数据或FIN时返回)
│   ├─ 后续 send(): 返回 ENETDOWN
│   └─ TCP 连接: 内核不主动断开, 但无法重传
│
├─ ZMQ 的行为:
│   ├─ engine out_event(): tcp_write → ENETDOWN
│   │   → write 错误只 reset_pollout, 不 close(fd)!
│   ├─ engine in_event(): recv buf 空则不被调用
│   └─ 不触发 close(fd)
│
└─ ip link set eth0 up 之后:
    ├─ carrier 恢复
    ├─ 路由恢复
    ├─ ARP 需要重新解析 (几十ms)
    ├─ TCP: 下次重传成功 → 连接恢复
    └─ 之前 ENETDOWN 的 send: 下次调用就能成功

结论: 0.5s ip link down → TCP 未断 → ZMQ 无感 → 不丢消息
     只有 ~200-500ms 延迟抖动 (TCP 重传等待)
```

### 15.4 观测到的 0.7~0.8ms 故障时间分析

```
0.7~0.8ms 远小于 0.5s IF Down 持续时间, 可能的解释:

  场景 A: 链路层 carrier detect 时间
    ip link down → up 后, 网卡从 "no carrier" 恢复
    到 "carrier detected" 需要 ~0.7ms
    这是物理层/驱动层的恢复时间

  场景 B: 监控工具观测的网络中断时间
    最后一个成功包到第一个恢复成功包的时间差
    如果注入工具实际 IF Down 只有 sub-ms 级

  场景 C: 实际 IF Down 只有 0.7ms 而非 0.5s
    注入脚本的实际执行精度问题
    在 0.7ms 尺度上: 可能只丢 1 个 TCP segment
    TCP 快速重传 (3 dup ACK) 几 ms 内恢复
    对 ZMQ 和应用层几乎无感知

需要确认: 注入方式 (ip link / tc / iptables / 物理拔线)
         和 0.7~0.8ms 的测量点 (网卡状态 / RPC延迟 / 丢包统计)
```

---

## 16. liveness=0 的精确触发条件

liveness 变为 0 只有两种方式：

### 16.1 方式 1 (慢路径): 自然递减到 0

前提：**长时间没收到任何 response（包括心跳 response）**。

```
WorkerEntry 主循环每一轮:

  HandleEvent(timeout) 返回 K_NOT_FOUND (idle)
    → 检查: t.ElapsedMilliSecond() < heartbeatInterval_ ?
    → 是: continue, 不减 liveness (跳回循环开头)
    → 否 (累计 idle >= heartbeatInterval_):
        liveness_--
        SendHeartBeats()  // 发应用心跳, 尝试让对端回 response
        t.Reset()         // 重置心跳计时器

每 heartbeatInterval_ (默认 1s) 减一次, 不是每 100ms
从 maxLiveness_ (默认 120) 减到 0:
  默认: 120 × 1s = 120s (2分钟)
  UpdateLiveness 调过后: 可能快至 ~2-3s
```

**什么能重置 liveness 阻止它到 0？收到任意一条 response：**

```
HandleEvent() → ZMQ_POLLIN 就绪 → ZmqSocketToBackend():
  frontend_->GetAllFrames()  // 从 DEALER 收到数据
  ResetLiveness()            // liveness 重置回 maxLiveness_ (120)

只要收到一条 response (RPC response 或心跳 response), liveness 就回满
```

### 16.2 方式 2 (快路径): K_TRY_AGAIN 直接置 0

```cpp
// zmq_stub_conn.cpp:348-352
if (rc.GetCode() == K_TRY_AGAIN) {
    liveness_ = 0;  // 不等递减, 直接判死
}
```

**什么时候 HandleEvent 返回 K_TRY_AGAIN？** 追踪调用链：

```
HandleEvent()
  ├─ ZmqSocketToBackend()         → RETURN_IF_NOT_OK (错误冒泡)
  └─ BackendToFrontend()          → RETURN_IF_NOT_OK
      └─ RouteToZmqSocket()
          └─ frontend_->SendAllFrames(p, DONTWAIT)
              └─ zmq_send(DONTWAIT) 返回 EAGAIN
                 → Status(K_TRY_AGAIN)
                 → 冒泡到 HandleEvent 返回值
```

即：**尝试通过 DEALER 发消息但 zmq_send(DONTWAIT) 返回 EAGAIN**。

zmq_send(DONTWAIT) 在 DEALER 上返回 EAGAIN 的条件：

```
1. ZMQ_IMMEDIATE=true 且没有已建立的连接
   → 当前配置了 IMMEDIATE=true
   → 含义: 只有 TCP 连接建立后才能发消息
   → 如果底层 TCP 连接断了且尚未重连 → EAGAIN

2. 所有 peer 的 pipe 都满了 (HWM 限制)
   → 当前 HWM=0 (无限), 几乎不可能
```

### 16.3 IF Down 时走哪条路径

```
IF Down 期间:

  TCP 连接还在! (内核层面没断, 只是重传中)
  DEALER socket 认为连接正常
  zmq_send(DONTWAIT) → 成功 (消息进入 pipe → TCP send buffer)
  → HandleEvent 不会返回 K_TRY_AGAIN
  → 方式 2 不触发

  但 Server response 回不来 (IF Down, 网络不通)
  → HandleEvent 持续返回 K_NOT_FOUND (idle)
  → 走方式 1 (慢路径), liveness 一次一次递减

结论: IF Down 时走方式 1
```

### 16.4 完整判定流程图

```
HandleEvent() 返回什么?
│
├─ OK (收到 response)
│    → ZmqSocketToBackend 中已 ResetLiveness()
│    → liveness = maxLiveness_ (120)
│    → 永远不会到 0
│
├─ K_NOT_FOUND (idle, 没事件)
│    → 累计 idle < heartbeatInterval_ → continue, 不减
│    → 累计 idle >= heartbeatInterval_ → liveness--
│    → 慢慢减到 0 (方式1, 约 120s 或 ~2-3s)
│
├─ K_TRY_AGAIN (EAGAIN, 发不出去)
│    → liveness = 0 (立即, 方式2)
│    → IF Down 时: TCP 还在, send 能成功, 几乎不走这条
│    → 真正触发场景: TCP 连接已断 + IMMEDIATE=true → send EAGAIN
│
├─ K_SHUTTING_DOWN
│    → break 退出循环, 不走 liveness 逻辑
│
└─ 其他错误 (K_RUNTIME_ERROR 等)
     → 从 HandleEvent 内部 RETURN_IF_NOT_OK 返回
     → 不匹配 K_NOT_FOUND 也不匹配 K_TRY_AGAIN
     → else 分支: timeout=0, continue
     → 不减 liveness, 下一轮继续
```

### 16.5 SendHeartBeats 也可能失败

```
每次 liveness-- 后会调 SendHeartBeats():

Status ZmqFrontend::SendHeartBeats() {
    events = frontend_->Get(ZMQ_EVENTS);
    if (!(events & ZMQ_POLLOUT))
        return K_RPC_UNAVAILABLE;      // 不可写 → 发不出心跳
    
    SendAllFrames(heartbeat, DONTWAIT); // 发心跳消息
}

如果 ZMQ_POLLOUT 不就绪 (TCP send buffer 满):
  → SendHeartBeats 返回错误
  → 但 WorkerEntry 中用的是 (void)SendHeartBeats()
  → 返回值被忽略! 不影响主循环逻辑
  → liveness 继续递减

所以心跳发不出去不会加速判死, 也不会阻止判死
只是一个"尽力而为"的保活尝试
```
