# /kind feature

**这是什么类型的 PR？**

/kind feature（可观测性增强；不修改错误码，不改对外 API）

---

**这个 PR 是做什么的 / 我们为什么需要它**

- 在 ZMQ/TCP RPC 最底层（`zmq_msg_send`/`zmq_msg_recv` 调用处）接入 `datasystem::metrics` 框架，暴露故障计数与 I/O 延迟 Histogram，实现两项可观测性能力：
  1. **故障定界**：`zmq.send.fail` / `zmq.recv.fail` / `zmq.net_error` 等 Counter 在失败路径上计数，配合 `zmq.last_errno` Gauge 保留最近 errno，10 秒内即可从指标判定故障层（ZMQ socket 层 vs 网络层 vs 对端）。
  2. **性能自证清白**：`zmq.io.send_us` / `zmq.io.recv_us` / `zmq.rpc.ser_us` / `zmq.rpc.deser_us` Histogram 独立量化 ZMQ I/O 与 protobuf 序列化耗时，提供公式化的"RPC 框架开销占比"计算依据。

---

**此 PR 修复了哪些问题**

关联：ZMQ TCP/RPC Metrics 可观测定界专项。  
Fixes #<ISSUE_ID>

---

**PR 对程序接口进行了哪些修改？**

- 无客户可见 API 签名变化。
- 无 `StatusCode` 枚举值变化（不修改错误码）。
- 新增内部可观测接口：
  - `zmq_metrics_def.h`：`ZmqMetricId` 枚举（ID 100-113）、`ZMQ_METRIC_DESCS[]`、`IsNetworkErrno()`
  - `zmq/BUILD.bazel`：新增 `zmq_metrics_def` header-only Bazel target
  - `tests/ut/common/rpc/BUILD.bazel`：新建，注册 `zmq_metrics_test` Bazel test target

---

**关键信息**

- **指标设计原则**
  - 成功路径仅增加 Histogram 计时（2 次 `steady_clock::now()` + `Observe()`，~70-100ns/call），无额外分支。
  - 失败路径 Counter 全部在 `rc == -1` 分支内，成功路径零开销。
  - 所有时延测量使用本机 `steady_clock`（单调时钟），不依赖跨机器时钟同步；跨机器分析通过 delta cycle 号对齐。
  - 不使用 PerfPoint，不修改已有 PerfPoint 调用。

- **故障定界（Layer 1）**
  - `zmq_socket_ref.cpp`：`SendMsg` / `RecvMsg` 失败路径分别递增 `zmq.send.fail` / `zmq.send.eagain` / `zmq.recv.fail` / `zmq.recv.eagain`；网络类 errno（ECONNREFUSED、ENETDOWN 等 9 种）额外递增 `zmq.net_error`；每次硬失败更新 `zmq.last_errno` Gauge。
  - `zmq_socket.cpp`：阻塞接收超时日志增加 `[ZMQ_RECV_TIMEOUT]` 前缀，提升检索精度。
  - `zmq_stub_conn.cpp`：gateway socket 重建后递增 `zmq.gw_recreate`。
  - `zmq_monitor.cpp`：`OnEventDisconnected` 递增 `zmq.evt.disconn`；三种握手失败回调各递增 `zmq.evt.hs_fail`。

- **性能定界（Layer 2）**
  - `zmq_socket_ref.cpp`：`zmq_msg_send` / `zmq_msg_recv` 系统调用前后分别取 `steady_clock::now()`，Observe 到 `zmq.io.send_us` / `zmq.io.recv_us` Histogram。
  - `zmq_common.h`：`pb.SerializeToArray` 前后计时写入 `zmq.rpc.ser_us`；`pb.ParseFromArray` 前后计时写入 `zmq.rpc.deser_us`。
  - errno 捕获时机：`int e = errno` 在 `Observe()` 调用之后、`ZmqErrnoToStatus` 之前保存，atomic 操作不修改 errno，安全。

- **Bazel 兼容**
  - 仓库 `build_defs.bzl` 使用 `native.cc_library`，与 Bazel 8/9 不兼容，需指定 `USE_BAZEL_VERSION=7.4.1`。
  - 已验证通过，建议后续补充 `.bazelversion: 7.4.1` 文件固化版本。

