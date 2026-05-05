# Test Walkthrough: ZMQ RPC 队列时延可观测

## 与实现对齐的验证点

以下 **Span 名** 仅用于测试用例设计；**Histogram 名字** 以 `kv_metrics.cpp` 导出为准（`zmq_*`）。

| 用例指向 | 关系式（wall tick，除非注明） | 对应 Histogram |
|----------|------------------------------|----------------|
| Client queuing | `CLIENT_TO_STUB − CLIENT_ENQUEUE` | `zmq_client_queuing_latency` |
| Server queue wait | `SERVER_DEQUEUE − SERVER_RECV` | `zmq_server_queue_wait_latency` |
| Server exec | `SERVER_EXEC_END − SERVER_DEQUEUE` | `zmq_server_exec_latency` |
| Server reply | `SERVER_SEND − SERVER_EXEC_END`（需 **EXEC_END 已打点**） | `zmq_server_reply_latency` |
| E2E | `CLIENT_RECV − CLIENT_ENQUEUE` | `zmq_rpc_e2e_latency` |
| Network（残差） | 见 `RecordRpcLatencyMetrics`（**非**单一墙钟差分） | `zmq_rpc_network_latency` |

**已删除的测试概念**：依赖 **`CLIENT_SEND`** 或 **`CLIENT_TO_STUB`** 之后单独拆 **「Client socket」** 段的用例——当前 **无** 该 wall tick **无** 独立 metric。

---

## 故障注入与预期（定性）

| 场景 | 预期偏高 |
|------|----------|
| Client 出站队列堆积 | `zmq_client_queuing_latency` |
| Server worker 队列堆积 | `zmq_server_queue_wait_latency` |
| 业务慢 | `zmq_server_exec_latency` |
| 回包路径慢（至 `SERVER_SEND` 前） | `zmq_server_reply_latency` |

**network 残差**：需结合 **e2e、client queuing、`SERVER_RPC_WINDOW_NS`** 一起看，不宜单行断言「网速」。

---

## 待办

- [ ] 在 ST/UT 中引用 `tests/ut/common/rpc/zmq_metrics_test.cpp`（或等价）中的 **fixture tick 序列**
- [ ] REPL：`scripts/` 下管线说明见 `run_commands.md`
