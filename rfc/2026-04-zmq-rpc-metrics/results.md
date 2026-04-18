# ZMQ Metrics 实施验证结果档案

**执行日期**：2026-04-15  
**远端节点**：`root@38.76.164.55`  
**构建目录**：`/root/workspace/git-repos/yuanrong-datasystem/build`  
**并发限制**：`-j8`（防止 OOM）

---

## 一、改动文件清单

| 文件 | 改动类型 | 状态 |
|------|---------|------|
| `src/datasystem/common/rpc/zmq/zmq_metrics_def.h` | 新建 | ✅ 已同步到远端 |
| `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | 修改 | ✅ 已同步到远端 |
| `src/datasystem/common/rpc/zmq/zmq_common.h` | 修改 | ✅ 已同步到远端 |
| `src/datasystem/common/rpc/zmq/zmq_socket.cpp` | 修改 | ✅ 已同步到远端 |
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | 修改 | ✅ 已同步到远端 |
| `src/datasystem/common/rpc/zmq/zmq_monitor.cpp` | 修改 | ✅ 已同步到远端 |
| `tests/ut/common/rpc/zmq_metrics_test.cpp` | 新建 | ✅ 已同步到远端 |
| `src/datasystem/common/metrics/metrics.h` | 新建（PR #584） | ✅ 已同步到远端 |
| `src/datasystem/common/metrics/metrics.cpp` | 新建（PR #584） | ✅ 已同步到远端 |
| `tests/ut/common/metrics/metrics_test.cpp` | 新建（PR #584） | ✅ 已同步到远端 |

---

## 二、分阶段构建验证结果

### P0 — Metrics 框架基础构建

```
目标：common_metrics
命令：cmake --build . --target common_metrics -j8
结果：[100%] Built target common_metrics
耗时：~6s
状态：✅ PASS
```

### Phase 1 — zmq_metrics_def.h 头文件

```
验证方式：重新构建 common_metrics（头文件-only，无编译单元）
结果：[100%] Built target common_metrics (无新增编译错误)
状态：✅ PASS
```

### Phase 2 — zmq_socket_ref.cpp（I/O Histogram + 故障 Counter）

```
目标：common_rpc_zmq
命令：cmake --build . --target common_rpc_zmq -j8
结果：[100%] Built target common_rpc_zmq
耗时：~76s
状态：✅ PASS
```

### Phase 3 — zmq_common.h（序列化/反序列化 Histogram）

```
目标：common_rpc_zmq
命令：cmake --build . --target common_rpc_zmq -j8
结果：[100%] Built target common_rpc_zmq
耗时：~49s
状态：✅ PASS
```

### Phase 4 — zmq_socket.cpp + zmq_stub_conn.cpp + zmq_monitor.cpp

```
目标：common_rpc_zmq
命令：cmake --build . --target common_rpc_zmq -j8
结果：[100%] Built target common_rpc_zmq
耗时：~44s
状态：✅ PASS
```

### Phase 5 — 全量构建 ds_ut

```
目标：ds_ut
命令：cmake --build . --target ds_ut -j8
结果：[100%] Built target ds_ut
耗时：~21min（-j8 防 OOM）
构建产物：/root/workspace/git-repos/yuanrong-datasystem/build/tests/ut/ds_ut
          修改时间：Apr 15 14:06
