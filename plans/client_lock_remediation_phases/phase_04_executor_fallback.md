# 阶段 4：兜底 — IKVExecutor / pthread 池隔离

## 目标

- 对 **短期无法拆锁** 的阻塞段，避免在 bthread 上直接持 pthread 锁进入长阻塞（与 brpc `bthread_mutex` 告警语义一致）。
- 与现有 **`KVClient` + `IKVExecutor` 注入** 机制对齐，不重复造轮子。

## 工作事项

1. **梳理入口**：列出仍可能在 bthread 中调用的 `KVClient` / Object API，标记「仍阻塞」的调用链。
2. **执行策略**：  
   - 优先 **继续阶段 1–3 拆锁**；  
   - 仅对剩余热点使用 **专用 executor**（pthread 线程池或已有 `GuardedBthreadExecutor` 模式）包裹阻塞段。
3. **参考测试**：`tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp` 中 `bad`/`good` 模式；阅读 `.third_party/.../bthread_mutex_unittest.cpp` 注释中的 pthread 锁风险说明。

## 依赖

- `datasystem/kv_executor.h`、`kv_client.cpp` 注入点；`brpc_bthread_reference_test_guide.md`。

## 风险

- 线程池过深可能导致延迟上升；需限并发、监控队列长度。
- 兜底 **不能替代** 锁范围治理，否则资源与复杂度持续累积。

## 本阶段验收

| 类型 | 标准 |
|------|------|
| 正确性 | `KVClientBrpcBthreadReferenceTest` **good 模式**仍成功；**bad 模式**仍可按设计暴露问题（若保留该对照）。 |
| 性能 | 注入路径的 **绝对时延** 在文档阈值内（可参考 `kv_executor_perf_analysis.py` 倍率与绝对值双重约束）。 |
| KV | **全部门禁 KV 用例通过**。 |
