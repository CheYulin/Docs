# 08 · 故障定位定界手册（通断 × 时延 双轴）

> **本文是什么**：一份**自包含**的现场定位定界操作手册。看到现象 → 分类 → 定界 → 定位。
>
> **面向谁**：开发、运维、测试、值班。不要求先读任何其它文档。
>
> **凭什么准**：错误码、日志字符串、metric 名、gflag 默认值均与 `yuanrong-datasystem` 主干行为对齐；需核对实现细节时请查代码库或研发侧专项文档。
>
> **两类故障**
>
> - **通断类（Availability）**：接口**返回失败** / 错误码非 0 / 功能不可用 / 进程挂 / 连接断。
> - **时延类（Latency）**：接口**返回成功**但**慢** / **P99↑** / 尾延迟 **max** 飙升 / 抖动（本手册以**时延与成功率**为主观测面）。
>
> **责任边界怎么读**（定界目标：判给谁修）
>
> 1. **用户（User）**：业务侧误用 — 参数非法、对象不存在、未初始化、buffer 重用。
> 2. **DataSystem 进程内（DS）**：跑在 Worker / Master / SDK **进程里**的实现与配置 — RPC 处理路径、线程池、心跳循环、SHM 元数据逻辑、扩缩容状态机等。**不含** etcd / OBS 等外部进程本体。
> 3. **三方依赖**：**etcd 集群**、OBS 等 — DS 只作为**客户端**访问；日志里会出现 `etcd is timeout` / `etcd is unavailable`、request_out、队列堆积，根因通常在 **etcd 集群或网络到 etcd**，不是 DS 业务代码里的「算错」。
> 4. **URMA**：UB 硬件 / UMDK 驱动 / UB 链路。
> 5. **OS 与环境**：内核、资源与系统调用失败面 — **TCP/IP**、iptables、路由；**`zmq_msg_send` / `zmq_msg_recv` 等返回的硬失败**（errno 多来自网络栈或本机资源）；**文件与块设备 I/O**、**fd / mmap / ulimit**、磁盘满、OOM 等。
>
> 工单上仍可按习惯写「主责 + 协查」；**不要把 etcd 进程故障写成「DataSystem 内部缺陷」**，除非已排除 etcd 集群与连通性。
>
> **手册使用顺序**：**§导入** 从接口日志看成功率与 P99 → **§0** 一图流 → **§1 / §2**（先 **§x.2** 定界，再 **§x.3** 定位）→ **§3** 工单模板。**全量 metric 名称**见正文 **§6**（紧贴在附录之前）。

---

## 导入：成功率与 P99（从接口日志切入）

优先从 **SDK Client 访问日志** `ds_client_access_<pid>.log` 读现象（字段格式见 **§1.3.1** ASCII 示意）：

| 观测目标 | 在接口日志里怎么看 | 补充 |
|----------|-------------------|------|
| **成功率 / 通断** | 每行 **第一列 `code`**（错误码）。按接口 grep 后做 `awk -F'|' '{print $1}' \| sort \| uniq -c` 看分布 | **Get 陷阱**：`K_NOT_FOUND` 可能被记成 **code=0**，业务「查不到」要看 **`respMsg`**，不能只数非 0 |
| **时延 / P99↑** | **第三列 `microseconds`**：单次调用耗时。用脚本或平台聚合 **P99、max**，或与基线对比是否整体右移 | 尾延迟还可对照 **Worker / Client** 的 `Metrics Summary` 里对应 Histogram（**§2.2**、`grep 'Compare with'`），时间窗要对齐 |

**怎么分流到后文**：

- 接口日志里 **非 0 明显增多**、或业务明确 **调用失败** → 先走 **§1 通断**。
- **code 多为 0**，但 **microseconds 或 P99 明显变差**、或监控报 **延迟 SLA** → 先走 **§2 时延**。

定界用 **Status + 结构化日志前缀 + Metrics delta**，请直接看 **§1.2 / §2.2**；下面 §1.1 / §2.1 只列**常见长什么样**，不是定界结论表。

---

## 0. 一图流：分类 → 定界 → 定位

