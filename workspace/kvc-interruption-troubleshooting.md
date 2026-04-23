# 12.2 KVCache中断异常

## 故障现象

- 客户侧SDK成功率 < 90%
- 客户KVC Worker成功率 < 90%

---

## 故障树总纲

> **注**：以下错误码为**内部码，不返回SDK**（不出现在access log中）：K_NOT_LEADER_MASTER(16)、K_RECOVERY_ERROR(17)、K_RECOVERY_IN_PROGRESS(18)、K_SHUTTING_DOWN(23)、K_WORKER_ABNORMAL(24)、K_SCALING(32在重试中)、K_RPC_STREAM_END(43)、K_SC_WORKER_WAS_LOST(62)、K_RDMA_NEED_CONNECT(73)

```
错误码(枚举) ─ 条件/日志/指标 ─→ 责任方
│
├─ 0(K_OK) / 2(K_INVALID) / 3(K_NOT_FOUND) / 8(K_NOT_READY) ─→ 【用户】业务代码问题
│
├─ 6(K_OUT_OF_MEMORY) / 7(K_IO_ERROR) / 13(K_NO_SPACE) / 18(K_FILE_LIMIT_REACHED) ─→ 【OS】资源问题
│
├─ 5(K_RUNTIME_ERROR) ─ 含"etcd" ─→ 【etcd】三方依赖
├─ 5(K_RUNTIME_ERROR) ─ 含"mmap" ─→ 【OS】内存锁定限制
├─ 5(K_RUNTIME_ERROR) ─ 含"urma" ─→ 【URMA】UB传输失败
│
├─ 25(K_MASTER_TIMEOUT) ─→ 【etcd】Master超时
│
├─ 29(K_SERVER_FD_CLOSED) ─→ 【数据系统】Worker退出（注：返回时转为K_TRY_AGAIN）
├─ 31(K_SCALE_DOWN) ─→ 【数据系统】缩容中
│
├─ 1004(K_URMA_ERROR) / 1009(K_URMA_CONNECT_FAILED) ─→ 【URMA】硬件/端口down
├─ 1006/1008/1010 ─ 见需进一步分析故障树
│
├─ 19(K_TRY_AGAIN) ─ ZMQ failure delta=0 ─→ 【数据系统】对端处理慢
├─ 19(K_TRY_AGAIN) ─ ZMQ failure delta>0 ─→ 【OS/网络】网络丢包/断连
│
├─ 23(K_CLIENT_WORKER_DISCONNECT) ─ 对端进程不存在 ─→ 【数据系统】Worker崩溃
├─ 23(K_CLIENT_WORKER_DISCONNECT) ─ ping不通 ─→ 【OS/网络】防火墙/路由
├─ 23(K_CLIENT_WORKER_DISCONNECT) ─ ping通 ─→ 【OS/网络】对端负载高/网络抖
│
├─ 1001(K_RPC_DEADLINE_EXCEEDED) ─ 含"[RPC_SERVICE_UNAVAILABLE]" ─→ 【数据系统】对端拒绝
├─ 1001(K_RPC_DEADLINE_EXCEEDED) ─ delta=0 + 对端在 ─→ 【数据系统】对端处理慢
├─ 1001(K_RPC_DEADLINE_EXCEEDED) ─ delta>0 或对端不在 ─→ 【OS/网络】网络问题
│
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"etcd" ─→ 【etcd】
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"TLS/handshake" ─→ 【数据系统】证书问题
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"TCP_CONNECT" + 对端不在 ─→ 【数据系统】Worker崩溃
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"TCP_CONNECT" + 对端在 ─→ 【OS/网络】防火墙/端口
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"TCP_CONNECT_RESET" ─→ 【OS/网络】网络闪断
├─ 1002(K_RPC_UNAVAILABLE) ─ 含"UDS/SHM_FD" ─→ 【OS】UDS/权限/fd
├─ 1002(K_RPC_UNAVAILABLE) ─ ZMQ failure delta>0 ─→ 【OS/网络】按errno细分
└─ 1002(K_RPC_UNAVAILABLE) ─ delta=0 + 对端在 ─→ 【数据系统】对端慢/拒绝
```

---

## 需进一步分析的故障树

