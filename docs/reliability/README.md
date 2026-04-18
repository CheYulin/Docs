# KV Client 可靠性文档

本目录是 **datasystem KV Client** 可靠性（FEMA / 故障处理 / 定位定界）的设计文档。组织原则：**每一篇文档对应一段代码逻辑**，少而明确，按阅读顺序从架构到排障。

代码基线：同级 `yuanrong-datasystem/` 仓库。所有表格、故障树、错误码均以该仓库源码为准。

---

## 阅读顺序

| 序号 | 文档 | 主题 | 对应代码层 |
|-----|------|------|------------|
| 01 | [01-architecture-and-paths.md](01-architecture-and-paths.md) | 架构、组件、正常/切流读写路径（6 步） | `kv_client.cpp` / `object_client_impl.cpp` / `worker_worker_oc_service_impl.cpp` |
| 02 | [02-failure-modes-and-sli.md](02-failure-modes-and-sli.md) | 业务流程 × 53 条故障模式，关键时间量级与 2/N SLI 粗算 | —（清单型，无单点代码锚点） |
| 03 | [03-status-codes.md](03-status-codes.md) | 客户端可见 `StatusCode` 全表 + L0~L5 分层映射 | `include/datasystem/utils/status.h` / `status_code.def` |
| 04 | [04-fault-tree.md](04-fault-tree.md) | 错误码 → 根因故障树（6 大类），含源码证据链 | `zmq_*` / `unix_sock_fd.cpp` / `urma_manager.cpp` / `rpc_util.h` |
| 04a | [04a-fault-tree-by-interface.md](04a-fault-tree-by-interface.md) | Init / MCreate / MSet / MGet 接口级故障树 | `kv_client.cpp` / `object_client_impl.cpp` |
| 05 | [05-reliability-design.md](05-reliability-design.md) | 通信 / 组件 / 数据 / etcd 可靠性方案与不变量 | `listen_worker.cpp` / `etcd_cluster_manager.cpp` / `worker_oc_service_impl.cpp` |
| 06 | [06-playbook.md](06-playbook.md) | 运维排障：部署/扩缩容、1002 三元化、31/32 可见性、`resource.log` | `res_metrics.def` / `client_worker_remote_api.cpp` |
| R | [references.md](references.md) | openYuanrong 官方文档入口、DryRun 模板 | —（外部） |

---

## 专项深挖（按需阅读）

`deep-dives/` 只放"高信息密度但非首次必读"的专题：

- [deep-dives/etcd-isolation-and-recovery.md](deep-dives/etcd-isolation-and-recovery.md) — Worker etcd 续约失败 → 快速隔离 / 轻量重连 / 被动缩容 SIGKILL 完整链路与参数调优
- [deep-dives/timeout-and-latency-budget.md](deep-dives/timeout-and-latency-budget.md) — 超时参数语义（`node_timeout_s` / `node_dead_timeout_s` / `requestTimeoutMs` 等），5ms/20ms 短超时下的重试行为
- [deep-dives/client-lock-rpc-logging.md](deep-dives/client-lock-rpc-logging.md) — 客户端锁内 RPC / spdlog flush 导致 bthread 阻塞的风险治理

---

## 图与时序

- 读写主路径时序：`../flows/sequences/kv-client/`
- 故障处理配图（PlantUML）：[diagrams/kv-client/](diagrams/kv-client/)

---

## 维护约定

1. **对齐代码**：文档顶部固定列出本篇对应的 datasystem 源码文件；代码变更后同步更新。
2. **不复述**：每个主题只在一处展开，其它文档引用即可；禁止为"导航"单独建文件。
3. **不引用 `plans/`**：`plans/` 是开发用工作区，`docs/` 自包含。
4. **新增文档先问**：新增主线文档必须能回答"这篇对应哪段代码逻辑、为什么现有文件装不下"。
