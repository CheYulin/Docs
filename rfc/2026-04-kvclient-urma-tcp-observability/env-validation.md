# KVClient URMA 环境验证执行清单

本文用于在**具备 URMA 环境**的机器上，验证本轮 KVClient 可观测与可靠性整改（尤其是 Phase 1）是否生效。  
当前无 URMA 的环境只能完成部分验证（UT 和非 URMA 构建），URMA 相关 ST 必须由具备环境的同事补充执行。

---

## 1. 验证目标（本轮重点）

### 1.1 错误码语义（与评审后实现一致）

- **共享原语** `Event::WaitFor` / `EventWaiter::WaitAny` 超时返回 **`K_RPC_DEADLINE_EXCEEDED`（1001）**，日志文案为通用等待超时（见 5.0），**不**再带 `[URMA_WAIT_TIMEOUT]`，避免 UCP 等非 URMA 路径被误标为 URMA。
- **`UrmaManager::WaitToFinish`** 在收到 `Event::WaitFor` 的 1001 后，**对外**映射为 **`K_URMA_WAIT_TIMEOUT`（1010）**；仅 URMA 完成等待对外暴露 1010。
- 注入 `UrmaManager.UrmaWaitError` 后，相关场景仍返回 `K_URMA_WAIT_TIMEOUT`。
- `IsRpcTimeout` / `IsRpcError` / `RetryOnRPCErrorByTime` 等已纳入 `K_URMA_WAIT_TIMEOUT`；业务侧 `RetryOnError` 白名单按需包含 1010。

### 1.2 关键日志可观测性

- **Event 等待超时（5.0）**：`RETURN_STATUS_LOG_ERROR` 打 **`ERROR`**，关键字 **`Timed out waiting for request`** / **`Timed out waiting for any event`**（与 1001 语义一致）。
- **URMA 管理器**：`timeoutMs < 0` 等路径仍可有 **`[URMA_WAIT_TIMEOUT]`** 前缀日志；`VLOG(1)` 含 **`[UrmaEventHandler] Started/Done waiting for the request id`**（需提高 verbose，如 `--v=1` 或 `FLAGS_v=1`）。
- `CheckUrmaConnectionStable` 返回 `K_URMA_NEED_CONNECT` 时有 `WARNING/ERROR` 可检索日志。
- `ServerEventHandleThreadMain` 对 `PollJfcWait` 的非 OK（非 `K_TRY_AGAIN`）结果有 `ERROR` 日志。
- 日志能区分 TCP 与 URMA 问题域（错误码 + 前缀 + 5.0/5.1–5.4 关键字）。

### 1.3 兼容与回归

- 非 URMA路径无回归（基础 UT 可通过）。
- URMA 开启后，核心 ST 用例可通过。

---

## 2. 前置条件

- 机器具备 URMA 依赖与运行环境（网卡/驱动/库/权限）并可正常进行 URMA 通信。
- 已同步本次代码（包含以下文件改动）：
  - `include/datasystem/utils/status.h`
  - `src/datasystem/common/util/status_code.def`
  - `src/datasystem/common/rdma/rdma_util.h`
  - `src/datasystem/common/rdma/urma_manager.cpp`
  - `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`
  - `src/datasystem/worker/object_cache/service/worker_oc_service_batch_get_impl.cpp`
  - `tests/ut/common/util/status_test.cpp`
  - `tests/ut/common/util/rpc_util_test.cpp`（`IsRpcTimeout` 与 1010）
  - `tests/st/client/object_cache/urma_object_client_test.cpp`

---

## 3. 构建步骤（URMA 环境）

建议使用独立 build 目录，避免污染现有非 URMA 构建产物。

```bash
cd /path/to/yuanrong-datasystem
mkdir -p build-urma
cd build-urma

# 按项目实际参数调整，关键是 BUILD_WITH_URMA=on
cmake .. -DBUILD_WITH_URMA=on
cmake --build . --target ds_ut ds_st_object_cache -j4
```

验收点：
- `CMakeCache.txt` 中应看到 `BUILD_WITH_URMA:BOOL=on`。
- 产物存在：
  - `build-urma/tests/ut/ds_ut`
  - `build-urma/tests/st/ds_st_object_cache`

---

## 4. 用例执行步骤

## 4.1 Phase 1 UT（必须通过，**无 URMA 环境也可跑**）

