# 当前 PR：死锁/假死如何复现？是否可复现？（实验验证步骤）

## 1. 结论（先回答）

- **可以复现**：在当前 PR 的 executor 注入机制下，存在一个**可确定复现**的“自提交 + 自等待”死锁/假死场景。
- **复现形态**：在测试用例中体现为 **RPC 超时**（`cntl.ErrorCode()!=0`），其根因是 KV 调度层在 executor worker 内部再次 `Submit()` 并 `Wait()`，导致**同一个单 worker executor 队列无法前进**（经典自等待死锁）。
- **对照组**：同一用例中提供了 “bad” 与 “good” 两种 executor 实现，能稳定展示“会死锁 vs 不会死锁”的对比。

对应用例位置：

- `tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp`
  - `BadBthreadExecutor`：`InExecutorThread()` 恒为 false（**必现问题模型**）
  - `GuardedBthreadExecutor`：用 `thread_local` 标记 executor worker（**正确模型**）
  - `TEST_F(..., BrpcRpcBthreadKvDeadlockContrast)`：同一进程内先跑 bad 再跑 good

> 说明：这里的“死锁/假死”是 **executor 层面的自等待死锁**，不是业务锁（pthread mutex）意义上的锁顺序环；但对用户表现一致：请求卡住直到超时。

---

## 2. 复现原理（为什么会卡住）

KVClient 的同步接口（`Set/Get/...`）内部统一走：

- 有 executor：`Submit(fn) -> handle->Wait()`
- 没 executor：inline 执行
- 为避免“worker 线程内二次 submit 自等待”，需要依赖 `IKVExecutor::InExecutorThread()`：
  - 若返回 true：直接 inline 执行 `fn()`（reentrant bypass）
  - 若返回 false：会再次 `Submit()` 然后 `Wait()` —— 如果 executor 只有单 worker，则会形成自等待死锁

用例中构造的 “bad” executor 正是让 `InExecutorThread()` 错误返回 false，从而稳定复现。

---

## 3. 实验步骤（复现 + 验证）

### 3.1 前置条件

- 已构建 ST 测试二进制（通常为）：`build/tests/st/ds_st_kv_cache`
- **需要 brpc/bthread 依赖可用**：该用例在源码中有条件编译：
  - 若 `<bthread/bthread.h>` 或 `<brpc/server.h>` 不可用，则会 `GTEST_SKIP()`，无法复现

### 3.2 运行单测（推荐一键命令）

在仓库根目录执行（按你们构建产物路径调整 `build/`）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
./build/tests/st/ds_st_kv_cache \
  --gtest_filter=KVClientBrpcBthreadReferenceTest.BrpcRpcBthreadKvDeadlockContrast \
  --gtest_color=yes
