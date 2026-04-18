# RFC: ZMQ TCP/RPC Metrics 定界可观测

- **Status**: **Done**（代码已入 `yuanrong-datasystem` 主干）
- **Started**: 2026-04
- **Completed**: 2026-04
- **Depended on**: PR #584（Add lightweight metrics framework）

---

## 落地位置（datasystem）

所有 metric ID 定义于 `src/datasystem/common/metrics/kv_metrics.{h,cpp}`，采集点分布如下：

| 类别 | 指标 | 采集位置 |
|------|------|----------|
| I/O 延迟 | `ZMQ_SEND_IO_LATENCY`、`ZMQ_RECEIVE_IO_LATENCY` | `common/rpc/zmq/zmq_socket_ref.cpp`（`METRIC_TIMER`） |
| 错误计数 | `ZMQ_SEND_FAILURE_TOTAL`、`ZMQ_RECEIVE_FAILURE_TOTAL`、`ZMQ_SEND_TRY_AGAIN_TOTAL`、`ZMQ_RECEIVE_TRY_AGAIN_TOTAL` | 同上 |
| errno 追踪 | `ZMQ_LAST_ERROR_NUMBER` | 同上，`Gauge.Set(errno)` |
| 网络类错误 | `ZMQ_NETWORK_ERROR_TOTAL` | 同上 + `zmq_network_errno.h` 判定 |
| 事件侧 | `ZMQ_EVENT_DISCONNECT_TOTAL`、`ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL` | `common/rpc/zmq/zmq_monitor.cpp` |
| 网关 | `ZMQ_GATEWAY_RECREATE_TOTAL` | `common/rpc/zmq/zmq_stub_conn.cpp` |

**不修改错误码**；`StatusCode` 枚举保持不变，metrics 是新增维度。

---

## 本目录文件

| 文件 | 说明 |
|------|------|
| [design.md](design.md) | 三层指标体系设计、metric 清单、定界场景矩阵、分阶段实施计划（原 `plan-zmq-rpc-metrics-定界可观测.md`） |
| [test-walkthrough.md](test-walkthrough.md) | 测试串讲：故障注入、看哪些日志/metrics、误区与验收 Checklist |
| [results.md](results.md) | 构建与 UT/ST/Bazel 验证记录；含远端复核与故障注入日志验收摘要 |
| [issue-rfc.md](issue-rfc.md) | Issue / RFC 文案模板 |
| [pr-description.md](pr-description.md) | PR 描述模板 |

---

## 对外文档去向

- metric 清单与运行期读取方式 → [`docs/observable/05-metrics-and-perf.md`](../../docs/observable/05-metrics-and-perf.md)
- 1002 桶码 respMsg 分流表 → [`docs/reliability/06-playbook.md § 2`](../../docs/reliability/06-playbook.md)
