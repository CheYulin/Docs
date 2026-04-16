# [RFC]：ZMQ TCP/RPC Metrics 可观测定界（故障定界 + 性能自证清白）

## 背景与目标描述

当前 ZMQ/TCP RPC 框架存在两类可观测性缺陷，导致生产故障难以快速定界：

**A. 故障定界缺失**

1. `zmq_msg_send` / `zmq_msg_recv` 失败无计数指标，无法从 metrics 维度发现通信故障，只能翻日志。
2. `errno` 信息在 `ZmqErrnoToStatus` → `StatusCode` 逐层转换后原始信息湮没，无法区分"网卡硬件故障（EHOSTUNREACH/ENETDOWN）"与"对端拒绝（ECONNREFUSED）"。
3. ZMQ Monitor 事件（disconnect、握手失败）仅靠日志且受限频，无法从指标趋势判断连接稳定性。

**B. 性能定界缺失（"自证清白"问题）**

1. 当整体 RPC 延迟高时，无法快速判定瓶颈是"底层 `zmq_msg_send/recv` socket I/O 慢"还是"RPC 框架 protobuf 序列化/反序列化慢"。
2. 现有 PerfPoint 不直接暴露 zmq I/O 与序列化的独立耗时对比，且跨机器时钟可能有 ms 级偏差。

**关联**：[urma-tcp-定界修复需求](../urma-tcp-定界修复需求/issue-rfc-kvclient-urma-tcp-可观测与可靠性整改.md)（TCP 域的互补措施）

---

## 建议的方案

基于已合入的 `datasystem::metrics` 轻量级框架（PR #584，Counter / Gauge / Histogram + 周期 `LOG(INFO)` 输出），分两层补齐 ZMQ 可观测性。

### Layer 1：故障定界指标（仅失败路径，零成功路径开销）

| 指标名 | 类型 | 触发时机 | 定界价值 |
|--------|------|---------|---------|
| `zmq_send_failure_total` | Counter | `zmq_msg_send` 返回 -1 且非 EAGAIN/EINTR | ZMQ 发送硬失败 |
| `zmq_receive_failure_total` | Counter | `zmq_msg_recv` 返回 -1 且非 EAGAIN/EINTR | ZMQ 接收硬失败 |
| `zmq_send_try_again_total` | Counter | 发送返回 EAGAIN | 发送队列 HWM 背压 |
| `zmq_receive_try_again_total` | Counter | 阻塞模式接收超时 EAGAIN | 接收超时（对端 hang） |
| `zmq_network_error_total` | Counter | errno 为网络类错误（ECONNREFUSED/ENETDOWN 等） | 网卡/网络层故障 |
| `zmq_last_error_number` | Gauge | 每次硬失败时更新 | 快速查看最近 errno 值 |
| `zmq_gateway_recreate_total` | Counter | gateway socket 重建成功 | 连接重建频率 |
| `zmq_event_disconnect_total` | Counter | ZMQ Monitor 收到 DISCONNECTED 事件 | 连接断开计数 |
| `zmq_event_handshake_failure_total` | Counter | ZMQ Monitor 握手失败事件（3 种变体） | TLS/认证握手故障 |

### Layer 2：性能定界指标（每次调用均采样，开销 ~70-100ns/call）

| 指标名 | 类型 | 测量点 | 定界价值 |
|--------|------|-------|---------|
| `zmq_send_io_latency` | Histogram | `zmq_msg_send` 系统调用前后 | socket 写耗时 |
| `zmq_receive_io_latency` | Histogram | `zmq_msg_recv` 系统调用前后 | socket 读耗时 |
| `zmq_rpc_serialize_latency` | Histogram | `pb.SerializeToArray()` 前后 | protobuf 序列化耗时 |
| `zmq_rpc_deserialize_latency` | Histogram | `pb.ParseFromArray()` 前后 | protobuf 反序列化耗时 |

**性能自证公式**：

```
RPC 框架额外开销占比 = (ser_us.avg + deser_us.avg) /
                      (io.send_us.avg + io.recv_us.avg + ser_us.avg + deser_us.avg)

示例：(12 + 8) / (120 + 450 + 12 + 8) = 3.4%
→ RPC 框架仅占 3.4%，瓶颈明确在 socket I/O 层
```

### 定界决策树