```

### 3.3 预期结果（如何判断“复现了”）

该用例内包含两段对比：

- **bad 模式**（必现）：`InvokeRunRpc(..., "bad", 1200ms, ...)` 之后
  - 断言：`ASSERT_NE(0, cntl.ErrorCode());`
  - 含义：RPC 在 1200ms 内**未完成**，触发超时/失败（表现为“卡住直到超时”）
- **good 模式**（应通过）：`InvokeRunRpc(..., "good", 4000ms, ...)`
  - 断言：`ASSERT_EQ(0, cntl.ErrorCode())` 且 `rsp.status_code()==K_OK`

如果你的环境 brpc/bthread 可用，那么该用例应稳定呈现上述对比。

---

## 4. 额外验证：如何用“证据”确认是自等待死锁

> 这部分不是必须，但能给客户“证据链”：**等待机制（futex/condvar）+ 系统调用（poll/epoll）/或队列不可前进**。

### 4.1 现象证据（无 root）

- 将 `bad` 子场景 timeout 适当调大（当前为 1200ms，已足够）后，在超时窗口内：
  - 观察进程线程数稳定、CPU 低、请求不返回

### 4.2 调试证据（可选）

如果可以在本机调试：

- 在卡住窗口内 attach 到 `ds_st_kv_cache`：
  - 使用 gdb 打印所有线程 backtrace（可在内部 runbook 里写标准命令）
  - 典型会看到：
    - 一个 executor worker bthread 在执行 outer task
    - outer task 内部调用 `KVClient::Set/Get`
    - KVClient 再次 `Submit` 并 `Wait`
    - executor worker 自己等待自己队列推进（无法推进）

---

## 5. 如何把“复现”变成“整改验收”

验收目标不是“bad 模式也能通过”（bad 模式本身就是错误实现的模拟器），而是：

1. **SDK 必须提供明确的契约**：实现 `IKVExecutor` 的人必须正确实现 `InExecutorThread()`，否则会死锁/假死。
2. **SDK 需要自保护（建议项）**：
   - 在 `DispatchKVSync` 的 `Submit` 分支增加防御性检测与日志（例如检测递归 submit 的 tag/深度、或对同线程重入做保护），把“卡死”降级为可诊断错误。
3. **good executor 必须稳定通过**：即 `GuardedBthreadExecutor` / pthread threadpool executor 路径长压不挂。

---

## 6. 关联文档

- 两套方案对比（方案 2=当前 PR executor 注入）：`plans/kvexec/kv_runtime_two_schemes.md`
- KV “锁内系统调用”case 报告（另一个维度的死锁/长尾风险）：`plans/lock_scope_analysis/kv_lock_in_syscall_cases_report.md`

---

## 7. 追加实验：验证“bthread 在可挂起点后可能切到另一个 pthread”

新增实验用例：

- `tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp`
- 用例名：`KVClientBrpcBthreadReferenceTest.BthreadMayResumeOnDifferentPthreadAfterYield`

实验方法（简述）：

1. 启动多条 bthread 任务并提升 bthread 并发度（`bthread_setconcurrency(8)`）。
2. 每条任务循环执行 `bthread_usleep(1000)`（可挂起点）。
3. 每轮比较 `pthread_self()` 是否变化，统计切换次数 `switchCount`。
4. 汇总 `totalSwitches`，断言 `totalSwitches > 0`。

这个实验用于回答机制问题：

- **成立**：在 bthread 可挂起点恢复后，**同一 bthread** 可能落到不同 pthread（迁移发生）。
- 因此，若业务在这类上下文中使用“依赖 pthread 线程亲和”的状态（例如 pthread TLS/锁假设），就必须显式评估并规避。

运行命令：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
./build/tests/st/ds_st_kv_cache \
  --gtest_filter=KVClientBrpcBthreadReferenceTest.BthreadMayResumeOnDifferentPthreadAfterYield \
  --gtest_color=yes
```

判定：

- 通过：说明本机运行时观测到 bthread->pthread 迁移；
- 若依赖缺失导致 `GTEST_SKIP()`：先按 `plans/kvexec/executor_injection_prs/brpc_bthread_reference_test_guide.md` 补齐 brpc/bthread 环境再复测。
- 若用例本身 `GTEST_SKIP()` 且提示 `No bthread->pthread migration observed in this run`：
  - 表示当前运行时/负载条件下未触发迁移，不代表机制上不可能；
  - 需要在更高并发、更长运行窗口或更贴近线上的 brpc 负载下继续采样验证。

### 7.1 本次实测记录（2026-04-02）

- 编译目标：`ds_st_kv_cache`（成功）
- 运行：`KVClientBrpcBthreadReferenceTest.BthreadMayResumeOnDifferentPthreadAfterYield`
- 结果：`SKIPPED`（观测值 `totalSwitches=0`）

结论解释：

- 当前环境中未直接观测到 bthread->pthread 迁移证据；
- 但该结果仅说明“**这次运行未触发**”，不能推翻“bthread 在可挂起点后可能迁移”的机制可能性；
- 因此，关于“pthread lock + 系统调用 + bthread 切 pthread”这条根因链，当前状态是：**理论成立、此轮未观测到正样本，需继续做高负载采样实验确认。**

### 7.2 多轮采样结果（2026-04-02，20 轮）

采样方法：

- 固定用例：`KVClientBrpcBthreadReferenceTest.BthreadMayResumeOnDifferentPthreadAfterYield`
- 连续运行 `20` 轮，提取每轮输出 `MIGRATION_SWITCHES total=<n>`

统计结果：

- `runs=20`
- `observed_migration_runs=0`
- `zero_switch_runs=20`
- `missing_switch_marker_runs=0`
- `passed_runs=0`
- `skipped_runs=20`
- `failed_runs=0`

结果文件：

- `workspace/observability/perf/bthread_pthread_migration_sampling.json`
- `workspace/observability/perf/bthread_pthread_migration_sampling.csv`

解释：

- 在当前测试环境与负载模型下，连续 20 轮均未观测到 bthread->pthread 迁移正样本；
- 这说明迁移在本环境中不是高概率事件，当前“pthread lock + 系统调用 + bthread 切 pthread”链路尚未被实测闭环；
- 若要进一步逼近线上行为，建议后续引入：
  - 更高 bthread 并发和更长运行窗口；
  - 更贴近 brpc 真实请求压力的 server 回调负载；
  - 结合线程级 trace（记录 bthread id 与 pthread id 对）进行长时间采样。

