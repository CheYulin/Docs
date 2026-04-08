# Client 锁治理 — 分阶段工作包

本目录把 [`docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md`](../../docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md) 中的路线拆成 **按阶段可执行的 md**，每份含：**目标、工作事项、依赖、风险、本阶段验收**。

总原则：**正确性优先**；**性能须用绝对时延（µs/ms）证明收益**；**KV 相关用例必须能跑过**（见下方门禁）。

## brpc + 多 bthread：先做哪件（性能优先）

见 **[brpc_many_bthread_priority.md](./brpc_many_bthread_priority.md)**。摘要：**每条 RPC 都走的 ZMQ 出站路径上，已把 `SetPollOut`（epoll_ctl）移出 `outMux_`**；**`Provider::FlushLogs` 锁外 flush**；Object client **ShutDown 锁外 Disconnect**、**Rediscover 锁外 `SelectWorker`**；`listen_worker` 切换路径 **锁外 LOG**（详见各 `phase_01`～`phase_03`）。

## 文档索引

| 文件 | 阶段 | 核心内容 |
|------|------|----------|
| [brpc_many_bthread_priority.md](./brpc_many_bthread_priority.md) | — | **多 bthread 场景下的收益排序 + 已落地项** |
| [phase_00_baseline_gate.md](./phase_00_baseline_gate.md) | 0 | 基线采集、无 sudo 门禁、run 目录约定 |
| [phase_01_zmq_spdlog_infra.md](./phase_01_zmq_spdlog_infra.md) | 1 | ZMQ 锁范围、spdlog Provider/Flush |
| [phase_02_object_client_wide_locks.md](./phase_02_object_client_wide_locks.md) | 2 | Object client 宽锁、mmap、ref、切换、DecreaseShmRef、CommFactory |
| [phase_03_logs_memory_tls.md](./phase_03_logs_memory_tls.md) | 3 | 业务锁外 LOG、MemoryCopy、TLS/context |
| [phase_04_executor_fallback.md](./phase_04_executor_fallback.md) | 4 | IKVExecutor / pthread 池兜底 |
| [**ACCEPTANCE_CHECKLIST.md**](./ACCEPTANCE_CHECKLIST.md) | — | **明日起床按条验收（正确性 + 性能 + KV）** |
| [**LOCK_SCOPE_INVENTORY.md**](./LOCK_SCOPE_INVENTORY.md) | — | **各锁保护域 + 持锁内 RPC/syscall/futex 风险清单（核对用）** |
| [**issue_rfc_client_lock_scope_remediation.md**](./issue_rfc_client_lock_scope_remediation.md) | — | **RFC Issue 正文（发帖用，中文）** |
| [**client_lock_scope_remediation_pr_description.md**](./client_lock_scope_remediation_pr_description.md) | — | **MR/PR 描述模板（中文）** |
| [**comm_factory_lock_rpc_remediation_deferred.md**](./comm_factory_lock_rpc_remediation_deferred.md) | — | **异构 CommFactory 锁外 RPC 设计备案（代码暂缓）** |
| [../kvexec/kv_concurrent_lock_perf.md](../kvexec/kv_concurrent_lock_perf.md) | — | **高并发 KV Set/Get 延迟基准（对比锁优化前后）** |

## 与总 plan 的关系

- 背景、风险表、与 KV 报告对照：仍以 [`docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md`](../../docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md) 为准。
- **落地拆活与阶段验收**：以本目录各 `phase_*.md` + `ACCEPTANCE_CHECKLIST.md` 为准。

## KV 与 brpc 门禁（全阶段通用）

任何合入本治理相关改动的 MR，在能启用 brpc 参考构建时，应保证：

```bash
bash scripts/verify/validate_brpc_kv_executor.sh
```

或至少：

```bash
ctest --test-dir <build> --output-on-failure -R "KVClientBrpcBthreadReferenceTest"
```

（需按 `plans/kvexec/executor_injection_prs/brpc_bthread_reference_test_guide.md` 配置 `ENABLE_BRPC_ST_REFERENCE` 与 `BRPC_ST_ROOT`。）

基线收集：

```bash
bash scripts/perf/collect_client_lock_baseline.sh [--build-dir build] [--skip-perf]
bash scripts/perf/compare_client_lock_baseline.sh <基线run目录> <当前run目录>
```
