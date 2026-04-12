# KV / Client 视角：`StatusCode` 与跑测时故障审视

本文供 **夜间或大批量跑用例** 时对照：从日志与断言里识别 **client 可见的返回码**，并把 **尚未覆盖的组合**记进 `results/` 下的执行记录（见 [`results/README.md`](../../results/README.md)）。

**权威定义**（以 `yuanrong-datasystem` 为准，版本漂移时请 diff 该文件）：

- 枚举：`include/datasystem/utils/status.h` → `enum StatusCode`
- 默认英文文案：`src/datasystem/common/util/status_code.def`（`STATUS_CODE_DEF`；**未在 .def 中出现的码**仅有枚举名，消息以运行时 `Status` 为准）

源码级证据链（重试、RPC 映射等）：[deep-dives/client-status-codes-evidence-chain.md](deep-dives/client-status-codes-evidence-chain.md)。

FEMA 业务场景与基础设施故障清单：[00-kv-client-fema-scenarios-failure-modes.md](00-kv-client-fema-scenarios-failure-modes.md)。**本文不替代**该表，而是补上 **「现象 ↔ 数字码」** 这一层。

---

## 1. 全量 `StatusCode` 数值表（Client API 共用）

| 数值 | 枚举名 | 典型默认消息 / 含义（摘自 .def 或枚举注释） |
|------|--------|-----------------------------------------------|
| 0 | `K_OK` | OK |
| 1 | `K_DUPLICATED` | Key duplicated |
| 2 | `K_INVALID` | Invalid parameter |
| 3 | `K_NOT_FOUND` | Key not found |
| 4 | `K_KVSTORE_ERROR` | KV store error |
| 5 | `K_RUNTIME_ERROR` | Runtime error（含 executor 抛错等场景） |
| 6 | `K_OUT_OF_MEMORY` | Out of memory |
| 7 | `K_IO_ERROR` | IO error |
| 8 | `K_NOT_READY` | Not ready |
| 9 | `K_NOT_AUTHORIZED` | Not authorized |
| 10 | `K_UNKNOWN_ERROR` | Unknown error |
| 11 | `K_INTERRUPTED` | Interrupt detected |
| 12 | `K_OUT_OF_RANGE` | Out of range |
| 13 | `K_NO_SPACE` | No space available |
| 14 | `K_NOT_LEADER_MASTER` | Not leader master |
| 15 | `K_RECOVERY_ERROR` | Recovery error |
| 16 | `K_RECOVERY_IN_PROGRESS` | Recovery in progress |
| 17 | `K_FILE_NAME_TOO_LONG` | File name is too long |
| 18 | `K_FILE_LIMIT_REACHED` | FD 数量达到上限等 |
| 19 | `K_TRY_AGAIN` | Try again |
| 20 | `K_DATA_INCONSISTENCY` | Master/Worker 数据不一致 |
| 21 | `K_SHUTTING_DOWN` | Shutting down |
| 22 | `K_WORKER_ABNORMAL` | Worker 状态异常 |
| 23 | `K_CLIENT_WORKER_DISCONNECT` | Client 与 Worker 连接断开 |
| 24 | `K_WORKER_DEADLOCK` | Worker 可能死锁 |
| 25 | `K_MASTER_TIMEOUT` | Master 超时/不可用 |
| 26 | `K_NOT_FOUND_IN_L2CACHE` | L2 未命中（语义层） |
| 27 | `K_REPLICA_NOT_READY` | 副本未就绪 |
| 28 | `K_CLIENT_WORKER_VERSION_MISMATCH` | 版本不匹配 |
| 29 | `K_SERVER_FD_CLOSED` | 服务端 fd 已关闭 |
| 30 | `K_RETRY_IF_LEAVING` | Worker 正在退出，宜重试 |
| 31 | `K_SCALE_DOWN` | Worker 缩容退出中 |
| 32 | `K_SCALING` | 集群扩缩容进行中 |
| 33 | `K_CLIENT_DEADLOCK` | Client 侧死锁风险/检测 |
| 34 | `K_LRU_HARD_LIMIT` | LRU 硬限制 |
| 35 | `K_LRU_SOFT_LIMIT` | LRU 软限制 |
| 36 | `K_NOT_SUPPORTED` | （.def 未列；语义：不支持） |
| 1000 | `K_RPC_CANCELLED` | RPC cancelled / 通道意外关闭 |
| 1001 | `K_RPC_DEADLINE_EXCEEDED` | RPC deadline exceeded |
| 1002 | `K_RPC_UNAVAILABLE` | RPC unavailable（运维文档中常与超时/不可达并列讨论） |
| 1003 | `K_RPC_STREAM_END` | RPC stream finished |
| 1004 | `K_URMA_ERROR` | Urma operation failed |
| 1005 | `K_RDMA_ERROR` | （.def 未列；RDMA 错误） |
| 1006 | `K_URMA_NEED_CONNECT` | Urma needs to reconnect |
| 1007 | `K_RDMA_NEED_CONNECT` | Rdma needs to reconnect |
| 1008 | `K_URMA_TRY_AGAIN` | Urma failed, try again |
| 2000 | `K_OC_ALREADY_SEALED` | Object already sealed |
| 2001 | `K_OC_OBJECT_NOT_IN_USED` | （.def 未列） |
| 2002 | `K_OC_REMOTE_GET_NOT_ENOUGH` | 远端大小变化等 |
| 2003 | `K_WRITE_BACK_QUEUE_FULL` | Write back queue full |
| 2004 | `K_OC_KEY_ALREADY_EXIST` | Object key already exists |
| 2005 | `K_WORKER_PULL_OBJECT_NOT_FOUND` | Worker pull object not found |
| 3000–3010 | `K_SC_*` | Stream / Producer / Consumer 相关（见 `status.h`） |
| 5000 | `K_ACL_ERROR` | 设备侧 ACL API |
| 5001 | `K_HCCL_ERROR` | HCCL |
| 5002 | `K_FUTURE_TIMEOUT` | Future 超时 |
| 5003 | `K_CUDA_ERROR` | CUDA |
| 5004 | `K_NCCL_ERROR` | NCCL |

