# 04 · 定位定界手册（Trace × 分支 × 责任域）

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/utils/trace.h` | `TraceGuard` / TraceID |
| `src/datasystem/common/log/access_recorder.cpp` | 客户端 access log |
| `src/datasystem/common/log/access_point.def` | handle 名定义 |
| `src/datasystem/client/listen_worker.cpp` | 心跳与 Worker 可用性 |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 日志主源 |

> **目标**：让使用方按"**一次 SDK 调用 = 一条请求 Trace**"上的日志，把问题 **落到具体阶段与责任域**。
>
> **配套**：[`diagrams/README.md`](diagrams/README.md) 总图 + 分图；[`workbook/sheet1-call-chain.md`](workbook/sheet1-call-chain.md) 调用链展开。

---

## 1. 观测粒度（必读）

| 事实 | 对排障的含义 |
|------|--------------|
| **单次请求** 在客户端日志里通常有 **TraceID**（与 `TraceGuard` 一致的前缀）| 筛选条件应以 **TraceID = 本次失败调用** 为主，避免把其它请求混进来 |
| **Worker / 远端** 日志是否带同一 TraceID，取决于部署是否全链路透传 | 若只有 Client 日志带 Trace：能确定 Client 侧分支；Worker 行为需 **时间窗 + objectKey + 运维侧检索** |
| **分支在代码中存在** ≠ **本次日志一定能看见** | 例如未走 UB 时不会出现 `urma_*` 行；未覆盖分支需查 CI 覆盖率报告 |

**结论**：本手册的"全量分支"指 **产品设计 / 代码路径上应考虑的决策点**；**客户在一次工单中能严格证明的**，是 **该 Trace 上实际出现的日志 + SDK 返回码**。

---

## 2. 客户标准操作步骤（SOP）

按顺序执行；任一步可终止并出结论。

| 步骤 | 要做的事 | 产出 / 判据 |
|-----|----------|-------------|
| **1** | 记录 **API 名称**（如 `MGet`）、**参数摘要**（key 个数、timeout、是否 offset 读）、**返回值**（数值码 + 文本）| 一行"复现摘要" |
| **2** | 在同一秒级时间窗的 Client 日志中，找到该次调用的 **TraceID**（通常是前缀中 UUID/字符串）| `TRACE_ID` 字符串 |
| **3** | 在日志平台过滤：`TraceID == TRACE_ID`，时间窗 ±5s | 仅该请求的日志序列 |
| **4** | 按时间升序浏览，标出 **第一条 ERROR** 或 **第一条含失败语义的 INFO/WARN**（`failed` / `error` / `Return`）| `FIRST_FAIL_LINE` |
| **5** | 用 § 4 ~ § 6 **分支表**，根据 **返回码 + FIRST_FAIL_LINE 关键词** 圈定 **Branch_ID** | 1 个主分支 + 备选 |
| **6** | URMA 相关：同 Trace 额外检索 `urma\|URMA\|jfc\|IMPORT\|REGISTER\|poll\|fallback\|TCP/IP payload` | 是否 UB 面参与 |
| **7** | RPC 相关：同 Trace 检索 `rpc\|RPC\|deadline\|unavailable\|Send.*Get\|Send.*Publish\|multi publish\|Register client` | 是否链路超时 / 不可达 |
| **8** | 打开 Excel **Sheet5**，用现象 / 关键词找对应 **Dxx** 行，再跳到 Sheet1 调用链行 | 责任归属 + 下钻列 |
| **9** | 若需 Worker 侧确认：向运维提交 **TRACE_ID + key + 时间 UTC**，索取 Worker 同源 trace | 工单附件说明 |
| **10** | 性能类（非明确错误码）：同 Trace 时间窗收集耗时；对照 [`05-metrics-and-perf.md`](05-metrics-and-perf.md) | 是否尾延迟 / 排队 |

### 2.1 grep 模板（离线日志）

```bash
# 将 TRACE 替换为实际 ID
grep 'TRACE' client.log | grep -Ei 'error|fail|urma|rpc|deadline|mmap|NOT_FOUND|status'

# URMA 是否与该次请求同事务
grep 'TRACE' client.log | grep -Ei 'urma|jfc|IMPORT|fallback|TCP/IP payload'