```
                  观察到现象（或 §导入 的成功率/P99）
                           │
        ┌──────────────────┴───────────────────┐
        │                                      │
        ▼                                      ▼
  ① 通断（§1）                           ② 时延（§2）
  Status ≠ K_OK                          Status = K_OK
  / 连接断 / 进程挂                        / 但 P99↑、latency max 飙升 / 抖动
        │                                      │
        ▼                                      ▼
   先定界（§1.2）                          先定界（§2.2）
   ┌──┬───┬───┬────┬───┐                 ┌──┬───┬───┬────┬───┐
   │用│DS │三方│URMA│OS │                 │用│DS │三方│URMA│OS │
   │户│   │etcd│    │   │                 │户│   │etcd│    │   │
   └─┬┴──┴───┴─┬──┴─┬─┘                 └─┬┴──┴───┴─┬──┴─┬─┘
     ▼  ▼  ▼  ▼  ▼                      ▼  ▼  ▼  ▼  ▼
                再定位（§1.3 / §2.3）
   按具体子场景落到 [日志前缀] × metric delta × 处置动作
                           │
                           ▼
                  §3 结论模板 / 贴工单
```

**五边界速记表**（DS **进程内** vs **etcd 等三方** vs **OS** 要分清）

| 边界 | 我判给你的触发特征 | 常见凭据 |
|------|-------------------|---------|
| **用户** | Status ∈ {2, 3, 8}，或 Status=0 但业务 respMsg 异常 | access log 的 `respMsg` |
| **DS 进程内** | Status ∈ {23,29,31,32}；或 **对端处理慢 / 拒绝**（`[RPC_RECV_TIMEOUT]` + 全链路 ZMQ fault=0）；或 **`[UDS_*]` / `[SHM_FD_TRANSFER_FAILED]`**（同机辅助通道）；或 **线程池打满**；扩缩容 `meta_is_moving` | `resource.log` 线程池 / SHM；结构化日志前缀 |
| **三方（etcd 等）** | Master/Worker 打 **`etcd is timeout` / `etcd is unavailable`**；`ETCD_QUEUE` 堆积、`ETCD_REQUEST_SUCCESS_RATE` 下降；Status=25；request_out 大量写 etcd 失败 | `grep etcd`；`etcdctl endpoint status`；**先查 etcd 集群与到 etcd 的网络** |
| **URMA** | Status ∈ {1004,1006,1008,1009,1010}；或 `[URMA_*]` / `fallback to TCP/IP payload` | `[URMA_*]`、`*_urma_*_bytes` |
| **OS** | Status ∈ {6,7,13,18}；**文件 / 磁盘 / fd** 类（含 `K_IO_ERROR`、`K_NO_SPACE`、`K_FILE_LIMIT_REACHED`）；**`K_RUNTIME_ERROR(5)` + `Get mmap entry failed`**；**`[TCP_*]` 通断且对端进程仍存活**；**`[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECEIVE_FAILURE_TOTAL]`**（底层多为 **errno / 网络栈 / 资源**） | `ulimit` / `ss` / `df` / `dmesg` / iptables；`zmq_last_error_number` |

> ⚠️ **`K_RPC_UNAVAILABLE(1002)` 是"桶码"**：相同 1002 可能来自 **DS 进程内**（Worker crash、对端拒绝）、**OS**（iptables、端口、路由、`zmq_*` 硬失败）或 **三方 etcd**（`etcd is unavailable` 路径）。**必须看下一层 `[...]` 前缀与 etcd 字符串才能定界**。
>
> ⚠️ **`K_OK(0) ≠ 一切正常`**：`KVClient::Get` 会把 `K_NOT_FOUND` 记成 `K_OK` 写入 access log；业务「查不到」时常为 **Status=0 + respMsg 含 NOT_FOUND**，要以 `respMsg` 判**用户**边界，不能只看错误码 0。

---

## 1. 通断类故障

### 1.1 常见长什么样（通断侧现象，非定界表）

