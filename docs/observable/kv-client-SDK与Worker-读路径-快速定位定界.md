# 读路径（Get/MGet）：SDK 与 Worker 快速定位定界（OS / URMA / 系统）

目标：**尽快判断** 故障属于 **OS（内核/系统调用语义）**、**URMA（UMDK/设备/数据面）**，还是 **系统本身（数据系统逻辑 + RPC 传输框架）**；若是系统本身，再落到 **哪一段链路、哪个模块、哪台 Worker**。

**分析对象只有两个**：**SDK（客户端进程）** 与 **Worker（服务端进程）**。第三方（etcd、Master、网络设备）通过 Worker 日志与返回码间接判定。

配套（细节与代码证据）：
- [kv-client-读接口-定位定界.md](./kv-client-读接口-定位定界.md)
- [kv-client-Get路径-树状错误矩阵.md](./kv-client-Get路径-树状错误矩阵.md)
- `docs/flows/sequences/kv-client/kv_client_read_path_normal_sequence.puml`（①～⑥ 分段）

---

## 1. 先定「类」：OS / URMA / 系统（30 秒）

用 **SDK 返回的 `StatusCode`（数值）** + **一侧日志关键词** 做第一刀；三者可叠加（例如先 RPC 超时再 URMA 失败），以 **最先出现且可复现的稳定信号** 为准。

| 第一刀信号 | 更可能 | 说明 |
|------------|--------|------|
| `K_URMA_ERROR`(1004)、`K_URMA_NEED_CONNECT`(1006) | **URMA** | 数据系统已把 URMA 路径映射为独立码段，见 `include/datasystem/utils/status.h`。 |
| `Prepare UB Get request failed` / `fallback to TCP/IP payload`（SDK **WARNING**） | **URMA 降级** | UB 池/信息获取失败时 **不一定** 向上返回 URMA 码，常 **静默降级** 为 TCP payload；功能可能仍成功，属 **URMA/环境** 或 **资源** 问题。 |
| `Get mmap entry failed`、`LookupUnitsAndMmapFd`、`Receive fd ... failed`、明确 **errno/mmap 失败** 链 | **OS + SDK/Worker 衔接** | 多为 **fd/共享内存/映射** 与内核交互；数据系统在失败时往往包成 `K_RUNTIME_ERROR`(5) 等，需结合日志区分「内核拒绝」与「逻辑未注册 fd」。 |
| `K_IO_ERROR`(7)、`K_NO_SPACE`(13)、`K_SERVER_FD_CLOSED`(29) | **OS/资源** 或 **严重运行时** | 偏磁盘/句柄/空间；也可能是 Worker 侧资源耗尽后的表现。 |
| `K_RPC_UNAVAILABLE`(1002)、`K_RPC_DEADLINE_EXCEEDED`(1001)、`K_TRY_AGAIN`(19) | **系统：RPC/传输层** | 控制面或承载 RPC 的通道（如 ZMQ/brpc）与对端可达性、超时；**不是**业务「对象不存在」。 |
| `K_INVALID`(2)、`K_NOT_FOUND`(3)、`Read offset verify failed`、`etcd is unavailable`（Worker 明确串） | **系统：逻辑与依赖** | 参数、对象状态、元数据链、etcd 续约等 **数据系统与业务规则**。 |

**口诀**  
- **1004/1006** → 先当 **URMA 域**。  
- **mmap/fd/空间** → 先当 **OS 域**，再查是 **SDK 未收到合法 fd** 还是 **内核/配额**。  
- **1001/1002/19** → 先当 **传输/RPC**，再分叉 SDK 连不上 **入口 Worker** 还是 Worker 连不上 **下游**。  
- **2/3 + 业务文案** → 先当 **系统逻辑**，少怪网卡。

---

## 2. 再定「边」：SDK 问题还是 Worker 问题

| 现象 | 优先侧 | 下一步 |
|------|--------|--------|
| 同请求在 **SDK 日志**已失败，**入口 Worker 无** `Get start from client` / 无对应 trace | **SDK ↔ 入口 Worker 之间**（传输/L1） | 查连接、地址、防火墙、Worker 监听；仍属「系统」中的 **RPC 段**，不是业务模块 bug 的先验。 |
| **入口 Worker 有** Get 入口，随后 `Authenticate failed` | **Worker**（安全/IAM 配置） | 查 AK/SK、租户、鉴权组件。 |
| **入口 Worker 有** `etcd is unavailable` / `IsKeepAliveTimeout` | **Worker + etcd 依赖** | 属 **系统逻辑 + 运维依赖**；定界到 **该 Worker 的 etcd 续约路径**，非 SDK。 |
| SDK `K_NOT_FOUND` 且 Worker 有 **远端** `Get from remote ... not exist` | **数据与元数据一致性**（多 Worker） | 入口 Worker 已工作；问题在 **对象所在副本 / meta 指向**，需 **第二个 Worker** 日志。 |
| SDK `K_RUNTIME_ERROR` + `Get mmap entry failed` | **SDK 进程内**（SHM ⑥ 段） | 常见为 **未正确建立 mmap 表项** 或 **fd 无效**；若 Worker 已发 fd 而 SDK 失败，查 **SDK 版本/重组/同机条件**。 |

