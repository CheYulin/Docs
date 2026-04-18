# /kind refactor

**这是什么类型的 PR？**

/kind refactor（含可靠性语义修复与可观测性增强；不改变对外 API）

---

**这个 PR 是做什么的 / 我们为什么需要它**

- 修复 URMA wait timeout 错误码语义，避免误落入 RPC 语义码。
- 补齐 TCP/URMA 关键故障日志，统一可检索前缀与上下文字段。
- 对 `K_RPC_UNAVAILABLE(1002)` 做子分类前缀，提升 TCP/RPC 问题定界效率。
- 提供自动化日志验收脚本与远端流程接入，降低人工漏检与回归成本。

---

**此 PR 修复了哪些问题**

关联：KVClient URMA/TCP 定界与可观测性整改专项。  
Fixes #<ISSUE_ID>

---

**PR 对程序接口进行了哪些修改？**

- 无客户可见 API 签名变化。
- 内部错误语义与日志增强：
  - URMA timeout 统一返回 `K_URMA_WAIT_TIMEOUT`
  - TCP/RPC 1002 前缀子分类
  - URMA 故障日志统一关联字段并限频

---

**关键信息**

- **可靠性语义**
  - 共享 `Event`/`EventWaiter` 超时为 **1001**；**仅** `UrmaManager::WaitToFinish` 对外映射 **1010**；UCP 等非 URMA 路径保持 **1001**（见下文「评审问题修复说明」）。
  - reconnect / poll / recreate 场景日志可直接检索。

- **可观测性**
  - TCP 与 URMA 双域定界关键字体系可独立检索。
  - URMA 故障日志关联字段：`remoteAddress`、`remoteInstanceId`、`operationType`。
  - worker 侧补充：`remoteWorkerId`（`remoteAddress -> workerId` 映射）。

- **性能开销控制**
  - 新增日志仅故障路径输出。
  - 使用 `LOG_EVERY_N` 限频，避免故障风暴时日志反压。

---

**实现思路（摘要）**

- **URMA 核心路径**
  - `rdma_util.h` / `urma_manager.cpp`：修复超时错误码语义。
  - `urma_manager.cpp`：`URMA_POLL_ERROR`、`URMA_NEED_CONNECT`、`URMA_RECREATE_JFS*` 日志增强。
  - `urma_resource.h/.cpp`：`UrmaEvent` 增加只读上下文，JFS 重建日志增强。

- **TCP/RPC 路径**
  - `zmq_msg_queue.h`、`zmq_stub_impl.h`、`zmq_stub_conn.cpp`、`unix_sock_fd.cpp`、`client_worker_common_api.cpp`：
    1002 子分类前缀统一。

- **验收流程**
  - 新增：`scripts/testing/verify/validate_urma_tcp_observability_logs.sh`
  - 新增：`./ops test.urma_tcp_logs`
  - 接入：`scripts/build/remote_build_run_datasystem.sh` 可选日志验收参数。

---

## 评审问题修复说明（共享 Event 与 1010 分类）

以下回应 Code Review 中两类问题：**(A) 共享 `Event` 超时误标 URMA；(B) `K_URMA_WAIT_TIMEOUT`(1010) 未纳入通用 timeout/retry 分类**。代码路径均以 **`yuanrong-datasystem` 仓库根目录** 为准。

### (A) 通用 `Event`/`EventWaiter` 超时不应直接返回 1010

**问题**：`Event::WaitFor` / `EventWaiter::WaitAny` 为共享原语；若超时统一返回 `K_URMA_WAIT_TIMEOUT`，则 **UCP** 等同样调用 `Event::WaitFor` 的路径（如 `src/datasystem/common/rdma/ucp_manager.cpp::WaitToFinish`）会被误标为 URMA，且与上层按 **`K_RPC_DEADLINE_EXCEEDED`(1001)** 处理超时的约定不一致。

**修复**：

1. **`Event::WaitFor` / `EventWaiter::WaitAny`**：超时返回 **`K_RPC_DEADLINE_EXCEEDED`**，通用文案（不带 URMA 专用语义）。
2. **`UrmaManager::WaitToFinish`**：在 `event->WaitFor` 返回 **1001** 时，**映射为 `K_URMA_WAIT_TIMEOUT`** 并保留原消息；UCP 无此映射，仍从 `WaitFor` 得到 **1001**。

**证据（代码）** — `src/datasystem/common/rdma/rdma_util.h`：`WaitAny` / `WaitFor` 使用 `K_RPC_DEADLINE_EXCEEDED`。

