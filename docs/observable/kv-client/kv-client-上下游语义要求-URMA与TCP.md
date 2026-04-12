# KV Client：上游调用与下游 URMA / TCP 的语义要求与建议

本文给 **集成方（上游）** 与 **平台/网络/UMDK（下游）** 一份可评审的 **契约说明**：哪些由业务保证、哪些由部署保证、哪些由数据系统内部消化。证据链见同目录 **Sheet1～3** 与 `docs/flows/sequences/kv-client/README.md`。

---

## 1. 术语对齐

| 术语 | 含义 |
|------|------|
| **控制面** | Client↔Worker 的 RPC（ZMQ 等），携带元数据、`urma_info`、小 payload 等 |
| **数据面（UB）** | `urma_write`/`urma_read`/poll 完成队列等大流量路径 |
| **数据面（TCP payload）** | UB 不可用或主动降级时，数据走 RPC payload / 共享内存等 **非 UB** 路径 |
| **同节点** | Client 与 **入口 Worker** 调度在同一宿主机或可达 UDS，**SHM+fd** 可行 |
| **跨节点** | 首跳 RPC 即跨机（见 `kv_client_read_path_switch_worker_sequence.puml`） |

---

## 2. 上游（业务 / SDK 调用方）语义要求

### 2.1 通用

- **超时**：`subTimeoutMs` / RPC 超时需大于 **P99(首跳 RPC + 远端拉取 + UB 一轮 poll)**；否则易出现 **`K_RPC_DEADLINE_EXCEEDED`**，与「宕机」在现象上不可分（见读接口定界文档）。
- **幂等与重试**：`K_TRY_AGAIN`、`K_SCALING`、部分 `1002` 属于 **可重试窗口**；业务需 **限制重试次数** 并 **打齐 trace/request_id**（若环境支持）。
- **批量约束**：`MCreate`/`Get` batch 上限以 **`Validator::IsBatchSizeUnderLimit`** 为准；超限 **`K_INVALID`** 为 **纯上游错误**。

### 2.2 `Init`

- **凭证/租户**：AK/SK、租户、CURVE 材料错误时，优先 **`Authenticate failed`** 类消息；属 **L0（集成方）与密钥分发约定（L3）** 交界（见 `kv-场景-故障分类与责任边界.md`）。
- **SHM**：同节点场景需保证 **UDS 路径可写、fd 未泄露、ulimit** 足够；否则 Init 后业务期才暴露为 **mmap/fd** 失败。

### 2.3 `MCreate`

- **与切流关系**：当前实现 **`MultiCreate` 通过 `LOCAL_WORKER` API** 发起（见 `object_client_impl.cpp` 证据）；**不要假设** MCreate 与 MGet 使用相同的「动态 Worker 选择」策略。  
- **existence / SHM 阈值**：仅在 **需要 existence 检查** 或 **超过 shm 阈值** 时走 RPC；纯小对象可能 **纯客户端分配**——监控上要区分。

### 2.4 `MSet`（`MultiPublish`）

- **对象须已 Create 且未 seal**：否则 **`K_OC_ALREADY_SEALED`**（客户端直接返回）。
- **写放大**：`MultiPublish` 含 **Worker→Directory（对象目录）** 与 **Worker→Worker UB**；扩缩容窗口 **`K_SCALING`** 为 **预期可重试**，不是单一「bug」信号。

### 2.5 `MGet` / `Get`

- **`K_NOT_FOUND` 与 `last_rc`**：批量 Get 可能出现 **顶层 OK + per-key 未命中**；业务必须按 **key 级**处理（见读接口定界）。
- **UB fallback 日志**：`UB ... fallback to TCP/IP payload` 多为 **性能信号**；若 **成功率仍 OK**，告警应走 **P99/降级率**，而非按功能失败计。

---

## 3. 下游（UB / URMA / 设备）语义要求

### 3.1 设备与 bonding

- **设备名**：UB 模式依赖 **`urma_get_device_list`**；代码在配置名不匹配时尝试 **`bonding`** 前缀设备（见 `UrmaGetEffectiveDevice`）。  
- **建议**：部署清单中明确 **URMA 设备名、EID、是否 bonding**；版本升级时 **对比 `urma_get_device_list` 输出**。

### 3.2 `urma_status_t` vs `errno`

- 数据系统大量路径记录 **`ret = %d`（urma_status_t）**；仅部分 API 分支打印 **`errno`**。  
- **建议**：UMDK 问题单需同时抓取：**日志中的 ret、errno（若有）、`/var/log/umdk/urma`（若启用 register_log）**。

### 3.3 poll / wait / rearm 语义

- `PollJfcWait` **组合** `wait`/`poll`/`ack`/`rearm`；任一步失败会映射 **`K_URMA_ERROR`**。  
- **建议**：性能问题先看 **完成是否积压**（队列深度）、再看 **是否进入重连**（`K_URMA_NEED_CONNECT` 类，见 `CheckUrmaConnectionStable`）。

### 3.4 与 TCP 控制面的关系

- **控制面必须先稳定**：若 `stub_->Get` 已失败，不必再分析 UB（读路径分层见 `../archive/kv-client-读接口-定位定界.md` §7/§8）。  
- **建议排障顺序**：**① TCP 是否到入口 Worker** → **② 是否有 Worker 内远端失败日志** → **③ UB poll/write**。

---

## 4. 下游（TCP / ZMQ / UDS）语义要求

- **连接前置**：`1002` 且 **Worker 无入口日志** → 优先 **网络/监听/安全组**（L1）。  
- **半开连接**：`1000`/`Connect reset` 类 → 查 **对端重启、LB、idle timeout**。  
- **UDS**：与 **容器卷、权限、SELinux** 强相关；与 **bonding** 无直接对应，但 **多网卡** 可导致 **服务发现拿到错 IP** 进而 TCP 失败。

---

## 5. 对观测与告警的建议（跨上下游）

1. **分面指标**：控制面成功率（ZMQ）与 UB 降级率（fallback 日志计数）**不要混为一个 SLO**。  
2. **链路上下文**：告警携带 **入口 Worker、是否跨节点、是否 fallback、错误码桶**。  
3. **版本冻结**：UMDK 与数据系统 **同步版本号** 写入发布说明，避免 `urma_status_t` 枚举漂移。

---

## 6. 外部参考（非代码仓内证据）

- **openEuler UMDK**：URMA 作为 UBUS 相关子系统实现，源码托管在 **Gitee openEuler/u** 生态（具体包名以现场为准）。**`urma_api.h` 以安装包为准**。  
- 网络检索对 raw 头文件 **不稳定**，评审时 **以内网制品库或容器内 `/usr/include` 实际文件** 为权威。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 初版：上下游语义与建议 |