---

## 3. 定「段」：链路 ①～⑥（与哪类问题对应）

| 段 | 含义（简写） | OS | URMA | 系统（RPC） | 系统（逻辑） |
|----|----------------|----|------|-------------|--------------|
| **①** | SDK → **入口 Worker** 的 Get RPC | 少 | 一般不经过 | **主战场** | 鉴权、超时策略 |
| **②** | 入口 Worker **查元数据**（含 etcd / Master） | 磁盘/IO（L2） | — | 与 Master 的 RPC | **etcd 不可用**、meta 解析 |
| **③** | **入口 → 远端 Worker** 控制 RPC | — | 可能并存 | **主战场** | 重连、切流 |
| **④** | **远端 → 入口** UB 数据面 | — | **主战场** | 降级则走 payload | 长度校验、重试 |
| **⑤** | 响应组包、`payload_info` / UB 填充 | — | 客户端 **FillUrmaBuffer** | payload 走 RPC | 溢出、part_index |
| **⑥** | 客户端 **SHM mmap** | **主战场** | — | — | fd 与 mmap 表一致性 |

定界输出示例（写法）：**「URMA，段④，入口 Worker A → 远端 Worker B」** 或 **「OS，段⑥，仅 SDK，mmap entry」**。

---

## 4. 定「模块」：SDK 与 Worker 各看谁

### 4.1 SDK（客户端）

| 模块/符号 | 责任 | 常见码/日志 |
|-----------|------|-------------|
| `KVClient` / `ObjectClientImpl::Get` | 入口、batch、就绪态 | `K_INVALID`、`K_NOT_READY` |
| `GetAvailableWorkerApi` / 切流 | **连哪台入口 Worker** | `1002`、连接类 |
| `ClientWorkerRemoteApi::Get` | 签名、`stub_->Get`、`RetryOnError` | `Start to send rpc to get object` |
| `ClientWorkerBaseApi::PrepareUrmaBuffer` / `FillUrmaBuffer` | UB 请求侧 | WARNING fallback；`K_RUNTIME_ERROR` 溢出 |
| `ObjectClientImpl::MmapShmUnit` / `mmapManager_` | ⑥ SHM | `Get mmap entry failed` |
| `UrmaManager` | URMA 设备/缓冲池 | `K_URMA_*`、底层 UMDK 日志 |

### 4.2 Worker（服务端）

| 模块/符号 | 责任 | 常见码/日志 |
|-----------|------|-------------|
| `WorkerOcServiceGetImpl::Get` | 读帧、鉴权、线程池派发 | `serverApi read request failed`、`RPC timeout` |
| `ProcessGetObjectRequest` | 总编排 | `Process Get failed` |
| `TryGetObjectFromLocal` | 本地缓存命中 | `not exist in memory`、`expired` |
| 元数据 + `etcdStore_` | ② | **`etcd is unavailable`** |
| `GetObjectFromRemoteWorker*` / `GetObjectRemote*` | ③④ 跨 Worker | `Get from remote failed` |
| `UrmaManager` / transport（Worker 侧） | ④ UB 数据面 | 与 SDK 对称的 URMA 错误映射 |

---

## 5. 定「哪台 Worker」：入口 vs 远端

| 角色 | 含义 | 怎么对齐 |
|------|------|----------|
| **W_entry（入口）** | SDK **当前 stub 连接**并完成 ① 的那台 | SDK 配置/路由日志中的 **worker 地址**；Worker 日志 **`Get start from client:`** + `clientId`。 |
| **W_remote（远端）** | 入口 Worker **拉取数据**时对话的对端 | 入口 Worker 日志里 **带 address 的远端拉取**（如 `Get from remote` / `GetObjectRemote` 相关上下文）；需 **同一 trace / 时间窗 / object key**。 |
| **W_meta（逻辑）** | 元数据认为的 **主副本/地址** | Master/etcd 查询结果；与 W_remote 不一致时归 **元数据或副本状态** 类问题。 |

**实操**：一次读失败至少回答三句话——**SDK 连的是谁（W_entry）**、**日志里是否出现第二地址（W_remote）**、**失败 Status 是 RPC 类还是 NOT_FOUND/业务类**。

---

## 6. 定界结论模板（可直接贴工单）

```text
【类】OS / URMA / 系统-RPC / 系统-逻辑（可多选，主因写第一）
【边】SDK / W_entry / W_remote / 依赖-etcd-Master
【段】①～⑥（填数字）
【模块】上表 4.1 或 4.2 中的符号
【证据】Status 数值 + msg；SDK 日志一行；Worker 日志一行（含实例标识）
```

---

## 7. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 初版：双对象（SDK/Worker）+ OS/URMA/系统 + 段/模块/Worker |
