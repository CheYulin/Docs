# Test Walkthrough: ZMQ RPC 队列时延可观测

## 测试计划（规划中）

### 1. UT 测试用例设计

| 用例 | 验证内容 |
|------|---------|
| `TickPropagationTest` | Server 追加的 tick 能正确传回 Client |
| `E2ELatencyTest` | E2E = CLIENT_RECV - CLIENT_ENQUEUE |
| `ClientFrameworkLatencyTest` | CLIENT_FRAMEWORK = CLIENT_TO_STUB - CLIENT_ENQUEUE |
| `ClientSocketLatencyTest` | CLIENT_SOCKET = CLIENT_SEND - CLIENT_TO_STUB |
| `ServerQueueWaitLatencyTest` | SERVER_QUEUE_WAIT = SERVER_DEQUEUE - SERVER_RECV |
| `ServerExecLatencyTest` | SERVER_EXEC = SERVER_EXEC_END - SERVER_DEQUEUE |
| `ServerReplyLatencyTest` | SERVER_REPLY = SERVER_SEND - SERVER_EXEC_END |
| `NetworkLatencyTest` | NETWORK = E2E - SERVER_EXEC |
| `BackwardCompatTest` | 旧 Server 无 SERVER_EXEC_NS 时 Client 行为 |

### 2. 故障注入测试

| 故障场景 | 预期观察 |
|---------|---------|
| Client 队列堆积 | CLIENT_FRAMEWORK 高 |
| Server 队列堆积 | SERVER_QUEUE_WAIT 高 |
| 网络延迟 | NETWORK 高 |
| Server 业务慢 | SERVER_EXEC 高 |

---

## 待完成

- [ ] 实现代码后补充具体测试步骤
- [ ] 补充远端验证命令
