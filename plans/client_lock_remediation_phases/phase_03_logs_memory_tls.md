# 阶段 3：业务日志、MemoryCopy、TLS / context（P1）

## 目标

- 减少 **业务临界区内的 spdlog 调用** 与同步路径。
- 避免 **大锁 + 并行 MemoryCopy + 线程池** 叠加放大尾延迟。
- bthread 落地时降低 **pthread TLS** 串扰导致的超时与重试。

## 工作事项

1. **业务锁内 LOG**  
   - 文件示例：`object_client_impl.cpp`、`comm_factory.cpp`、`stream_cache/*`、`listen_worker.cpp`、`router_client.cpp`。  
   - 模式：锁内只拷字符串/数字到局部变量，**锁外** `LOG/VLOG`；热路径用 `VLOG` + `LOG_EVERY_N/T`。  
   - **已部分落地**：`listen_worker.cpp` 中 `SwitchToRemoteWorker` / `TrySwitchBackToLocalWorker` 的异步任务在 `switchWorkerHandleMutex_` 内只拷贝 `workerId`/`clientId` 并执行 `switchWorkerHandle_`，**锁外**再打 `LOG(INFO)`。

2. **spdlog sink / async**  
   - 与运维/配置约定：延迟敏感服务启用 async、控制队列、避免请求路径 `FlushLogs`。

3. **MemoryCopy + ThreadPool**（KV Case H）  
   - 禁止在持有 `shutdownMux_` / 其它大粒度业务锁时发起 **大块** `MemoryCopy`（并行线程池路径）。  
   - 调 `memcpyParallelThreshold_`、线程池背压；观测上区分 latch 等待 vs 队列等待。

4. **TLS**  
   - `reqTimeoutDuration`、`g_ContextTenantId` 等：向 **显式 context** 或 fiber-local 迁移（与 `thread_local.h`、KV 报告 §5 一致）。

## 依赖

- 阶段 1–2 主干已稳定；本阶段可与阶段 2 尾部 **并行**（不同文件），但合并前仍须统一跑门禁。

## 风险

- 日志外移可能改变多线程下日志顺序（仅影响排查，一般不改变业务语义）。
- TLS 改造面大，需分 PR、配特性开关。

## 本阶段验收

| 类型 | 标准 |
|------|------|
| 正确性 | 相关模块测试通过；租户/超时上下文在单测或集成测试中无串扰回归。 |
| 性能 | 在约定压测下 **绝对时延或 p99** 不劣化于阶段 2（理想为继续下降）；须附对比数据。 |
| KV | **KV brpc 参考用例仍通过**（每次合入前跑）。 |