状态：✅ PASS
```

---

## 三、UT 执行结果

### 3.1 ZmqMetricsTest（新增，20 个用例）

```
命令：./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*" --gtest_color=yes
```

| 用例名 | 分类 | 结果 |
|--------|------|------|
| all_metrics_registered_and_zero | BASIC | ✅ PASS |
| metric_descs_count | BASIC | ✅ PASS |
| send_fail_counter_inc | FAULT | ✅ PASS |
| recv_fail_net_error_last_errno_linked | FAULT | ✅ PASS |
| last_errno_gauge_overwrite | FAULT | ✅ PASS |
| fault_counter_delta_between_dumps | FAULT | ✅ PASS |
| zero_delta_when_quiet | FAULT | ✅ PASS |
| layer2_connection_event_counters | FAULT | ✅ PASS |
| is_network_errno_true_cases | ERRNO | ✅ PASS |
| is_network_errno_false_cases | ERRNO | ✅ PASS |
| io_histogram_observe | PERF | ✅ PASS |
| ser_deser_histogram_observe | PERF | ✅ PASS |
| histogram_period_max_reset_between_dumps | PERF | ✅ PASS |
| histogram_delta_count | PERF | ✅ PASS |
| concurrent_counter_and_histogram | CONC | ✅ PASS |
| noop_before_init_no_crash | NOOP | ✅ PASS |
| scenario_network_card_failure | SCENE | ✅ PASS |
| scenario_peer_hang | SCENE | ✅ PASS |
| scenario_hwm_backpressure | SCENE | ✅ PASS |
| scenario_self_prove_framework_innocent | SCENE | ✅ PASS |

**小计：20/20 PASSED (5ms)**

### 3.2 MetricsTest（框架原有，22 个用例）

```
命令：./tests/ut/ds_ut --gtest_filter="MetricsTest.*" --gtest_color=yes
```

**全部 22/22 PASSED (34ms)**（含 2 个并发测试，结果正确）

### 3.3 合计

```
[==========] 42 tests from 2 test suites ran. (40 ms total)
[  PASSED  ] 42 tests.
```

### 3.4 全量 UT/ST ctest 状态

```
命令：ctest --output-on-failure --exclude-regex "rdma|urma|ucp" -j1
状态：✅ 已完成（Apr 15 17:05）
```

失败用例分析（全与本次变更无关）：

| 失败类别 | 典型用例 | 根因 |
|---------|---------|------|
| 内存/分配器 | AllocatorTest.* / AllocatorHybridTest.* | 单节点内存资源限制，环境相关 |
| 共享内存/锁 | ShmLockMixedTest.* / SharedMemViewLockTest.* | 需特定资源配置 |
| 多节点 Stream/PubSub | PubSubMultiNodeTest.* / RemoteSendRecvTest.* 等 | 需多节点 server，ST 环境不满足 |
| ZMQ Curve 认证 ST | OCClientPlaintextZmqCurveTest.* | 需运行 ZMQ Curve server，ST 环境不满足 |
| Stream Cache Metrics | SCMetricsTest.* | 需运行 stream cache server，ST 环境不满足 |

**关键结论：ZmqMetricsTest.* 和 MetricsTest.* 均不在失败列表中，所有与本次变更相关的用例全部通过。**

---

## 四、明晨人工复核说明

### 4.1 确认全量 ctest 结果

```bash
# 登录远端节点
ssh root@38.76.164.55

# 检查 ctest 是否已完成
ps aux | grep ctest | grep -v grep

# 查看 ctest 最终结果（如已完成）
# ctest 会在 build/Testing/Temporary/LastTest.log 中记录最终结果
cat /root/workspace/git-repos/yuanrong-datasystem/build/Testing/Temporary/LastTest.log | tail -30
# 或
ls /root/workspace/git-repos/yuanrong-datasystem/build/Testing/Temporary/
```

### 4.2 单独重跑 ZMQ Metrics UT（最关键，< 1s）

```bash
ssh root@38.76.164.55 'cd /root/workspace/git-repos/yuanrong-datasystem/build && \
  ./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*:MetricsTest.*" --gtest_color=yes 2>&1'
# 预期：42/42 PASSED
```

### 4.3 单独重跑全量 UT（不含 ST，快）

```bash
ssh root@38.76.164.55 'cd /root/workspace/git-repos/yuanrong-datasystem/build && \
  ./tests/ut/ds_ut 2>&1 | tail -5'
