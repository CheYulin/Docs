# RFC: KVClient Executor Injection for Coroutine-Safe Sync Calls

## Metadata

- **Status**: Draft
- **Authors**: datasystem client team
- **Last Updated**: 2026-04-01
- **Related PR Description**: `plans/kvexec/executor_injection_prs/kv_client_executor_injection_pr_description.md`

## 1. Background

`KVClient` currently exposes synchronous APIs. In coroutine runtimes (especially M:N scheduling models such as bthread/brpc), directly executing sync KV flows in coroutine context can increase deadlock risk when lock scope and blocking behavior interact.

We need a non-intrusive way to adapt runtime execution behavior without changing existing `KVClient` API usage.

## 2. Problem Statement

We need to:

- keep `KVClient` public interface unchanged;
- allow runtime-injected execution strategy (submit + wait);
- preserve backward-compatible behavior when no runtime executor is injected;
- provide a path for coroutine-friendly executors (bthread-adapted).

## 3. Goals

- Introduce an executor abstraction for sync KV dispatch.
- Support optional process-wide runtime injection.
- Avoid nested-submit deadlock via reentrant short-circuit.
- Provide E2E tests for normal and error branches.
- Prepare bthread-based executor integration with graceful capability fallback.

## 4. Non-Goals

- No public API signature changes for existing `KVClient` methods.
- No mandatory dependency on brpc/bthread in all builds.
- No full runtime scheduler redesign in this RFC.

## 5. Proposed Design

### 5.1 Runtime abstraction

Introduce:

- `IKVExecutor`
- `IKVTaskHandle`

Global registry:

- `RegisterKVExecutor(...)`
- `ClearKVExecutor()`
- `GetKVExecutor()`

### 5.2 Dispatch model in KVClient

For synchronous KV calls:

1. If no executor is registered: execute inline in current thread.
2. If current thread is already executor thread: execute inline (reentrant guard).
3. Otherwise: submit task, synchronously wait for completion.

Error handling:

- null task handle -> runtime error
- submit/wait throws `std::exception` -> runtime error with detail
- submit/wait throws unknown -> runtime error

### 5.3 bthread adapter (optional capability)

Provide:

- `CreateBthreadKVExecutor(std::shared_ptr<IKVExecutor>&)`

Behavior:

- if bthread headers/runtime are available: create bthread-backed executor
- if unavailable: return `K_NOT_SUPPORTED` and keep system behavior unchanged

This keeps default builds dependency-safe while enabling brpc/bthread integration in capable environments.

## 6. API and Interface Changes

### Added

- `include/datasystem/kv_executor.h`
- `include/datasystem/kv_bthread_executor.h`

### No breaking changes

- Existing `KVClient` user-facing APIs remain unchanged.
- Existing callers do not need migration.

## 7. Compatibility

- **Backward compatibility**: preserved (inline behavior by default).
- **Build compatibility**: preserved (bthread adapter is capability-gated).
- **Runtime compatibility**: executor injection is optional and process-scoped.

## 8. Risk Analysis

### R1: Nested submit deadlock

- **Mitigation**: `InExecutorThread()` short-circuit to inline execution.

### R2: Runtime dependency mismatch

- **Mitigation**: bthread adapter returns `K_NOT_SUPPORTED` when unavailable; tests skip accordingly.

### R3: Error-path invisibility

- **Mitigation**: dedicated E2E tests for null handle and exception branches.

## 9. Testing Strategy

Primary suite:

- `tests/st/client/kv_cache/kv_client_executor_runtime_e2e_test.cpp`

Coverage targets:

- inline fallback path
- submit+wait path
- reentrant path
- null handle path
- std exception path
- unknown exception path
- bthread path (enabled when dependency exists, skip otherwise)

## 10. Rollout Plan

1. Merge abstraction + dispatch + tests.
2. Enable bthread adapter where dependency exists.
3. Observe deadlock-related regressions and timeout telemetry.
4. Expand stress scenarios in coroutine runtime environments.

## 11. Rollback Plan

Fast rollback options:

- clear process executor registration (`ClearKVExecutor()`) to force inline path
- revert `KVClient` dispatch wrapping commit if severe regression appears

## 12. Acceptance Criteria

- All existing `kv_cache` STs pass under default (no executor) behavior.
- Executor runtime E2E passes for all non-capability-gated branches.
- bthread scenario executes and validates no deadlock in environments with bthread support.
- No public API break for existing callers.

## 13. Issue Template (optional)

**Title**: KVClient sync API deadlock risk in coroutine runtime; introduce optional executor injection

**Description**:

- In coroutine runtimes, current sync KV execution path may deadlock under lock+blocking interactions.
- Propose adding process-wide optional executor injection for sync dispatch.
- Keep `KVClient` public API unchanged.
- Add bthread-capable executor adapter and E2E deadlock regression tests.

**Definition of Done**:

- abstraction + dispatch + tests merged
- error branches covered
- bthread path validated or capability-gated skip with clear signal