### code=5 — K_RUNTIME_ERROR

**查看命令**：
```bash
grep -E 'Get mmap entry failed|etcd is|urma' $LOG/datasystem_worker.INFO.log
```

```
code=5 K_RUNTIME_ERROR
  │ 错误消息: "Runtime error"
  │
  ├─ 日志含"Get mmap entry failed"
  │   ├─ 错误消息: "Get mmap entry failed"
  │   ├─ errno: ENOMEM(mlock限制)
  │   └─→ 【OS】内存锁定限制
  │       处置: ulimit -l unlimited
  │       验证: cat /proc/$(pgrep datasystem_worker)/limits | grep 'Max locked memory'
  │
  ├─ 日志含"etcd is timeout" / "etcd is unavailable"
  │   ├─ 错误消息: "etcd is timeout/unavailable"
  │   └─→ 【etcd】三方依赖
  │       处置: etcdctl endpoint status -w table
  │       验证: systemctl status etcd
  │
  └─ 日志含"urma ... payload ..."
      ├─ 错误消息: "urma ... payload ..."
      └─→ 【URMA】UB传输失败
          查: grep -E '\[URMA_' $LOG/datasystem_worker.INFO.log
```

---

### code=19 — K_TRY_AGAIN

**查看命令**：
```bash
# ZMQ failure delta
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_receive_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
# 对端状态
ssh <peer_ip> "pgrep -af datasystem_worker"
```

```
code=19 K_TRY_AGAIN
  │ 错误消息: "Try again"
  │ 代码: zmq_msg_queue.h:884（recv返回EAGAIN背压）
  │
  ├─ ZMQ failure delta=0
  │   └─→ 【数据系统】对端处理慢
  │       查: grep 'WAITING_TASK_NUM' $LOG/resource.log
  │       查: top -bn1 | head -20
  │
  └─ ZMQ failure delta>0
      └─→ 【OS/网络】网络丢包/断连
          查: grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log
          按errno表细分
```

---

### code=23 — K_CLIENT_WORKER_DISCONNECT

**查看命令**：
```bash
# 对端进程是否存在
ssh <peer_ip> "pgrep -af datasystem_worker"
# Worker退出日志
grep 'Worker is exiting' $LOG/datasystem_worker.INFO.log
# 心跳超时
grep 'Cannot receive heartbeat' $LOG/datasystem_worker.INFO.log
# 网络连通性
ping <peer_ip>
```

```
code=23 K_CLIENT_WORKER_DISCONNECT
  │ 错误消息: "Client and Worker disconnect"
  │ 代码: listen_worker.cpp:114（心跳超时）
  │
  ├─ 对端进程不存在
  │   └─→ 【数据系统】Worker崩溃
  │       证据: grep 'Worker is exiting' $LOG/datasystem_worker.INFO.log
  │
  ├─ 对端存活 + ping不通
  │   └─→ 【OS/网络】防火墙/路由
  │       处置: iptables -L -n
  │
  └─ 对端存活 + ping通
      └─→ 【OS/网络】对端负载高/网络抖
          证据: grep 'Cannot receive heartbeat' $LOG/datasystem_worker.INFO.log
          查: grep 'WAITING_TASK_NUM' $LOG/resource.log
          查: ping -c 100 <peer_ip>
```

---

### code=1001 — K_RPC_DEADLINE_EXCEEDED

**查看命令**：
```bash
# ZMQ failure delta
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
# 对端状态
ssh <peer_ip> "pgrep -af datasystem_worker"
# 主动拒绝
grep 'RPC_SERVICE_UNAVAILABLE' $LOG/datasystem_worker.INFO.log
```

```
code=1001 K_RPC_DEADLINE_EXCEEDED
  │ 错误消息: "RPC deadline exceeded"
  │ 代码: zmq_service.cpp:724（remainingTime<=0，服务端deadline到期）
  │
  ├─ 日志含"[RPC_SERVICE_UNAVAILABLE]"
  │   └─→ 【数据系统】对端拒绝服务
  │       证据: grep 'RPC_SERVICE_UNAVAILABLE' $LOG/datasystem_worker.INFO.log
  │
  ├─ ZMQ failure delta=0 + 对端存活
  │   └─→ 【数据系统】对端处理慢
  │       查: grep 'WAITING_TASK_NUM' $LOG/resource.log
  │
  └─ ZMQ failure delta>0 或对端不在
      └─→ 【OS/网络】网络问题
          查: grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log
```

