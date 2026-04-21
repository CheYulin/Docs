# 08 · KV 故障定位定界手册（通断 × 时延）

> **谁用**：值班 / 运维 / 测试 / 研发现场排障。
> **怎么用**：接口日志看**成功率** / **P99** → **§2** 30 秒分类 → **§3 / §4** 1–3 分钟定界 → **§5** 出工单。
> **怎么判**：五边界 — **用户 / DS 进程内 / 三方(etcd 等) / URMA / OS**。凭据均与 `yuanrong-datasystem` 主干行为对齐；代码细节、全量 metric / 标签 / 注入矩阵见附录。

---

## 一、从接口日志切入

### 1.1 Access Log 字段

```
code | handleName | microseconds | dataSize | reqMsg | respMsg
  ↑      ↑            ↑            ↑         ↑         ↑
 错误码  接口名        耗时(μs)     数据大小   请求参数   响应信息
```

- **成功率 / 通断** → `code`：`awk -F'|' '{print $1}' $LOG/ds_client_access_*.log | sort | uniq -c`
- **时延 / P99** → `microseconds`：脚本或平台聚合 P99 / max 或对比基线
- **注意陷阱**：`K_NOT_FOUND` 在 access log 会被记成 **`code=0`**；业务「查不到」场景需同时看 `respMsg` 是否含 `NOT_FOUND` / `Can't find object`，不能只数非 0。

### 1.2 日志体系全景

| # | 类型 | 路径 | 用途 |
|---|------|------|------|
| 1 | Worker 运行 | `$log_dir/datasystem_worker.INFO.log` | ERROR/WARN/INFO 文本 + 结构化 `[PREFIX]` |
| 2 | Worker access | `$log_dir/access.log` | POSIX 接口访问（需 `log_monitor=true`） |
| 3 | **Worker 资源** | `$log_dir/resource.log` | 周期聚合资源 / 线程池 / `ETCD_*` / `OC_HIT_NUM` |
| 4 | 三方请求 | `$log_dir/request_out.log` | Worker 访问 **etcd** 轨迹 |
| 5 | Client 运行 | `$log_dir/ds_client_<pid>.INFO.log` | SDK 运行日志 |
| 6 | **Client access** | `$log_dir/ds_client_access_<pid>.log` | **首要观测面**（§1.1） |

### 1.3 Metrics Summary 格式

```
Metrics Summary, version=v0, cycle=<N>, interval=<intervalMs>ms

Total:
  <metric>=<value>

Compare with <intervalMs>ms before:
  <metric>=+<delta>                    ← Counter
  <metric>,count=+<N>,avg=<us>,max=<us> ← Histogram
```

读法：**先看 `cycle` 连续性** → **再看 `Compare with` delta 段** → **Histogram 看 `max`**（时延定界核心）。

### 1.4 两类故障分流

| 现象 | 走这一章 |
|------|---------|
| 接口大量失败、`code` 非 0 明显增多、进程挂、连接断 | **§3 通断** |
| `code` 多为 0 但 **P99↑**、`microseconds` 右移、抖动 | **§4 时延** |

---

## 二、五边界速记（30 秒分类）

### 2.1 故障处理路线图

```
       现象（成功率↓ / P99↑ / 抖动）
                  │
                  ▼
┌─ 用户（User） ────────────────────────────────┐
│  code ∈ {2,3,8}；code=0 + respMsg 异常          │
│  → §3.5.1 respMsg 表                           │
└─────────────────────────────────────────────┘
                  │
                  ▼
┌─ DS 进程内（Worker/Master/SDK） ──────────────┐
│  code ∈ {19,23,29,31,32}；[RPC_*] / [ZMQ 事件]  │
│  线程池 WAITING_TASK_NUM 打满                   │
│  → §3.5.2 子场景 (a)~(d)                       │
└─────────────────────────────────────────────┘
                  │
                  ▼
┌─ 三方（etcd） ──────────────────────────────┐
│  code=25；`etcd is timeout/unavailable`        │
│  ETCD_QUEUE↑；ETCD_REQUEST_SUCCESS_RATE↓       │
│  → §3.5.2(c) 主责**写三方**                    │
│  注：分布式网盘经 POSIX File 接口访问，        │
│      故障归 OS（§3.5.4 文件 I/O）              │
└─────────────────────────────────────────────┘
                  │
                  ▼
┌─ URMA ─────────────────────────────────────┐
│  code ∈ {1004,1006,1008,1009,1010}            │
│  [URMA_*]；fallback to TCP/IP payload         │
│  → §3.5.3 / §4.5                              │
└─────────────────────────────────────────────┘
                  │
                  ▼
┌─ OS 与环境 ────────────────────────────────┐
│  code ∈ {5(mmap),6,7,13,18}                  │
│  [TCP_*] + 对端仍活；[UDS_*]                 │
│  [SHM_FD_TRANSFER_FAILED]（同机 UDS/SCM_RIGHTS）│
│  [ZMQ_*_FAILURE_TOTAL] + errno              │
│  → §3.5.4 / §4.5                              │
└─────────────────────────────────────────────┘
```

### 2.2 错误码 → 边界总表

| 错误码 | 枚举 | 主责边界 | 备注 |
|-------|------|---------|------|
| 0 | `K_OK` | **用户** | 业务正常；**备注**：Get 查不到 key 时 `K_NOT_FOUND` 会被记成 `code=0`，要看 `respMsg` |
| 2 / 3 / 8 | `K_INVALID` / `K_NOT_FOUND` / `K_NOT_READY` | **用户** | 业务参数 / Init 顺序 |
| 5 | `K_RUNTIME_ERROR` | **OS / 三方 / URMA** | mmap→OS；`etcd is ...`→三方；payload→URMA |
| 6 / 7 / 13 / 18 | `K_OUT_OF_MEMORY` / `K_IO_ERROR` / `K_NO_SPACE` / `K_FILE_LIMIT_REACHED` | **OS** | 内存 / IO / 磁盘 / fd |
| 19 | `K_TRY_AGAIN` | **DS / OS** | 结合前缀；瞬时繁忙 |
| 23 | `K_CLIENT_WORKER_DISCONNECT` | **DS / OS / 机器** | 先确认进程与节点 |
| 25 | `K_MASTER_TIMEOUT` | **三方(etcd)** | 兼查 Master 与网络 |
| 29 / 31 / 32 | `K_SERVER_FD_CLOSED` / `K_SCALE_DOWN` / `K_SCALING` | **DS 进程内** | 生命周期 / 扩缩容 |
| 1001 / 1002 | `K_RPC_DEADLINE_EXCEEDED` / `K_RPC_UNAVAILABLE` | **DS / OS / 三方** | 桶码；必看日志前缀（§3.3） |
| 1004 / 1006 / 1008 / 1009 / 1010 | `K_URMA_*` | **URMA** | UB 硬件 / 驱动 / 链路 |

