# RFC: ZMQ RPC 队列时延可观测（自证清白 + 定界）

- **Status**: **In-Progress**（PR #706 已修复 ENABLE_PERF=false 时的 tick 记录问题）
- **Started**: 2026-04
- **Depended on**: PR #584（Add lightweight metrics framework）
- **Related PR**: PR #706（修复 ENABLE_PERF=false 时 metrics 无法打印的问题）

---

## 落地位置（datasystem）

所有 metric ID 定义于 `src/datasystem/common/metrics/kv_metrics.{h,cpp}`：

| Metric | 类型 | 采集位置 | 含义 |
|--------|------|----------|------|
| `ZMQ_CLIENT_QUEUING_LATENCY` | Histogram | Client: `zmq_stub_impl.cpp` | Client 框架队列等待 |
| `ZMQ_CLIENT_STUB_SEND_LATENCY` | Histogram | Client: `zmq_stub_conn.cpp` | Client Stub 发送 |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | Histogram | Server: `zmq_service.cpp` | Server 队列等待 |
| `ZMQ_SERVER_EXEC_LATENCY` | Histogram | Server: `zmq_service.cpp` | Server 业务执行 |
| `ZMQ_SERVER_REPLY_LATENCY` | Histogram | Server: `zmq_service.cpp` | Server 回复入队 |
| `ZMQ_RPC_E2E_LATENCY` | Histogram | Client: `zmq_stub_impl.cpp` | 端到端延迟 |
| `ZMQ_RPC_NETWORK_LATENCY` | Histogram | Client: `zmq_stub_impl.cpp` | 网络延迟 = E2E - ServerExec |

**根因对照表**：

| Metric | 可能根因 |
|--------|---------|
| `CLIENT_QUEUING_LATENCY` | MsgQue 队列堆积，prefetcher 处理不过来 |
| `CLIENT_STUB_SEND_LATENCY` | ZmqFrontend 线程繁忙，或 zmq_msg_send 系统调用慢 |

---

## 本目录文件

| 文件 | 说明 |
|------|------|
| [issue-rfc.md](issue-rfc.md) | Issue / RFC 文案模板 |
| [design.md](design.md) | 详细设计方案（Tick 定义、Metric 计算公式、正交性分析） |
| [test-walkthrough.md](test-walkthrough.md) | 测试串讲（规划中） |
| [results.md](results.md) | 验证记录（规划中） |

---

## 核心价值

1. **自证清白**：当 RPC 延迟高时，可明确区分是 Client 框架、Client Socket、Server 队列、Server 执行、Server 回复哪一端的问题
2. **网络延迟可计算**：通过 E2E - ServerExec 得出网络开销
3. **零 proto 修改**：复用现有的 `MetaPb.ticks` 字段传递时间戳

---

## 对外文档去向

- metric 清单与运行期读取方式 → [`docs/observable/05-metrics-and-perf.md`](../../docs/observable/05-metrics-and-perf.md)
