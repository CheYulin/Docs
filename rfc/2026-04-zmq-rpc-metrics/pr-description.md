# /kind feature

**这是什么类型的 PR？**

/kind feature（可观测性增强；不改错误码、不改对外接口）

---

**这个 PR 做了什么 / 为什么需要**

本 PR 在 ZMQ/TCP RPC 路径补齐“可定界 + 可自证”的 metrics 与测试能力：

1. **故障定界**  
   在 `zmq_msg_send/recv` 失败路径记录 `zmq_send_failure_total`、`zmq_receive_failure_total`、`zmq_network_error_total`、`zmq_last_error_number`，并结合连接事件指标（`zmq_gateway_recreate_total`、`zmq_event_disconnect_total`、`zmq_event_handshake_failure_total`）定位问题层次。

2. **性能自证**  
   记录 `zmq_send_io_latency`、`zmq_receive_io_latency`、`zmq_rpc_serialize_latency`、`zmq_rpc_deserialize_latency`，将 I/O 与 RPC 序列化开销拆分，支持“框架是否瓶颈”的量化判断。

3. **测试可落地**  
   新增故障注入 ST 用例与日志校验脚本，验证“故障场景下关键日志/指标确实可见”，并形成测试串讲文档。

---

**基线与分支说明**

- 当前变更已按要求 rebase 到 `main/master`（openeuler 主干）。
- 按要求丢弃了旧的 metrics 框架提交（`20ce4860`），复用主干已有 metrics 框架能力。

---

**接口/兼容性影响**

- 无对外 API 签名变化。
- 无 `StatusCode` 枚举变化。
- 无协议字段变化。
- Bazel 兼容：新增/调整 ZMQ Bazel target 依赖；运行时建议使用 `USE_BAZEL_VERSION=7.4.1`。

---

**主要代码变更（已对齐 !586）**

**新增/扩展**

- `src/datasystem/common/metrics/kv_metrics.h`
  - `KvMetricId` 新增 13 个 ZMQ 通用指标枚举（不加 CLIENT/WORKER 前缀）
- `src/datasystem/common/metrics/kv_metrics.cpp`
  - `InitKvMetrics()` 统一注册 KV + ZMQ 的 `MetricDesc`
- `tests/ut/common/rpc/zmq_metrics_test.cpp`
  - ZMQ metrics UT（20 个场景）
- `tests/ut/common/rpc/BUILD.bazel`
  - 注册 `zmq_metrics_test`
- `tests/st/common/rpc/zmq/zmq_metrics_fault_test.cpp`
  - 4 个故障注入 E2E 场景（Normal / ServerKilled / SlowServer / HighLoad）

**修改**

- `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp`
  - send/recv 失败计数 + I/O histogram（计数类写法对齐 `METRIC_INC`）
- `src/datasystem/common/rpc/zmq/zmq_common.h`
  - serialize/deserialize histogram
- `src/datasystem/common/rpc/zmq/zmq_socket.cpp`
  - timeout 日志标签 `[ZMQ_RECV_TIMEOUT]`
- `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`
  - gateway recreate 计数
- `src/datasystem/common/rpc/zmq/zmq_monitor.cpp`
  - disconnect / handshake-fail 计数
- `src/datasystem/common/rpc/zmq/BUILD.bazel`
  - 移除 `zmq_metrics_def` target，统一切换到 `common_metrics` 依赖
- `tests/st/common/rpc/zmq/BUILD.bazel`
  - 注册 `zmq_metrics_fault_test`
- `tests/ut/common/rpc/BUILD.bazel`
  - 移除对 `zmq_metrics_def` 的依赖

**删除**

- `src/datasystem/common/rpc/zmq/zmq_metrics_def.h`
  - 独立 ZMQ 指标定义头已收敛进 `kv_metrics` 体系

**测试辅助变更（与 ZMQ metrics 功能正交，需在 PR 中知晓）**

- `tests/st/common/rpc/zmq/zmq_test.h`：`zmq_metrics_fault_test` 为在 Bazel 下避免对 `//tests/st:st_common`（及 `tests/st/cluster/common.cpp`）的过重链接依赖，与 `zmq_test.h` 中 Demo 服务实现自洽编译；原先 `datasystem::st::GetCrc32` 来自 ST 公共库，解耦后改为头文件内 **`CalcCrc32`**（与 `GetCrc32` 同语义：CRC-32 逐位算法；多项式以命名常量 **`CRC32_POLYNOMIAL`** 表示）。该改动不改变 ZMQ metrics 行为，仅服务 ST 构建与可维护性。

---

**测试与脚本/文档交付**

- 脚本：
  - `vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh`
  - `vibe-coding-files/scripts/testing/verify/verify_zmq_metrics_fault.sh`
  - `vibe-coding-files/scripts/testing/verify/run_zmq_metrics_ut_regression_remote.sh`
  - `vibe-coding-files/scripts/testing/verify/run_zmq_metrics_fault_e2e_remote.sh`
- 文档：
  - `.../RESULTS.md`（分阶段证据 + 复跑证据）
  - `.../ZMQ-metrics-故障注入与日志定界-测试串讲.md`

---

**最新验证结果（基于当前实现）**

1. **远端构建**
   - `cmake --build . --target common_rpc_zmq -j8`
   - 结果：`Built target common_rpc_zmq`

2. **UT（主回归）**
   - `./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*:MetricsTest.*"`
   - 结果：`82/82 PASSED`（`MetricsTest` 62 + `ZmqMetricsTest` 20）

3. **ST（故障注入）**
   - `./tests/st/ds_st --gtest_filter="ZmqMetricsFaultTest.*" --alsologtostderr`
   - 结果：`4/4 PASSED`
   - 总耗时：`6746 ms`
   - 关键耗时：
     - `ServerKilled_GwRecreateDetectsPeerCrash`: `3712 ms`
     - `SlowServer_ZmqCountersZeroProvesFrameworkInnocent`: `1508 ms`
   - 典型定界日志：`[FAULT INJECT]`、`[METRICS DUMP - ...]`、`[ISOLATION]`、`[SELF-PROOF REPORT]`

4. **日志自动验收**
   - `verify_zmq_fault_injection_logs.sh <full-log>`
   - 结果：`Mandatory RESULT: 15 matched | 0 missing`

5. **新增 ST 耗时评估（CI 影响）**
   - 当前优化后 `ZmqMetricsFaultTest.*` 总耗时约 `6.7s`
   - `ZmqMetricsTest.*` UT 墙钟约 `0.01s`

---

**关联**

关联：ZMQ TCP/RPC Metrics 可观测定界专项  
Fixes #<ISSUE_ID>

---

**建议的 PR 标题**

`feat(zmq): add metrics for ZMQ I/O fault isolation and performance profiling`

---

**Self-checklist**

- [x] 不改错误码，不改对外 API
- [x] ZMQ 故障/性能 metrics 已接入 send/recv 与 ser/deser 路径
- [x] CMake 构建通过（`common_rpc_zmq`、`ds_ut`、`ds_st`）
- [x] UT 主回归通过（`82/82`）
- [x] 故障注入 ST 通过（`4/4`）
- [x] 关键日志自动校验通过（`15/15`）
- [x] 远端复跑证据与测试串讲文档已补充
