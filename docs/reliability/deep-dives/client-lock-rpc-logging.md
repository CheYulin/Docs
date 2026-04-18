# Client 锁内 RPC / 日志阻塞治理

> 原 `client-lock-in-rpc-logging-bthread-blocking.md` 的内容整理版。梳理 client 侧锁内 RPC / IO / 日志风险，按"收益优先"分阶段治理；栈底为 **ZMQ + spdlog（datasystem 封装层）**，业务宽锁为 `shutdownMux_` / `mmap` / `ref` 等。gRPC（含 etcd 所用 grpc）对热路径 QPS 影响相对小，不单独作为 P0 栈底项。

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | `RouteToUnixSocket`、`outMux_` 下的 `epoll_ctl` / `SetPollOut` |
| `src/datasystem/common/log/spdlog/provider.cpp` | `Provider::FlushLogs`（持 `shared_mutex` 锁内 flush） |
| `src/datasystem/common/log/spdlog/logger_context.cpp` | `LoggerContext::ForceFlush` / `apply_all(FlushLogger)` |
| `src/datasystem/client/object_cache/object_client_impl.cpp` | `shutdownMux_` / `globalRefMutex_` / `switchNodeMutex_` 三把宽锁 |
| `src/datasystem/client/mmap_manager.cpp` | `LookupUnitsAndMmapFds` / `GetClientFd` / `MmapAndStoreFd` |
| `src/datasystem/client/object_cache/device/comm_factory.cpp` | `SendRootInfo` / `RecvRootInfo` 持 `mutex_` |
| `src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp` | `ClientWorkerRemoteApi::DecreaseShmRef` |

---

## 1. 问题定义

**目标问题**：在 bthread 协程上下文调用 client 方法时，出现卡死 / 死锁风险。

**已确认的触发模式**：

- 持有 `std::mutex` / `std::shared_timed_mutex` 时执行 client-worker RPC。
- 持锁期间执行等待型操作（futex / wait / mmap / fd 收发等）。
- 持锁期间执行 `LOG` / `VLOG`（可能触发日志后端磁盘写或阻塞）。

**结论**：上述模式叠加时，会显著放大 bthread 调度阻塞，极端场景形成互等。

### 1.1 组件覆盖口径

- **spdlog（必须纳入主逻辑）**：工程内日志栈基于 spdlog 经 datasystem 封装（`Provider::FlushLogs`、`LoggerContext::ForceFlush`、`apply_all(FlushLogger)`）。锁内 flush / 热路径同步写 sink 可能落到 `write / fsync` 类 syscall，与业务锁叠加会放大尾延迟。阶段 1（Provider）+ 阶段 3（调用点与 sink 策略）都要覆盖 spdlog 全链路。
- **gRPC（不作为主优先级）**：etcd / discovery 走 gRPC 的调用频率相对 KV / Object 主路径低；不单独开"gRPC 客户端栈"改造里程碑；仅在阶段 2e（`RediscoverLocalWorker` 持锁 `SelectWorker`）处理"业务锁 + 网络"即可。

---

## 2. 关键风险点（当前代码）

### 2.1 object client 主路径

`src/datasystem/client/object_cache/object_client_impl.cpp`：

- `shutdownMux_` 锁范围内存在 worker RPC：
  - `ShutDown()` 中持锁循环 `workerApi_[i]->Disconnect(...)`
  - `Create / MultiCreate / Put / Seal / Publish / MultiPublish` 等在持 `shutdownMux_` shared lock 时进入 worker API 调用路径
- `globalRefMutex_` 锁范围内存在 worker RPC：
  - `GIncreaseRef / GDecreaseRef` 持锁期间调用 `GIncreaseWorkerRef / GDecreaseWorkerRef`
- `switchNodeMutex_` 锁范围存在外部 IO：
  - `RediscoverLocalWorker()` 持锁时调用 `serviceDiscovery_->SelectWorker(...)`（etcd 网络路径）

### 2.2 设备通信与 mmap 路径

- `client/object_cache/device/comm_factory.cpp`：持 `mutex_` 调用 `SendRootInfo / RecvRootInfo` 与通信初始化
- `client/mmap_manager.cpp`：持 `mutex_` 调用 `GetClientFd(...)`（RPC + fd 传输）及 `MmapAndStoreFd(...)`

### 2.3 spdlog 封装层 + 业务侧锁内日志

**A. spdlog 封装（全局 / 基础设施）**

- `common/log/spdlog/provider.cpp`：`FlushLogs` 在 provider 的 `shared_mutex` 锁内调用下游 `ForceFlush()`，可能触发各 logger / sink 的同步 flush（典型 `write` / `fsync`，取决于 sink 与 async 配置）。
- `common/log/spdlog/logger_context.cpp`：`ForceFlush` / `apply_all(FlushLogger)` 路径 — 与 Provider 配套，阶段 1 整改时需一并考虑"谁在什么锁下触发 flush"。

**B. 业务代码锁内 LOG/VLOG**

