# 12.2 KVCache中断异常

## 一、故障现象

- 客户侧SDK成功率 < 90%
- 客户KVC Worker成功率 < 90%

## 二、故障排查

### 步骤1：确认成功率聚集服务器

**操作**：查看司南平台和DongMonitor平台，筛选成功率异常的Pod IP分布

**判断**：
- 如果集中在个别服务器上 → 进入该服务器，通过步骤2排查
- 如果分布广泛 → 挑选报错服务器进行排查

---

### 步骤2：查看KVCache故障日志

**操作**：查看行云平台/日志平台，执行以下命令查看接口返回错误码

```bash
grep "DS_KV_CLIENT_PUT" $LOG/ds_client_access_*.log | awk -F'|' '{print $1}' | sort | uniq -c
grep "DS_KV_CLIENT_GET" $LOG/ds_client_access_*.log | awk -F'|' '{print $1}' | sort | uniq -c
```

---

### 1.1 Client返回错误码定界

| 错误码 | 枚举 | 责任边界主体 | 责任组织 | 定位方法 |
|--------|------|--------------|----------|----------|
| 0 | `K_OK` | 客户业务 | - | Get查不到时需看respMsg |
| 2 | `K_INVALID` | 客户业务 | 客户业务 | 业务校验失败 |
| 3 | `K_NOT_FOUND` | 客户业务 | 客户业务 | 对象不存在 |
| 5 | `K_RUNTIME_ERROR` | OS/三方/URMA | 按日志细分 | 见1.2 |
| 6 | `K_OUT_OF_MEMORY` | OS | 客户运维 | 内存不足 |
| 7 | `K_IO_ERROR` | OS | 客户运维 | IO错误 |
| 8 | `K_NOT_READY` | 客户系统 | 客户业务 | 未初始化 |
| 13 | `K_NO_SPACE` | OS | 客户运维 | 磁盘满 |
| 18 | `K_FILE_LIMIT_REACHED` | OS | 客户运维 | fd耗尽 |
| **19** | **`K_TRY_AGAIN`** | **元戎数据系统/OS** | **按日志细分** | **见1.3** |
| **23** | **`K_CLIENT_WORKER_DISCONNECT`** | **元戎数据系统/OS/机器** | **按日志细分** | **见1.4** |
| 25 | `K_MASTER_TIMEOUT` | etcd三方 | 客户运维 | etcd超时 |
| 29 | `K_SERVER_FD_CLOSED` | 元戎数据系统 | 分布式并行实验室 | Worker退出 |
| 31 | `K_SCALE_DOWN` | 元戎数据系统 | 分布式并行实验室 | 缩容中 |
| 32 | `K_SCALING` | 元戎数据系统 | 分布式并行实验室 | 扩容中 |
| **1001** | **`K_RPC_DEADLINE_EXCEEDED`** | **数据系统/OS/三方** | **按日志细分** | **见1.5** |
| **1002** | **`K_RPC_UNAVAILABLE`** | **数据系统/OS/三方** | **按日志细分** | **见1.6** |
| 1004 | `K_URMA_ERROR` | URMA | 分布式并行实验室/海思 | URMA错误 |
| 1006 | `K_URMA_NEED_CONNECT` | URMA | 分布式并行实验室/海思 | 连接需要重建 |
| 1008 | `K_URMA_TRY_AGAIN` | URMA | 分布式并行实验室/海思 | URMA重试 |
| 1009 | `K_URMA_CONNECT_FAILED` | URMA | 海思 | 连接失败 |
| 1010 | `K_URMA_WAIT_TIMEOUT` | URMA | 分布式并行实验室 | 等待超时 |

---

### 1.2 接口错误码为：5（K_RUNTIME_ERROR）

**操作**：

```bash
grep -E 'K_RUNTIME_ERROR|Get mmap entry failed|etcd is|urma' $LOG/datasystem_worker.INFO.log | tail -50
```

**错误信息定界**：

