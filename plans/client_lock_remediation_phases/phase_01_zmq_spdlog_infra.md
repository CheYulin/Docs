# 阶段 1：栈底 — ZMQ + spdlog（Provider / Flush）

**brpc 多 bthread 优先顺序**：见 [brpc_many_bthread_priority.md](./brpc_many_bthread_priority.md)。ZMQ **出站锁内 epoll_ctl** 已按该优先级在 `RouteToUnixSocket` / `IOService::Send` 落地；本文件其余为 spdlog 与回归说明。

## 目标

- 缩短 **所有经 ZMQ 的 RPC** 路径上的临界区（锁内不再 `epoll_ctl` 等）。
- 缩短 **spdlog Provider** 全局锁内同步 flush 时间。

## 工作事项

### 1.1 ZMQ（KV 报告 Case A）— **已落地（多 bthread 首选）**

- **文件**：  
  - `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` — `ZmqFrontend::RouteToUnixSocket`：`outMux_` 内 **仅** `emplace_back`，**锁外** `SetPollOut`。  
  - `src/datasystem/common/rpc/zmq/zmq_server_impl.cpp` — `IOService::Send`：同上（服务端回包路径，高并发下同样受益）。
- **说明**：`BackendToFrontend` / `ServiceToClient` 仍在锁内 `UnsetPollOut`（队列空时），与入队侧对称；若后续 profiling 仍热点再评估是否外移。
- **锁序**：`RouteToUnixSocket` 仍为 `connInfo->mux_` 读锁 → `outMux_` 写锁（仅队列）；与 `SetSvcFdInvalid`（先 `mux_` 写再 `outMux_` 写）避免循环依赖。

### 1.2 spdlog（KV 报告 Case B / B-1）

- **文件**：`src/datasystem/common/log/spdlog/provider.cpp`、`logger_context.cpp`。
- **已落地（Provider 层）**：`Provider::FlushLogs` 在 **`mutex_` 下仅拷贝 `provider_` shared_ptr**，**锁外**调用 `ForceFlush()`（内部仍为 `LoggerContext::ForceFlush` → `spdlog::apply_all`）。多 bthread 并发打日志时，其它读者不再被整段 flush 堵在全局 Provider 锁上。
- **仍建议人工审查**：`apply_all(FlushLogger)` 调用点、以及是否在 **业务大锁** 内调用 `FlushLogs` / `ForceFlush`（本改动不解决「调用方持大锁再 flush」的问题）。

### 1.3 回归与基线（操作项，无额外代码）

- 合入前后：`collect_client_lock_baseline.sh`，与阶段 0 run 做 `compare_client_lock_baseline.sh`。
- **必须**：`inline_*_avg_us_mean` 或等价绝对指标 **较阶段 0 下降**（同环境）；同时 **KV 门禁全绿**。

## 依赖

- 阶段 0 已完成并存在可对比的 `runs/` 目录。
- 参考：`plans/lock_scope_analysis/kv_lock_in_syscall_cases_report.md` Case A、B。

## 风险

- `SetPollOut` 外移可能导致边缘竞态，需重点测 **高并发发送** 与 **连接切换**。
- Flush 外移后，极短窗口内「进程崩溃丢日志」语义若变弱，需在发布说明中写明可接受范围。

## 本阶段验收

| 类型 | 标准 |
|------|------|
| 正确性 | `validate_brpc_kv_executor.sh` / 相关 ZMQ 与日志单测通过；无新增 flaky。 |
| 性能 | 对比基线：**至少一项绝对 µs 指标下降**（见 `ACCEPTANCE_CHECKLIST.md`）。 |
| KV | **KVClientBrpcBthreadReferenceTest**（及脚本内关联 ctest）**必须通过**。 |
