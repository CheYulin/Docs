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

```
┌──────────────────────┬──────────────────────────────────────────┐
│     IF Down 时刻      │              是否丢失                     │
├──────────────────────┼──────────────────────────────────────────┤
│                      │                                          │
│ Request 在 ZMQ pipe  │ 如果TCP不断: 不丢                        │
│ (zmq_send 成功)      │ 如果TCP断开: 丢失(pipe drain或TCP buf丢) │
│                      │                                          │
│ Request 在 TCP buf   │ 如果TCP不断: 不丢(TCP重传)               │
│                      │ 如果TCP断开: 丢失                        │
│                      │                                          │
│ Request 在网络中     │ 如果TCP不断: 不丢(TCP重传)               │
│ (未达Server)         │ 如果TCP断开: 丢失                        │
│                      │                                          │
│ Request 已达Server   │ 不丢(已被Server收到)                     │
│ Server正在处理       │ 但response可能丢失(见下)                  │
│                      │                                          │
│ Response 在Server    │ 如果TCP不断: 不丢                        │
│ TCP buf (回传中)     │ 如果TCP断开:                              │
│                      │   ROUTER丢弃该peer的pending msg          │
│                      │   *** Response 丢失 ***                   │
│                      │                                          │
│ Response 在网络中    │ 如果TCP不断: 不丢                        │
│                      │ 如果TCP断开: 丢失                        │
│                      │                                          │
│ Response 在Client    │ 如果TCP不断: 不丢                        │
│ TCP recv buf         │ 如果TCP断开: 丢失(socket被close)         │
│                      │                                          │
│ Response 已到ZMQ     │ 不丢(已在应用层)                         │
│ MsgQue               │                                          │
└──────────────────────┴──────────────────────────────────────────┘
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
