# [RFC]: Optional Executor Injection and Sync Dispatch Refactor for KVClient

## 背景与目标描述

当前 `KVClient` 同步接口在默认实现中直接于调用线程执行。该模式在普通线程场景下可用，但在协程调度/混合线程模型下，若调用链中存在阻塞等待与锁交互，可能放大卡顿或死锁风险。与此同时，业务侧已广泛依赖现有 `KVClient` 接口，接口变更成本高。

本 RFC 的目标是：

- 在不改变 `KVClient` 用户接口签名和用法的前提下，提供可选执行器注入能力。
- 将同步接口统一走“提交 + 同步等待”的可控分发路径（可选）。
- 保持默认行为兼容：未注册执行器时仍为当前线程内联执行。
- 通过测试覆盖关键分支，确保功能正确性与稳定性。

## 建议的方案

1. **新增抽象接口与注册机制**
- 新增 `IKVExecutor` 与 `IKVTaskHandle` 抽象接口。
- 新增运行时注册 API：`RegisterKVExecutor`、`ClearKVExecutor`、`GetKVExecutor`。

2. **KVClient 同步接口统一分发**
- 在 `KVClient` 内部引入统一分发辅助逻辑：
  - 若执行器存在且当前不在执行器线程：`Submit` 后 `Wait`。
  - 若执行器不存在或当前已在执行器线程：直接内联执行（避免嵌套提交）。
- 对执行器异常（标准异常/未知异常）收敛为运行时错误，确保外部行为稳定可预期。

3. **接口清理与边界约束**
- 不引入额外客户可见的特定运行时适配接口。
- 删除无意义对外头文件暴露（`kv_bthread_executor.h`），避免 API 面污染。

4. **工程可复现验证能力**
- 提供一键脚本：`scripts/verify/validate_kv_executor.sh`，自动执行构建、关键测试、关键字审计。
- 补充验证文档，降低复现成本与误用成本。

## 涉及到的对外API

### 变更项
- 新增公开 API（抽象层）：
  - `include/datasystem/kv_executor.h`
    - `class IKVTaskHandle`
    - `class IKVExecutor`
    - `Status RegisterKVExecutor(const std::shared_ptr<IKVExecutor> &executor)`
    - `Status ClearKVExecutor()`
    - `std::shared_ptr<IKVExecutor> GetKVExecutor()`

### 不变项
- `KVClient` 既有业务接口签名保持不变（`Set/Get/Create/MSet/...` 等）。
- 默认使用方式不变；不注册执行器时行为与历史一致。

### 周边影响
- SDK/业务调用方无需改造即可继续使用原接口。
- 需要执行器能力的场景可按需注册，不影响未使用方。
- 清理了无意义公开头文件，减少客户侧误依赖风险。

## 测试验证

为保证功能、可靠性及回归质量，采用以下验证策略：

1. **功能正确性（ST）**
- 新增并运行 `KVClientExecutorRuntimeE2ETest.*`，覆盖：
  - 无执行器内联回退路径。
  - 注入执行器后的提交与同步等待路径。
  - 执行器线程重入避免嵌套提交路径。
  - 执行器返回空 handle 分支。
  - 执行器抛标准异常分支。
  - 执行器抛未知异常分支。

2. **构建与集成验证**
- 验证 `ds_st_kv_cache` 可完整构建并链接通过。
- 验证关键测试可通过 `ctest` 稳定执行。

3. **约束一致性验证**
- 审计 `src` 目录不包含 `brpc/bthread` 关键字，确保主实现层不耦合特定运行时术语。

4. **可复现流程**
- 使用 `scripts/verify/validate_kv_executor.sh` 一键复现：
  - build `ds_st_kv_cache`
  - run `KVClientExecutorRuntimeE2ETest`
  - audit forbidden keywords

> 已有验证结果与步骤可参考：
`plans/kvexec/executor_injection_prs/kv_client_executor_validation_report_2026-04-01.md`

## 期望的反馈时间

- 建议反馈周期：**7 天**（至少一周）。
- 期望在反馈周期内重点收集：
  - API 抽象边界是否合理（是否还需扩展能力）
  - 默认兼容策略是否满足现网接入预期
  - 测试覆盖是否满足合入门槛（特别是稳定性与异常路径）