- `object_client_impl.cpp`、`comm_factory.cpp`、`stream_client_impl.cpp`、`listen_worker.cpp`、`router_client.cpp` 等：先加业务锁再打日志。
- 最终仍进入 spdlog（或宏展开后的同一后端）；是否立即磁盘 IO 取决于 async 队列、sink、是否 flush；在临界区内仍可能拉长持锁时间。**阶段 3** 以"锁外打印 + 级别 / 频控 + spdlog 异步策略"为主。

**结论**：本治理把 spdlog 与业务 LOG 当作一条链，阶段 1 削"基础设施锁内 flush"，阶段 3 削"业务锁内打日志 + sink 配置"。

---

## 3. 设计原则（治理方向）

- **原则 1**：锁内只做内存态读取 / 更新，不做 RPC、阻塞等待、磁盘 / 网络 IO。
- **原则 2**：改为"快照 + 解锁 + 外部调用 + 回写（必要时二次校验）"。
- **原则 3**：缩小锁粒度，避免全局锁包住高延迟路径。
- **原则 4**：日志与锁解耦 —— 业务侧在锁内只组装字段，锁外写入 spdlog；基础设施侧避免在 provider 全局锁内做 spdlog 同步 flush。

---

## 4. 解法分层

### 4.1 P0（必须）：消除锁内 RPC / 等待

**方案 A：快照后解锁再 RPC**（推荐，改动最小）

适用函数：

- `ObjectClientImpl::ShutDown`
- `ObjectClientImpl::GIncreaseRef` / `GDecreaseRef`
- `ObjectClientImpl::RediscoverLocalWorker`（etcd 选择节点）
- `MmapManager::LookupUnitsAndMmapFds`

通用步骤：

1. 锁内完成必要快照（worker 列表、待处理 key、状态版本号等）。
2. 立即解锁。
3. 锁外执行 RPC / 等待操作。
4. 需要写回时加短锁并做版本校验（防止并发状态漂移）。

**方案 B：拆锁（逻辑锁与 IO 锁分离）**

对 `shutdownMux_` / `globalRefMutex_` 按"状态保护"和"并发序列化"拆分，避免一个锁承载所有语义。适合后续演进，不建议首批大改。

### 4.2 P1：spdlog + 业务日志降阻塞

- **方案 C：业务侧日志锁外化** —— 锁内仅提取字段到局部变量，锁外执行 `LOG`。
- **方案 D：日志级别与采样降噪** —— 高频路径默认降到 `VLOG`，关键错误保留 `LOG(ERROR/WARNING)`；循环内日志增加频控（`LOG_EVERY_N/T`）。
- **方案 E：spdlog 后端策略**（与阶段 1 互补）—— 异步 sink / 批量 flush；延迟敏感环境避免在请求路径上触发全量 `FlushLogs`；Provider 层锁外再调 `ForceFlush`。

**注意**：spdlog / flush 优化只能减轻抖动与尾延迟，不能替代 ZMQ / 业务锁内 RPC 等 P0；但与阶段 1 叠加后收益更明显。

### 4.3 P1：bthread 入口隔离（兜底）

对不可快速改造的阻塞接口，在入口处切换到 pthread 线程池执行。保证 bthread worker 不直接承载长阻塞 syscall / RPC。该方案是兼容兜底，不应替代锁语义治理。

---

## 5. "只改日志能不能解决？"

**结论：不能根治。**

原因：

- 当前核心风险来自"持锁期间 RPC / 等待"，这与日志是否落盘是两个层面的阻塞源。
- 即便把日志全部关掉，锁内 RPC 仍可能导致长时间占锁，协程仍会被放大阻塞。

可达成效果：

- 仅改业务侧打日志或减少 spdlog flush，可减少部分长尾抖动和额外阻塞。
- 若不做 ZMQ + Provider / spdlog flush 与业务锁内 RPC 剥离，死锁 / 卡死主风险仍在。

---

## 6. 分阶段路线图

**原则**：先动"所有 Object / KV RPC 共用"的栈底（ZMQ + spdlog Provider），再动业务宽锁；业务侧 spdlog 调用与 sink 策略在阶段 3 收紧。gRPC 不单独占一档。

### 阶段 0：基线与门禁

- 主门禁：构建 + ctest（`KVClientBrpcBthreadReferenceTest` 等）
- 可选 perf：在有集群的开发机上运行 `kv_executor_perf_analysis.py`
- 不推荐纳入默认门禁：`bpftrace`、需提权的 `perf record`（深度采集时单次使用）

### 阶段 1：P0-栈底 —— ZMQ + spdlog（Provider / Flush 链）

**改什么**：

- **ZMQ** (`common/rpc/zmq/zmq_stub_conn.cpp`)：持 `outMux_` 仅入队；锁外 `SetPollOut`；必要时用原子 / 标志避免丢唤醒。
- **spdlog Provider** (`common/log/spdlog/provider.cpp`)：`FlushLogs` 锁内只拷贝 `provider_` shared_ptr（或等价快照），锁外调用 `ForceFlush()` / 遍历 flush，避免 provider 全局 `shared_mutex` 长时间占着又打 spdlog IO。
- **LoggerContext** (`common/log/spdlog/logger_context.cpp`)：与 `ForceFlush`、`apply_all(FlushLogger)` 联动；确保没有"在更外层锁内反复触发全量 flush"的调用模式。

