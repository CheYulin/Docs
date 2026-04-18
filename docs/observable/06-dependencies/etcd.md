# etcd 依赖

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/kvstore/etcd/grpc_session.h` | `SendRpc` / `AsyncSendRpc`（统一 gRPC 封装）|
| `src/datasystem/common/kvstore/etcd/etcd_keep_alive.cpp` | `EtcdKeepAlive::Run` / `SendKeepAliveMessage` |
| `src/datasystem/common/kvstore/etcd/etcd_store.cpp` | `RunKeepAliveTask` / `AutoCreate` / `LaunchKeepAliveThreads` / `IsKeepAliveTimeout` / `Writable` |
| `src/datasystem/common/kvstore/etcd/etcd_health.cpp` | 启动时 `Maintenance.Status` 探活（`CheckEtcdHealth`）|
| `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp` | `CheckEtcdStateWhenNetworkFailed` 跨 Worker 二次确认、`HandleNodeRemoveEvent`、`DemoteTimedOutNode` |
| `src/datasystem/worker/worker_oc_server.cpp` | `ConstructClusterInfo` 启动前探活入口 |
| `src/datasystem/worker/worker_worker_oc_service_impl.cpp` | `CheckEtcdState`（被其它 Worker 请求确认本机 etcd 状态）|

> etcd 隔离 / 恢复的深度分析见 [`../../reliability/deep-dives/etcd-isolation-and-recovery.md`](../../reliability/deep-dives/etcd-isolation-and-recovery.md)。本篇聚焦**可观测点**：如何发现、看哪些日志、有哪些指标。

---

## 1. 当前 etcd 健康检测机制

| 检测方式 | 何时触发 | 实现要点 | 典型日志 / 返回 |
|----------|----------|----------|----------------|
| **Maintenance.Status 探活** | Worker 构造集群信息 `ConstructClusterInfo` 时 | `CheckEtcdHealth(FLAGS_etcd_address)` 新建 `Maintenance` stub，10s deadline 调 `Status` | 失败：`K_RUNTIME_ERROR`，消息 **`Connect to etcd failed, as: <grpc error_message>`**（`etcd_health.cpp`） |
| **可写探测 Writable** | 其它 Worker 响应 `CheckEtcdState`、Watch 初始化时作为 `checkEtcdStateHandler` | `EtcdStore::Writable()` 对 `ETCD_HEALTH_CHECK_TABLE` 做一次 `Put`（短超时 `MIN_RPC_TIMEOUT_MS`）| 成功：`CheckEtcdStateRspPb.available=true`；失败：Put 错误同 `SendRpc` 统一包装 |
| **续租与 Watch 运行态** | 进程常驻 | `EtcdKeepAlive::Run` / `SendKeepAliveMessage`；`EtcdStore::LaunchKeepAliveThreads` 重试；`WatchRun` 重连 | 见 § 2 / § 3 |
| **本机断 etcd 但集群仍可用（间接）** | KeepAlive 连续失败后 | `EtcdClusterManager::CheckEtcdStateWhenNetworkFailed` 向**其它活跃 Worker** 发 `CheckEtcdState`，任一回 `available==true` 则认为 etcd 可用、本机更像网络故障 | `The nodes to be queried are: ...`；`... confirms that etcd is OK`；RPC 写失败：`Rpc write failed, with rc: ...` |

**结论**：有启动时直连 etcd 的 Status 探活，运行期还有 Writable 探针（Put 健康表）、续租流、Watch 重连与跨 Worker 间接确认；**没有单独的周期性告警模块**，需依赖日志 / 指标平台。

---

## 2. gRPC 调用失败（统一包装 + 细分）

### 2.1 统一行为

同步 RPC `SendRpc` 在 `!status.ok()` 时返回 **`K_RPC_UNAVAILABLE(1002)`**，消息形如：

```text
[<methodName>] Send rpc failed: (<grpc_error_code_int>) <grpc error_message>
```

异步 `AsyncSendRpc`（如 `LeaseGrant`）：

```text
[<addresses>,LeaseGrant] Send rpc failed:<grpc error_message>
```

**粗分 "TCP/连接" 的方法**：gRPC 码常为 **14 UNAVAILABLE**、**4 DEADLINE_EXCEEDED**（超时也走同一包装）、TLS 失败等，以 `(<int>)` 与 `error_message` 为准。

### 2.2 故障细分

| 故障检测 | 细分类型 | 典型 Status / 日志 | 指标 / 访问记录 | 告警建议 |
|----------|---------|-------------------|----------------|---------|
| `SendRpc` 返回错误 | TCP / 连接 / 对端不可用 | `K_RPC_UNAVAILABLE`：`[Put::etcd_kv_Put] Send rpc failed: (14) ...` | `AccessRecorderKey::DS_ETCD_PUT` 等（`GetEtcdReqRecorderKey`）| `DS_ETCD_*` 失败率 + gRPC 码 TopN |
| `LeaseGrant` 失败 | 建连后 Lease 接口失败 | `GetLeaseID: LeaseGrant error: ...` | `DS_ETCD_LEASE_GRANT` | LeaseGrant 连续失败告警 |
| `EtcdKeepAlive::Init` 失败 | LeaseKeepAlive 双向流创建失败 | `K_KVSTORE_ERROR`：`Init stream grpc failed!`；伴随 `Finish stream with error: ...` | 无独立 key | 关键字 `Init stream grpc failed` |
| `SendKeepAliveMessage` 收到 ttl=0 | 续租逻辑失败（租约已失效）| `K_RUNTIME_ERROR`：`Failed to refresh lease: the new ttl is 0.` | 同上 | 与节点下线 / 迁移关联 |
| KeepAlive 等待超时 | 租约周期内未收到有效续租响应 | `K_RPC_UNAVAILABLE`：`SendKeepAlive Timeout`；循环中 `Retrying KeepAlive taken ...` | 无 | 续租超时次数、SIGKILL 前窗口 |
| 写集群节点（带租约 Put）失败 | `AutoCreate` / `PutWithLeaseId` 写本节点 key 失败 | 同 `SendRpc` 包装；本机判死：`local node is failed, keepAliveTimeoutTimer ... not put data to etcd` | `DS_ETCD_PUT` | 集群表 Put 失败 + "local node is failed" |
| 退出 / 缩容场景 | 避免 leaving 时访问 etcd | `K_RETRY_IF_LEAVING`：`During worker exit, avoid accessing etcd if etcd fails.` | 依调用 | 仅审计，一般不告警 |

### 2.3 gRPC 调用超时（deadline）

`SendRpc` 对每次调用设置 `context.set_deadline(..., rpcTimeoutMs)`，超时后 gRPC 通常返回 `DEADLINE_EXCEEDED`，仍被包装为 `K_RPC_UNAVAILABLE`，消息中带 `(4)` 及 `Deadline Exceeded` 类文案。

| 场景 | 典型日志 | 指标 | 告警建议 |
|------|----------|------|----------|
| 同步 Put / Get / Range 超时 | `[Put::etcd_kv_Put] Send rpc failed: (4) deadline exceeded` | `DS_ETCD_PUT / GET / ...` | Put 超时率、P99 |
| `LeaseGrant`（Async）| `[<addr>,LeaseGrant] Send rpc failed:...` + deadline 文案 | `DS_ETCD_LEASE_GRANT` | 连续超时 |
| KeepAlive 交互超时 | `SendKeepAlive Timeout`、`Retrying KeepAlive taken ...` | 无 | 续租超时趋势 |

---

## 3. Worker 侧"etcd 续约失败"的业务影响

**底层 gRPC 细节见 § 2；此处只列 Worker 如何感知、对外表现。**

| 故障检测 | 细分类型 | 典型日志 / 返回码 | 指标 | 告警建议 |
|----------|---------|-------------------|------|----------|
| `EtcdStore::LaunchKeepAliveThreads` 重试循环 | 续租失败、租约重建失败 | `Keep alive task completed with error: ...`；`Retry to recreate keep alive`；`SendKeepAlive Timeout`；`Failed to refresh lease: the new ttl is 0.` | `IsKeepAliveTimeout()` 为 true 后行为变化 | 续租连续失败次数 |
| 业务路径显式拒绝 | etcd 被判定不可用 | Get 路径：`K_RPC_UNAVAILABLE` + `etcd is unavailable`（`worker_oc_service_get_impl.cpp` 对 `IsKeepAliveTimeout()` 的检查）| 客户端错误码 | `1002` + 日志含 `etcd is unavailable` |
| 集群管理 | 本机续约超时后节点状态 | `etcd_cluster_manager.cpp` 结合 `IsKeepAliveTimeout()` 的逻辑 | `ETCD_REQUEST_SUCCESS_RATE`（见 `worker_oc_server.cpp::RegisteringThirdComponentCallbackFunc`） | etcd 请求成功率突降 |

---

## 4. Worker `resource.log` 的 etcd 相关字段

参见 [`../05-metrics-and-perf.md § 3`](../05-metrics-and-perf.md) 和 [`../../reliability/06-playbook.md § 4`](../../reliability/06-playbook.md)：

| 顺序 | 指标（`ResMetricName`）| 含义 |
|------|-------------------------|------|
| 10 | `ETCD_QUEUE` | 异步写 etcd 队列积压；Master 上 `GetETCDAsyncQueueUsage()`；非 Master 为 `0/0/0` |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | `etcdStore_->GetEtcdRequestSuccessRate()` |

**读法**：etcd 请求成功率突降 → 优先定界基础设施；队列积压 → 控制面写路径受阻；与 `requestout.log` 中 `DS_ETCD_*`、客户端 `32/25` 一起读。

---

## 5. 健康检查的多路并存

### 5.1 逻辑健康位 `IsHealthy()` / K8s 风格文件探针

| 故障检测 | 典型返回 / 日志 | 告警建议 |
|----------|-----------------|----------|
| `ValidateWorkerState`：Worker 未就绪 | `K_NOT_READY`：`Worker not ready`（`IsHealthy()` 为 false） | 就绪探针失败率 |
| 重组（recon）锁长时间占用 | `K_NOT_READY`：`Waiting for the reconFlag...` | 长时间 `K_NOT_READY` + recon 日志 |
| 文件探针 `FLAGS_health_check_path` | `ResetHealthProbe`：`Create healthy check file failed!`；`SetUnhealthy`：`Worker is unhealthy now!` | 文件系统权限、与上游降级联动 |

### 5.2 RPC `HealthCheck`

`WorkerOCServiceImpl::HealthCheck`：

- 状态校验失败：`LOG(WARNING) << rc`，返回 `K_NOT_READY` 等
- 认证失败：`Authenticate failed.`
- 节点退出中：`K_SCALE_DOWN`：`Worker is exiting now`（`LOG_EVERY_T`，避免日志风暴）

### 5.3 进程内 Liveness（`FLAGS_liveness_check_path`）

| 故障检测 | 典型日志 | 说明 |
|----------|----------|------|
| `WorkerLivenessCheck::Run` 周期执行 | `DoLivenessCheck, Status: ...`；失败时 `liveness probe failed, try delete liveness probe file!` | 探针文件写入 `liveness check failed` |
| RPC 线程池卡死（`CheckWorkerServices`）| `K_WORKER_ABNORMAL`：`Liveness check failed, service of <name> is failed.` | `GetRpcServicesUsage(name)`：`threadPoolUsage==1` 且超时无 `taskLastFinishTime` 更新 |
| Master 节点 RocksDB 元数据探针（`CheckRocksDbService`）| `CheckRocksDbService failed in allowed time.`；超时 `K_WORKER_ABNORMAL`：`CheckRocksDbService timeout.` | 仅 Master 节点注册 |
| 探针文件被外部读（如 K8s）| `liveness file not update for <n> s`；`<path> not exist` | `CheckLivenessProbeFile` |

### 5.4 启动就绪自旋

`WaitForServiceReady`：`Readiness probe retrying, detail: ...`，直到成功或 SIGTERM。

### 5.5 HashRing 健康（控制面一致性）

`HashRingHealthCheck::Run`：检测环不一致、缩容状态异常等。日志 `Start HashRing health check thread.` 及后续 policy 内 LOG。与扩缩容、etcd 事件同窗分析。

---

## 6. 关键节奏参数

对应 `src/datasystem/common/util/gflag/common_gflag_define.cpp`：

| 参数 | 默认值 | 含义 |
|------|-------|------|
| `node_timeout_s` | 60 | etcd lease TTL（秒）；Worker 隔离速度由此决定 |
| `node_dead_timeout_s` | 300 | 从 lease 到期起，等多久把节点判死；Path 1（轻量重连）窗口 = `dead - timeout` |
| `heartbeat_interval_ms` | 1000 | etcd 续约 / 心跳间隔 |
| `auto_del_dead_node` | true | 是否自动从 hash ring 剔除死节点 |
| `passive_scale_down_ring_recheck_delay_ms` | 0 | 本地被动 SIGKILL 前再读 etcd 环的等待（0 = 关闭） |

**约束**：`node_dead_timeout_s > node_timeout_s`；`heartbeat_interval_ms < node_timeout_s * 1000`。

**隔离时机与参数的详细关系**：见 [`../../reliability/deep-dives/etcd-isolation-and-recovery.md`](../../reliability/deep-dives/etcd-isolation-and-recovery.md)：

- 故障隔离（停止向 A 发请求 + 路由切换）在 `t = node_timeout_s` 完成
- `node_dead_timeout_s` 只控制 `TIMEOUT → FAILED` 的等待窗口
- 当前测试配置（`timeout=2s, dead=3s`）下 Path 1（轻量重连）实际走不到；推荐 `dead=30s`

---

## 7. 告警建议汇总

| 告警项 | 信号 | 阈值 |
|--------|------|------|
| etcd 请求成功率下降 | `ETCD_REQUEST_SUCCESS_RATE` | 持续 < X% |
| etcd 写队列积压 | `ETCD_QUEUE` | 积压超过阈值 |
| `DS_ETCD_PUT / GET / ...` 失败率 | access log 聚合 | > 基线 3σ |
| `etcd is unavailable` 日志 | grep | 单位时间出现次数 |
| 续租连续失败 | `Keep alive task completed with error` | N 次以上且距 SIGKILL 窗口剩余小 |

当前**无统一告警平台**；落地前按日志 / metrics 自建规则。