> ⚠️ **1002 是桶码**：DS crash、OS 网络断、etcd 不可用都会给 1002，必须看 §3.3 前缀。
> ⚠️ **0 ≠ 一切正常**：Get 的 NOT_FOUND 被记成 0，业务语义异常看 `respMsg`。

### 2.3 五边界典型信号

| 边界 | 典型信号 | 核心凭据 |
|------|---------|---------|
| **用户** | code ∈ {2,3,8}；code=0 + `respMsg` 异常 | access log 的 `respMsg` |
| **DS 进程内** | code ∈ {23,29,31,32}；`[RPC_RECV_TIMEOUT]` + ZMQ fault=0；`[RPC_SERVICE_UNAVAILABLE]`；`zmq_gateway_recreate/event_disconnect`↑；线程池 `WAITING_TASK_NUM` 堆积 | Worker/Client INFO log、`resource.log` |
| **三方 etcd** | `etcd is timeout` / `etcd is unavailable`；`ETCD_QUEUE` 堆积、`ETCD_REQUEST_SUCCESS_RATE`↓；code=25 | `grep etcd`、`etcdctl endpoint status` |
| **URMA** | code ∈ {1004,1006,1008,1009,1010}；`[URMA_*]`；`fallback to TCP/IP payload` | `[URMA_*]`、`*_urma_*_bytes` |
| **OS** | code ∈ {6,7,13,18}；`K_RUNTIME_ERROR(5) + Get mmap entry failed`；`[TCP_*]` + 对端仍活；`[UDS_*]` / `[SHM_FD_TRANSFER_FAILED]`（同机 UDS / SCM_RIGHTS）；`[ZMQ_*_FAILURE_TOTAL]`（errno / 网络栈 / 资源） | `ulimit`/`ss`/`df`/`dmesg`/iptables；`zmq_last_error_number` |

---

## 三、通断定界（1 分钟）

### 3.1 定界流程

```
         access / SDK 日志 / 告警
                   │
                   ▼
    ┌──────────────────────────┐
    │ Step1  错误码树（§3.2）   │
    │ 0→respMsg；1004+→URMA    │
    │ 1001/1002→进 Step2       │
    └────────────┬─────────────┘
                 │
    ┌────────────┼────────────┐
    │ 已判边界    │ 桶码需前缀  │
    ▼            ▼            │
 直接出结论  ┌──────────────┐ │
            │ Step2  日志   │ │
            │ 前缀分流(§3.3)│ │
            └──────┬───────┘ │
                   ▼          │
            ┌──────────────┐ │
            │ Step3  交叉   │◄┘
            │ 验证(§3.4)    │
            └──────┬───────┘
                   ▼
         主责边界 → §3.5 定位
```

### 3.2 Step 1：错误码树

```
Status →
├─ 0       → 看 respMsg：NOT_FOUND/invalid → 用户；否则跳 §4
├─ 2/3/8   → 用户
├─ 5       → 按日志串细分：
│             "Get mmap entry failed" → OS
│             "etcd is timeout/unavailable" → 三方(etcd)
│             "urma ... payload ..." → URMA
├─ 6/7/13/18 → OS（内存/IO/磁盘/fd）
├─ 25        → 三方(etcd) 为主
├─ 19/23/29/31/32 → DS 进程内
├─ 1001/1002 → 进 Step 2
└─ 1004+     → URMA
```

### 3.3 Step 2：1001 / 1002 按日志前缀分流（按主责部件聚合）

**→ OS（TCP / UDS / ZMQ 系统调用层）**