Python/Java/Go 最终会映射到上述语义；具体绑定以各 SDK 文档为准。

---

## 2. FEMA 故障模式 → 可能暴露的 `StatusCode`（启发式，非保证）

同一基础设施故障在不同路径上可能表现为 **RPC 层**或 **通用层** 多码；下列 **仅作 triage 起点**。

| FEMA 类别（见场景分册） | 客户端常见表现 | 宜优先对照的码 |
|-------------------------|----------------|----------------|
| Worker 宕机 / 反复重启 / 容器退出 | 连接失败、读写过半失败 | `K_RPC_UNAVAILABLE` (1002)、`K_CLIENT_WORKER_DISCONNECT` (23)、`K_SERVER_FD_CLOSED` (29) |
| Master 故障 / etcd 异常 | 路由/元数据长时间不可用 | `K_MASTER_TIMEOUT` (25)、`K_NOT_LEADER_MASTER` (14)、`K_TRY_AGAIN` (19)、RPC 超时类 |
| 网络闪断 / UB/TCP 丢包抖动 | 间歇失败、重试后可恢复 | `K_RPC_DEADLINE_EXCEEDED` (1001)、`K_TRY_AGAIN` (19)、`K_URMA_TRY_AGAIN` (1008) |
| URMA/RDMA 路径 | 远端读、高性能路径失败 | `K_URMA_ERROR` (1004)、`K_URMA_NEED_CONNECT` (1006)、`K_RDMA_ERROR` (1005)、`K_RDMA_NEED_CONNECT` (1007) |
| 缩容 / 主动下线 | 特定 key 连续失败、带「重试」语义 | `K_SCALE_DOWN` (31)、`K_RETRY_IF_LEAVING` (30)、`K_SCALING` (32) |
| 资源耗尽（内存 / 磁盘 / FD） | 批量操作失败 | `K_OUT_OF_MEMORY` (6)、`K_NO_SPACE` (13)、`K_FILE_LIMIT_REACHED` (18) |
| L2 / 缓存策略 | 未命中与淘汰 | `K_NOT_FOUND` (3)、`K_NOT_FOUND_IN_L2CACHE` (26)、`K_LRU_*` (34/35) |
| 业务逻辑 / 参数错误 | 稳定复现、与负载无关 | `K_INVALID` (2)、`K_NOT_FOUND` (3)、`K_DUPLICATED` (1) |

---

## 3. 跑用例时如何「审视」日志

在 **`$DS/build`** 或 **`ctest`/`ds_st_*` 完整输出** 中可配合：

```bash
# 数字码（日志里可能出现裸数字或枚举名）
grep -E 'StatusCode|GetCode\(\)|K_[A-Z_]+|code:\s*[0-9]+|\(100[0-9]\)|\b(23|25|31|32|1001|1002|1004)\b' "$RUN_DIR/log.txt" | head -200

# brpc / RPC 关键字（常与 1000–1008 同时出现）
grep -Ei 'rpc|brpc|deadline|unavailable|cancelled|URMA|RDMA' "$RUN_DIR/log.txt" | head -200
```

- **GTest 断言**：搜索 `EXPECT.*Status`、`ASSERT.*IsOk`、`GetCode()`。  
- **失败用例名**：`CrossAZ`、`ScaleDown`、`RemoteGet`、`Etcd` 等常与上表 **Master/Worker/RPC** 列相关。  
- 若失败主因是 **端口占用（errno 98）** 等环境问题，**不应**强行归因到某一 `StatusCode`；在记录里标注 **infra / parallel ctest**（见 [`cmake-non-bazel.md`](../verification/cmake-non-bazel.md) §9）。

---

## 4. 执行记录模板（可复制到 `results/<run>/CLIENT_FAULT_OBSERVATIONS.md`）

```markdown
# Client 故障抽样 — <日期> <run 标签>

## 环境
- DS SHA: 
- 命令: 
- 通过/失败: 

## 新观察（断言或日志中的码）

| 用例或日志片段 | StatusCode（名+数值） | 一句话场景 | 是否已在本表 §2 覆盖 |
|----------------|----------------------|------------|----------------------|
| | | | |

## 待验证假设
- 
```

---

## 5. 相关文档

| 文档 | 用途 |
|------|------|
| [00-kv-client-fema-index.md](00-kv-client-fema-index.md) | FEMA 总入口 |
| [00-kv-client-fema-scenarios-failure-modes.md](00-kv-client-fema-scenarios-failure-modes.md) | 业务流程与故障模式编号 |
| [client-worker-master-retry-fault-handling.md](../flows/narratives/client-worker-master-retry-fault-handling.md) | 重试与故障处理叙事 |
| [operations/](operations/) | 运维与 triage 长文 |