| 业务或监控上你先注意到 | access / 运行日志上典型长什么样 |
|------------------------|----------------------------------|
| 接口大量失败、错误码非 0 | `ds_client_access_*.log` **第一列**频繁出现 1001、1002、1004… 或 6、7、13、18 等 |
| 返回「成功」但业务说数据不对 / 查不到 | **code=0** 但 **`respMsg`** 含 `NOT_FOUND`、`invalid`、`not ready` 等（Get 的 NOT_FOUND 陷阱见 §导入） |
| 客户端连不上 Worker、扩缩容卡顿 | SDK/Client 日志出现 `Cannot receive heartbeat from worker.`；或 Worker 侧 `[HealthCheck] Worker is exiting now` |
| 元数据 / Master 卡住 | Master 或 Worker 日志出现 **`etcd is timeout` / `etcd is unavailable`**；或 `request_out` 里 etcd 请求异常增多 |
| 机器宕机、节点驱逐、对端进程没了 | 心跳与 RPC 同时异常；**resource.log / Metrics** 里对象数、连接数断崖（细节在 §1.3） |
| SHM / mmap 相关报错 | Client 或 Worker 日志出现 `Get mmap entry failed` 等；常与 Status=5 同屏 |
| URMA 仍返回成功但日志提示走 TCP | 日志含 `fallback to TCP/IP payload` — 通断上可能仍「成功」，**时延**见 §2 |

**定界**：必须用 **§1.2** 的 Status 树 + Step2 前缀，不能单靠上表。

### 1.2 通断故障的定界（三步，≤ 1 分钟）

> 目标：拿到**用户 / DS 进程内 / 三方(etcd) / URMA / OS** 之一为主责结论（可备注协查）。

**通断定界总览**（与 Step 1～3 对应）：

```
              access / SDK 日志 / 告警
                        │
                        ▼
           ┌────────────────────────────┐
           │ Step 1  扫 Status 树       │
           │ 0→看 respMsg；1004+→URMA   │
           │ 1001/1002→进 Step 2        │
           └─────────────┬──────────────┘
                         │
       ┌─────────────────┼─────────────────┐
       │ 已能判五边界之一 │ 桶码 / 需前缀    │
       ▼                 ▼                 │
  用户/OS/URMA    ┌──────────────┐        │
  /三方(25/5)     │ Step 2 日志   │        │
                  │ 前缀 + errno  │        │
                  └──────┬───────┘        │
                         ▼                 │
                  ┌──────────────┐        │
                  │ Step 3 交叉   │◄───────┘
                  │ ping/ss/对端  │
                  │ 是否存活      │
                  └──────┬───────┘
                         ▼
               主责边界 → §1.3 定位小节
```

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
│    ├─ Worker/Client 日志有 "Get mmap entry failed"     → OS（mmap/fd）
│    ├─ 有 "etcd is timeout" / "etcd is unavailable"   → 三方（etcd）
│    └─ 有 "urma ... payload ..."                       → URMA
├─ 6 / 7 / 13 / 18                           → OS（内存/IO/磁盘/fd/文件）
├─ 25（K_MASTER_TIMEOUT）                    → 三方（etcd）为主，兼查 Master 与网络
├─ 19 / 23 / 29 / 31 / 32                    → DS 进程内（可用性/扩缩容/心跳）
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
| `[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECEIVE_FAILURE_TOTAL]`（`zmq_msg_send` / `zmq_msg_recv` 硬失败） | **OS** 为主 | 多为 **errno / 内核网络栈 / 本机资源**；按 `zmq_last_error_number` 对照 `errno` |
| 日志先出现 **`etcd is timeout` / `etcd is unavailable`**（可与 1002/25 同屏） | **三方（etcd）** | DS 仅客户端；先恢复 etcd 集群与连通性 |
| `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]` | **OS 或 DS** | 握手迟；看对端 Worker 是否存活再判 |
| `zmq_event_handshake_failure_total` delta > 0 | **DS**（安全/证书） | TLS / 认证配置 |

**Step 3：交叉验证（给出最终结论）**

- **ping / ss / iptables**：对端 IP 可达、端口 LISTEN、无 DROP/REJECT → 排除 OS。
- **对端 Worker INFO log 同时间窗有无受理日志**：有 → 对端活着，排除 DS 进程侧通断；没有则再看 `[HealthCheck] Worker is exiting now` 判 DS。
- **`worker_object_count` / access log 计数**：一边涨一边归零 → Worker 重启了。

### 1.3 通断故障的定位（按边界展开）

#### 1.3.1 用户边界

**定位依据**：Client Access Log（字段竖线分隔，与测试侧 `08-fault-triage-guide` 一致）。

```
code | handleName | microseconds | dataSize | reqMsg | respMsg
  ↑      ↑            ↑            ↑         ↑         ↑
 错误码  接口名        耗时(μs)     数据大小   请求参数   响应信息
```

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

#### 1.3.2 DS 进程内边界

**进程内**可再分子场景（与 **三方 etcd**、**OS** 区分后再看本节）。