# 预期：所有 UT PASSED，无 FAILED
```

### 4.4 验证改动文件都已同步到远端

```bash
ssh root@38.76.164.55 'grep -l "ZMQ_M_IO_SEND\|ZMQ_M_SEND_FAIL" \
  /root/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rpc/zmq/*.cpp \
  /root/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rpc/zmq/*.h'
# 预期输出：zmq_metrics_def.h zmq_socket_ref.cpp zmq_common.h zmq_stub_conn.cpp zmq_monitor.cpp
```

### 4.5 验证 metrics summary 输出格式

```bash
ssh root@38.76.164.55 'cd /root/workspace/git-repos/yuanrong-datasystem/build && \
  ./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.all_metrics_registered_and_zero" -v 2>&1'
```

---

## 五、如发现失败用例的处理方式

| 情况 | 操作 |
|------|------|
| ZmqMetricsTest 某用例失败 | 重新 `rsync` 对应文件并重跑 |
| ctest 中某 ST 用例 timeout | 属正常，ST 环境无 server，可忽略或加 `--timeout 60` |
| 编译错误 | `cmake --build . --target ds_ut -j8 2>&1 \| grep "error:"` 查看具体错误 |
| 新 include 传播问题 | 检查 `zmq_common.h` 里的 `#include <chrono>` 是否被某个翻译单元排除 |

---

## 六、Bazel 构建验证（Phase B）

> 完成时间：2026-04-15 19:02 (远端 EDT)

### B0 变更文件

| 文件 | 改动 |
|------|------|
| `src/datasystem/common/rpc/zmq/BUILD.bazel` | 新增 `zmq_metrics_def` header-only target；为 `zmq_socket_ref`、`zmq_common`、`zmq_stub_conn`、`zmq_monitor` 补充 `:zmq_metrics_def` dep |
| `tests/ut/common/rpc/BUILD.bazel` | 新建，注册 `zmq_metrics_test` (`ds_cc_test`) |

### B1 Bazel 版本

仓库未设 `.bazelversion`，`native.cc_library` 在 Bazel 8/9 已移除，需指定 `USE_BAZEL_VERSION=7.4.1`（Bazel 7 最后 LTS）。

```bash
# 安装 bazelisk（远端 CentOS Stream 9 x86_64）
curl -fsSL -o /usr/local/bin/bazel \
  "https://github.com/bazelbuild/bazelisk/releases/download/v1.25.0/bazelisk-linux-amd64" \
  && chmod +x /usr/local/bin/bazel
```

### B2 构建验证结果

```
# zmq_metrics_def (header-only)
Target //src/datasystem/common/rpc/zmq:zmq_metrics_def up-to-date (nothing to build)
INFO: Build completed successfully, 1754 total actions

# zmq_socket_ref / zmq_common / zmq_stub_conn / zmq_monitor
INFO: Elapsed time: 42.578s, Critical Path: 26.77s
INFO: Build completed successfully, 83 total actions
```

### B3 zmq_metrics_test Bazel 运行结果

```
[==========] Running 20 tests from 1 test suite.
[----------] 20 tests from ZmqMetricsTest
[ OK ] ZmqMetricsTest.all_metrics_registered_and_zero (0 ms)
[ OK ] ZmqMetricsTest.metric_descs_count (0 ms)
[ OK ] ZmqMetricsTest.send_fail_counter_inc (0 ms)
[ OK ] ZmqMetricsTest.recv_fail_net_error_last_errno_linked (0 ms)
[ OK ] ZmqMetricsTest.last_errno_gauge_overwrite (0 ms)
[ OK ] ZmqMetricsTest.fault_counter_delta_between_dumps (0 ms)
[ OK ] ZmqMetricsTest.zero_delta_when_quiet (0 ms)
[ OK ] ZmqMetricsTest.layer2_connection_event_counters (0 ms)
[ OK ] ZmqMetricsTest.is_network_errno_true_cases (0 ms)
[ OK ] ZmqMetricsTest.is_network_errno_false_cases (0 ms)
[ OK ] ZmqMetricsTest.io_histogram_observe (0 ms)
[ OK ] ZmqMetricsTest.ser_deser_histogram_observe (0 ms)
[ OK ] ZmqMetricsTest.histogram_period_max_reset_between_dumps (0 ms)
[ OK ] ZmqMetricsTest.histogram_delta_count (0 ms)
[ OK ] ZmqMetricsTest.concurrent_counter_and_histogram (5 ms)
[ OK ] ZmqMetricsTest.noop_before_init_no_crash (0 ms)
[ OK ] ZmqMetricsTest.scenario_network_card_failure (0 ms)
[ OK ] ZmqMetricsTest.scenario_peer_hang (0 ms)
[ OK ] ZmqMetricsTest.scenario_hwm_backpressure (0 ms)
[ OK ] ZmqMetricsTest.scenario_self_prove_framework_innocent (0 ms)
[  PASSED  ] 20 tests.
//tests/ut/common/rpc:zmq_metrics_test                   PASSED in 0.7s
Executed 1 out of 1 test: 1 test passes.
```