**证据（代码）** — `src/datasystem/common/rdma/urma_manager.cpp`：`WaitToFinish` 内 `waitRc.GetCode() == K_RPC_DEADLINE_EXCEEDED` 时 `return Status(K_URMA_WAIT_TIMEOUT, waitRc.GetMsg())`。

**证据（代码）** — `src/datasystem/common/rdma/ucp_manager.cpp`：`WaitToFinish` 仅 `RETURN_IF_NOT_OK(event->WaitFor(...))`，无 1010 映射。

**证据（单测）** — `tests/ut/common/util/status_test.cpp`：`EventWaitForTimeoutReturnsDeadlineExceeded`、`EventWaitAnyTimeoutReturnsDeadlineExceeded` 断言 **1001** 与 `Timed out waiting for ...` 文案。

---

### (B) 1010 需同步纳入 timeout / RPC 错误分类与基于时间的重试白名单

**问题**：若 **`IsRpcTimeout` / `IsRpcError`** 不认 **1010**，且 **`RetryOnRPCErrorByTime`** 等显式重试集合不含 **1010**，则 URMA wait timeout 会绕开原有「超时 / 重试」语义。

**修复**：

- **`IsRpcTimeout`**（`src/datasystem/common/util/rpc_util.h`）：增加 **`StatusCode::K_URMA_WAIT_TIMEOUT`**（`IsRpcTimeoutOrTryAgain` 随之覆盖）。
- **`IsRpcError`**（`src/datasystem/common/rpc/zmq/zmq_common.h`）：增加 **1010**。
- **`RetryOnRPCErrorByTime`**（`rpc_util.h`）：`RetryOnError` 的 retry 码集合增加 **`K_URMA_WAIT_TIMEOUT`**。
- 业务侧 **`RetryOnError(..., 显式 retry 集合)`** 已在相关路径按需包含 1010；其它手写码表需个案审计。

**证据（代码）** — `rpc_util.h`：`IsRpcTimeout` 含 `K_URMA_WAIT_TIMEOUT`；`RetryOnRPCErrorByTime` 的集合含 `K_URMA_WAIT_TIMEOUT`。

**证据（代码）** — `zmq_common.h`：`IsRpcError` 含 `K_URMA_WAIT_TIMEOUT`。

**证据（单测）** — `tests/ut/common/util/rpc_util_test.cpp`：`IsRpcTimeoutIncludesUrmaWaitTimeout` 断言 **1010** 被 `IsRpcTimeout` / `IsRpcTimeoutOrTryAgain` 识别。

**说明**：`include/datasystem/utils/status.h` 与 `src/datasystem/common/util/status_code.def` 需已定义 **`K_URMA_WAIT_TIMEOUT`**，与上述引用保持一致。

**验证命令（示例）**：

```bash
./ds_ut --gtest_filter='StatusTest.EventWaitForTimeoutReturnsDeadlineExceeded:StatusTest.EventWaitForSucceedsAfterNotify:StatusTest.EventWaitAnyTimeoutReturnsDeadlineExceeded:StatusTest.EventWaitAnySucceedsAfterNotify:RpcUtilTest.IsRpcTimeoutIncludesUrmaWaitTimeout'
```

期望：**5/5 PASSED**；超时路径若输出 glog，可见 `Timed out waiting for request` / `Timed out waiting for any event`（与 `RETURN_STATUS_LOG_ERROR` 一致）。

---

**验证结果（简版）**

- 构建通过：
  - `common_rdma`
  - `worker_object_cache`
- 定向回归：
  - `UnixSockFdStatusTest.*` 通过（3/3）
- 脚本校验：
  - 新增脚本与 `ops` 入口语法校验通过
  - 文档与验收清单已同步更新

---

**Commit 提交信息说明**

**PR 标题示例**：  
`refactor(urma,tcp): improve fault observability boundaries and timeout semantics`

**Commit 信息建议**：

```text
refactor(urma,tcp): improve fault observability and timeout semantics

- return K_URMA_WAIT_TIMEOUT for urma wait timeout paths
- add structured URMA error logs with rate limiting
- add 1002 subclassification prefixes for TCP/RPC errors
- add automated URMA/TCP log validation script and ops entry
- sync verification docs and acceptance checklist
```

---

**Self-checklist**

- [ ] URMA wait timeout 语义一致（无 RPC 语义回退）
- [ ] `URMA_NEED_CONNECT` / `URMA_POLL_ERROR` / `URMA_RECREATE_JFS*` 日志可检索
- [ ] 1002 子分类前缀覆盖核心场景
- [ ] 自动与手工验收流程均可执行
- [ ] 无未声明的对外 API 行为变化