---

### code=1002 — K_RPC_UNAVAILABLE

**查看命令**：
```bash
# Worker退出
grep 'Worker is exiting' $LOG/datasystem_worker.INFO.log
# TLS握手
grep 'zmq_event_handshake_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
# etcd
grep 'etcd is' $LOG/datasystem_worker.INFO.log
# TCP连接
grep -E '\[TCP_CONNECT_FAILED\]|\[TCP_CONNECT_RESET\]' $LOG/datasystem_worker.INFO.log
# ZMQ failure delta
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log | tail -3
# 对端状态
ssh <peer_ip> "pgrep -af datasystem_worker"
```

```
code=1002 K_RPC_UNAVAILABLE
  │ 错误消息: "RPC unavailable"
  │ 代码: zmq_socket_ref.cpp:175,211（ZMQ send/recv真失败）
  │
  ├─ 对端进程不存在
  │   └─→ 【数据系统】Worker崩溃
  │       证据: grep 'Worker is exiting' $LOG/datasystem_worker.INFO.log
  │
  ├─ 日志含"[RPC_SERVICE_UNAVAILABLE]"
  │   └─→ 【数据系统】对端主动拒绝
  │
  ├─ 日志含"zmq_event_handshake_failure_total"↑
  │   └─→ 【数据系统】TLS/证书问题
  │       证据: grep 'zmq_event_handshake_failure_total' $LOG/datasystem_worker.INFO.log
  │
  ├─ 日志含"etcd is ..."
  │   └─→ 【etcd】
  │       处置: etcdctl endpoint status -w table
  │
  ├─ 日志含"[TCP_CONNECT_FAILED]" + 对端存活
  │   └─→ 【OS/网络】防火墙/端口
  │       处置: ss -tnlp | grep <port>
  │       处置: iptables -L -n
  │
  ├─ 日志含"[TCP_CONNECT_RESET]" / "[TCP_NETWORK_UNREACHABLE]"
  │   └─→ 【OS/网络】网络闪断
  │       处置: dmesg | tail -50
  │
  ├─ 日志含"[UDS_CONNECT_FAILED]"
  │   └─→ 【OS/网络】UDS路径/权限问题
  │
  ├─ 日志含"[SHM_FD_TRANSFER_FAILED]"
  │   └─→ 【OS】fd耗尽/权限
  │       处置: ulimit -n
  │
  ├─ ZMQ failure delta>0
  │   └─→ 【OS/网络】按errno表细分
  │       证据: grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log
  │
  └─ ZMQ failure delta=0 + 对端存活
      └─→ 【数据系统】对端处理慢/拒绝
          查: grep 'WAITING_TASK_NUM' $LOG/resource.log
```

---

### code=1006 — K_URMA_NEED_CONNECT

**查看命令**：
```bash
grep -E '\[URMA_NEED_CONNECT\]|\[URMA_POLL_ERROR\]' $LOG/datasystem_worker.INFO.log
```

```
code=1006 K_URMA_NEED_CONNECT
  │ 错误消息: "Urma needs to reconnet"
  │
  ├─ remoteInstanceId变化
  │   └─→ 【数据系统】对端Worker重启（正常）─ SDK自重连
  │       证据: grep 'URMA_NEED_CONNECT' $LOG/datasystem_worker.INFO.log
  │
  ├─ instanceId不变 + 连接断开
  │   └─→ 【URMA】连接断开需重建
  │       证据: grep 'URMA_NEED_CONNECT' $LOG/datasystem_worker.INFO.log
  │
  └─ instanceId不变 + 持续出现 + [URMA_POLL_ERROR]并存
      └─→ 【URMA】UB链路不稳
          证据: grep -E 'URMA_NEED_CONNECT|URMA_POLL_ERROR' $LOG/datasystem_worker.INFO.log
          查: ifconfig ub0
```

---

### code=1008 — K_URMA_TRY_AGAIN

