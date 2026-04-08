# 第三方库锁/IO风险识别报告（基于 KV Tests + Strace）

## 背景与方法

目标：通过已有 `kv tests`（含 brpc+sdk smoke）识别第三方库中可能放大 bthread 阻塞/死锁风险的代码点，并评估整改工作量。

本次采用两步：

1. **动态证据**：使用 `scripts/perf/trace_kv_lock_io.sh` 对以下用例采集 `strace -ff`  
   - `KVClientBrpcBthreadReferenceTest.BrpcSdkExecutorSmokeGoodPathBatch`
   - `KVClientExecutorRuntimeE2ETest.*`
2. **静态审计**：针对仓库内第三方源码（重点 `brpc/bthread/butil`）做锁+IO模式扫描。

采样产物：

- `workspace/observability/strace/trace_20260402_122304_report.md`
- `workspace/observability/strace/trace_20260402_122304_summary.json`

## 动态结果摘要（strace）

- 锁相关 syscall：
  - `futex`: `150863` 次，`15021.445653s`
  - `fcntl`: `2851` 次
- 等待/IO相关 syscall：
  - `epoll_wait`: `22196` 次，`1774.479896s`
  - `poll`: `15986` 次，`244.936607s`
  - `read/write/sendto/recvfrom/recvmsg/sendmsg` 高频
  - `pread64/pwrite64` 存在

结论：在当前测试链路中，第三方运行时（事件循环 + 锁等待）与网络/文件IO叠加明显，具备“锁内阻塞被放大”的客观条件。

## 风险代码点（第三方）

## P0-1：`butil logging` 在全局日志锁内执行文件写与 flush

文件：`.third_party/brpc_st_compat/src/brpc/src/butil/logging.cc`

```426:447:.third_party/brpc_st_compat/src/brpc/src/butil/logging.cc
void Log2File(const std::string& log) {
    LoggingLock::Init(LOCK_LOG_FILE, NULL);
    LoggingLock logging_lock;
    if (InitializeLogFileHandle()) {
        fwrite(log.data(), log.size(), 1, log_file);
        fflush(log_file);
    }
}
```

风险：

- 日志锁持有期间执行 `fwrite/fflush`，在磁盘压力、NFS、容器慢盘场景下可能长阻塞。
- 该阻塞会放大调用方线程/协程的停顿。

建议：

1. 优先启用异步日志路径，减少同步 `fflush` 频率。  
2. 评估把 flush 改为批量/定时策略（非每条日志 flush）。  
3. 高频路径降级日志级别，避免在临界路径密集写日志。

工作量评估：**M（3~5人日）**，主要是参数/策略和回归验证。

## P0-2：`NamingServiceThread::AddWatcher` 在内部锁下回调外部 watcher

文件：`.third_party/brpc_st_compat/src/brpc/src/brpc/details/naming_service_thread.cpp`

```338:353:.third_party/brpc_st_compat/src/brpc/src/brpc/details/naming_service_thread.cpp
int NamingServiceThread::AddWatcher(...) {
    BAIDU_SCOPED_LOCK(_mutex);
    if (_watchers.emplace(watcher, filter).second) {
        if (!_last_sockets.empty()) {
            std::vector<ServerId> added_ids;
            ...
            watcher->OnAddedServers(added_ids);
        }
        return 0;
    }
    return -1;
}
```

风险：

- 在 `_mutex` 持有期间执行外部回调 `OnAddedServers`。  
- 若回调内部触发网络IO/锁竞争/阻塞等待，会形成锁放大，甚至反向锁依赖。

建议：

1. 改成“锁内快照 -> 解锁 -> 回调”。  
2. 仅在锁内维护 `_watchers/_last_sockets` 状态，不执行用户代码。  
3. 增加回调超时/慢回调监控。

工作量评估：**M~L（5~8人日）**，涉及行为兼容和并发回归。

## P1-3：`bthread mutex` 已显式记录 bootstrap/采样死锁敏感性

文件：`.third_party/brpc_st_compat/src/brpc/src/bthread/mutex.cpp`

```525:552:.third_party/brpc_st_compat/src/brpc/src/bthread/mutex.cpp
// ... otherwise deadlock may occur.
static __thread bool tls_inside_lock = false;
...
LOG_BACKTRACE_ONCE(ERROR) << "bthread is suspended while holding "
                          << tls_pthread_lock_count << " pthread locks.";
```

风险：

- 该模块本身已有“采样/锁/调度”死锁敏感注释与保护逻辑，说明运行时层面对 lock+schedule 非常敏感。
- 不是直接 bug，但提示上层应避免“持 pthread 锁进入可挂起路径”。

建议：

1. 上层（datasystem）坚持“锁内不做RPC/等待/重IO”。  
2. 压测时打开相关诊断日志，监控 `holding pthread locks` 告警。

工作量评估：**S（1~2人日）**，以监控和文档约束为主。

## P1-4：`Socket::WaitEpollOut` 显式 butex 等待，调用方若持业务锁会放大阻塞

文件：`.third_party/brpc_st_compat/src/brpc/src/brpc/socket.cpp`

```1253:1275:.third_party/brpc_st_compat/src/brpc/src/brpc/socket.cpp
int Socket::WaitEpollOut(...) {
    ...
    int rc = bthread::butex_wait(_epollout_butex, expected_val, abstime);
    ...
    return rc;
}
```

风险：

- 等待语义本身合理，但如果上层在持有业务锁时进入该路径，锁持有时长会被网络可写等待放大。

建议：

1. 上层避免持业务锁进入 socket/connect/wait 类路径。  
2. 对关键调用链加锁等待分位观测（p95/p99）。

工作量评估：**S（1~2人日）**，以调用约束和监控为主。

