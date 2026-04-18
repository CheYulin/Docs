# RFC: KVClient URMA/TCP 可观测与可靠性整改

- **Status**: **Done**（代码已入 `yuanrong-datasystem` 主干）
- **Started**: 2026-04
- **Completed**: 2026-04

---

## 落地位置（datasystem）

| 改动点 | 位置 | 证据 |
|-------|------|------|
| URMA wait 超时新错误码 | `include/datasystem/utils/status.h` | `K_URMA_WAIT_TIMEOUT = 1010` |
| URMA 建连失败新错误码 | `include/datasystem/utils/status.h` | `K_URMA_CONNECT_FAILED = 1009` |
| URMA wait 超时返回改写 | `src/datasystem/common/rdma/rdma_util.h::Event::WaitFor` / `EventWaiter::WaitAny` | 由 `K_RPC_DEADLINE_EXCEEDED` 改为 `K_URMA_WAIT_TIMEOUT` |
| `CheckUrmaConnectionStable` 增加 WARNING 日志 | `src/datasystem/common/rdma/urma_manager.cpp` | 重连触发时刻可定位 |
| `ServerEventHandleThreadMain` 处理 `PollJfcWait` 错误 | 同上 | 不再隐藏 URMA 异常 |
| URMA 关键操作 Trace 上下文 | 同上 | 跨 Worker 可串联 |

---

## 本目录文件

| 文件 | 说明 |
|------|------|
| [design.md](design.md) | 问题分析（9 项 P0-P2）+ 代码修改方案 + 分阶段实施计划（原 `kv-client-可观测与可靠性-问题分析与代码修改计划.md`） |
| [env-validation.md](env-validation.md) | 有 URMA 环境时的验证步骤、验收点与回填模板（原 `kv-client-URMA环境验证执行清单.md`） |
| [zmq-reconnect-analysis.md](zmq-reconnect-analysis.md) | ZMQ 重连场景分析（历史调研） |
| [test-walkthrough-observability-enhancement.md](test-walkthrough-observability-enhancement.md) | 可观测定位定界增强测试串讲（原 `KVClient-可观测定位定界增强-测试串讲.md`） |
| [issue-rfc.md](issue-rfc.md) | Issue / RFC 文案模板 |
| [pr-description.md](pr-description.md) | PR 描述模板 |

---

## 与另一 RFC 的关系

- 本 RFC 聚焦 **URMA 错误码语义修复和故障日志补齐**（数据面）
- [2026-04-zmq-rpc-metrics/](../2026-04-zmq-rpc-metrics/README.md) 聚焦 **ZMQ 通信栈的 metrics 指标建设**（控制面/传输面）
- 两者互补：URMA 覆盖数据面，ZMQ metrics 覆盖控制面/传输面

---

## 对外文档去向

实施完成后，相关设计沉淀到 `docs/`：

- 新错误码 → [`docs/reliability/03-status-codes.md § 1.2`](../../docs/reliability/03-status-codes.md)
- URMA 故障定界 → [`docs/observable/06-dependencies/urma.md`](../../docs/observable/06-dependencies/urma.md)
- URMA 三码与重连路径 → [`docs/reliability/04-fault-tree.md § 2.2`](../../docs/reliability/04-fault-tree.md)