**查看命令**：
```bash
grep -E '\[URMA_RECREATE_JFS\]|\[URMA_RECREATE_JFS_FAILED\]|\[URMA_RECREATE_JFS_SKIP\]' $LOG/datasystem_worker.INFO.log
```

```
code=1008 K_URMA_TRY_AGAIN
  │ 错误消息: "Urma operation failed, try again"
  │
  ├─ [URMA_RECREATE_JFS] + cqeStatus=9(ACK TIMEOUT)
  │   └─→ 自动重建中（继续观察是否有FAILED）
  │
  ├─ [URMA_RECREATE_JFS_FAILED]连续
  │   └─→ 【URMA】JFS重建失败
  │       证据: grep 'URMA_RECREATE_JFS_FAILED' $LOG/datasystem_worker.INFO.log
  │
  ├─ [URMA_RECREATE_JFS_SKIP]
  │   └─→ 连接过期跳过，正常 ── 无需处置
  │
  └─ 无FAILED（仅有[URMA_RECREATE_JFS]）
      └─→ 自愈（无需处置）
```

---

## OS/ZMQ/URMA 日志关键字

### OS/ZMQ 日志关键字

| 日志关键字 | 错误消息 | errno/ret | 责任方 |
|------------|----------|-----------|--------|
| `[TCP_CONNECT_FAILED]` | TCP connect failed | errno | OS/网络 |
| `[TCP_CONNECT_RESET]` | Connect reset | errno | OS/网络 |
| `[TCP_NETWORK_UNREACHABLE]` | Network unreachable | - | OS/网络 |
| `[UDS_CONNECT_FAILED]` | UDS connect failed | - | OS/网络 |
| `[SHM_FD_TRANSFER_FAILED]` | SHM fd transfer failed | - | OS |
| `[ZMQ_SEND_FAILURE_TOTAL]` | ZMQ send failed | errno | OS/网络 |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | ZMQ recv failed | errno | OS/网络 |
| `[ZMQ_RECV_TIMEOUT]` | ZMQ recv timeout | - | 数据系统 |
| `[RPC_RECV_TIMEOUT]` | RPC recv timeout | - | 数据系统/OS |
| `[RPC_SERVICE_UNAVAILABLE]` | Service unavailable | - | 数据系统 |
| `[SOCK_CONN_WAIT_TIMEOUT]` | Sock conn wait timeout | - | OS/网络 |
| `zmq_event_handshake_failure_total`↑ | TLS handshake failed | - | 数据系统 |

### URMA 日志关键字

| 日志关键字 | 错误消息 | errno/ret | 责任方 |
|------------|----------|-----------|--------|
| `[URMA_NEED_CONNECT]` | Urma needs to reconnet | remoteInstanceId/instanceId | 数据系统/URMA |
| `[URMA_POLL_ERROR]` | PollJfcWait failed | ret | URMA |
| `[URMA_WAIT_TIMEOUT]` | timedout waiting for request | requestId | 数据系统 |
| `[URMA_RECREATE_JFS]` | JFS recreating | cqeStatus=9 | URMA |
| `[URMA_RECREATE_JFS_FAILED]` | JFS recreate failed | ret | URMA |
| `[URMA_RECREATE_JFS_SKIP]` | JFS skip (connection expired) | - | 正常 |
| `fallback to TCP/IP payload` | UB降级TCP | - | URMA |

### OS 系统错误（dmesg/ulimit/df）

| 系统调用 | 错误消息 | errno | 责任方 |
|----------|----------|-------|--------|
| mlock/mlockall | Get mmap entry failed | ENOMEM | OS |
| open/creat | No space available | ENOSPC | OS |
| open/accept | Limit on file descriptors reached | EMFILE/ENFILE | OS |
| read/write | IO error | EIO | OS |

---

## ZMQ failure 判断（核心定界）

**查看**：
```bash
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_receive_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
```

**代码逻辑**（`zmq_socket_ref.cpp`）：
```
ZMQ send/recv 返回-1时：
  errno == EAGAIN  → K_TRY_AGAIN（背压，非故障）
                     → zmq_send/receive_try_again_total++
  errno == EINTR   → K_INTERRUPTED
  其他 errno       → K_RPC_UNAVAILABLE
                     → zmq_send/receive_failure_total++
                     → zmq_last_error_number = errno
                     → 网络errno → zmq_network_error_total++
```