# 广谱：RPC + URMA + 降级（已含 03 § 3.2 常用组合）
grep -E 'Register client failed|1001|1002|Failed to urma|fallback to TCP/IP payload|Failed to poll jfc|Urma connect unstable|1006|Query from master failed' client.log worker.log
```

### 2.2 访问日志第一列的陷阱

`KVClient::Get` 对 `K_NOT_FOUND` 的处理 —— access log 中记为 `K_OK(0)`：

```cpp
// src/datasystem/client/kv_cache/kv_client.cpp (Get)
StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode();
accessPoint.Record(code, ...);
```

**排障时**，若只看 access log 第一列，`K_NOT_FOUND` 看起来是成功。需结合 `rc.GetMsg()` 或上层返回值判断。

---

## 3. 先定"类"：OS / URMA / 系统（30 秒定界）

用 **SDK 返回的 `StatusCode` 数值** + **一侧日志关键词** 做第一刀；三者可叠加（例如先 RPC 超时再 URMA 失败），以 **最先出现且可复现的稳定信号** 为准。

| 第一刀信号 | 更可能 | 说明 |
|------------|--------|------|
| `K_URMA_ERROR(1004)`、`K_URMA_NEED_CONNECT(1006)`、`K_URMA_TRY_AGAIN(1008)` | **URMA** | 数据系统已把 URMA 路径映射为独立码段；新增的 `K_URMA_CONNECT_FAILED(1009)` / `K_URMA_WAIT_TIMEOUT(1010)` 同属 |
| `Prepare UB Get request failed` / `fallback to TCP/IP payload`（SDK **WARNING**）| **URMA 降级** | UB 池 / 信息获取失败时**不一定**向上返回 URMA 码，常**静默降级**为 TCP payload；功能可能仍成功 |
| `Get mmap entry failed`、`LookupUnitsAndMmapFd`、`Receive fd ... failed`、明确 errno/mmap 失败链 | **OS + SDK/Worker 衔接** | 多为 **fd / 共享内存 / 映射** 与内核交互；失败时常包成 `K_RUNTIME_ERROR(5)` |
| `K_IO_ERROR(7)`、`K_NO_SPACE(13)`、`K_SERVER_FD_CLOSED(29)` | **OS / 资源** | 偏磁盘 / 句柄 / 空间；也可能 Worker 侧资源耗尽 |
| `K_RPC_UNAVAILABLE(1002)`、`K_RPC_DEADLINE_EXCEEDED(1001)`、`K_TRY_AGAIN(19)` | **系统：RPC / 传输层** | 控制面或承载 RPC 的通道与对端可达性；**不是**业务"对象不存在" |
| `K_INVALID(2)`、`K_NOT_FOUND(3)`、`Read offset verify failed`、`etcd is unavailable`（Worker 明确串）| **系统：逻辑与依赖** | 参数、对象状态、元数据链、etcd 续约等 |

**口诀**：
- **1004 / 1006 / 1008 / 1009 / 1010** → 先当 **URMA 域**
- **mmap / fd / 空间** → 先当 **OS 域**，再分 **SDK 未收到合法 fd** / **内核 / 配额**
- **1001 / 1002 / 19** → 先当 **传输 / RPC**，再分叉 **SDK ↔ 入口 Worker** / **Worker ↔ 下游**（1002 respMsg 子类见 [`../reliability/06-playbook.md § 2`](../reliability/06-playbook.md)）
- **2 / 3 + 业务文案** → 先当 **系统逻辑**，少怪网卡

---

## 4. 再定"边"：SDK 问题还是 Worker 问题

| 现象 | 优先侧 | 下一步 |
|------|--------|--------|
| 同请求在 **SDK 日志** 已失败，**入口 Worker 无** `Get start from client` / 无对应 trace | **SDK ↔ 入口 Worker 之间**（传输 / L1）| 查连接、地址、防火墙、Worker 监听；属"系统"中的 **RPC 段** |
| **入口 Worker 有** Get 入口，随后 `Authenticate failed` | **Worker**（安全 / IAM 配置）| 查 AK/SK、租户、鉴权组件 |
| **入口 Worker 有** `etcd is unavailable` / `IsKeepAliveTimeout` | **Worker + etcd 依赖** | 属 **系统逻辑 + 运维依赖**；定界到 Worker 的 etcd 续约路径 |
| SDK `K_NOT_FOUND` 且 Worker 有远端 `Get from remote ... not exist` | **数据与元数据一致性**（多 Worker）| 问题在对象所在副本 / meta 指向，需第二个 Worker 日志 |
| SDK `K_RUNTIME_ERROR` + `Get mmap entry failed` | **SDK 进程内**（SHM 段）| 常见为未正确建立 mmap 表项 / fd 无效 |

---

## 5. 定"段"：链路 ①～⑥（与哪类问题对应）

正常远端读 6 步见 [`02-call-chain-and-syscalls.md § 4.3`](02-call-chain-and-syscalls.md)。

| 段 | 含义 | OS | URMA | 系统（RPC）| 系统（逻辑）|
|----|------|----|------|-------------|--------------|
| **①** | SDK → 入口 Worker 的 Get RPC | 少 | 一般不经过 | **主战场** | 鉴权、超时策略 |
| **②** | 入口 Worker 查元数据（含 etcd / Master）| 磁盘 / IO（L2）| — | 与 Master 的 RPC | **etcd 不可用**、meta 解析 |
| **③** | 入口 → 远端 Worker 控制 RPC | — | 可能并存 | **主战场** | 重连、切流 |
| **④** | 远端 → 入口 UB 数据面 | — | **主战场** | 降级则走 payload | 长度校验、重试 |
| **⑤** | 响应组包、`payload_info` / UB 填充 | — | 客户端 `FillUrmaBuffer` | payload 走 RPC | 溢出、part_index |
| **⑥** | 客户端 SHM mmap | **主战场** | — | — | fd 与 mmap 表一致性 |

**定界输出示例**：
- "URMA，段④，入口 Worker A → 远端 Worker B"
- "OS，段⑥，仅 SDK，mmap entry"

---

## 6. 定"模块"：SDK 与 Worker 各看谁

### 6.1 SDK（客户端）

| 模块 / 符号 | 责任 | 常见码 / 日志 |
|-------------|------|---------------|
| `KVClient` / `ObjectClientImpl::Get` | 入口、batch、就绪态 | `K_INVALID`、`K_NOT_READY` |
| `GetAvailableWorkerApi` / 切流 | 连哪台入口 Worker | `1002`、连接类 |
| `ClientWorkerRemoteApi::Get` | 签名、`stub_->Get`、`RetryOnError` | `Start to send rpc to get object` |
| `ClientWorkerBaseApi::PrepareUrmaBuffer` / `FillUrmaBuffer` | UB 请求侧 | WARNING fallback；`K_RUNTIME_ERROR` 溢出 |
| `ObjectClientImpl::MmapShmUnit` / `mmapManager_` | 段⑥ SHM | `Get mmap entry failed` |
| `UrmaManager` | URMA 设备 / 缓冲池 | `K_URMA_*`、底层 UMDK 日志 |

### 6.2 Worker（服务端）

| 模块 / 符号 | 责任 | 常见码 / 日志 |
|-------------|------|---------------|
| `WorkerOcServiceGetImpl::Get` | 读帧、鉴权、线程池派发 | `serverApi read request failed`、`RPC timeout` |
| `ProcessGetObjectRequest` | 总编排 | `Process Get failed` |
| `TryGetObjectFromLocal` | 本地缓存命中 | `not exist in memory`、`expired` |
| 元数据 + `etcdStore_` | 段② | **`etcd is unavailable`** |
| `GetObjectFromRemoteWorker*` / `GetObjectRemote*` | 段③④ 跨 Worker | `Get from remote failed` |
| `UrmaManager` / transport（Worker 侧）| 段④ UB 数据面 | 与 SDK 对称的 URMA 错误映射 |

---

## 7. 定"哪台 Worker"

| 角色 | 含义 | 怎么对齐 |
|------|------|----------|
| **W_entry（入口）** | SDK 当前 stub 连接并完成段① 的那台 | SDK 配置 / 路由日志中的 worker 地址；Worker 日志 `Get start from client:` + `clientId` |
| **W_remote（远端）** | 入口 Worker 拉取数据时对话的对端 | 入口 Worker 日志里带 address 的远端拉取（`Get from remote / GetObjectRemote`）；需同 trace / 时间窗 / objectKey |
| **W_meta（逻辑）** | 元数据认为的主副本 / 地址 | Master / etcd 查询结果；与 W_remote 不一致时归 **元数据或副本状态** 类问题 |

**实操**：一次读失败至少回答三句话 —— **SDK 连的是谁（W_entry）**、**日志里是否出现第二地址（W_remote）**、**失败 Status 是 RPC 类还是 NOT_FOUND / 业务类**。

---

## 8. 责任边界（集成 / 平台 / 三方件 / 数据系统）

| 层级 | 含义 | 典型归属 |
|------|------|----------|
| **L0 集成方** | 业务进程配置、超时、并发、K8s 探针、资源限额 | 业务 / 集成团队 |
| **L1 平台与网络** | 节点互通、安全组、DNS、端口监听、磁盘挂载、内核参数、宿主机 OOM | 平台 / SRE / 网络 |
| **L2 三方件** | etcd 可用性与性能、共享存储、观测系统 | 中间件 / 平台 |
| **L3 数据系统** | Worker / Master / SDK 逻辑、RPC、SHM / URMA、元数据与数据面协同 | 数据系统团队 |

**自证要点**：用同一时间线对齐 **客户端 `Status::ToString()` / access 日志**、**入口 Worker 日志**、**etcd 事件**（若可拿），避免仅凭 `K_RPC_UNAVAILABLE` 定责到单一侧。

---

## 9. 定界结论模板（工单可直接贴）

```text
【类】OS / URMA / 系统-RPC / 系统-逻辑（可多选，主因写第一）
【边】SDK / W_entry / W_remote / 依赖-etcd-Master
【段】①～⑥（填数字）
【模块】§ 6.1 或 § 6.2 中的符号
【证据】Status 数值 + msg；SDK 日志一行；Worker 日志一行（含实例标识）
```

---

## 10. 典型场景示例

### 10.1 UB 降级（功能成功但性能退化）

- **现象**：Get 返回 OK；SDK 日志含 `Prepare UB Get request failed ... fallback to TCP/IP payload`；CPU 占用与 `memcpy` 上升
- **定义**：URMA 准备失败 + 自动降级 TCP；功能可能成功，属 **URMA / 环境** 或 **资源** 问题
- **结论模板**：`URMA域 + client1 + UB缓冲准备，命中 "fallback to TCP/IP payload"，判断为UB降级，功能可能成功但性能退化`

### 10.2 1002 混合 URMA 抖动

- **现象**：`K_RPC_UNAVAILABLE`，respMsg 含 `has not responded within the allowed time`
- **定界**：按 [`../reliability/06-playbook.md § 2`](../reliability/06-playbook.md) 1002 桶码分流表，判定是"等回复超时"子类，不是 UB 坏；优先 L1 + L3 排查 RPC 通道

### 10.3 32 / 31 在 Get 批量路径不体现

- **现象**：集群扩缩容窗口，`KVClient::Get` 返回 `Status::OK()`，但业务层发现 per-object 缺失
- **原因**：`Get` 的 `RetryOnError` lambda 只对 `IsRpcTimeoutOrTryAgain` + 特定 OOM 触发重试；`last_rc == K_SCALING` 时 lambda 返回 OK 结束重试
- **建议**：业务侧看 per-object 状态；见 [`../reliability/06-playbook.md § 3`](../reliability/06-playbook.md)

### 10.4 Init 失败

- **现象**：`Init` 直接返回错误，access log 尚未记录本次调用
- **排查**：应用日志搜 `KVClient`、`Status`、`StatusCode`、`Register client failed`、`Cannot receive heartbeat from worker`
- **典型定界**：
  - `K_INVALID` → L0 集成方（HostPort / 超时参数）
  - `K_RPC_UNAVAILABLE` + `Get socket path failed` → L1/L3（Worker 未就绪 / 网络）
  - `K_CLIENT_WORKER_DISCONNECT(23)` → L1 + L3（首心跳路径）

---

## 11. 自动化判定（日志 → 责任域）

可以把日志规则做成简单的"模式匹配 + 打分"。

```python
def classify(log_line, status_code):
    if any(k in log_line for k in ["Failed to urma", "poll jfc", "advise jfr", "need to reconnect"]):
        return "URMA", "06-dependencies/urma.md"
    if any(k in log_line for k in ["recvmsg", "sendmsg", "mmap", "invalid fd", "Unexpected EOF read"]):
        return "OS", "06-dependencies/os-syscalls.md"
    if status_code in [1001, 1002, 19] or "Register client failed" in log_line:
        return "RPC", "02-call-chain-and-syscalls.md"
    return "系统逻辑", "03-fault-mode-library.md"
```

最小自动化输出字段：

- `接口`（Init / MGet / Get / MSet / Put）
- `发生位置`（client1 / client1→worker1 / worker1→worker2 / worker1→worker3 / worker3）
- `疑似责任域`（URMA / OS / RPC / 系统逻辑）
- `命中规则`（关键词）
- `建议下一步`（优先 FM-xxx；再查哪个 sheet / 哪个模块日志）