**§1.3.2 (a)～(e) 怎么选**（先对信号，再下钻小节；**(c) 主责多为三方 etcd**）：

```
        通断已需读 §1.3.2（RPC/连接/排队类）
                        │
         ┌──────────────┴──────────────┐
         │ 你最先抓到的信号更偏哪一类？  │
         └──────────────┬──────────────┘
    ┌────────┬──────────┼──────────┬────────┐
    ▼        ▼          ▼          ▼        ▼
 RPC 超时  网关重建    etcd/      心跳/    mmap/
 或服务    /disconnect  ETCD_QUEUE 扩缩容   SHM fd
 不可用    对端仍活     /25 同屏   23/31/32  传递失败
    │        │          │          │        │
    ▼        ▼          ▼          ▼        ▼
  (a)      (b)        (c)        (d)      (e)
 对端慢    会话抖动   三方元数据  生命周期  同机通道
 fault≈0   非主动退出  路径      HealthCheck 常与 OS 交叉
```

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

##### (c) 三方依赖 — etcd / 元数据路径

| 证据 | 判据 |
|------|------|
| Master log `etcd is timeout` | Master 侧认为 etcd 超时（**etcd 集群或链路**） |
| Worker log `etcd is unavailable` | Worker 侧认为 etcd 不可达 |
| `resource.log` `ETCD_QUEUE.CURRENT_SIZE` 堆积、`ETCD_REQUEST_SUCCESS_RATE` 下降 | 写 **etcd** 受阻或失败率高 |
| Status=25（`K_MASTER_TIMEOUT`） | 多与控制面 / **etcd** 不可用同屏出现 |

> ⚠️ **两串文并存**：Master 常见 `etcd is timeout`，Worker 常见 `etcd is unavailable`；grep **两个都加**。

**处置**：`systemctl status etcd`（或集群等价命令）；`etcdctl endpoint status`；查 **到 etcd 的网络**；恢复后观察 1002/25 是否自愈。**责任归属写「三方：etcd」**，除非已证明 DS 仅误配 endpoint。

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

### 2.1 常见长什么样（时延侧现象，非定界表）

| 业务或监控上你先注意到 | 接口日志 / Metrics 上典型长什么样 |
|------------------------|-----------------------------------|
| 接口变慢、P99↑、超时增多 | access **`microseconds`** 整体变大或重尾拉长；或监控上 **P99↑**（与 §导入 对齐时间窗） |
| 成功率还行，只是「慢」 | access **code 多为 0**，但耗时列仍恶化 |
| 只有「最慢的几次」特别夸张 | `Metrics Summary` 里对应 Histogram **max 飙升**，avg 可能还行（§2.2 Step1） |
| 怀疑 UB / 降级 | 日志 **`fallback to TCP/IP payload`**；或 **URMA 字节 counter 不涨、TCP 字节涨**（metric 名见 §6） |
| 不报错但感觉「卡住」 | 无新错误码时，可看 **`zmq_send_try_again_total`** 等是否持续上涨（§2.3.2(d)） |

**定界**：用 **§2.2** 三步（Client vs Worker、再拆链路）；上表不替代 Step2/3。

### 2.2 时延故障的定界（三步，≤ 3 分钟）

> 目标：同样输出 **用户 / DS 进程内 / 三方(etcd) / URMA / OS** 之一为主（时延类里 etcd 常体现为 `worker_rpc_create_meta_latency` max↑ + `ETCD_*` 异常）。

**时延定界总览**（与 Step 1～3 对应）：

```
        access P99↑ / microseconds 变差（code 多为 0）
                        │
                        ▼
           ┌────────────────────────────┐
           │ Step 1  delta 段确认慢     │
           │ Histogram max；count=0→停  │
           └─────────────┬──────────────┘
                         ▼
           ┌────────────────────────────┐
           │ Step 2  client_rpc_*       │
           │   vs worker_process_*      │
           │ 谁慢、是否同幅？            │
           └─────────────┬──────────────┘
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   同幅→§2.3.2      Client 更慢      Worker 快
   (a)～(d)         → Step 3 拆链路   Client 慢
                         │          → 用户/SDK
                         ▼
           ┌────────────────────────────┐
           │ Step 3  URMA / TCP 降级     │
           │ ZMQ IO + fault / RTT 丢包   │
           └─────────────┬──────────────┘
                         ▼
               主责边界 → §2.3 各小节
```