## 三方整改优先级与总工作量评估

1. **P0**：`logging.cc` flush策略 + `naming_service_thread.cpp` 回调锁外化  
   - 估计：**8~13 人日**（含回归）
2. **P1**：运行时约束与观测（mutex/scheduler/socket等待）  
   - 估计：**2~4 人日**

总计：**10~17 人日**（按 1~2 名开发并行可在 1~2 周内完成）。

## 边界说明

- 本报告的“第三方锁/IO问题”基于：
  - 真实测试链路 `strace` 证据
  - 仓库内第三方源码静态审计
- `strace` 不能直接给出“锁与IO同一临界区”的源码级精确因果，建议后续结合 `perf -g` 或 `strace -k` 做栈级确认。

---

## 补充风险：client 路径 thread_local / TLS（与三方 lock+IO 分析耦合）

> 该项不是“第三方库实现缺陷”本身，但会显著影响三方调用链上的 lock+IO 风险表达，应在整改时并行标识。

已确认命中：

1. `common/util/thread_local.*`（全局 TLS）
   - `reqTimeoutDuration`、`timeoutDuration`、`scTimeoutDuration`
   - `g_ContextTenantId`
   - `g_SerializedMessage`
   - `g_ReqAk/g_ReqSignature/g_ReqTimestamp`
2. `common/rpc/zmq/exclusive_conn_mgr.cpp`
   - `thread_local ExclusiveConnMgr gExclusiveConnMgr`

client 侧关联用法（示例）：

- `client/context/context.cpp`：`Context::SetTenantId` 写 `g_ContextTenantId`
- `client/client_worker_common_api.h`：`SetTenantId` 读 `g_ContextTenantId`
- `client/*worker_api*.cpp`：大量 `reqTimeoutDuration.Init(...)`
- `client/client_worker_common_api.cpp`：使用 `gExclusiveConnMgr` 关闭独占连接

风险结论：

- `reqTimeoutDuration` / `g_ContextTenantId`：**中风险**（线程复用下状态残留、上下文串用、超时语义漂移）
- `gExclusiveConnMgr`：**中高风险**（线程绑定连接在跨线程回调/清理时可能不一致）

建议（与三方 lock+IO 改造并行）：

1. 增加 `ScopedTenantContext` / `ClearTenantId`，在请求边界强制恢复 TLS。
2. 关键 RPC 入口统一初始化 timeout，避免深层函数“靠约定”写 TLS。
3. 给独占连接管理加创建/关闭计数与线程维度诊断，补兜底清理。

交叉文档：

- `plans/lock_io_blocking_special_assessment/04_evidence_based_analysis.md` §2.5
- `plans/lock_io_blocking_special_assessment/07_client_third_party_call_sites.md` §9

## 补充证据（2026-04-02 14:48:30 bpftrace）

对应文件：

- 原始：`workspace/observability/bpftrace/trace_20260402_144830_stacks.txt`
- 符号化：`workspace/observability/bpftrace/trace_20260402_144830_stacks.sym.txt`
- 报告：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_144830_report.md`

关键结论（client-only）：

- `futex` 与 `read/write` 仍是主导（等待 + IO 并存）。
- 三方符号已看到 `ds_spdlog`，且命中 `libzmq` 动态库帧。
- 本轮未命中 `grpc` 可读符号；该结论更可能是“覆盖不足/符号不全”，不是“grpc 路径不存在”。

建议：

1. 在保持当前采样脚本不变的前提下，追加 gRPC 路径更集中的 test filter 再跑一轮。  
2. 对日志热路径继续推进“锁外写/批量化/降级开关”，优先处理 `rw` 高计数簇。  

## 补充证据（2026-04-02 15:00:17，grpc/etcd 定向）

对应文件：

- 原始：`workspace/observability/bpftrace/trace_20260402_150017_stacks.txt`
- 符号化：`workspace/observability/bpftrace/trace_20260402_150017_stacks.sym.txt`
- 报告：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_150017_report.md`

结论更新：

- grpc 相关错误链路在日志正文里已明确触发（`grpc_session.h`、`RPC unavailable`、连接拒绝）。
- 但聚合栈段（`--- futex` 起）仍未出现可读 `grpc/gpr/protobuf` 栈帧，说明 bpftrace ustack 对 grpc 函数级归因仍不充分。
- `futex + rw` 主导格局不变，`ds_spdlog` 与 `libzmq` 仍有命中。

风险与建议：

1. 不能因“聚合栈无 grpc 符号”而排除 grpc 风险；日志证据已表明 grpc 重试/失败路径参与。  
2. 建议并行使用 `perf dwarf` 交叉获取 grpc 用户态调用栈，再与 bpftrace 结果合并归因。  

## 补充证据（2026-04-02 15:18:24，KV set/get 重点）

对应文件：

- 原始：`workspace/observability/bpftrace/trace_20260402_151824_stacks.txt`
- 符号化：`workspace/observability/bpftrace/trace_20260402_151824_stacks.sym.txt`
- 报告：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_151824_report.md`

结论更新：

- 在 KV set/get 过滤下，`futex + rw` 热度进一步升高（`futex top≈10000`，`rw top≈1625`）。
- `rw` 聚合簇继续出现 `ds_spdlog`，说明日志链路仍是主要风险放大器。
- `grpc/gpr/protobuf` 聚合栈可读符号依旧缺失；本轮同时有 `failed to look up stack id -17`，说明 bpftrace 栈完整性存在噪声。

建议：

1. 优先按 `rw` Top 簇推进 kv 热路径日志优化（锁外写、降级、批量化）。  
2. 对 grpc 归因继续采用 “bpftrace + perf dwarf” 双证据闭环，不单看 bpftrace 聚合栈。  