| 错误信息 | 代码路径 | 责任边界 | 责任组织 | 解决措施 |
|----------|----------|----------|----------|----------|
| `Get mmap entry failed` | 共享内存映射失败 | OS | 客户运维 | 检查mlock限制：`ulimit -l unlimited` |
| `etcd is timeout/unavailable` | etcd访问超时/不可达 | etcd三方 | 客户运维 | 检查etcd集群状态：`etcdctl endpoint status` |
| `urma ... payload ...` | URMA数据传输失败 | URMA | 分布式并行实验室/海思 | 检查UB端口和驱动 |

---

### 1.3 接口错误码为：19（K_TRY_AGAIN）

> **根因**：RPC处理慢或瞬时繁忙，需要重试

**代码路径**：
- `src/datasystem/common/rpc/zmq/zmq_stub_impl.cpp`：RPC接收超时返回K_TRY_AGAIN
- `src/datasystem/common/rpc/zmq/zmq_msg_queue.h`：消息队列处理超时

**操作**：

```bash
# 查看ZMQ故障统计
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_receive_failure_total' $LOG/datasystem_worker.INFO.log | tail -3

# 检查对端是否存活
ping <peer_ip>
ssh <peer_ip> "pgrep -af datasystem_worker"
ss -tnlp | grep <worker_port>
```

**错误日志定界**：

| 故障信息 | 代码位置 | 问题定位 | 责任组织 | 定界依据 | 解决措施 |
|----------|----------|----------|----------|----------|----------|
| `[RPC_RECV_TIMEOUT]` + `fault=0` | `zmq_stub_impl.cpp:574` | 对端处理慢 | **元戎数据系统** | 网络正常但对端不响应 | 检查对端CPU/锁/线程池 |
| `[RPC_RECV_TIMEOUT]` + `fault>0` | `zmq_msg_queue.h:890` | 网络问题 | 客户运维/网络 | 网络丢包/断开 | 检查网络链路 |
| `[ZMQ_SEND_FAILURE_TOTAL]` + 对端存活 | `zmq_socket.cpp` | 网络故障 | 客户运维/网络 | 网络故障但对端存活 | 检查防火墙/路由 |
| `[ZMQ_RECV_TIMEOUT]` | `zmq_msg_queue.h:889` | 接收超时 | 按fault值判断 | 同上 | 同上 |

---

### 1.4 接口错误码为：23（K_CLIENT_WORKER_DISCONNECT）

> **根因**：Client与Worker之间连接断开

**代码路径**：
- `src/datasystem/client/listen_worker.cpp`：心跳超时返回K_CLIENT_WORKER_DISCONNECT
- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`：连接断开检测

**操作**：

```bash
# 检查对端是否存活
ping <peer_ip>
ssh <peer_ip> "pgrep -af datasystem_worker"

# 检查心跳相关日志
grep 'Cannot receive heartbeat' $LOG/datasystem_worker.INFO.log | tail -20
grep 'HealthCheck' $LOG/datasystem_worker.INFO.log | tail -20

# 检查Worker是否正常退出
grep 'Worker is exiting' $LOG/datasystem_worker.INFO.log | tail -20
```

**错误日志定界**：

| 故障信息 | 代码位置 | 对端状态 | 问题定位 | 责任组织 | 解决措施 |
|----------|----------|----------|----------|----------|----------|
| `[TCP_CONNECT_FAILED]` + 对端不在 | `zmq_stub_conn.cpp` | Worker已退出 | Worker崩溃/重启 | **元戎数据系统** | 检查Worker崩溃原因 |
| `[TCP_CONNECT_FAILED]` + 对端存活 | `zmq_stub_conn.cpp` | 端口不通/防火墙 | 客户运维/网络 | 检查防火墙规则 |
| `Cannot receive heartbeat` | `listen_worker.cpp` | 心跳超时 | 对端负载高/网络抖 | 按对端状态判断 | 检查对端资源/网络 |
| `[HealthCheck] Worker is exiting` | Worker生命周期 | Worker主动退出 | 分布式并行实验室 | 检查编排/扩缩容 | 正常流程 |

**定界决策树**：
```
K_CLIENT_WORKER_DISCONNECT (23)
     │
     ├── 对端不在（进程消失）→ 【元戎数据系统】检查Worker崩溃
     │
     ├── 对端存活 + ping不通 → 【客户运维】检查网络/防火墙
     │
     └── 对端存活 + 心跳超时 → 检查对端资源/网络稳定性
