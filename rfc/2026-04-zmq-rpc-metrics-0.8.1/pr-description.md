# /kind feature

**这是什么类型的 PR？**

/kind feature（可观测性增强；不改错误码、不改对外接口、不改网络协议）

---

**这个 PR 做了什么 / 为什么需要**

修复 ZMQ metrics 在 `ENABLE_PERF=false` 时无法分段时间的问题。

当 `ENABLE_PERF=false` 时，原来的 `GetLapTime()` 和 `GetTotalTime()` 直接返回 0，导致 RPC tracing metrics 无法工作。本 PR 通过新增 `RecordTick()` 和 `GetTotalElapsedTime()` 函数（始终生效，不受 `ENABLE_PERF` 控制）解决了这个问题。

1. **始终记录 tick**
   新增 `RecordTick()` 函数，始终记录 tick，不受 `ENABLE_PERF` 控制

2. **始终计算总时间**
   新增 `GetTotalElapsedTime()` 函数，始终计算 E2E 时间

3. **自证清白能力**
   通过新的 metrics 可区分：
   - `zmq_server_queue_wait_latency`：network 等待时间
   - `zmq_server_exec_latency`：业务逻辑执行时间
   - `zmq_server_reply_latency`：RPC framework 回复时间

---

**接口/兼容性影响**

- 无对外 API 签名变化
- 无 `StatusCode` 枚举变化
- 无协议字段变化（复用 `MetaPb.ticks`）
- 向后兼容：`ENABLE_PERF=true` 行为不变

---

**主要代码变更**

**新增函数**

- `zmq_common.h`：
  - `RecordTick()` - 始终记录 tick
  - `GetTotalElapsedTime()` - 始终计算总时间

**修改调用点**

- `zmq_service.cpp`：
  - `GetLapTime` → `RecordTick`（用于 TICK_SERVER_DEQUEUE、TICK_SERVER_EXEC_END、TICK_SERVER_SEND）
  - 时间单位 ns→us 转换

- `zmq_stub_conn.cpp`：
  - `GetLapTime` → `RecordTick`（用于 TICK_CLIENT_SEND）

- `zmq_stub_impl.h`：
  - `GetTotalTime` → `GetTotalElapsedTime`

**新增 MetricId（7个）**

- `kv_metrics.h/cpp`：
  - `ZMQ_CLIENT_QUEUING_LATENCY`
  - `ZMQ_CLIENT_STUB_SEND_LATENCY`
  - `ZMQ_SERVER_QUEUE_WAIT_LATENCY`
  - `ZMQ_SERVER_EXEC_LATENCY`
  - `ZMQ_SERVER_REPLY_LATENCY`
  - `ZMQ_RPC_E2E_LATENCY`
  - `ZMQ_RPC_NETWORK_LATENCY`

---

**核心等式（自证清白）**

```
E2E = CLIENT_QUEUING + CLIENT_STUB_SEND + SERVER_QUEUE_WAIT + SERVER_EXEC + SERVER_REPLY + NETWORK

NETWORK = E2E - SERVER_EXEC
```

---

**Tick 时间线**

```
                    CLIENT                                 SERVER
                       │                                     │
   CLIENT_ENQUEUE ────┬──── CLIENT_TO_STUB ────┬──── CLIENT_SEND
       │              │         │              │         │
       │   CLIENT     │         │   CLIENT     │         │   SERVER
       │  QUEUING     │         │ STUB_SEND   │         │  QUEUE_WAIT
       │              │         │              │         │        │
   ◄───┼─────────────┼─────────┼──────────────┼─────────┼────────┼────────────────►
       │              │         │              │         │        │
       │              │         │              │         │ SERVER_RECV
       │              │         │              │         │◄────────┼────────────────►
       │              │         │              │         │        │
   ────┴─────────────┴─────────┴──────────────┴─────────┴────────┴─────────────────►
   CLIENT_ENQUEUE   CLIENT_TO_STUB CLIENT_SEND  SERVER_RECV SERVER_DEQUEUE SERVER_EXEC_END SERVER_SEND CLIENT_RECV
```

---

**测试验证**

| 用例 | 验证内容 |
|------|---------|
| smoke_test | `ENABLE_PERF=false` 时 metrics 正常打印 |
| `zmq_server_queue_wait_latency` | 有非零值 |
| `zmq_server_exec_latency` | 有非零值 |
| `zmq_server_reply_latency` | 有非零值 |

---

**关联**

RFC：[`2026-04-zmq-rpc-metrics-0.8.1`](README.md)
Fixes: TCP 故障时无法通过 ZMQ metrics 定位问题

---

**建议的 PR 标题**

`fix(zmq): ensure RPC queue latency metrics work when ENABLE_PERF=false`

---

**Self-checklist**

- [x] 不改错误码，不改对外 API
- [x] 不改网络协议（复用 MetaPb.ticks）
- [x] `ENABLE_PERF=true` 行为不变
- [x] `ENABLE_PERF=false` 时 metrics 仍能分段时间
- [x] 7 个新增 metrics 正交（时间不重叠）
- [x] 可自证清白 network 和 RPC framework 时间