```bash
cd build-urma/tests/ut
./ds_ut --gtest_filter="StatusTest.EventWaitForTimeoutReturnsDeadlineExceeded:StatusTest.EventWaitForSucceedsAfterNotify:StatusTest.EventWaitAnyTimeoutReturnsDeadlineExceeded:StatusTest.EventWaitAnySucceedsAfterNotify:RpcUtilTest.IsRpcTimeoutIncludesUrmaWaitTimeout"
```

期望：
- 5/5 通过（前 4 个断言 **1001** + 超时文案；最后一个断言 **`IsRpcTimeout(1010)`**）。
- **超时路径若开启 glog 输出**：`ERROR` 日志正文含 **`Timed out waiting for request`** 或 **`Timed out waiting for any event`**（**不再**要求日志里出现字符串 `URMA_WAIT_TIMEOUT`——与共享 `Event` 语义一致）。

## 4.2 Phase 1 ST（URMA 关键用例）

```bash
cd build-urma/tests/st
./ds_st_object_cache --gtest_filter="UrmaDisableFallbackTest.TestUrmaRemoteGetWaitTimeoutReturnsUrmaWaitTimeout"
```

期望：
- 用例执行数为 1，且通过。
- 断言命中 `StatusCode::K_URMA_WAIT_TIMEOUT`。

如返回 `0 tests`，优先检查：
1. 是否 `BUILD_WITH_URMA=on`；
2. 该测试是否位于 `#ifdef USE_URMA` 代码块；
3. 是否使用了错误二进制或错误 build 目录。

## 4.3 Phase 2（1002 子分类）最小 UT

```bash
cd build-urma/tests/ut
./ds_ut --gtest_filter="UnixSockFdStatusTest.*"
```

期望：
- `UnixSockFdStatusTest.ConnectResetMapsToRpcUnavailableWithPrefix` 通过。
- `UnixSockFdStatusTest.EagainMapsToTryAgain` 通过。
- `UnixSockFdStatusTest.EpipeMapsToRpcUnavailableWithPrefix` 通过。

当前进展（2026-04-15，非 URMA 环境）：
- 已完成该组定向执行，结果为 `3/3 PASS`。

---

## 5. 日志验证步骤

建议在执行 ST 前先清理日志，再按关键字检索。

### 5.0 Event / URMA wait 超时（本轮语义与检索）

| 场景 | 对外/返回码 | 典型检索关键字（`ERROR` 为主） | 说明 |
|------|----------------|--------------------------------|------|
| `Event::WaitFor` / `WaitAny` 超时（任意调用方） | **1001** | `Timed out waiting for request` / `Timed out waiting for any event` | 共享原语，**非** URMA 专用前缀 |
| `UrmaManager::WaitToFinish` 映射后对外 | **1010** | 业务/Status；上游若打完整 `Status::ToString()` 可见 **1010** | 内部先经 `Event::WaitFor`，日志仍多为上一行通用文案 |
| `UrmaManager` `timeoutMs < 0` 等 | **1010** | **`[URMA_WAIT_TIMEOUT] timedout waiting for request`** | 仍带 URMA 前缀，便于定界 |
| 注入 `UrmaManager.UrmaWaitError` | **1010** | 依实现/注入文案 | ST/注入环境 |

**无 URMA 硬件时**：用 **4.1 UT** 锁定「1001 + 文案」与「`IsRpcTimeout` 含 1010」；不依赖真实 RDMA。

### 5.1 `K_URMA_NEED_CONNECT` 关键日志

检索关键字示例：
- `URMA_NEED_CONNECT`
- `remoteAddress`
- `remoteInstanceId`
- `remoteWorkerId`

验收点：
- 触发重连路径时，能够在日志中直接定位“何时、对哪个 remoteAddress、对应哪个 remoteWorkerId、为何重连”。

### 5.2 `PollJfcWait` 错误不再静默

检索关键字示例：
- `URMA_POLL_ERROR`
- `PollJfcWait failed`

验收点：
- 非 `K_TRY_AGAIN` 的异常返回有 `ERROR` 级日志。

### 5.3 JFS 重建故障日志验收

检索关键字示例：
- `URMA_RECREATE_JFS`
- `URMA_RECREATE_JFS_FAILED`
- `URMA_RECREATE_JFS_SKIP`
- `newJfsId`

验收点：
- JFS 重建相关异常有可检索日志，并包含 `requestId`、`remoteAddress`、`remoteInstanceId`。

### 5.4 1002 子分类日志验收

建议至少覆盖 3 种前缀并留存样本：