| 最先出现的前缀 / 信号 | 原因 |
|---------------------|------|
| `[TCP_CONNECT_FAILED]` + 对端 Worker **活** | 端口不通 / iptables / 路由 |
| `[TCP_CONNECT_RESET]` / `[TCP_NETWORK_UNREACHABLE]` | 网络闪断（除非同窗 Worker 重启） |
| `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | 同机 UDS / SCM_RIGHTS 传 fd 失败（路径、权限、fd 限制） |
| `[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `zmq_msg_send/recv` 硬失败；按 `zmq_last_error_number` 对照 errno |

**→ 三方（etcd）**

| 最先出现的前缀 / 信号 | 原因 |
|---------------------|------|
| `etcd is timeout` / `etcd is unavailable`（常同屏 1002/25） | etcd 集群或到 etcd 的网络 |

**→ DS 进程内（Worker/Master/SDK 实现与状态）**

| 最先出现的前缀 / 信号 | 原因 |
|---------------------|------|
| `[TCP_CONNECT_FAILED]` + 对端 Worker **不在** | Worker crash / 未拉起 / 机器故障 |
| `[RPC_RECV_TIMEOUT]` + ZMQ fault=0 | 对端处理慢拖超时，非网络 |
| `[RPC_SERVICE_UNAVAILABLE]` | 对端主动拒绝（状态 / shutting down） |
| `zmq_event_handshake_failure_total` ↑ | TLS / 认证配置 |

**→ 需进一步验证**

| 前缀 / 信号 | 分叉 |
|------------|------|
| `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]` | 握手迟；看对端 Worker 存活 → 活=OS 网络慢，不活=DS |

> `zmq_last_error_number` 的 errno 对照见 §3.5.4 底部表。

### 3.4 Step 3：交叉验证

- `ping / ss / iptables`：对端 IP 可达、端口 LISTEN → 排除 OS。
- 对端 Worker INFO log 同时间窗有无受理日志：有 → 对端活；无 → 再看 `[HealthCheck] Worker is exiting now`。
- `worker_object_count` / access log 计数断崖 → Worker 重启。

### 3.5 按边界定位

#### 3.5.1 用户

| respMsg 片段 | 含义 | 处置 |
|--------------|------|------|
| `The objectKey is empty` / `dataSize should be bigger than zero` / `length not match` | 参数非法 | 业务校验 |
| `ConnectOptions was not configured` | 未配置 Init | 检查 Init |
| `Client object is already sealed` | buffer 重复 Publish | 业务逻辑 |
| `OBJECT_KEYS_MAX_SIZE_LIMIT` | 批次超限 | 拆 batch |
| `Can't find object` / `K_NOT_FOUND` | 对象不存在 | 业务自查 key |

#### 3.5.2 DS 进程内

```
             §3.2/3.3 已落到 DS 进程内
                       │
      ┌────────┬───────┼───────┬────────┐
      ▼        ▼       ▼       ▼
   RPC 超时 / ZMQ 相关  etcd /   心跳 /
   服务不可用 故障      ETCD_*  扩缩容
   fault=0   重建/断开  /25同屏 23/31/32
      │        │        │        │
      ▼        ▼        ▼        ▼
     (a)      (b)      (c)      (d)
```

| 子场景 | 证据 | 处置 |
|--------|------|------|
| **(a) 对端处理慢 / 拒绝** | `[RPC_RECV_TIMEOUT]` / `[RPC_SERVICE_UNAVAILABLE]`；ZMQ fault=0；`*_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM` 堆积 | 查 Worker CPU / 锁；扩 `oc_rpc_thread_num` |
| **(b) ZMQ 相关问题**（重建 / 断开 / 握手） | `zmq_gateway_recreate_total`↑；`zmq_event_disconnect_total`↑；`zmq_event_handshake_failure_total`↑；对端 Worker 仍活 | 低频忽略（SDK 自重连）；高频转 OS 查网络；握手失败查 TLS / 认证配置 |
| **(c) 三方 etcd** | Master `etcd is timeout`；Worker `etcd is unavailable`；`ETCD_QUEUE`↑ / 成功率↓；code=25 | **主责写三方**；`systemctl status etcd`；`etcdctl endpoint status`；查到 etcd 的网络 |
| **(d) 心跳 / 生命周期 / 扩缩容** | `Cannot receive heartbeat from worker.`(code=23)；`[HealthCheck] Worker is exiting now`；`meta_is_moving`(31/32) | 心跳断 → `kill -CONT <pid>`；退出由编排拉起；扩缩容 SDK 自重试 |

> (c) 实为三方 etcd，此处仅因信号出现在 DS 日志中一并列出；工单**主责写三方**。
> `[SHM_FD_TRANSFER_FAILED]` / `Get mmap entry failed` 归 OS（同机 UDS / `ulimit -l` / fd / SCM_RIGHTS），见 §3.5.4。

#### 3.5.3 URMA

```
              URMA 故障（code 1004+ / [URMA_*]）
                         │
        ┌────────────────┼────────────────┬──────────────┐
        ▼                ▼                ▼              ▼
  [URMA_NEED_       [URMA_RECREATE_  fallback to      [URMA_POLL_
   CONNECT]         JFS(_FAILED)]    TCP/IP payload   ERROR]
        │                │                │              │
        ▼                ▼                ▼              ▼
  (a) 会话重连       (b) JFS 异常     (c) UB 降级      (d) 驱动 / CQ
```

**基于 URMA 日志进一步定位**：

| 证据 | 含义 | 下一步定位 |
|------|------|-----------|
| `[URMA_NEED_CONNECT]` + `remoteInstanceId` 变化 | 对端 Worker 重启 | 同屏查对端 Worker 日志（`[HealthCheck]`、新 pid）；若确认重启 → 等 SDK 自重连稳定 |
| `[URMA_NEED_CONNECT]` 持续 + `instanceId` 不变 | UB 链路不稳 | 查同期是否伴 `[URMA_POLL_ERROR]` / `[URMA_RECREATE_JFS]`；两者都有 → UB 硬件 / 驱动；仅此 → UB 端口 / 交换机抖动 |
| `[URMA_RECREATE_JFS]` + `cqeStatus=9`（ACK TIMEOUT） | JFS 异常自动重建 | **继续 grep `[URMA_RECREATE_JFS_FAILED]`**：无 → 自愈成功；有且连续 → (b) 失败 |
| `[URMA_RECREATE_JFS_FAILED]` 连续出现 | JFS 重建失败 | 看 `[URMA_RECREATE_JFS_SKIP]` 是否并存（connection 已过期则属正常跳过）；否则查 UMDK / 驱动日志并上报 URMA 团队 |
| `fallback to TCP/IP payload` | URMA 已降级 TCP | 看频率与 `client_*_urma_*_bytes` / `client_*_tcp_*_bytes` delta 对比（详见 §4.5）；间歇少量 → UB 抖；持续高频 → UB 端口 down |
| `[URMA_POLL_ERROR]` | `PollJfcWait` 报错（驱动 / 硬件） | 看同期是否伴 `[URMA_WAIT_TIMEOUT]`；驱动错先 grep UMDK 日志 / `dmesg` |
| `[URMA_WAIT_TIMEOUT]`（code=1010） | 等待 CQE 超时 | 看 `instanceId` 是否同期变动（是→与 (a) 合并）；单独出现则 SDK 重试白名单自愈 |
| code=1009（`K_URMA_CONNECT_FAILED`） | URMA 建连失败 | `ifconfig ub0` / `ubinfo` 查端口 up/down；下 `ls /dev/ub*` 看设备节点 |

> `fallback to TCP/IP payload` **非通断**，功能成功 → 归 §4.5 时延侧。

#### 3.5.4 OS

```
                      OS 故障
                          │
   ┌────────┬─────────┬───┴────┬──────────┬──────────────┐
   ▼        ▼         ▼        ▼          ▼              ▼
 code=6   code=13   code=18  code=5     [TCP_*]          [ZMQ_*_
 (OOM)    (磁盘满)  (fd 满)  + mmap     /[UDS_*]          FAILURE_TOTAL]
                            / ulimit   /[SHM_FD_         errno 对照
                              -l       TRANSFER_FAILED]
   │        │         │        │          │              │
   ▼        ▼         ▼        ▼          ▼              ▼
 dmesg    df -h    /proc/fd  ulimit -l  ss -tnlp        zmq_last_
 free -h  清理 /   ulimit -n unlimited  iptables        error_number
          扩容                          UDS 路径 / 权限   对照 errno
```

**证据 × 枚举 × 处置**（DS 错误码 = `K_*`；OS errno = `<errno.h>` 标准名）：

| 证据 | DS 枚举 | OS 枚举 | 处置 |
|------|--------|--------|------|
| code=6 | `K_OUT_OF_MEMORY` | `ENOMEM` | `dmesg \| grep -i 'Out of memory'`；`free -h`；扩内存 / 调 cgroup |
| code=7 | `K_IO_ERROR` | `EIO` | `dmesg`；查块设备 / 文件系统；**分布式网盘** POSIX 接口失败同样归此 |
| code=13 | `K_NO_SPACE` | `ENOSPC` | `df -h`；`resource.log` `SPILL_HARD_DISK` / `SHARED_DISK`；清理 / 扩容（本地盘或分布式网盘挂载点） |
| code=18 | `K_FILE_LIMIT_REACHED` | `EMFILE` / `ENFILE` | `ls /proc/<pid>/fd \| wc -l` vs `ulimit -n`；调大 `ulimit -n` |
| code=5 + `Get mmap entry failed` | `K_RUNTIME_ERROR` | `ENOMEM`（mlock 限制） | `ulimit -l unlimited`；或看 `/proc/<pid>/limits` |
| `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]` | `K_RPC_UNAVAILABLE`(1002) | `ENOENT` / `EACCES` / `EPIPE` | 同机 UDS 路径 / 权限 / fd 上限；SCM_RIGHTS 发送失败多为 fd 耗尽或权限 |
| `[TCP_CONNECT_FAILED]` + 对端活 | `K_RPC_UNAVAILABLE` | `ECONNREFUSED` / `EHOSTUNREACH` | `ss -tnlp`；`iptables -L -n`；开端口 / 删规则 |
| `[TCP_CONNECT_RESET]` | `K_RPC_UNAVAILABLE` | `ECONNRESET` / `EPIPE` | `dmesg`；`netstat -s \| grep reset` |
| `[ZMQ_SEND/RECV_FAILURE_TOTAL]` + `zmq_last_error_number=N` | `K_RPC_UNAVAILABLE` | 见下表（按 N 对照 `<errno.h>`） | 对应 OS 排查 |

**`zmq_last_error_number` → OS errno**：

| N | 枚举 | 典型含义 |
|---|------|---------|
| 11 | `EAGAIN` / `EWOULDBLOCK` | 背压（非错） |
| 101 | `ENETUNREACH` | 路由不可达 |
| 104 | `ECONNRESET` | 对端 reset |
| 110 | `ETIMEDOUT` | TCP 超时 |
| 111 | `ECONNREFUSED` | 端口无监听 |
| 113 | `EHOSTUNREACH` | 主机不可达 |

---

## 四、时延定界（3 分钟）

### 4.1 定界流程

```
      接口日志 P99↑ / microseconds 变差（code 多为 0）
                       │
                       ▼
         ┌──────────────────────────┐
         │ Step1  delta 段确认劣化    │
         │ Histogram max；count=0 停 │
         └────────────┬─────────────┘
                      ▼
         ┌──────────────────────────┐
         │ Step2  client_rpc_*      │
         │   vs worker_process_*    │
         └────────────┬─────────────┘
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
   同幅飙升       Client 更慢     Worker 快/Client 慢
   → §4.4 (a-d)  → Step3 拆链路   → 用户 / SDK 本地
                      │
                      ▼
         ┌──────────────────────────┐
         │ Step3  URMA/TCP/ZMQ IO   │
         │ +fault / RTT / 丢包      │
         └────────────┬─────────────┘
                      ▼
              主责边界 → §4.5
```

### 4.2 三步要点

**Step 1**：`grep 'Compare with' $LOG/*.INFO.log` 看 delta 段；对应 Histogram `max` 相对 baseline 飙升（如 2–3×）或 P99↑ → 确认真慢。`count=+0` 则无流量，非时延。

**Step 2**：Client vs Worker

| 对比 | 结论 |
|------|------|
| `client_rpc_*_latency` max 显著 > `worker_process_*_latency` max | 中间链路慢 → Step 3 |
| 两者同幅 max 飙升 | **DS 进程内** Worker 业务慢 |
| Worker 快 / Client 慢、`worker_to_client_total_bytes` 正常 | **用户 / SDK 本地**（反序列化、用户线程阻塞） |

**Step 3**：拆中间链路

- `worker_urma_write_latency` max↑ → **URMA**。
- `worker_tcp_write_latency` max↑ + `*_urma_*_bytes` delta=0 + `fallback to TCP/IP payload` → **URMA**（UB 降级）。
- `zmq_send/receive_io_latency` max↑ + `zmq_send/receive_failure_total` 有 delta → **OS**。
- `zmq_*_io_latency` max↑ + fault=0 → 再看**框架占比**：
  - `(serialize + deserialize) / (send_io + recv_io + serialize + deserialize)`
  - **< 5%** → 中间网络或对端处理（看 `worker_process_*` 是否同幅）
  - **≥ 5%** → **DS 进程内**框架（大 payload / protobuf）
- `ping RTT 抖` / `tc qdisc` netem / `nstat` 丢包 → **OS**。

### 4.3 用户时延

- 过大 batch（接近 `OBJECT_KEYS_MAX_SIZE_LIMIT`）→ 拆。
- SDK 调用线程被业务阻塞（metrics 仍滚动但 pstack 卡在 app 代码）。
- 客户端 GC / 同步 IO。

### 4.4 DS 进程内时延

```
            同幅飙升 / Worker 侧为主
                       │
     worker_rpc_get_remote_object_latency 单独突出？
         是 ───────────────────────────► (c) 跨 Worker Get
         否
                       │
     create_meta_latency↑ 且 ETCD_* 差？
         是 ───► **三方 etcd**（对照 §3.5.2(c)）
         否
                       │
     RPC 框架占比 ≥ 5%？
         是 ───────────────────────────► (b) 序列化 / 大 payload
         否
                       │
     zmq_send_try_again↑ 且 fault=0？
         是 ───────────────────────────► (d) HWM 背压
         否
                       ▼
                 (a) 业务路径 / 线程池 / 锁 / CPU
```

| 子场景 | 证据 | 处置 |
|--------|------|------|
| **(a) Worker 业务慢** | `worker_process_*_latency` max↑；`*_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM` 堆积 | 查 CPU / 锁；扩线程池 |
| **(b) 框架 / 大 payload** | `serialize+deserialize` 占比 ≥5%；`worker_to/from_client_total_bytes` 异常大 | 拆对象 / 启 URMA 零拷贝 / Publish+Get 走 SHM |
| **(c) 跨 Worker Get** | `worker_rpc_get_remote_object_latency` max↑ | 远端也慢 → 远端业务；否则转 §4.5 |
| **(d) ZMQ 背压** | `zmq_send_try_again_total`↑ 其它 fault=0 | 加消费线程 / 降峰限流；Status 仍为 0，以 max/P99 观测 |

### 4.5 URMA / OS 时延

| 边界 | 证据 | 处置 |
|------|------|------|
| **URMA** | `worker_urma_write_latency` max↑；`*_urma_*_bytes` delta=0 + TCP 字节正常（降级）；`fallback to TCP/IP payload` 频率>0；`[URMA_NEED_CONNECT]/[URMA_RECREATE_JFS]` 间歇 | 查 UMDK / UB 端口；`ibstat \|\| ubinfo \|\| ifconfig ub0` |
| **OS** | `ping` RTT 抖；`tc qdisc` netem 残留；`nstat/ss -ti` 重传↑；`iostat/vmstat` IO wait/swap；`resource.log` `SHARED_MEMORY` 接近 `TOTAL_LIMIT` | `tc qdisc del`；`dmesg`；扩资源 |

---

## 五、结论模板

```
【故障类型】通断 / 时延
【责任边界】用户 / DS 进程内 / 三方(etcd 等) / URMA / OS（必须给其一；跨界写"主责+协查"）
【错误码】<code> <枚举> + rc.GetMsg()（时延类写 "N/A, Status=K_OK"）
【日志证据】
  - <SDK 一行，含 TraceID / 时间 / objectKey>
  - <Worker 一行，同时间窗，带 [PREFIX]>
【Metrics delta】cycle=<N>, interval=<ms>ms
  <Counter>=+<N>；<Histogram> count=+<N>, max=<val>
【根因】一句话
【处置】对应 §3.5 / §4.4 动作
【闭环验证】X 分钟后哪些信号回 baseline
```

---

## 六、实战示例

### 通断 / DS：1002 + 对端 Worker 正常
```
Step1：code=1002 → Step2
Step2：[RPC_RECV_TIMEOUT]，ZMQ fault=0 → DS 对端处理慢
Step3：resource.log 对端 WORKER_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM=128
【边界】DS 进程内（线程池打满）；扩 oc_rpc_thread_num
```

### 通断 / OS：1002 + iptables 注入
```
Step2：[ZMQ_SEND_FAILURE_TOTAL] + zmq_last_error_number=113(EHOSTUNREACH)
Step3：iptables -L -n 有 DROP
【边界】OS；iptables -D ...；zmq_send_failure_total 归零即恢复
```

### 通断 / 三方：1002 + etcd 不可用
```
Step2：Master/Worker 同时打 "etcd is timeout" / "etcd is unavailable"
       resource.log ETCD_REQUEST_SUCCESS_RATE 断崖
【边界】三方(etcd)；修 etcd 集群或到 etcd 的网络
```

### 通断 / URMA：Put 返回 1009
```
Step1：code=1009 → URMA
Step3：[URMA_NEED_CONNECT] 高频 + [URMA_RECREATE_JFS_FAILED] 连续
       ifconfig ub0 DOWN
【边界】URMA；ifconfig ub0 up
```

### 时延 / URMA：Put avg 500us→3000us，code=0
```
Step1：client_rpc_publish_latency max 飙升
Step2：worker_process_publish_latency 同幅不成立
       client_put_urma_write_total_bytes delta=0，TCP 字节 +50MB
Step3：fallback to TCP/IP payload 200/min
【边界】URMA（UB 降级）；修 UMDK / ub0
```

### 时延 / OS：框架占比低、中间链路抖
```
Step1：client_rpc_get_latency max↑，worker_process_get_latency 未变
Step2：zmq_send_io_latency max↑；serialize+deserialize 占比 ~3%
Step3：ping RTT 抖动；tc qdisc 有 netem
【边界】OS；tc qdisc del ...
```

### 通断 / DS：SHM 钉住泄漏
```
无错误码；SHARED_MEMORY 3.58GB→37.5GB
worker_shm_ref_table_bytes↑，worker_object_count 持平
worker_allocator_alloc_bytes_total delta > free delta
【边界】DS 进程内（SHM ref 未释放）；查 client DecRef
```

---

# 附录

## 附录 A · 速查卡

### A.1 一纸禅 grep

```bash
LOG=${log_dir:-/var/log/datasystem}

# 结构化日志前缀（通断主抓手）
grep -E '\[(TCP|UDS|ZMQ|RPC|SOCK|REMOTE|SHM_FD|URMA)_' \
  $LOG/datasystem_worker.INFO.log $LOG/ds_client_*.INFO.log

# Metrics delta 段（时延必看）
grep 'Compare with' $LOG/datasystem_worker.INFO.log | tail -3

# URMA 降级 / Worker 退出 / 心跳 / etcd
grep -E 'fallback to TCP/IP payload' $LOG/*.INFO.log
grep -E '\[HealthCheck\] Worker is exiting now|Cannot receive heartbeat from worker' $LOG/*.INFO.log
grep -E 'etcd is (timeout|unavailable)' $LOG/*.INFO.log

# SHM 钉住
grep -E 'worker_shm_(ref_table|unit|ref_(add|remove))|worker_allocator_(alloc|free)_bytes_total' \
  $LOG/datasystem_worker.INFO.log

# resource.log 核心
grep -E 'SHARED_MEMORY|ETCD_QUEUE|ETCD_REQUEST_SUCCESS_RATE|OC_HIT_NUM|WAITING_TASK_NUM' $LOG/resource.log

# 错误码分布（Client）
grep 'DS_KV_CLIENT_GET' $LOG/ds_client_access_*.log | awk -F'|' '{print $1}' | sort | uniq -c

# code=2 INVALID 类；code=K_NOT_FOUND
grep '^2 |' $LOG/ds_client_access_*.log
grep -E 'K_NOT_FOUND|Can.?t find object' $LOG/ds_client_*.INFO.log
```

### A.2 现场命令

```bash
# OS
ulimit -a; free -h; df -h; dmesg | tail -200
ls /proc/<pid>/fd | wc -l; ss -tnlp | grep <port>
iptables -L -n; tc qdisc show dev eth0

# URMA
ibstat 2>/dev/null || ubinfo 2>/dev/null; ifconfig ub0; ls /dev/ub*

# DS 进程
pgrep -af datasystem_worker; pidstat -p <pid> 1; gstack <pid>

# etcd
systemctl status etcd; etcdctl endpoint status -w table
```

### A.3 处置速查

| 故障 | 恢复 | 验证 |
|------|------|------|
| ZMQ 发送失败（iptables） | `iptables -D ...` | `zmq_send_failure_total` 归零 |
| RPC 超时（tc） | `tc qdisc del dev eth0 root netem` | latency 回 baseline |
| TCP 建连失败 | 开端口 / 删 iptables / 拉起 Worker | `[TCP_CONNECT_FAILED]` 消失 |
| UB 降级 | `ifconfig ub0 up`；修 UMDK | `client_*_urma_*_bytes` > 0 |
| 心跳超时（手工 STOP） | `kill -CONT <pid>` | 心跳恢复 |
| etcd 超时 | 修 etcd 集群 / 网络 | `etcd is ...` 消失 |
| mmap 失败 | `ulimit -l unlimited` | `Get mmap entry failed` 消失 |
| fd 耗尽 | `ulimit -n` 调大 | code=18 消失 |
| SHM 钉住 | 查 DecRef；必要时重启 Worker | `worker_shm_ref_table_bytes` 回稳 |

---

## 附录 B · 结构化日志标签全量

### B.1 OS / 控制面（TCP / UDS / RPC / ZMQ）

| 标签 | 语义 |
|------|------|
| `[TCP_CONNECT_FAILED]` | `connect()` 对端不可达（addrinfo 全失败） |
| `[TCP_CONNECT_RESET]` | `ECONNRESET` / `EPIPE` |
| `[TCP_NETWORK_UNREACHABLE]` | `ZMQ_POLLOUT` 失败（心跳探测） |
| `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]` | 建连等待超时 |
| `[UDS_CONNECT_FAILED]` | 同机 UDS 路径失败 |
| `[SHM_FD_TRANSFER_FAILED]` | SCM_RIGHTS 传 shm fd 失败 |
| `[RPC_RECV_TIMEOUT]` | Client 等应答超时 |
| `[RPC_SERVICE_UNAVAILABLE]` | 服务端主动把失败回包 |
| `[ZMQ_SEND_FAILURE_TOTAL]` | `zmq_msg_send` 硬失败 |
| `[ZMQ_RECEIVE_FAILURE_TOTAL]` | `zmq_msg_recv` 硬失败 |
| `[ZMQ_RECV_TIMEOUT]` | 阻塞 recv 超时 |

### B.2 URMA

| 标签 | 语义 |
|------|------|
| `[URMA_NEED_CONNECT]` | 连接不存在 / 实例不匹配（检查 `instanceId` 变化判断对端重启 vs 链路不稳） |
| `[URMA_RECREATE_JFS]` | JFS 重建触发（`cqeStatus=9` ACK TIMEOUT 等） |
| `[URMA_RECREATE_JFS_FAILED]` | 重建失败 |
| `[URMA_RECREATE_JFS_SKIP]` | connection 已过期跳过重建 |
| `[URMA_POLL_ERROR]` | `PollJfcWait` 报错 |
| `[URMA_WAIT_TIMEOUT]` | URMA 事件等待超时 |
| `fallback to TCP/IP payload` | **降级**（非通断）→ 时延观测 |

### B.3 组件 / 生命周期 / etcd

| 关键字 | 语义 |
|--------|------|
| `[HealthCheck] Worker is exiting now` | Worker 主动退出（编排拉起） |
| `Cannot receive heartbeat from worker.` | 心跳超时（code=23） |
| `etcd is timeout` | Master 看到 etcd 超时 |
| `etcd is unavailable` | Worker 看到 etcd 不可达 |
| `Disconnected from remote node` | 与 etcd 节点断开 |
| `meta_is_moving = true` | 扩缩容中（code=31/32，SDK 自重试） |
| `Get mmap entry failed` | mmap 表项未建 / fd 无效（code=5） |

---

## 附录 C · `resource.log` 字段（22 项，按域分类）

### C.1 容量 / 存储 / 对象

| # | 字段 | 关键子项 | 观测用途 |
|---|------|---------|---------|
| 1 | `SHARED_MEMORY` | MEMORY_USAGE / PHYSICAL_MEMORY_USAGE / TOTAL_LIMIT / WORKER_SHARE_MEMORY_USAGE / SC_MEMORY_USAGE / SC_MEMORY_LIMIT | 共享内存使用；接近 TOTAL_LIMIT 或突增判 SHM 钉住 / 泄漏 |
| 2 | `SPILL_HARD_DISK` | SPACE_USAGE / PHYSICAL_SPACE_USAGE / TOTAL_LIMIT | spill 盘用量；配合 code=13 |
| 20 | `SHARED_DISK` | USAGE / PHYSICAL_USAGE / TOTAL_LIMIT / USAGE_RATE | 共享盘 |
| 21 | `SC_LOCAL_CACHE` | USAGE / RESERVED_USAGE / TOTAL_LIMIT / USAGE_RATE | Stream 本地缓存 |
| 4 | `OBJECT_COUNT` | — | 对象数；与 `worker_object_count` 交叉；断崖→Worker 重启 |
| 5 | `OBJECT_SIZE` | — | 对象总大小；与 OBJECT_COUNT 反向看 SHM 钉住 |

### C.2 线程池（排队 / 打满 → DS 对端慢）

| # | 字段 | 子项（五元组） |
|---|------|---------------|
| 6 | `WORKER_OC_SERVICE_THREAD_POOL` | IDLE_NUM / CURRENT_TOTAL_NUM / MAX_THREAD_NUM / **WAITING_TASK_NUM** / THREAD_POOL_USAGE |
| 7 | `WORKER_WORKER_OC_SERVICE_THREAD_POOL` | 同上 |
| 8 | `MASTER_WORKER_OC_SERVICE_THREAD_POOL` | 同上 |
| 9 | `MASTER_OC_SERVICE_THREAD_POOL` | 同上 |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | 同上 |
| 15 | `WORKER_SC_SERVICE_THREAD_POOL` | 同上 |
| 16 | `WORKER_WORKER_SC_SERVICE_THREAD_POOL` | 同上 |
| 17 | `MASTER_WORKER_SC_SERVICE_THREAD_POOL` | 同上 |
| 18 | `MASTER_SC_SERVICE_THREAD_POOL` | 同上 |

> **`WAITING_TASK_NUM` 堆积** 是 §3.5.2(a) 对端处理慢 / §4.4(a) Worker 业务慢的核心凭据。

### C.3 三方依赖（etcd）与远端 Stream

| # | 字段 | 含义 |
|---|------|------|
| 10 | `ETCD_QUEUE` | CURRENT_SIZE / TOTAL_LIMIT / ETCD_QUEUE_USAGE；堆积 → 三方 etcd 瓶颈 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | etcd 请求成功率；下降 → §3.5.2(c) |
| 19 | `STREAM_REMOTE_SEND_SUCCESS_RATE` | 远端 Stream 发送成功率 |

> `OBS_REQUEST_SUCCESS_RATE` (#12) 为历史遗留字段，现场已不用 OBS；**分布式网盘经 POSIX File 接口**访问，失败以 `K_IO_ERROR(7)` / `K_NO_SPACE(13)` 体现，归 **OS 文件 I/O**（§3.5.4），不在本节。

### C.4 客户端 / 流 / 命中率

| # | 字段 | 含义 |
|---|------|------|
| 3 | `ACTIVE_CLIENT_COUNT` | 已建连客户端数；断崖 → 批量断连 |
| 14 | `STREAM_COUNT` | 活动 Stream 数 |
| 22 | `OC_HIT_NUM` | MEM_HIT_NUM / DISK_HIT_NUM / L2_HIT_NUM / REMOTE_HIT_NUM / MISS_NUM |

---

## 附录 D · KV Metrics 全量（54 条，按域分类）

`KvMetricId = 0~53`（`KV_METRIC_END = 54`），定义在 `common/metrics/kv_metrics.{h,cpp}`。下按**业务 / 延迟 / 数据面 / 容量 / ZMQ / SHM / Master / Client 异步**分类。

### D.1 业务成功率（请求 / 错误计数）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 0 | `client_put_request_total` | Counter | count |
| 1 | `client_put_error_total` | Counter | count |
| 2 | `client_get_request_total` | Counter | count |
| 3 | `client_get_error_total` | Counter | count |

> 成功率 = 1 − `*_error_total / *_request_total`；与 access log `code` 分布交叉验证。

### D.2 延迟 — Client 侧（SDK RPC）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 4 | `client_rpc_create_latency` | Histogram | us |
| 5 | `client_rpc_publish_latency` | Histogram | us |
| 6 | `client_rpc_get_latency` | Histogram | us |

> §4.2 Step 2 时延定界：与 `worker_process_*_latency` 对比谁慢。

### D.3 延迟 — Worker 侧（RPC / 处理 / URMA / TCP 写）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 11 | `worker_rpc_create_meta_latency` | Histogram | us |
| 12 | `worker_rpc_query_meta_latency` | Histogram | us |
| 13 | `worker_rpc_get_remote_object_latency` | Histogram | us |
| 14 | `worker_process_create_latency` | Histogram | us |
| 15 | `worker_process_publish_latency` | Histogram | us |
| 16 | `worker_process_get_latency` | Histogram | us |
| 17 | `worker_urma_write_latency` | Histogram | us |
| 18 | `worker_tcp_write_latency` | Histogram | us |

> `rpc_create_meta` 单飙 + `ETCD_*` 差 → **三方 etcd**；`process_*` 同幅飙 → **DS 业务慢**（§4.4）；`urma_write` vs `tcp_write` 看 URMA 降级（§4.5）。

### D.4 数据面字节（URMA vs TCP，降级判断）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 7 | `client_put_urma_write_total_bytes` | Counter | bytes |
| 8 | `client_put_tcp_write_total_bytes` | Counter | bytes |
| 9 | `client_get_urma_read_total_bytes` | Counter | bytes |
| 10 | `client_get_tcp_read_total_bytes` | Counter | bytes |
| 19 | `worker_to_client_total_bytes` | Counter | bytes |
| 20 | `worker_from_client_total_bytes` | Counter | bytes |

> 降级判据：**`urma_*` delta=0** + **`tcp_*` delta↑** + 日志 `fallback to TCP/IP payload`。

### D.5 Worker 容量（Gauge）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 21 | `worker_object_count` | Gauge | count |
| 22 | `worker_allocated_memory_size` | Gauge | bytes |

> 断崖 → Worker 重启 / 驱逐；与 `resource.log` `OBJECT_COUNT`、`SHARED_MEMORY` 交叉。

### D.6 ZMQ 故障与事件（控制面）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 23 | `zmq_send_failure_total` | Counter | count |
| 24 | `zmq_receive_failure_total` | Counter | count |
| 25 | `zmq_send_try_again_total` | Counter | count |
| 26 | `zmq_receive_try_again_total` | Counter | count |
| 27 | `zmq_network_error_total` | Counter | count |
| 28 | `zmq_last_error_number` | Gauge | — |
| 29 | `zmq_gateway_recreate_total` | Counter | count |
| 30 | `zmq_event_disconnect_total` | Counter | count |
| 31 | `zmq_event_handshake_failure_total` | Counter | count |

> **fault = 0** 排除 ZMQ/网络故障（→ DS 对端处理慢，§3.3）；`last_error_number` 按 errno 对照；`try_again` 涨 → HWM 背压（§4.4(d)）。

### D.7 ZMQ 延迟（IO / 序列化，框架占比分析）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 32 | `zmq_send_io_latency` | Histogram | us |
| 33 | `zmq_receive_io_latency` | Histogram | us |
| 34 | `zmq_rpc_serialize_latency` | Histogram | us |
| 35 | `zmq_rpc_deserialize_latency` | Histogram | us |

> 框架占比 = `(serialize + deserialize) / (send_io + recv_io + serialize + deserialize)`；**< 5%** 瓶颈不在 ZMQ/protobuf（§4.2 Step3）。

### D.8 SHM / 内存分配（含泄漏检测）

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
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

> 泄漏判据：`alloc_bytes delta > free_bytes delta` + **`ref_table_bytes` 持续涨** + `worker_object_count` 持平（实战示例 §六 最后一条）。

### D.9 Master — 元数据 / TTL

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 46 | `master_object_meta_table_size` | Gauge | count |
| 47 | `master_ttl_pending_size` | Gauge | count |
| 48 | `master_ttl_fire_total` | Counter | count |
| 49 | `master_ttl_delete_success_total` | Counter | count |
| 50 | `master_ttl_delete_failed_total` | Counter | count |
| 51 | `master_ttl_retry_total` | Counter | count |

> `ttl_delete_failed` / `ttl_retry` 涨 → 多为 **三方 etcd** 或 Master 慢。

### D.10 Client — 异步释放 / DecRef

| ID | 名 | 类型 | 单位 |
|----|----|------|------|
| 52 | `client_async_release_queue_size` | Gauge | count |
| 53 | `client_dec_ref_skipped_total` | Counter | count |

> 队列堆积或 skip 涨 → SDK 侧释放链路异常，配合 D.8 看是否导致 Worker 端 SHM 钉住。

---

## 附录 E · 故障注入矩阵 & 验收 Checklist（测试用）

### E.1 注入矩阵

| 故障类型 | 注入方法 | 预期 metric | 预期日志 |
|---------|---------|------------|---------|
| ZMQ 发送失败 | `iptables -I OUTPUT ... -j DROP` | `zmq_send_failure_total`↑ | `[ZMQ_SEND_FAILURE_TOTAL]` |
| RPC 超时 | `tc qdisc add ... netem delay` | `client_rpc_get_latency` max↑ | `[RPC_RECV_TIMEOUT]` |
| TCP 建连失败 | `iptables -I INPUT ... -j REJECT` | — | `[TCP_CONNECT_FAILED]` |
| URMA 连接断 | kill 远端 Worker | `zmq_gateway_recreate_total`↑ | `[URMA_NEED_CONNECT]` |
| UB 降级 TCP | `ifconfig ub0 down` | TCP bytes↑、URMA bytes=0 | `fallback to TCP/IP payload` |
| JFS 重建 | 触发 `cqeStatus=9` | `worker_urma_write_latency` max↑ | `[URMA_RECREATE_JFS]` |
| etcd 不可用 | `systemctl stop etcd` | `K_MASTER_TIMEOUT`(25) | `etcd is timeout/unavailable` |
| 内存泄漏 | 模拟 ref_table 钉住 | `worker_shm_ref_table_bytes`↑ | — |
| Worker 退出 | `kill -9 <worker>` | `worker_object_count`↓ | `[HealthCheck] Worker is exiting now` |
| 心跳超时 | `kill -STOP <worker>` | — | `Cannot receive heartbeat from worker.` |
| mmap 失败 | `ulimit -l 0` + 触发 | — | `Get mmap entry failed` |

### E.2 验收 Checklist

**基础观测**：
- [ ] Worker / Client INFO log 有 `Metrics Summary, version=v0, cycle=...`
- [ ] `resource.log` 周期输出，含 `SHARED_MEMORY` / `ETCD_*` / `*_THREAD_POOL`
- [ ] access log 字段六列齐全，`handleName` 与接口对应

**故障注入**（每条可独立跑）：
- [ ] ZMQ：`zmq_send_failure_total` delta>0 + `[ZMQ_SEND_FAILURE_TOTAL]`
- [ ] URMA 重连：`[URMA_NEED_CONNECT]` 或 `[URMA_RECREATE_JFS]`
- [ ] UB 降级：`client_get_tcp_read_total_bytes`↑ 且 `urma_*_bytes` 不涨
- [ ] etcd：`etcd is (timeout|unavailable)` + code=25
- [ ] 心跳：`Cannot receive heartbeat from worker.` + code=23
- [ ] SHM 泄漏：`worker_shm_ref_table_bytes` 持续涨、`worker_object_count` 持平

---

## 附录 F · 日志路径与 gflag 开关

| 项 | 说明 |
|----|------|
| `$log_dir` | 由 `--log_dir` / 环境决定 |
| Worker 运行 | `datasystem_worker.INFO.log` |
| Client 运行 | `ds_client_<pid>.INFO.log` |
| Client access | `ds_client_access_<pid>.log` |
| Worker access | `access.log`（需 `log_monitor=true`） |
| `resource.log` | 资源 / 线程池 / `ETCD_*` 聚合 |
| `request_out.log` | Worker 访问 etcd 轨迹 |
| `log_monitor` | 默认 `true`；关掉后 Summary 不打印 |
| `log_monitor_interval_ms` | 默认 `10000` |
| `log_monitor_exporter` | 现场用 `harddisk` 落盘（帮助文本提及的 `backend` 会被 reject） |