---

**实现思路（摘要）**

**新建文件**

- `src/datasystem/common/rpc/zmq/zmq_metrics_def.h`
  - `ZmqMetricId` 枚举（ID 范围 100-119，业务 0-99，URMA 200-299）
  - `ZMQ_METRIC_DESCS[]`：13 个 MetricDesc 描述符
  - `IsNetworkErrno(int e)`：9 种网络类 errno 判定
- `tests/ut/common/rpc/zmq_metrics_test.cpp`：20 个 gtest 用例
- `tests/ut/common/rpc/BUILD.bazel`：Bazel test target

**修改文件**

- `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp`：I/O Histogram + 故障 Counter（含 errno 保存顺序修正）
- `src/datasystem/common/rpc/zmq/zmq_common.h`：序列化/反序列化 Histogram
- `src/datasystem/common/rpc/zmq/zmq_socket.cpp`：超时日志前缀
- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`：gateway 重建 Counter
- `src/datasystem/common/rpc/zmq/zmq_monitor.cpp`：Monitor 事件 Counter
- `src/datasystem/common/rpc/zmq/BUILD.bazel`：`zmq_metrics_def` target + 4 个 target 补充 dep

---

**验证结果**

- **CMake 构建**：`common_rpc_zmq` target 编译通过（`cmake --build . --target common_rpc_zmq -j8`）
- **Bazel 构建**：5 个 zmq target 全部 `Build completed successfully`
  ```
  //src/datasystem/common/rpc/zmq:zmq_metrics_def  ✓
  //src/datasystem/common/rpc/zmq:zmq_socket_ref   ✓
  //src/datasystem/common/rpc/zmq:zmq_common        ✓
  //src/datasystem/common/rpc/zmq:zmq_stub_conn     ✓
  //src/datasystem/common/rpc/zmq:zmq_monitor       ✓
  ```
- **CMake UT**：`ZmqMetricsTest.*` 20/20 PASSED；`MetricsTest.*` 22/22 PASSED（共 42 用例）
- **Bazel UT**：`//tests/ut/common/rpc:zmq_metrics_test` 20/20 PASSED in 0.7s

---

**Commit 提交信息说明**

**PR 标题示例**：  
`feat(zmq): add metrics for ZMQ I/O fault isolation and performance profiling`

**Commit 信息建议**：

```text
feat(zmq): add metrics for ZMQ I/O fault isolation and performance profiling

- add zmq_metrics_def.h: 13 metric IDs (counter/gauge/histogram, IDs 100-113)
- instrument zmq_socket_ref: I/O histogram (send/recv us) + fault counters
  with IsNetworkErrno classification and zmq.last_errno gauge
- instrument zmq_common.h: protobuf ser/deser latency histograms
- add zmq.gw_recreate counter in zmq_stub_conn on gateway recreation
- add zmq.evt.disconn / zmq.evt.hs_fail counters in zmq_monitor
- add zmq_metrics_def Bazel target; wire deps in zmq/BUILD.bazel
- add tests/ut/common/rpc/BUILD.bazel with zmq_metrics_test (20 cases)
- all 42 UT cases pass on both CMake and Bazel (USE_BAZEL_VERSION=7.4.1)
```

---

**Self-checklist**

- [ ] `zmq.send.fail` / `zmq.recv.fail` / `zmq.net_error` 在失败路径上正确递增
- [ ] `zmq.last_errno` 在每次硬失败时更新（EAGAIN / EINTR 不更新）
- [ ] `errno` 在 `Observe()` 之后、`ZmqErrnoToStatus` 之前捕获（无 errno 污染风险）
- [ ] I/O Histogram 在成功路径无额外分支（仅 2 次 `now()` + `Observe()`）
- [ ] `zmq_common.h` 序列化 Histogram 不影响现有 PerfPoint 调用（保持不动）
- [ ] CMake 与 Bazel 构建均通过
- [ ] 20 个 UT 用例全部通过（CMake + Bazel 双验证）
- [ ] `BUILD.bazel` 新增 `zmq_metrics_def` header-only target，无 zmq 传递依赖
- [ ] 无对外 API 签名变化，无 StatusCode 枚举变化