- `[RPC_RECV_TIMEOUT]`
- `[RPC_SERVICE_UNAVAILABLE]`
- `[TCP_CONNECT_RESET]`
- `[TCP_CONNECT_FAILED]`
- `[UDS_CONNECT_FAILED]`
- `[SOCK_CONN_WAIT_TIMEOUT]`
- `[REMOTE_SERVICE_WAIT_TIMEOUT]`
- `[SHM_FD_TRANSFER_FAILED]`

### 5.5 自动化日志验收脚本（建议）

可直接执行：

```bash
cd /path/to/vibe-coding-files
./ops test.urma_tcp_logs /path/to/logs
```

说明：
- 支持传入一个或多个日志文件/目录；
- 脚本会输出每类关键字命中数与最终 PASS/FAIL；
- 1002 子分类至少要求命中 3 类前缀。

### 5.6 手工日志验收命令（兜底）

当自动脚本未覆盖到现场日志布局时，可用以下命令手工抽查。

示例（变量）：

```bash
LOG_PATH=/path/to/logs
```

1) `URMA_NEED_CONNECT` 及关联字段：

```bash
grep -R -E "URMA_NEED_CONNECT|remoteAddress=|remoteInstanceId=|remoteWorkerId=" "${LOG_PATH}"
```

2) `PollJfcWait` 错误日志：

```bash
grep -R -E "URMA_POLL_ERROR|PollJfcWait failed" "${LOG_PATH}"
```

3) JFS 重建相关日志：

```bash
grep -R -E "URMA_RECREATE_JFS|URMA_RECREATE_JFS_FAILED|URMA_RECREATE_JFS_SKIP|newJfsId" "${LOG_PATH}"
```

4) 1002 子分类前缀（至少命中 3 类）：

```bash
grep -R -E "\[RPC_RECV_TIMEOUT\]|\[RPC_SERVICE_UNAVAILABLE\]|\[TCP_CONNECT_RESET\]|\[TCP_CONNECT_FAILED\]|\[UDS_CONNECT_FAILED\]|\[SOCK_CONN_WAIT_TIMEOUT\]|\[REMOTE_SERVICE_WAIT_TIMEOUT\]|\[SHM_FD_TRANSFER_FAILED\]|\[TCP_NETWORK_UNREACHABLE\]" "${LOG_PATH}"
```

手工验收通过标准：
- `URMA_NEED_CONNECT`、`URMA_POLL_ERROR`、`URMA_RECREATE_JFS*` 三类日志均可检索；
- 1002 子分类前缀至少出现 3 类；
- 关键日志中可定位 `remoteAddress`，并尽可能包含 `remoteInstanceId` / `remoteWorkerId`。

---

## 6. 建议补充的故障注入验证

在 URMA 环境可进一步做以下注入验证：

1. `UrmaManager.UrmaWaitError`  
   - 目标：确认返回码为 `K_URMA_WAIT_TIMEOUT`，而非 `K_RPC_DEADLINE_EXCEEDED` / `K_RPC_UNAVAILABLE`。
2. `UrmaManager.UrmaWriteError`  
   - 目标：验证异常路径下日志完整且错误域归属正确。
3. Worker 重启/链路抖动  
   - 目标：验证 `K_URMA_NEED_CONNECT` 触发时日志可检索，重连行为可观测。

---

## 7. 结果回填模板（给验证同事）

建议在提测群或任务单中按下表回填：

| 项目 | 结果 | 证据 |
|---|---|---|
| `BUILD_WITH_URMA=on` | PASS/FAIL | `CMakeCache.txt` 关键行截图/文本 |
| Phase1 UT 4项 | PASS/FAIL | `ds_ut` 输出 |
| `UrmaDisableFallbackTest.TestUrmaRemoteGetWaitTimeoutReturnsUrmaWaitTimeout` | PASS/FAIL | `ds_st_object_cache` 输出 |
| `URMA_NEED_CONNECT` 日志可检索 | PASS/FAIL | 日志片段 |
| `URMA_POLL_ERROR` 日志可检索 | PASS/FAIL | 日志片段 |
| 其他异常/回归 | 描述 | 复现步骤 + 日志 |

---

## 8. 已知说明

- 非 URMA 环境下，UT 可以验证错误码接口语义，但无法替代 URMA 数据面真实验证。
- 若 ST 目标编译耗时长，优先保留独立 `build-urma` 目录做增量编译，避免反复全量重编。