**为何优先**：凡走 ZMQ 的 client 调用都受益；spdlog flush 是跨模块共享的基础设施锁，与业务 `shutdownMux_`、ZMQ 锁叠加时尾延迟放大明显。

### 阶段 2：P0-业务 —— 宽 `shutdownMux_` + mmap + ref + 切换

按子阶段拆 MR：

| 子阶段 | 内容 | 收益侧重 |
|--------|------|----------|
| 2a | `ShutDown`：`shutdownMux_` 内仅快照 `workerApi_`，锁外 `Disconnect` | 关停 / 退出互等 |
| 2b | `shutdownMux_` shared 全路径：`Create / Put / Seal / Publish / MultiCreate / MultiPublish / Set(buffer) / GIncreaseRef` 等 —— 缩短持锁跨度或拆"状态读 + 锁外 RPC" | QPS 与 p99（调用频率最高） |
| 2c | `MmapManager::LookupUnitsAndMmapFds` 三段式（收集 → 锁外 `GetClientFd + mmap` → 锁内回写） | 冷启动 / 多 fd、全局 `mutex_` 热点 |
| 2d | `globalRefMutex_` + `GIncrease / GDecrease`：锁内计数与快照，锁外 RPC，失败短锁回滚 | ref 风暴时全局互斥 |
| 2e | `RediscoverLocalWorker`：`SelectWorker` 锁外，锁内二次校验提交 | etcd 抖动不堵切换锁 |
| 2f | `ClientWorkerRemoteApi::DecreaseShmRef`：与 `shutdownMtx` / `mtx_` 拆分等待与 RPC | shm 降 ref 长尾 |
| 2g | （可选）`CommFactory`：`SendRootInfo / RecvRootInfo` 锁外（异构开启时 P0） | 设备路径 |

### 阶段 3：P1 —— 业务侧 spdlog 调用点、sink 策略、MemoryCopy + 线程池、TLS

- 锁内 `LOG / VLOG` → 字段快照 + 锁外再写入 spdlog；热路径 `VLOG` + `LOG_EVERY_*`
- spdlog：确认 async 模式、队列深度、drop 策略；避免热路径同步 flush
- `Buffer::MemoryCopy` + `ThreadPool`：禁止在大业务锁内触发大块并行拷贝；调阈值与背压
- bthread 落地时：TLS / `reqTimeoutDuration` / tenant 上下文改为显式传递或 fiber-local

### 阶段 4：兜底

对短期无法拆干净的入口：`IKVExecutor` / 独立 pthread 池执行阻塞段。

---

## 7. 验收指标

### 7.1 合入门槛（必须）

1. **绝对时延**：在预先登记的基线 run 与当前 run 上，至少一条主路径（如 inline Set / Get 平均 µs，或扩展压测的 p95 / p99 µs）明确下降；对比表中写出基线数值 → 当前数值（同一口径）。
2. **功能**：对应阶段相关测试全绿。
3. **不退化**：在观测绝对收益的同时，超时率、`K_RPC_DEADLINE_EXCEEDED` / `K_TRY_AGAIN` 占比不劣化于基线（或下降）。

### 7.2 建议满足（增强信心）

- 锁等待或临界区占用：p95 / p99 绝对值下降（若有 instrument 或采样）
- bthread worker 长阻塞事件数下降（tracer / perf 栈）
- 长压测中不再出现"持业务锁卡在 RPC / 等待"的典型堆栈

### 7.3 明确不作为"收益"依据的项

- 仅 injected / inline 倍率变化而无任一路径绝对 µs 改善
- 仅单测通过、无数值对比

---

## 8. 优先级（按"锁范围 × 锁冲突"重排）

1. **P0-栈底（所有 RPC 共用）**：ZMQ 锁内 `epoll_ctl`（Case A）；spdlog —— `Provider::FlushLogs` / `LoggerContext::ForceFlush` 锁内或持全局锁 flush（Case B / B-1）。
2. **P0-业务宽锁**：`shutdownMux_` 全路径（不仅 `ShutDown`）、`MmapManager`（Case C）、`globalRefMutex_` ref RPC（Case E）、`switchNodeMutex_` + etcd 选择（低频网络，gRPC 不单独开栈）（Case F）、`CommFactory`（Case G）、`DecreaseShmRef` 链。
3. **P1 并行**：业务锁内打 spdlog（P1-1）、TLS / context（P1-2）、MemoryCopy + 线程池组合（H）。
4. **兜底**：bthread 入口线程池隔离。

**gRPC**：当前结论为对热路径影响不大，不进入上表独立一项；若后续观测到 grpc completion 线程与业务锁互锁，再补"grpc 专用"里程碑。

---

## 9. 风险与回滚

- **风险**：解锁后状态可能变化，需要版本号或状态检查确保语义不回退。
- **回滚**：所有改造建议加开关，先灰度到低流量环境再全量。