```
整体 RPC 延迟高？
      │
      ├── zmq_receive_io_latency avg 高 (>1ms)?
      │       ├── zmq_network_error_total / zmq_send_failure_total / zmq_receive_failure_total > 0 → 网卡/网络故障
      │       └── 全 +0 → 对端处理慢或网络延迟
      │
      ├── zmq_rpc_serialize_latency avg 高 (>100us) → 消息体过大，序列化瓶颈
      ├── zmq_rpc_deserialize_latency avg 高         → 反序列化瓶颈
      └── 全部 avg 低                     → 瓶颈不在 RPC/ZMQ 层，检查业务逻辑
```

---

## 涉及到的变更

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/datasystem/common/rpc/zmq/zmq_metrics_def.h` | ZMQ 指标 ID 枚举、MetricDesc 数组、`IsNetworkErrno()` 工具函数 |
| `tests/ut/common/rpc/zmq_metrics_test.cpp` | 20 个 gtest 用例，覆盖全部指标、场景模拟、并发安全 |
| `tests/ut/common/rpc/BUILD.bazel` | Bazel 构建声明（新目录） |

### 修改文件

| 文件 | 改动说明 |
|------|---------|
| `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | `RecvMsg` / `SendMsg` 增加 I/O Histogram 计时 + 失败 Counter |
| `src/datasystem/common/rpc/zmq/zmq_common.h` | `SerializeToZmqMessage` / `ParseFromZmqMessage` 增加序列化 Histogram |
| `src/datasystem/common/rpc/zmq/zmq_socket.cpp` | 阻塞超时日志增加 `[ZMQ_RECV_TIMEOUT]` 前缀 |
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | gateway 重建后递增 `zmq_gateway_recreate_total` Counter |
| `src/datasystem/common/rpc/zmq/zmq_monitor.cpp` | disconnect / handshake fail 事件递增对应 Counter |
| `src/datasystem/common/rpc/zmq/BUILD.bazel` | 新增 `zmq_metrics_def` header-only target；补充 4 个 target 的 dep |

### 不变项

- 无对外 API 签名变更。
- `StatusCode` 枚举值不变（不修改错误码）。
- 已有 `PerfPoint` 调用保持不动。

---

## 测试验证

### UT（CMake）

```bash
# 远端节点 root@38.76.164.55
cd /root/workspace/git-repos/yuanrong-datasystem/build
./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*:MetricsTest.*" -v
# 结果：42/42 PASSED（ZmqMetricsTest 20 + MetricsTest 22）
```

### UT（Bazel）

```bash
cd /root/workspace/git-repos/yuanrong-datasystem
USE_BAZEL_VERSION=7.4.1 bazel test \
  //tests/ut/common/rpc:zmq_metrics_test \
  --jobs=8 --test_output=all
# 结果：20/20 PASSED，PASSED in 0.7s
```

### 构建验证（Bazel）

```bash
USE_BAZEL_VERSION=7.4.1 bazel build \
  //src/datasystem/common/rpc/zmq:zmq_metrics_def \
  //src/datasystem/common/rpc/zmq:zmq_socket_ref \
  //src/datasystem/common/rpc/zmq:zmq_common \
  //src/datasystem/common/rpc/zmq:zmq_stub_conn \
  //src/datasystem/common/rpc/zmq:zmq_monitor \
  --jobs=8
# 结果：Build completed successfully
```

---

## 遗留事项（待人工决策）

1. **Init 注册入口**：当前只有 UT 层调用 `metrics::Init(ZMQ_METRIC_DESCS, ...)`，worker / client 进程启动路径尚未接入，需确认统一注册点及是否合并其他模块的 `MetricDesc`。
2. **`metrics::Start()` 时机**：应在 main 的 flags 解析后调用，与 `FLAGS_log_monitor` 联动。
3. **Bazel 版本固化**：仓库未设 `.bazelversion`，`build_defs.bzl` 使用 `native.cc_library` 与 Bazel 8/9 不兼容，建议补充 `.bazelversion: 7.4.1`。
4. **跨机器分析工具**：delta 模式对比（按 cycle 号对齐）目前靠人工日志比对，后续可考虑脚本化。

## 期望的反馈时间

- 建议反馈周期：5~7 天。
- 重点反馈：
  1. `metrics::Init` 统一注册点是否接受在 ZMQ 模块内部自注册，或要求集中到 main 函数；
  2. Layer 2 性能 Histogram（~70-100ns/call 开销）在最高 QPS 场景下是否可接受；
  3. Bazel `.bazelversion` 文件是否可以提 PR 补充。