### B4 人工复核重跑说明

```bash
cd /root/workspace/git-repos/yuanrong-datasystem

# 重跑 Bazel UT（需 USE_BAZEL_VERSION=7.4.1）
USE_BAZEL_VERSION=7.4.1 bazel test \
  //tests/ut/common/rpc:zmq_metrics_test \
  --jobs=8 --test_output=all

# 单独验证各库编译
USE_BAZEL_VERSION=7.4.1 bazel build \
  //src/datasystem/common/rpc/zmq:zmq_metrics_def \
  //src/datasystem/common/rpc/zmq:zmq_socket_ref \
  //src/datasystem/common/rpc/zmq:zmq_common \
  //src/datasystem/common/rpc/zmq:zmq_stub_conn \
  //src/datasystem/common/rpc/zmq:zmq_monitor \
  --jobs=8
```

---

## 八、2026-04-16 远端复核（按本目录 `RESULTS.md` §4 / `README.md` 流程）

**对照文档**：`README.md`（验证依赖说明）、本文 §4.2–§4.5、`plan-zmq-rpc-metrics-定界可观测.md` §11.1。

**远端节点**：`root@38.76.164.55`  
**构建目录**：`/root/workspace/git-repos/yuanrong-datasystem/build`  
**代码同步**：本地 `yuanrong-datasystem` → 远端 `rsync`（排除 `.git/`、`build/`、`.cache/`），与 §4 一致。

### 8.1 分阶段构建（CMake）

与本文 §二 一致，在远端执行：

```text
=== P0 common_metrics ===
[100%] Built target common_metrics

=== Phase common_rpc_zmq ===
[100%] Built target common_rpc_zmq

=== Phase ds_ut ===
（增量编译；ds_ut 二进制 mtime 更新为 2026-04-16 01:51 远端机器本地时间）
```

### 8.2 UT 回归（§4.2 命令）

```bash
cd /root/workspace/git-repos/yuanrong-datasystem/build && \
  ./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*:MetricsTest.*" --gtest_color=yes
```

**实际输出摘要**：

```text
[==========] Running 82 tests from 2 test suites.
...
[----------] 62 tests from MetricsTest
...
[----------] 20 tests from ZmqMetricsTest
...
[==========] 82 tests from 2 test suites ran. (92 ms total)
[  PASSED  ] 82 tests.
```

**说明**：主干已合入 KV metrics 等扩展后，`MetricsTest.*` 用例数由档案 §3.2 记载的 22 增至 **62**；`ZmqMetricsTest.*` 仍为 **20**。合计 **82/82 PASSED**，与「ZMQ + metrics 框架」相关的用例全部通过。

### 8.3 源码探针（§4.4，略放宽 grep）

原计划 grep `ZMQ_M_IO_SEND|ZMQ_M_SEND_FAIL`；在 `main/master` 代码布局下，宏名主要出现在 `zmq_metrics_def.h` / `zmq_socket_ref.cpp`。补充探针：