```

---

### 1.5 接口错误码为：1001（K_RPC_DEADLINE_EXCEEDED）

> **根因**：RPC处理超时

**代码路径**：
- `src/datasystem/common/rpc/zmq/zmq_stub_impl.cpp:201`：RPC响应超时
- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp:574`：ZMQ接收超时

**操作**：

```bash
# 查看ZMQ故障统计
grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log | tail -3
grep 'zmq_send_failure_total' $LOG/datasystem_worker.INFO.log | tail -3

# 检查对端是否在运行
pgrep -af datasystem_worker
ss -tnlp | grep <worker_port>

# 检查是否是主动拒绝
grep 'RPC_SERVICE_UNAVAILABLE' $LOG/datasystem_worker.INFO.log | tail -20
```

**错误日志定界**：

| 故障信息 | 代码位置 | 问题定位 | 责任组织 | 定界依据 | 解决措施 |
|----------|----------|----------|----------|----------|----------|
| `[RPC_SERVICE_UNAVAILABLE]` | `zmq_stub_conn.cpp:224` | 对端主动拒绝 | **元戎数据系统** | 服务不可用 | 检查对端Worker状态 |
| `[RPC_RECV_TIMEOUT]` + `fault=0` | `zmq_stub_impl.cpp:201` | 对端处理慢 | **元戎数据系统** | 网络正常但超时 | 检查对端CPU/锁/线程池 |
| `[RPC_RECV_TIMEOUT]` + `fault>0` | `zmq_msg_queue.h:890` | 网络导致超时 | 客户运维/网络 | 网络丢包/延迟 | 检查网络链路 |
| `[TCP_CONNECT_TIMEOUT]` | `zmq_socket.cpp` | TCP建连超时 | 客户运维/网络 | 网络连接建立失败 | 检查防火墙/路由 |

**定界决策树**：
```
K_RPC_DEADLINE_EXCEEDED (1001)
     │
     ├── [RPC_SERVICE_UNAVAILABLE] → 【元戎数据系统】对端拒绝服务
     │
     ├── fault=0 + 对端在运行 → 【元戎数据系统】对端处理慢
     │
     └── fault>0 或对端不在 → 【客户运维/网络】检查网络
```

---

### 1.6 接口错误码为：1002（K_RPC_UNAVAILABLE）

> **根因**：RPC服务不可用

**代码路径**：
- `src/datasystem/common/rpc/zmq/zmq_stub_impl.cpp:201`：ZMQ连接/接收失败
- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`：多种RPC错误

**操作**：

```bash
# 1. 检查对端是否存活
ping <peer_ip>
ssh <peer_ip> "pgrep -af datasystem_worker"
ss -tnlp | grep <worker_port>

# 2. 查看ZMQ错误码
grep 'zmq_last_error_number' $LOG/datasystem_worker.INFO.log | tail -3

# 3. 检查TLS/认证问题
grep 'zmq_event_handshake_failure_total' $LOG/datasystem_worker.INFO.log | tail -3

