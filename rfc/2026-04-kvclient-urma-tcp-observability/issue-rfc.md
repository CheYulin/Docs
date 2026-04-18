# [RFC]：KVClient TCP/URMA 可观测与可靠性整改（错误定界、日志补齐、URMA 超时语义修复）

## 背景与目标描述

当前 KVClient 在 TCP/URMA 混合路径下存在以下问题，影响可维与可观测：

1. TCP 错误与 URMA 异步错误日志不够结构化，排障需要拼接大量上下文。
2. 异常日志覆盖不完整，关键场景（URMA reconnect、poll jfc 错误、JFS 重建）检索效率低。
3. URMA wait timeout 语义历史上存在混入 RPC 语义码的风险，需要统一返回 URMA 专属超时码。
4. URMA 关键链路（建链、urma write、urma wait、poll jfc、JFR/JFS 故障处理）缺少统一验收与脚本化核对流程。

本 RFC 目标：

- 明确 TCP 与 URMA 故障域边界，统一日志前缀和错误语义。
- 修复 URMA wait timeout 错误码语义。
- 补齐关键故障日志并增加关联字段（remoteAddress/remoteInstanceId/remoteWorkerId）。
- 建立自动化日志验收与手工兜底流程，降低回归成本。
- 在不放宽正确性的前提下控制性能开销（仅故障路径打印 + 限频）。

## 建议的方案（分阶段，可拆 MR）

1. **Phase 1：URMA 错误语义与关键日志修复**
   - `Event::WaitFor` / `EventWaiter::WaitAny` / `UrmaManager::WaitToFinish` 超时统一返回 `K_URMA_WAIT_TIMEOUT`。
   - `PollJfcWait` 非 `K_TRY_AGAIN` 错误输出 `URMA_POLL_ERROR`。
   - `CheckUrmaConnectionStable` 返回 `K_URMA_NEED_CONNECT` 时输出可检索日志。

2. **Phase 2：1002 子分类（TCP/RPC）**
   - 对 `K_RPC_UNAVAILABLE(1002)` 增加子分类前缀：
     - `[RPC_RECV_TIMEOUT]`
     - `[RPC_SERVICE_UNAVAILABLE]`
     - `[TCP_CONNECT_RESET]`
     - `[TCP_CONNECT_FAILED]`
     - `[UDS_CONNECT_FAILED]`
     - `[SOCK_CONN_WAIT_TIMEOUT]`
     - `[REMOTE_SERVICE_WAIT_TIMEOUT]`
     - `[SHM_FD_TRANSFER_FAILED]`
     - `[TCP_NETWORK_UNREACHABLE]`
   - 保持错误码兼容，仅提升定界能力。

3. **Phase 3：URMA 故障上下文增强（低开销）**
   - `UrmaEvent` 增加只读上下文字段：`remoteAddress`、`remoteInstanceId`、`operationType(enum)`。
   - `URMA_POLL_ERROR`、`URMA_RECREATE_JFS*`、`URMA_NEED_CONNECT` 仅在故障路径打印并限频。
   - worker 侧 reconnect/connection-stable 日志补 `remoteWorkerId`（由 `remoteAddress -> workerId` 映射）。

4. **Phase 4：验收脚本化**
   - 新增 `scripts/testing/verify/validate_urma_tcp_observability_logs.sh`。
   - 接入 `./ops test.urma_tcp_logs`。
   - 接入 `scripts/build/remote_build_run_datasystem.sh` 可选开关：
     - `--validate-urma-tcp-logs`
     - `--urma-log-path <path>`

## 涉及到的对外 API

### 变更项

- 无对外 API 签名变更。

### 不变项

- 对外行为语义保持不变，变更集中在错误语义修正与可观测增强。

### 周边影响

- 日志关键字体系、验收脚本、远端验证流程会新增/更新。
- 需要 URMA 环境补齐最终 ST 与日志证据验收。

## 测试验证

1. **UT**
   - `StatusTest.EventWaitForTimeoutReturnsUrmaWaitTimeout`
   - `StatusTest.EventWaitAnyTimeoutReturnsUrmaWaitTimeout`
   - `UnixSockFdStatusTest.*`（1002 子分类）

2. **构建/回归**
   - `common_rdma`、`worker_object_cache` 构建通过。
   - `UnixSockFdStatusTest.*` 定向回归通过（3/3）。

3. **日志验收**
   - 自动：`./ops test.urma_tcp_logs <log_path>`
   - 手工：`URMA_NEED_CONNECT` / `URMA_POLL_ERROR` / `URMA_RECREATE_JFS*` / 1002 前缀抽查。

## 期望的反馈时间

- 建议反馈周期：5~7 天。
- 重点反馈：
  1. `worker_uuid` 是否要求扩展到 URMA manager 内核日志全覆盖；
  2. AE/JFC 汇总型指标是否本轮并入；
  3. 上线前最小验收门槛（UT/ST/日志证据）是否认可。