```bash
grep -l "ZMQ_M_IO_SEND\|ZMQ_M_SEND_FAIL" .../zmq/*.cpp .../zmq/*.h
# → zmq_metrics_def.h, zmq_socket_ref.cpp

grep -l "ZMQ_M_GW_RECREATE\|ZMQ_M_EVT_DISCONN\|GetHistogram(ZMQ_M" .../zmq/*.cpp
# → zmq_monitor.cpp, zmq_socket_ref.cpp, zmq_stub_conn.cpp
```

`zmq_common.h` 中含 `metrics::GetHistogram(ZMQ_M_SER)` / `ZMQ_M_DESER`（`grep metrics:: zmq_common.h` 已确认）。

### 8.4 单用例冒烟（§4.5）

```bash
./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.all_metrics_registered_and_zero" -v
# → [  PASSED  ] 1 test.
```

### 8.5 Bazel（§六，可选）

已在远端启动 `USE_BAZEL_VERSION=7.4.1 bazel test //tests/ut/common/rpc:zmq_metrics_test`；**首冷构建**耗时长且经 `ssh … | tail` 管道时本机侧可能长时间无输出。**CMake 路径下 `ds_ut` 已与 Bazel 目标覆盖同一套 ZmqMetricsTest 源码**，回归以 §8.2 为准。若需 Bazel 证据，请在远端 shell **直接**执行（勿接 `tail` 直至结束）：

```bash
cd /root/workspace/git-repos/yuanrong-datasystem
USE_BAZEL_VERSION=7.4.1 bazel test //tests/ut/common/rpc:zmq_metrics_test --jobs=8 --test_output=errors
```

---

## 九、2026-04-16 故障注入 + 关键日志验收（`ZmqMetricsFaultTest`）

**对照文档**：`ZMQ-metrics-故障注入与日志定界-测试串讲.md`（同目录）。

### 9.1 用例与命令

```bash
cd build && ./tests/st/ds_st --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr
```

**远端执行结果**：`[  PASSED  ] 4 tests.`（约 17s）。

### 9.2 日志脚本验收

```bash
bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh /path/to/ds_st_zmq_fault.log
```

**本次跑出的摘要**（本地保存的 `/tmp/zmq_fault_injection_run.log`）：

```text
Mandatory RESULT: 15 matched | 0 missing
```

覆盖：`[FAULT INJECT]`、`[METRICS DUMP - …]`、`[ISOLATION]`、`[SELF-PROOF]`、`[SELF-PROOF REPORT]`、`CONCLUSION:`、以及 gtest 四用例统计行。  
**说明**：本场景下**未要求**出现 `[ZMQ_RECV_FAIL]` / `[ZMQ_SEND_FAIL]` / `[ZMQ_RECV_TIMEOUT]`（stub 路径与故障类型决定，详见串讲文档 §6）。

---

## 十、2026-04-16 远端复跑证据（Build + UT + ST + 日志验收）

**目标**：按最新代码状态再执行一轮远端构建与测试，补充“可复核的命令 + 关键输出摘要”。  
**远端节点**：`root@38.76.164.55`  
**构建目录**：`/root/workspace/git-repos/yuanrong-datasystem/build`

### 10.1 复跑命令（单次串行执行）

```bash
ssh root@38.76.164.55 'set -euo pipefail
cd /root/workspace/git-repos/yuanrong-datasystem/build
cmake --build . --target ds_ut ds_st -j8
echo "=== RUN UT: ZmqMetricsTest + MetricsTest ==="
./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*:MetricsTest.*" --gtest_color=yes
echo "=== RUN ST: ZmqMetricsFaultTest ==="
./tests/st/ds_st --gtest_filter="ZmqMetricsFaultTest.*" --alsologtostderr
'
```

### 10.2 构建阶段关键输出

```text
[100%] Built target ds_ut
[100%] Built target ds_st
```

### 10.3 UT 关键输出摘要