**Step 1：是否真慢？**

- 看 `Metrics Summary` 的 `Compare with ... ms before` 段（下称 *delta 段*）；关注对应接口 Histogram 的 `max`（本周期 periodMax）。
- delta 段的 `max` 相对 baseline **明显抬升**（例如 **2～3 倍以上**）或 **P99↑** 与现象一致 → 确认慢。
- delta 段 `count=+0` 但 Total 段很大 → 无流量，非时延问题。

**Step 2：是 Client 链路慢还是 Worker 处理慢？**

| 对比 | 结论 |
|------|------|
| `client_rpc_get_latency` max 显著 > `worker_process_get_latency` max | 中间链路慢 → 进入 Step 3（可能 DS 框架 / URMA / OS 网络） |
| 两者同幅 **max 飙升** | Worker 业务自身慢 → **DS 进程内**；看 CPU / 线程池 / 锁 |
| Worker 快、Client 慢、且 `worker_to_client_total_bytes` delta 正常 | SDK 本地慢（反序列化 / 用户线程阻塞）→ **用户** 或 **DS 客户端** |

**Step 3：拆 Client ↔ Worker 的中间链路**

- `worker_urma_write_latency` max **飙升** → **URMA**。
- `worker_tcp_write_latency` max **飙升** + `*_urma_*_bytes` delta=0 + `fallback to TCP/IP payload` → **URMA**（UB 故障导致 TCP 降级）。
- `zmq_send_io_latency` / `zmq_receive_io_latency` max **飙升** 且 **`zmq_send_failure_total` / `zmq_receive_failure_total` 有 delta** → **OS**（`zmq_msg_send` / `zmq_msg_recv` 硬失败，errno 多来自网络栈或本机资源）。
- `zmq_send_io_latency` / `zmq_receive_io_latency` max **飙升** + **fault counter 全 0** → 再看 `zmq_rpc_serialize_latency / deserialize_latency`：
  - **序列化+反序列化占比 < 5%** → **对端处理慢 → DS 进程内** 与 **中间链路 → OS** 二选一：看 `worker_process_*_latency` 是否同幅 **飙升**。
  - 占比 ≥ 5% → **DS 进程内**框架侧（大 payload / protobuf 低效）。
- ping RTT **抖** / `tc qdisc` 有 netem 规则 / `nstat` 丢包 → **OS**。

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

#### 2.3.2 DS 进程内边界

**§2.3.2 (a)～(d) 怎么选**（默认前提：**§2.2 Step2** 已判断 **client 与 worker process 延迟同幅飙升**，或瓶颈明确在 Worker 处理侧）：

```
              同幅飙升 / Worker 侧为主
                        │
     worker_rpc_get_remote_object_latency 单独突出？
              是 ──────────────────────────► (c) 跨 Worker Get
              否
                        │
     create_meta_latency↑ 且 ETCD_* / etcd 日志差？
              是 ──► 主责 **三方 etcd**（对照 §1.3.2(c)）
              否
                        │
     RPC 框架占比 ≥ 5%？（见下文公式）
              是 ──────────────────────────► (b) 序列化/大 payload
              否
                        │
     zmq_send_try_again↑ 且 fault counters≈0？
              是 ──────────────────────────► (d) HWM 背压
              否
                        ▼
                   (a) 业务路径 / 线程池 / 锁 / CPU
```

##### (a) Worker 业务慢

| 证据 | 判据 |
|------|------|
| `worker_process_get_latency / publish_latency` max **飙升** | Worker 业务路径慢 |
| `worker_rpc_create_meta_latency` max **飙升** | 写元数据路径慢；若伴 **`ETCD_*` 异常** → 主责 **三方 etcd** |
| `resource.log` `*_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM` 堆积 | RPC 线程池打满 |
| `resource.log` `ETCD_QUEUE` / `ETCD_REQUEST_SUCCESS_RATE` | **etcd** 请求排队或成功率跌 → **三方** |

**处置**：线程池 / CPU / 锁；若 etcd 指标差，**先 etcd 集群与网络**，再谈 DS 调参。

##### (b) DS 框架自身（序列化 / protobuf / ZMQ）