# 4. 检查是否是etcd问题
grep 'etcd is timeout\|etcd is unavailable' $LOG/datasystem_worker.INFO.log | tail -20
```

**zmq_last_error_number → errno对照**：

| N | errno | 典型含义 |
|----|-------|----------|
| 11 | EAGAIN/EWOULDBLOCK | 背压（非错） |
| 101 | ENETUNREACH | 路由不可达 |
| 104 | ECONNRESET | 对端reset |
| 110 | ETIMEDOUT | TCP超时 |
| 111 | ECONNREFUSED | 端口无监听 |
| 113 | EHOSTUNREACH | 主机不可达 |

**错误日志定界**：

| 故障信息 | 代码位置 | 对端状态 | 问题定位 | 责任组织 | 解决措施 |
|----------|----------|----------|----------|----------|----------|
| `[TCP_CONNECT_FAILED]` | `zmq_socket.cpp` | 不在 | Worker重启/崩溃 | **元戎数据系统** | 检查对端为何退出 |
| `[TCP_CONNECT_FAILED]` | `zmq_socket.cpp` | 存活 | 端口不通/防火墙 | 客户运维/网络 | 检查iptables/端口 |
| `[TCP_CONNECT_RESET]` | `zmq_socket.cpp` | - | 网络闪断 | 客户运维/网络 | 检查网络稳定性 |
| `[UDS_CONNECT_FAILED]` | `unix_sock_fd.cpp` | - | UDS路径/权限问题 | 客户运维 | 检查UDS配置 |
| `[SHM_FD_TRANSFER_FAILED]` | `zmq_socket.cpp` | - | fd耗尽/权限问题 | 客户运维 | 检查fd限制 |
| `[ZMQ_SEND_FAILURE_TOTAL]` + `zmq_last_error_number=N` | `zmq_socket.cpp` | - | 按errno细分 | 客户运维/网络 | 对照errno表排查 |
| `zmq_event_handshake_failure_total`↑ | `zmq_socket.cpp` | - | TLS/认证问题 | **元戎数据系统** | 检查证书配置 |
| `etcd is timeout/unavailable` | `etcd_cluster_manager.cpp` | - | etcd问题 | 客户运维 | 检查etcd集群 |
| fault=0 + 对端在运行 | - | - | 对端处理慢/拒绝 | **元戎数据系统** | 检查对端资源 |

**定界决策树**：
```
K_RPC_UNAVAILABLE (1002)
     │
     ├── 对端不在 → 【元戎数据系统】对端崩溃/重启
     │
     ├── 对端存活 + fault>0 → 【客户运维/网络】检查网络
     │
     ├── 对端存活 + fault=0 → 【元戎数据系统】对端处理慢/拒绝
     │
     └── etcd相关 → 【客户运维】检查etcd
```

---

## 三、归责速查

| 责任主体 | 归属 | 判断依据 |
|----------|------|----------|
| **元戎数据系统** | 分布式并行实验室 | fault=0+对端在运行 / Worker崩溃/主动拒绝 |
| **客户运维/网络** | 客户运维 | fault>0 / ping不通 / iptables / tc |
| **客户运维** | 客户运维 | etcd超时 / 磁盘满 / fd耗尽 / 内存 |
| **URMA** | 分布式并行实验室/海思 | URMA相关错误码1004/1006/1008/1009/1010 |

---

## 四、日志位置速查

| 日志类型 | 文件位置 | 说明 |
|----------|----------|------|
| Client access日志 | `ds_client_access_*.log` | 接口访问日志，含错误码 |
| Worker运行日志 | `datasystem_worker.INFO.log` | 结构化错误日志 |
| ZMQ指标 | `datasystem_worker.INFO.log` | ZMQ故障统计 |

---

## 五、Metric速查

### ZMQ故障监控

| 数据字段 | 名称 | 单位 | 指标说明 | 判定方法 | 解决措施 |
|----------|------|------|----------|----------|----------|
| `zmq_send_failure_total` | ZMQ发送失败次数 | count | ZMQ发送失败累计次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_receive_failure_total` | ZMQ接收失败次数 | count | ZMQ接收失败累计次数 | delta>0表示网络/连接故障 | 检查网络和防火墙 |
| `zmq_last_error_number` | ZMQ最后错误码 | - | errno对照码 | N值对照errno表 | 按errno处理 |
| `zmq_event_handshake_failure_total` | TLS握手失败次数 | count | TLS/认证握手失败 | delta>0 | 检查证书配置 |