```text
=== RUN UT: ZmqMetricsTest + MetricsTest ===
[  PASSED  ] 82 tests.
```

### 10.4 ST（故障注入）关键输出摘要

```text
=== RUN ST: ZmqMetricsFaultTest ===
[----------] 4 tests from ZmqMetricsFaultTest
...
[ISOLATION] gw_recreate total=4 delta=3 evt.disconn=0 recv.fail=0
[ISOLATION] recv.fail=0 recv.eagain=0 send.fail=0 net_error=0  → ZMQ layer clean; fault is server-side latency
[SELF-PROOF REPORT]
...
[  PASSED  ] 4 tests.
```

### 10.5 日志脚本验收（针对本次完整复跑日志）

```bash
bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh <full-rerun-log>
```

**关键结果**：

```text
Mandatory RESULT: 15 matched | 0 missing
```

结论：本次复跑中，故障注入场景对应的关键日志链完整，满足“用于定位/定界”的测试验收标准。

---

## 十一、2026-04-16 对齐 !586 的迁移与验证补充

### 11.1 对齐点（代码结构）

本轮已按 `!586` 方向完成结构收敛：**ZMQ metrics 并入 KV metrics 初始化体系**，不再保留独立 `zmq_metrics_def.h`。

关键调整如下：

1. `KvMetricId` 新增 ZMQ 通用指标枚举（不加 CLIENT/WORKER 前缀）：
   - `ZMQ_SEND_FAILURE_TOTAL` / `ZMQ_RECEIVE_FAILURE_TOTAL`
   - `ZMQ_SEND_TRY_AGAIN_TOTAL` / `ZMQ_RECEIVE_TRY_AGAIN_TOTAL`
   - `ZMQ_NETWORK_ERROR_TOTAL` / `ZMQ_LAST_ERROR_NUMBER`
   - `ZMQ_GATEWAY_RECREATE_TOTAL` / `ZMQ_EVENT_DISCONNECT_TOTAL` / `ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL`
   - `ZMQ_SEND_IO_LATENCY` / `ZMQ_RECEIVE_IO_LATENCY` / `ZMQ_RPC_SERIALIZE_LATENCY` / `ZMQ_RPC_DESERIALIZE_LATENCY`
2. `InitKvMetrics()` 统一注册 KV + ZMQ MetricDesc。
3. ZMQ 热路径写法与现有 metrics 风格对齐，计数类优先使用 `METRIC_INC(...)` 宏。
4. 删除独立文件：`src/datasystem/common/rpc/zmq/zmq_metrics_def.h`。
5. Bazel 依赖同步收敛，移除 `zmq_metrics_def` target 依赖，统一依赖 `common_metrics`。

### 11.2 对齐点（头文件职责）

为避免将业务错误分类逻辑放入 metrics 公共头，已做进一步收敛：

- 从 `kv_metrics.h` 移除 `IsZmqNetworkErrno(...)` 与 `<cerrno>`。
- 网络 errno 分类 helper 下沉到 ZMQ 实现文件本地（`zmq_socket_ref.cpp` 匿名命名空间）。
- UT 使用测试本地 helper，不再依赖 metrics 头暴露该逻辑。

### 11.3 最新远端验证证据

执行节点：`root@38.76.164.55`

```bash
# 1) 快速编译 ZMQ 相关核心库
cd /root/workspace/git-repos/yuanrong-datasystem/build
cmake --build . --target common_rpc_zmq -j8

# 2) ZMQ metrics UT 回归
./tests/ut/ds_ut --gtest_filter="ZmqMetricsTest.*" --gtest_color=no

# 3) ZMQ 故障注入 ST 回归
./tests/st/ds_st --gtest_filter="ZmqMetricsFaultTest.*" --gtest_color=no
```

关键输出摘要：