| 证据 | 判据 |
|------|------|
| `zmq_rpc_serialize_latency / deserialize_latency` 与 IO latency 比例 ≥ 5% | 框架占比偏高 |
| 请求 payload 异常大（`worker_to_client_total_bytes` / `worker_from_client_total_bytes`） | 数据面放大 |

**处置**：拆大对象 / 启用 URMA 零拷贝 / 用 Publish+Get 走 SHM。

##### (c) 跨 Worker Get 慢（远端对象）

| 证据 | 判据 |
|------|------|
| `worker_rpc_get_remote_object_latency` max **飙升** | 远端拉取慢 |
| 远端 Worker `worker_process_get_latency` 同幅 **飙升** | 远端业务慢 |
| 远端 Worker 正常 | 中间网络或 URMA → 转 §2.3.3 / §2.3.4 |

##### (d) ZMQ 背压（无错误码，但尾延迟劣化）

| 证据 | 判据 |
|------|------|
| `zmq_send_try_again_total` 持续涨，其它 fault counter 为 0 | HWM 背压，发送侧等槽位 |
| `zmq_receive_try_again_total`（仅 blocking 模式）持续涨 | 接收端消费慢 |

**处置**：加消费端线程 / 降峰限流；**Status 仍可为 0**，以 **latency max / P99** 观测。

#### 2.3.3 URMA 边界

| 证据 | 判据 | 处置 |
|------|------|------|
| `worker_urma_write_latency` max **飙升** | UB 硬件 / 驱动慢 | 查 UMDK / UB 端口状态 |
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
| `nstat / ss -ti` 重传率 **飙升** | TCP 重传 | 查网卡 / 驱动 |
| iostat / vmstat 显示 IO wait / swap | 本机资源饱和 | 扩资源 / 隔离业务 |
| `resource.log` `SHARED_MEMORY` 接近 `TOTAL_LIMIT` | 内存压力传导到 GC/分配慢 | 扩 SHM 池 |
| `worker_shm_ref_table_bytes` gauge 持续涨 + `worker_object_count` 持平 | SHM 钉住（DS 实现问题，但表征是 OS 内存被吃光） | 见 §1.3.2(e) |

---

## 3. 结论模板（贴工单）

```
【故障类型】通断 / 时延（二选一，主因写第一）
【责任边界】用户 / DS 进程内 / 三方(etcd 等) / URMA / OS（必须给出其一；跨界写主责+协查）
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
【类型】通断 【边界】DS 进程内（RPC 对端慢）
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
Step1：delta 段 client_rpc_publish_latency max **飙升**
Step2：worker_process_publish_latency 同幅 **飙升** 不成立；
       client_put_urma_write_total_bytes delta=0，client_put_tcp_write_total_bytes delta=+50MB
Step3：grep 'fallback to TCP/IP payload' 200/min
【类型】时延 【边界】URMA（UB 降级 TCP）
【处置】ifconfig ub0 / UMDK；恢复后 urma 字节 delta 回升
```

### 示例 6 · 时延 / DS：Get **P99↑**，Status=0

```
Step1：client_rpc_get_latency max=50ms，baseline 2ms
Step2：ZMQ fault counter 全 0；worker_process_get_latency max=38ms（同幅 **飙升**）
Step3：resource.log WORKER_OC_SERVICE_THREAD_POOL.WAITING_TASK_NUM 堆积
【类型】时延 【边界】DS 进程内（Worker 业务慢）
【处置】查 Worker CPU / 线程池 / 锁；必要时扩线程数
```

### 示例 7 · 时延 / OS：ZMQ 框架占比低，中间链路抖

```
Step1：client_rpc_get_latency max **飙升**，worker_process_get_latency 未变
Step2：zmq_send_io_latency max **飙升**；zmq_rpc_serialize+deserialize 占比 ~3%
Step3：ping 对端 RTT **抖动**；tc qdisc 有 netem 延迟
【类型】时延 【边界】OS（网络）
【处置】tc qdisc del ...；或换网卡 / 换交换路径
```

### 示例 8 · 通断 / DS：SHM 钉住泄漏

```
Step1：无错误码，但 resource.log SHARED_MEMORY 从 3.58GB → 37.5GB
Step3：worker_shm_ref_table_bytes gauge 持续上涨
       worker_object_count gauge 持平
       worker_allocator_alloc_bytes_total delta > worker_allocator_free_bytes_total delta
【类型】通断（容量型，最终 OOM）【边界】DS 进程内（SHM ref 未释放）
【处置】查 client DecRef；Worker 清理超时
```