**网络类errno**（`IsZmqSocketNetworkErrno`）：
ECONNREFUSED / ECONNRESET / ECONNABORTED / EHOSTUNREACH / ENETUNREACH / ENETDOWN / ETIMEDOUT / EPIPE / ENOTCONN

| 判断 | 结论 |
|------|------|
| delta=0 | 无ZMQ层I/O失败 → 对端慢/数据系统 |
| delta>0 | 有ZMQ层I/O失败 → 网络/OS |

---

## errno 参考

| errno | 枚举 | 含义 | 典型原因 |
|-------|------|------|----------|
| 11 | EAGAIN/EWOULDBLOCK | 背压 | 对方缓冲区满（非错） |
| 101 | ENETUNREACH | 路由不可达 | 路由配置 |
| 104 | ECONNRESET | 对端reset | 对端崩溃/网络闪断 |
| 110 | ETIMEDOUT | TCP超时 | 网络慢/防火墙丢包 |
| 111 | ECONNREFUSED | 端口无监听 | Worker未启动/端口未开 |
| 113 | EHOSTUNREACH | 主机不可达 | 主机层面网络不通 |

---

## 快速定界

### 第一步：抓错误码分布

```bash
grep "DS_KV_CLIENT_PUT" $LOG/ds_client_access_*.log | awk -F'|' '{print $1}' | sort | uniq -c
grep "DS_KV_CLIENT_GET" $LOG/ds_client_access_*.log | awk -F'|' '{print $1}' | sort | uniq -c
```

### 第二步：直接出结论

| 错误码 | 枚举 | 错误消息 | 责任方 | 证据/日志 |
|--------|------|----------|--------|-----------|
| 0 | K_OK | OK | 用户 | respMsg含"NOT_FOUND" |
| 2 | K_INVALID | Invalid parameter | 用户 | 空key/大小为0 |
| 3 | K_NOT_FOUND | Key not found | 用户 | Get时 |
| 6 | K_OUT_OF_MEMORY | Out of memory | OS | `dmesg\|grep -i oom` |
| 7 | K_IO_ERROR | IO error | OS | `dmesg`/磁盘smart |
| 8 | K_NOT_READY | Not ready | 用户 | 未Init |
| 13 | K_NO_SPACE | No space available | OS | `df -h` |
| 18 | K_FILE_LIMIT_REACHED | Limit on file descriptors reached | OS | `ulimit -n` |
| 25 | K_MASTER_TIMEOUT | The master may timeout/dead | etcd | `etcdctl endpoint status` |
| 29 | K_SERVER_FD_CLOSED | The server fd has been closed | 数据系统 | 返回时转为K_TRY_AGAIN |
| 31 | K_SCALE_DOWN | The worker is exiting | 数据系统 | SDK自重试 |
| 1004 | K_URMA_ERROR | Urma operation failed | URMA | `dmesg\|grep ub`/`ibstat`；ret=%d |
| 1009 | K_URMA_CONNECT_FAILED | Urma connect failed | URMA | `ifconfig ub0` |
| 1010 | K_URMA_WAIT_TIMEOUT | Urma wait for completion timed out | 数据系统 | 无需处置 |

> 注：K_SCALING(32)为内部码，不出现在access log中

---

## 归责总览

| 责任方 | 判断依据 |
|--------|----------|
| **数据系统** | fault delta=0+对端在运行 / 主动拒绝 / Worker崩溃退出 / TLS握手失败 |
| **OS/网络** | fault delta>0 / ping不通 / 防火墙 / TCP reset / UDS失败 |
| **用户** | code=0(respMsg异常)/2/3/8 |
| **URMA** | code=1004/1006/1008/1009/1010 / fallback to TCP |
| **etcd** | code=25 / 日志含"etcd is ..." |

---

## 日志位置

| 类型 | 路径 |
|------|------|
| 接口错误码 | `$LOG/ds_client_access_*.log` |
| ZMQ指标/错误 | `$LOG/datasystem_worker.INFO.log` |
| URMA日志 | `$LOG/*.INFO.log` 含`[URMA_]` |
