# KV 客户端视角：分析报告归档

本文档归档「从 E2E 指标（P99、成功率）与部署场景出发」的分析结论，与 [KV_CLIENT_TRIAGE_PLAYBOOK.md](./KV_CLIENT_TRIAGE_PLAYBOOK.md)（access log 自导）配合使用。**树状故障检测与排查**（TP99 × 成功率、责任方、影响与措施）：见 [KV_CLIENT_FAULT_TRIAGE_TREE.md](./KV_CLIENT_FAULT_TRIAGE_TREE.md)。**处理边界、故障定义、URMA/OS 指标分解、客户配合与无法定界时操作**：见 [KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md](./KV_CLIENT_FAULT_SCOPE_AND_DEFINITIONS.md)。

**范围说明**：**不包含鉴权逻辑**（如 Token/AKSK）；聚焦 [cases.md](./cases.md) 中的**故障模式**及 [可靠性设计](./cases.md#可靠性设计) 中的**处理机制**在客户端侧的映射。

**业务场景 Case 全量**（业务流程、故障模式、关键读写路径、可靠性表）：见 [cases.md](./cases.md)。**报告二** 与业务流程、读写路径对照；**报告三** 与故障模式、处理机制对照。

**流程图（PlantUML）**：见 [diagrams/](./diagrams/) 目录。

**系统可靠性方案**（与 cases 交叉引用、含 UB **~128ms / ~133ms** 等口径与 triage 对齐说明）：[FAULT_HANDLING_AND_DATA_RELIABILITY.md](./FAULT_HANDLING_AND_DATA_RELIABILITY.md)；方案配图见 [diagrams/README.md](./diagrams/README.md#fault-handling-diagrams)。

---

## 报告一：从 P99 时延、成功率出发 — 观测、定界、与错误码的边界

### 1. 从成功率出发

| 观测形式 | 可能含义 | 定界（DryRun 风格） | 错误码能做什么 | 需其它手段时 |
|----------|----------|---------------------|----------------|--------------|
| KV Get/Set 成功率下降（监控平台、业务 SLI） | 端到端失败或部分 key 失败 | 负载均衡器/网关时延 → 业务请求处理实例/SDK 日志 → StatusCode 与 Worker IP:Port | `K_RPC_DEADLINE_EXCEEDED` / `K_FUTURE_TIMEOUT`：预算耗尽；`K_RPC_UNAVAILABLE`：链路；`K_URMA_*`：UB；`K_NOT_FOUND`：缺 key | 同码多因：TCP 与 UB 都可能 1001 → 网卡/交换机/UB 指标、抓包、Jetty |
| 间歇失败、重试后成功 | 抖动、扩缩容窗口 | 是否 `K_TRY_AGAIN`、`K_SCALING`、batch 部分成功 | 区分可重试与数据缺失 | RPC 重试次数、迁移时间窗 |
| 客户端未就绪 | 启动阶段请求 | Init 顺序 | `K_NOT_READY` | 编排/健康检查 |

### 2. 从 P99 时延出发

| 观测形式 | 可能含义 | 定界 | 错误码/辅助 | 硬件/网络手段 |
|----------|----------|------|-------------|----------------|
| P99 升高、错误率仍低 | 排队、重试叠加、跨机、UB→TCP 降级 | 对比本机 Worker vs 远端；是否刚切流 | `K_URMA_TRY_AGAIN`、重试路径；Perf CLIENT_GET 等 | UB 降 lane、Jetty 拥塞；TCP RTT/丢包 |
| P99 与失败同时出现 | 超时边缘 | 对齐业务 timeout 与 RPC 最小预算 | `K_RPC_DEADLINE_EXCEEDED` (1001) | TCP 重试间隔、UB 检测时间窗 |
| 长尾仅在扩缩容窗口 | 路由变更 | 运维事件与 etcd/元数据 | `K_SCALING`、`K_RETRY_IF_LEAVING` | 网络分区时延 |

### 3. 结论（客户端视角）

- 错误码适合作为 **第一层** 分类：RPC vs URMA vs 未就绪 vs 未找到。
- **1001 / 1002 / 1004** 往往无法单独区分「TCP 网卡」与「UB 交换机」等根因，需结合 **监控、Worker 日志、TraceID、（规划中的）对端 IP:Port 回传**。

---

## 报告二：部署与流程 DryRun — 可恢复性与不可恢复范围

**说明**：客户端可见行为由 `GetAvailableWorkerApi`、`CheckConnection`、`workerApi->Get/Publish` 等路径决定；集群内多跳对 SDK 常表现为 RPC/URMA 超时或错误。[cases.md](./cases.md) 中的 **正常读写** / **SDK 切流** 路径用于对照跨机元数据、拉取、UB Write、Get resp 超时等定界。

### 部署与运维场景（与 cases.md「业务流程」对齐）

| 场景 | cases.md 对应 | 客户端路径特征 | 典型现象 | 主要 StatusCode | 可恢复性（按设计意图） |
|------|----------------|----------------|----------|-----------------|------------------------|
| 部署：本机有 KVCache worker | 业务流程 1、4 | 本地 RPC + 本机 SHM | 成功率高、P99 低 | `K_OK` | 是 |
| 部署：本机无 worker | 业务流程 2、6 | 远端 RPC，无本机 SHM | P99 上升 | `K_RPC_*`, `K_URMA_*` | 切流/建链后可恢复 |
| KVCache worker 实例部署 | 业务流程 3 | 集群出现新 worker，路由渐变 | 短暂路由变化 | `K_TRY_AGAIN`, `K_SCALING`（视实现） | 是 |
| 本节点未命中，跨节点读 | 业务流程 5 | Get 触发跨 worker 拉取 | 拉取慢 → P99 | `K_RPC_DEADLINE_EXCEEDED`, `K_WORKER_PULL_OBJECT_NOT_FOUND` | 数据在则可恢复 |
| SDK 切流（异常读写路径） | cases「切流 Case」 | client→远端入口跨机为主 | 短时失败 + 建链时延 | `K_CLIENT_WORKER_DISCONNECT`, `K_NOT_READY` | 是 |
| 业务实例扩容 / 缩容 | 业务流程 7、8 | Init/连接数变化 | 短暂异常 | `K_NOT_READY` 等 | 是 |
| KVCache worker 扩容 / 缩容 | 业务流程 9、10 | 分片迁移 | 抖动 | `K_SCALING`, `K_TRY_AGAIN`, `K_RETRY_IF_LEAVING` | 是 |
| Worker 故障；数据自动恢复 | 业务流程 11 | 心跳丢失 → 切流；后台恢复 | 秒级失败窗口；恢复期可读失败 | `K_CLIENT_WORKER_DISCONNECT`, `K_RPC_UNAVAILABLE`, `K_NOT_FOUND` 等 | 隔离后业务恢复；数据依赖二级存储与容量 |
| etcd 不可用 | cases 故障 etcd | 控制面降级 | 发现/扩缩容弱 | 未必直报 etcd；可能 `K_MASTER_TIMEOUT` | 控制面随 etcd 恢复 |
| 二级存储故障 | cases 可靠性 | 持久化/加载失败 | 长期缺数据或旧数据 | `K_IO_ERROR`, `K_RECOVERY_*`, `K_NOT_FOUND` | **数据面可能不可完全恢复** |

上表中 **KVCache worker 扩容/缩容** 已含缩容时的 `K_RETRY_IF_LEAVING`、`K_SCALE_DOWN`。

### 不可恢复或仅部分可恢复（客户端边界）

1. **数据已丢失或未加载**：多表现为 `K_NOT_FOUND` / `K_WORKER_PULL_OBJECT_NOT_FOUND`，与「key 不存在」码可能相同，需结合恢复进度与 Worker 元数据。
2. **版本长期不一致**：`K_CLIENT_WORKER_VERSION_MISMATCH` — 需发布与滚动升级对齐，非单靠自动重试。
3. **双路径同时不可用且在超时内无响应**：单次请求失败；链路恢复后后续请求可恢复。

---

## 报告三：cases.md 故障模式 ↔ 可靠性处理机制（客户端视角）

下表依据 [cases.md § 可靠性设计](./cases.md#可靠性设计)（**通信故障处理方案**、**整体可靠性方案**），将 **故障模式大类** 与 **系统侧处理机制**、**客户端典型表现** 做归纳；**不包含鉴权**。

### 3.1 通信类（TCP / UB）— 与 cases「通信故障处理方案」对应

| 故障模式（cases § 故障模式） | 处理机制（摘要） | 客户端典型表现 / 码 |
|------------------------------|------------------|---------------------|
| TCP 网卡 down/抖动/闪断/两口故障/交换机等（编号 32–38 等） | 超时内 **RPC 重试**；多档 TCP 重试间隔；**最小 RPC 预算**耗尽则退出；端口切换后恢复 | `K_RPC_DEADLINE_EXCEEDED`、`K_RPC_UNAVAILABLE`；成功率/P99 随窗口劣化 |
| UB 端口/芯片/交换机（25–31、39–42）与 Jetty 异常 | **检测后 TCP 回退**；未检测到时随用户超时（如 20ms）报错；硬件感知约 128ms 量级；Jetty 不可用则**重连**、必要时 **切 TCP**；平面恢复后 URMA 自愈 | `K_URMA_*`、超时；精排偏成功率，召排偏 **TP99**（降 lane 等） |

### 3.2 主机、容器、进程类 — 与 cases「整体可靠性方案」对应

| 故障模式（cases） | 处理机制（摘要） | 客户端典型表现 / 码 |
|-------------------|------------------|---------------------|
| OS 重启 / Panic / BMC（1–3） | 节点与进程不可用，依赖**切流与集群恢复**（同 Worker 故障类） | 连接失败、心跳失败 → `K_CLIENT_WORKER_DISCONNECT`、`K_RPC_UNAVAILABLE` |
| 主机资源不足、内存故障、时间跳变（4–11） | 进程 Crash、**故障隔离**；时间异常导致超时/重试乱序 | `K_RUNTIME_ERROR`、`K_OUT_OF_MEMORY`、`K_RPC_DEADLINE_EXCEEDED` 等 |
| Client/Worker 容器或进程异常、挂死、反复重启（12–24） | Worker：**etcd 心跳 + 隔离 + 元数据重分布**；SDK：**心跳检测 + 切流**；SDK 异常：**清理 SHM** | `K_CLIENT_WORKER_DISCONNECT`、`K_NOT_READY`；切流窗口内失败 |
| UBSE / UBM 进程故障（17–18） | 归入 UB 链路或主机组件恢复，常体现为 URMA/Jetty 不可用路径 | `K_URMA_*`、建链失败 |

### 3.3 控制面与持久化 — 与 cases「整体可靠性方案」对应

| 故障模式（cases） | 处理机制（摘要） | 客户端典型表现 / 码 |
|-------------------|------------------|---------------------|
| etcd 集群不可用、脑裂、网络中断（43–48） | **KVC 降级**；数据面读写删除**通常仍可进行**；与 etcd **重连直至恢复** | 未必直报 etcd；服务发现/扩缩容/隔离能力受限；可能 `K_MASTER_TIMEOUT` 等 |
| 分布式网盘慢/中断/时延抖动/丢包（49–53） | 与 **二级存储**、异步持久化/加载相关；见 cases「二级存储故障」 | `K_IO_ERROR`、`K_RECOVERY_*`；恢复中 `K_NOT_FOUND` 等 |

### 3.4 小结

- **处理机制**的权威展开仍以 **cases.md 可靠性设计表格**为准；本报告三为 **客户端视角索引**，便于与报告一错误码、报告二部署场景联读。
- **TCP 与 UB** 在短超时场景下的语义（是否回退、是否直接失败）见 [REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md](./REMOTE_META_VS_DATA_FAILURE_OBSERVABILITY.md)。

### 时间指标与单点故障粗算（观测 SLI）

[cases.md](./cases.md) 中 **「时间指标与单点故障影响（粗算）」** 一节汇总了可靠性表里的 **2s/3s、100ms、20ms、128ms** 等与 **成功率/P99** 的对应关系，并给出单点故障下工程粗算：

\[
\text{粗算失败占比} \approx \frac{2}{N} \times \frac{T_{\mathrm{剔除}}}{T_{\mathrm{monitor}}}
\]

示例：\(N=64\)，\(T_{\mathrm{剔除}}=3\,\mathrm{s}\)，\(T_{\mathrm{monitor}}=5\,\mathrm{s}\) → **2/64 × 3/5 ≈ 1.875%**（详见 cases 原文与符号说明）。

---

## 与仓库代码的索引

| 主题 | 路径 |
|------|------|
| KV 对外 API | `include/datasystem/kv_client.h` |
| Status 枚举 | `include/datasystem/utils/status.h` |
| 读路径 | `src/datasystem/client/object_cache/object_client_impl.cpp`（`GetBuffersFromWorker` 等） |
| 心跳/断连 | `src/datasystem/client/listen_worker.cpp` |

---

## 修订记录

- 与 [cases.md](./cases.md) 业务流程对齐；补充部署表「cases.md 对应」列。
- **报告三**：按 cases **故障模式** 归类，对齐 **可靠性设计中的处理机制**；**剔除鉴权**相关表述，聚焦通信/组件/etcd/存储。
- 引用 cases **时间指标与单点粗算**（2/N×T_剔除/T_监控）及与 SLI 对齐说明。