---

## 5. 现场速查卡

### 5.1 错误码 → 边界一览

```
StatusCode                           边界        备注
0    K_OK                             用户?       看 respMsg；NOT_FOUND→K_OK 陷阱
2    K_INVALID                        用户
3    K_NOT_FOUND                      用户
5    K_RUNTIME_ERROR                  OS/三方/URMA  mmap→OS；etcd 串→三方；payload→URMA
6    K_OUT_OF_MEMORY                  OS
7    K_IO_ERROR                       OS         文件/IO
8    K_NOT_READY                      用户
13   K_NO_SPACE                       OS
18   K_FILE_LIMIT_REACHED             OS         fd/文件限制
19   K_TRY_AGAIN                      DS/OS      结合前缀；常为瞬时繁忙或网络类
20   K_DATA_INCONSISTENCY             DS
23   K_CLIENT_WORKER_DISCONNECT       DS/OS/机器  先确认进程与节点
25   K_MASTER_TIMEOUT                 三方(etcd) 为主 兼查 Master 与网络
29   K_SERVER_FD_CLOSED               DS
31   K_SCALE_DOWN                     DS
32   K_SCALING                        DS
1001 K_RPC_DEADLINE_EXCEEDED          DS/OS      §1.2 Step2
1002 K_RPC_UNAVAILABLE                DS/OS/三方   桶码；含 etcd unavailable 路径
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

# etcd 两种字符串（Master / Worker 日志都搜）
grep -E 'etcd is (timeout|unavailable)' $LOG/*.INFO.log

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

### 5.3 OS / etcd / URMA / DS 进程速查

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

## 6. KV Metrics 全量清单（54 条）

与 `yuanrong-datasystem` 主干一致时，`KvMetricId` 为 **0～53**，**`KV_METRIC_END` = 54**。定义在 `common/metrics/kv_metrics.{h,cpp}` 的 `KV_METRIC_DESCS`；发布版本若有增减，以代码库 `static_assert` 为准。下表供值班与 **§1 / §2** 对照 **grep Metrics Summary** 全文。

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
| 28 | `zmq_last_error_number` | Gauge | — |
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

## 附录 · 运维速查（无源码行号）

### A. 日志与 Metrics 开关

| 项 | 说明 |
|----|------|
| `$log_dir` | 由 `--log_dir` / 环境决定；下文路径均在其下 |
| Worker / Client 运行日志 | `datasystem_worker.INFO.log`，`ds_client_<pid>.INFO.log` |
| Client access log | `ds_client_access_<pid>.log` |
| `resource.log` | 资源、线程池、`ETCD_*` 等聚合 |
| `request_out.log` | Worker 访问 **etcd / OBS** 等三方请求轨迹 |
| `log_monitor` | 默认 `true` |
| `log_monitor_interval_ms` | 默认 `10000` |
| `log_monitor_exporter` | 现场请用 **`harddisk`** 落盘 Summary |
| Metrics Summary | `Total:` 与 `Compare with ...ms before:` 为 **delta 段**；时延看 Histogram 的 **max / P99↑** |

### B. 定界常用 metric（子集）

**全量 ID 与名称见上文 §6。** 值班最常 grep 的延迟与故障计数：`client_rpc_get_latency`、`client_rpc_publish_latency`、`worker_process_get_latency`、`worker_process_publish_latency`、`worker_rpc_create_meta_latency`、`worker_urma_write_latency`、`worker_tcp_write_latency`、`zmq_send_io_latency`、`zmq_receive_io_latency`、`zmq_rpc_serialize_latency`、`zmq_rpc_deserialize_latency`、`zmq_send_failure_total`、`zmq_receive_failure_total`、`zmq_send_try_again_total`、`zmq_last_error_number`；降级对比 `client_*_urma_*_bytes` / `client_*_tcp_*_bytes`；SHM `worker_shm_ref_table_bytes`、`worker_allocator_*_bytes_total`、`worker_object_count`。

### C. `resource.log` 值班 grep

优先：`SHARED_MEMORY`、`SPILL_HARD_DISK`、`OBJECT_COUNT`、各 `*_THREAD_POOL`（含 `WAITING_TASK_NUM`）、`ETCD_QUEUE`、`ETCD_REQUEST_SUCCESS_RATE`、`OC_HIT_NUM`。

---
