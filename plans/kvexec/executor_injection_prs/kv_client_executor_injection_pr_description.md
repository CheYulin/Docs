# /kind feat

**这是什么类型的PR？**

/kind feat（新增能力）

---

**这个PR是做什么的/我们为什么需要它**

- 在不改 `KVClient` 用户接口的前提下，引入可选执行器注入能力。
- 同步接口统一走“可选 submit+wait 分发”：
  - 未注册执行器：内联执行（保持历史行为）。
  - 已注册执行器：提交执行并同步等待。
  - 当前已在执行器线程：内联执行（避免嵌套提交风险）。
- 清理无意义对外暴露：删除 `include/datasystem/kv_bthread_executor.h`。

---

**此PR修复了哪些问题**:

Fixes #（替换为实际 issue 编号）

---

**PR对程序接口进行了哪些修改？**

- 新增公开抽象：`include/datasystem/kv_executor.h`
  - `IKVTaskHandle`
  - `IKVExecutor`
  - `RegisterKVExecutor / ClearKVExecutor / GetKVExecutor`
- `KVClient` 现有业务接口签名不变，仅内部执行路径改为统一分发。
- `include/datasystem/datasystem.h` 移除 `kv_bthread_executor.h` 包含。
- 删除 `include/datasystem/kv_bthread_executor.h`（不再作为客户接口）。

---

**关键信息**

- 方案边界确认：主模块仅保留 `IKVExecutor` / `IKVTaskHandle` 抽象，不引入运行时特定实现术语到 `src`。
- 调度策略确认：同步接口统一分发，采用“执行器优先 + 内联回退 + 重入短路”三段逻辑。
- 兼容性确认：`KVClient` 对外方法签名不变，未注册执行器时行为与历史版本一致。
- 风险控制确认：通过 `InExecutorThread()` 避免嵌套提交；异常路径统一收敛为稳定错误返回。
- 后续演进建议：
  - 评估 `WaitFor(...)` 超时策略是否需要框架级统一；
  - 评估执行器注册器是否从进程级演进为实例级隔离（如后续多租户/多配置场景需要）。

---

**实现思路**

- 统一分发入口：所有同步调用先进入内部 `DispatchKVSync`。
- 三段执行逻辑：
  - 无执行器：直接内联执行；
  - 有执行器且不在执行器线程：`Submit + Wait`；
  - 已在执行器线程：直接内联，避免嵌套提交。
- 异常处理：空任务句柄、标准异常、未知异常统一转换为稳定错误返回。
- 设计边界：主模块仅依赖 `IKVExecutor/IKVTaskHandle` 抽象，不耦合具体运行时实现。

---

**验证结果（简版）**

- 构建：`ds_st_kv_cache` 构建通过。
- 用例：`KVClientExecutorRuntimeE2ETest.*` 覆盖无执行器、注入执行器、重入、异常分支并通过。
- 约束：`src` 目录关键字审计（`brpc/bthread`）无命中。
- 可复现：见 `plans/kvexec/executor_injection_prs/kv_client_executor_validation_report_2026-04-01.md` 与 `scripts/verify/validate_kv_executor.sh`。

---

**Commit提交信息说明**：

**MR标题格式**：`feat[kv_cache]：支持KVClient可选执行器注入并保持接口兼容`

**Commit信息格式（建议）**：

```text
feat: add optional executor injection for KVClient sync dispatch

- add IKVExecutor/IKVTaskHandle and runtime registry APIs
- dispatch KVClient sync APIs through executor with inline fallback
- cover no-executor/injected/reentrant/exception branches in ST
- remove non-meaningful public header kv_bthread_executor.h

Signed-off-by: <YourName> <your.email@example.com>
```

---

**Self-checklist**:（请在提交前确认）

- [x] **设计**：已按“接口不变 + 可选注入 + 默认兼容”实现。
- [x] **测试**：已覆盖无执行器、注入执行器、重入、异常分支。
- [x] **验证**：已有可复现验证文档与一键脚本。
- [x] **接口**：业务接口签名不变，新增抽象接口并清理无意义公开头文件。
- [x] **文档**：RFC/PR/验证文档已补齐到 `plans`。