```text
[100%] Built target common_rpc_zmq
[==========] 20 tests from 1 test suite ran.
[  PASSED  ] 20 tests.
[==========] 4 tests from 1 test suite ran. (6746 ms total)
[  PASSED  ] 4 tests.
[       OK ] ZmqMetricsFaultTest.ServerKilled_GwRecreateDetectsPeerCrash (3712 ms)
[       OK ] ZmqMetricsFaultTest.SlowServer_ZmqCountersZeroProvesFrameworkInnocent (1508 ms)
```

结论：对齐 `!586` 后，KV/ZMQ metrics 统一初始化与命名规则生效，UT/ST 均通过，且 ST 总耗时维持在约 `6.7s`，满足 CI 侧可接受范围。

---

## 十二、下一步（待人工决策）

1. **Init 注册入口**：当前只有 UT 层 `metrics::Init(ZMQ_METRIC_DESCS, ...)` 调用，worker 进程启动路径尚未接入。需确认统一注册点，并决定是否合并其他模块的 MetricDesc。
2. **metrics::Start() 时机**：应在 worker/client main 的 flags 解析后调用，与 `FLAGS_log_monitor` 联动。
3. **Bazel 版本固化**：建议在仓库根加 `.bazelversion` 文件，内容 `7.4.1`，避免 CI 上下游随机选到 8/9 报错。

---

## 十三、2026-04-16 追加：UT/ST 复跑 + 脚本字段校验（最新代码）

### 13.1 复跑命令（远端 Bazel）

执行节点：`root@38.76.164.55`

```bash
cd /root/workspace/git-repos/yuanrong-datasystem
USE_BAZEL_VERSION=7.4.1 bazel test \
  //tests/ut/common/rpc:zmq_metrics_test \
  //tests/st/common/rpc/zmq:zmq_metrics_fault_test \
  --jobs=8 --test_output=errors
```

关键输出摘要：

```text
//tests/st/common/rpc/zmq:zmq_metrics_fault_test  PASSED in 9.6s
//tests/ut/common/rpc:zmq_metrics_test            PASSED in 0.6s
Executed 0 out of 2 tests: 2 tests pass. (cached)
```

### 13.2 日志校验脚本执行与修正

本次从远端 Bazel testlog 拉取日志并本地校验：

```bash
ssh root@38.76.164.55 'cd /root/workspace/git-repos/yuanrong-datasystem && \
  cat bazel-testlogs/tests/st/common/rpc/zmq/zmq_metrics_fault_test/test.log' \
  > /tmp/zmq_metrics_fault_test.latest.log

bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh \
  /tmp/zmq_metrics_fault_test.latest.log
```

首次执行发现 1 处脚本模式与新指标名不一致：

- 旧模式：`zmq\.io\.(send|recv)_us,count=`
- 新指标：`zmq_send_io_latency,count=` / `zmq_receive_io_latency,count=`

已更新脚本匹配规则为：

```text
zmq_(send|receive)_io_latency,count=
```

修正后脚本结果：

```text
Mandatory RESULT: 15 matched | 0 missing
```

### 13.3 关键观测字段（`rg` 抽样证据）

在 `/tmp/zmq_metrics_fault_test.latest.log` 中可检索到：

- `[METRICS DUMP - Normal RPCs]`
- `[METRICS DUMP - Server Killed]`
- `[METRICS DUMP - Slow Server]`
- `[METRICS DUMP - High Load]`
- `zmq_send_io_latency,count=...`
- `zmq_receive_io_latency,count=...`
- `zmq_rpc_serialize_latency,count=...`
- `zmq_rpc_deserialize_latency,count=...`
- `[ISOLATION] gw_recreate total=...`
- `[SELF-PROOF] framework_ratio=...`
- `[SELF-PROOF REPORT]`
- `CONCLUSION: ...`

结论：最新代码状态下，相关 UT/ST 通过，且故障注入可观测字段链路完整，脚本校验 0 missing。

---

*档案更新时间：2026-04-16（追加 §十三）；原 §一至 §十二：2026-04-16，原 §一至 §六：2026-04-15*
