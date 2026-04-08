# brpc + 大量 bthread 并发：收益排序与落地说明

## 为何单独排序

在 brpc 下，**大量 bthread 映射到少量 pthread**。若热路径持 **`std::mutex` / `WriteLock` 期间做 `epoll_ctl`、同步 flush、RPC**，则：

- 多个 bthread 会在 **同一把用户态锁** 上排队；
- 持锁线程阻塞 syscall 时，**占满所属 pthread**，放大 M:N 下的尾延迟与假死风险。

因此：**谁被「每条 RPC」调用、谁在锁内 syscall，谁就排第一。**

## 推荐优先级（性能受益大 → 小）

| 顺序 | 项 | 理由 |
|------|-----|------|
| **1** | **ZMQ 出站：`outMux_` 内只做入队，`SetPollOut`（epoll_ctl）锁外** | 每条走 UDS/TCP 池的发送都经过；多 bthread 同时 `Channel::Call` 时竞争同一 `outMux_`，原先锁内 `epoll_ctl` 把临界区拉满。**已落地**：`zmq_stub_conn.cpp::RouteToUnixSocket`、`zmq_server_impl.cpp::IOService::Send`。 |
| **2** | **spdlog `Provider::FlushLogs` 锁外 flush** | 全局 provider 锁 + 多 bthread 打日志时串行；次热但面广。**已落地**：`provider.cpp` 中锁内仅拷贝 `provider_` shared_ptr，锁外 `ForceFlush()`。`LoggerContext::ForceFlush` 仍含 `apply_all`，见 `phase_01_zmq_spdlog_infra.md`。 |
| **3** | **`shutdownMux_` shared 跨整段 RPC**（阶段 2b） | Object/KV 业务路径高频；持锁跨度长时，多 bthread 在 shared 上仍与 unique 升级/写者竞争。 |
| **4** | **`globalRefMutex_` 内 RPC**、**MmapManager 大锁**、**DecreaseShmRef** 等 | 按调用频率与持锁时间次之。 |

## 与验收的关系

- 改动 **1** 后，在 **相同集群、相同 QPS、多 bthread 并发** 下，应能看到 **绝对时延**（如 `inline_*_avg_us_mean` 或自测 p95）相对基线 **下降**；仅 ratio 不够（见 `ACCEPTANCE_CHECKLIST.md`）。
- **KV brpc 参考用例**仍须全绿：`scripts/verify/validate_brpc_kv_executor.sh`。

## 后续可增强的压测（建议）

在 `kv_client_brpc_bthread_reference_test.cpp` 或独立 binary 上增加：**N 个并发 bthread 同时发 `Run` RPC**（N ∈ {8, 32, 64}），对比改造前后 **p99 / 超时次数**；无需 sudo。
