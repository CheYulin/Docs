# Worker：etcd 续约、健康检查、内存/线程、线程池、客户端数、缓存命中 — 故障检测与告警

本文与 [worker-etcd与二级存储-故障检测与告警.md](./worker-etcd与二级存储-故障检测与告警.md) **同粒度**：**故障如何被检测**、**细分类型**、**典型日志/返回码**、**已有指标埋点**；**业务告警规则在代码中未统一实现**，表中「建议告警」为待补充项。

**主要代码位置**：

- etcd 续约 / `IsKeepAliveTimeout`：`etcd_store.cpp`、`etcd_keep_alive.cpp`（详见 etcd 专文）
- RPC **`HealthCheck`**：`worker_oc_service_impl.cpp`
- 进程 **`IsHealthy()` / 探针文件**：`worker_health_check.cpp`、`worker_oc_server.cpp`（`SetHealthProbe` / `ReadinessProbe`）
- **存活与深度探测**：`worker_liveness_check.cpp` / `.h`（`FLAGS_liveness_check_path`）
- **客户端与 lockId 上限**：`client_manager/client_manager.cpp`（`FLAGS_max_client_num`）
- **线程池与资源指标**：`worker_oc_server.cpp`（`ResMetricCollector::RegisterCollectHandler`）、`worker_liveness_check.cpp`（`CheckWorkerServices`）
- **缓存命中统计**：`cache_hit_info.cpp`、`worker_oc_service_get_impl.cpp`（`IncMemHit` / `IncL2Hit` / …）

---

## 1. Worker 侧「etcd 续约失败」（与数据面交互）

> 底层 gRPC 消息与续租流细节见 **etcd 专文 §1.2～1.3**；此处只列 **Worker 如何感知、对外表现**。

| 故障检测 | 细分类型 | 典型日志 / 返回码 | 指标 / 其它 | 建议告警 |
|----------|----------|-------------------|-------------|----------|
| `EtcdStore::LaunchKeepAliveThreads` 重试循环 | 续租失败、租约重建失败 | `Keep alive task completed with error: ...`；`Retry to recreate keep alive`；**`SendKeepAlive Timeout`**；**`Failed to refresh lease: the new ttl is 0.`** | `EtcdStore::IsKeepAliveTimeout()` 为 true 后行为变化 | 续租连续失败次数、距 SIGKILL 窗口 |
| 业务路径显式拒绝 | etcd 被判定不可用 | 例如 Get 路径：**`K_RPC_UNAVAILABLE`** + **`etcd is unavailable`**（`worker_oc_service_get_impl.cpp` 对 `IsKeepAliveTimeout()` 的检查） | 客户端错误码分布 | `1002` + 日志含 `etcd is unavailable` |
| 集群管理 | 本机续约超时后的节点状态 | `etcd_cluster_manager.cpp` 中结合 **`IsKeepAliveTimeout()`** 的逻辑（如退出/迁移相关） | `ETCD_REQUEST_SUCCESS_RATE`（`WorkerOCServer::RegisteringThirdComponentCallbackFunc`） | etcd 请求成功率突降 |

---

## 2. 健康检查失败（多路并存，需区分「哪一种 health」）

### 2.1 逻辑健康位 `IsHealthy()` / K8s 风格文件探针

| 故障检测 | 细分类型 | 典型日志 / 返回码 | 指标 | 建议告警 |
|----------|----------|-------------------|------|----------|
| 业务前 **`ValidateWorkerState`** | Worker 未就绪 | **`K_NOT_READY`**：**`Worker not ready`**（`IsHealthy()` 为 false） | 请求失败码 `K_NOT_READY` | 就绪探针失败率 |
| | 重组（recon）锁长时间占用 | **`K_NOT_READY`**：**`Worker not ready`**（`reconFlag_` 未在窗口内释放）；日志 **`Waiting for the reconFlag...`** | 同上 | 长时间 `K_NOT_READY` + recon 日志 |
| **文件探针** `FLAGS_health_check_path` | 启动/重置 | `ResetHealthProbe`：**`Create healthy check file failed!`**；`Delete health check file failed.` | 无 | 文件系统权限 |
| | 置健康 | `SetHealthProbe`：**`Worker is healthy, health probe set.`** | 无 | — |
| | 置不健康 | **`SetUnhealthy`**：**`Worker is unhealthy now!`** | 无 | 与上游显式降级联动告警 |

### 2.2 RPC `HealthCheck`（客户端/负载均衡调用）

| 故障检测 | 细分类型 | 典型日志 / 返回码 | 说明 | 建议告警 |
|----------|----------|-------------------|------|----------|
| `WorkerOCServiceImpl::HealthCheck` | 状态校验失败 | `ValidateWorkerState` 失败时 **`LOG(WARNING) << rc`** | 返回码同 **`K_NOT_READY`** 等 | HealthCheck 失败率 |
| | 认证失败（带 `client_id`） | **`Authenticate failed.`** | IAM 问题 | 与租户凭证相关 |
| | 节点正在退出 | **`K_SCALE_DOWN`**：**`Worker is exiting now`**；日志 **`[HealthCheck] Worker is exiting now`**（`LOG_EVERY_T`） | 预期缩容行为 | 与扩缩容事件关联，避免误报 |

### 2.3 进程内 **Liveness**（`FLAGS_liveness_check_path` 非空时启用）

| 故障检测 | 细分类型 | 典型日志 / 消息 | 说明 | 建议告警 |
|----------|----------|-----------------|------|----------|
| **`WorkerLivenessCheck::Run`** 周期执行 | 任一 policy 失败 | **`DoLivenessCheck, Status: ...`**；失败时 **`liveness probe failed, try delete liveness probe file!`** | 探针文件写入 **`liveness check failed`** | liveness 连续失败 |
| **RPC 线程池卡死**（`CheckWorkerServices`） | 某服务池满载且长期无任务完成 | **`K_WORKER_ABNORMAL`**：**`Liveness check failed, service of <name> is failed.`** | `GetRpcServicesUsage(name)`：`threadPoolUsage==1` 且超时无 `taskLastFinishTime` 更新 | **与 `WORKER_*_THREAD_POOL` 指标联动** |
| **Master 节点 RocksDB 元数据探针**（`CheckRocksDbService`） | CreateMeta 长期失败 | `CheckRocksDbService failed in allowed time.`；超时：**`K_WORKER_ABNORMAL`** **`CheckRocksDbService timeout.`** | 仅 Master 节点注册该 policy | Master 元数据路径告警 |
| **探针文件被外部读**（如 K8s） | 文件内容 / mtime | **`liveness check failed`** 文本；**`liveness file not update for <n> s`**；**`<path> not exist`** | `CheckLivenessProbeFile`（`LivenessHealthCheckEvent` 订阅者） | Pod 重启、探针路径错误 |

### 2.4 启动就绪自旋（本机调自己的 HealthCheck）

| 故障检测 | 细分类型 | 典型日志 | 说明 |
|----------|----------|----------|------|
| `WaitForServiceReady` | HealthCheck 一直失败 | **`Readiness probe retrying, detail: ...`** | 直到成功或 SIGTERM |

### 2.5 HashRing 健康（控制面一致性，非 HTTP health）

| 故障检测 | 细分类型 | 典型日志 | 建议告警 |
|----------|----------|----------|----------|
| `HashRingHealthCheck::Run` | 环不一致、缩容状态异常等 | **`Start HashRing health check thread.`** 及后续 policy 内 `LOG`（见 `hash_ring_health_check.cpp`） | 与扩缩容、etcd 事件同窗分析 |

---

## 3. 申请内存失败、创建线程失败

| 故障检测 | 细分类型 | 典型返回 / 日志 | 代码模式 | 建议告警 |
|----------|----------|-----------------|----------|----------|
| **`RETURN_IF_EXCEPTION_OCCURS`** 创建 **`ThreadPool`** 等 | `std::bad_alloc` | **`K_RUNTIME_ERROR`**：**`std::bad_alloc + ", cannot allocate resources"`** | 如 `WorkerOcEvictionManager::Init`、`WorkerOcServiceImpl` 内多个池 | 启动失败即致命告警 |
| | `std::system_error`（含线程创建失败） | **`K_RUNTIME_ERROR`**：**`<what>, cannot acquire resources`** | 同上 | 线程/ulimit/cgroup |
| **共享内存初始化** | Allocator 失败 | `WorkerOCServer::Init`：**`Init allocator failed`**（`LOG` 由宏打印） | `memory::Allocator::Instance()->Init(...)` | 共享内存/大页/磁盘配额 |
| **运行业务路径** | 对象/传输内存不足 | 常见 **`K_OUT_OF_MEMORY`**（Get/Publish 等，见读写定位定界文档） | Worker 内分配、远端拉取 | OOM 错误码突增 |

---

## 4. 资源异常：线程池、客户端数、缓存命中率

### 4.1 线程池（RPC 服务维度）

| 故障检测 | 细分类型 | 典型现象 / 日志 | 指标（已有） | 建议告警 |
|----------|----------|-----------------|--------------|----------|
| 池满载且任务不再推进 | 服务假死 / 死锁 / 慢阻塞 | **Liveness**：`Liveness check failed, service of <WorkerOCService|...> is failed.` | **`ResMetricName::WORKER_OC_SERVICE_THREAD_POOL`**、**`WORKER_WORKER_OC_SERVICE_THREAD_POOL`**（`GetRpcServicesUsage(...).ToString()`） | 线程池使用率 + liveness 失败同窗 |
| SC 相关 | 流式服务池 | 同上（服务名不同） | **`WORKER_SC_SERVICE_THREAD_POOL`**、**`WORKER_WORKER_SC_SERVICE_THREAD_POOL`** | 同上 |
| 队列积压（通用 ThreadPool） | `IsPoolFull`、自定义阈值 | 需结合日志与指标字符串（若导出字段含 queue/running） | 同上 | 队列深度阈值（若可解析） |

### 4.2 客户端数目（`FLAGS_max_client_num`）

| 故障检测 | 细分类型 | 典型返回 / 日志 | 指标（已有） | 建议告警 |
|----------|----------|-----------------|--------------|----------|
| **`ClientManager::GetLockId`** | 连接数达上限 | **`K_RUNTIME_ERROR`**：**`Client number upper to the limit`** | **`ResMetricName::ACTIVE_CLIENT_COUNT`**（`GetClientCount()`） | active client 接近/等于 `max_client_num` |
| **`AddClient` 插入失败** | 重复 clientId 等 | **`Failed to insert client <id> to table`** | 同上 + 注册失败日志 | RegisterClient 失败率 |
| **心跳丢失** | 客户端被摘除 | **`Client <id> lost heartbeat, worker will remove this client.`** | client 数下降 | 异常断连风暴 |

### 4.3 缓存命中率（OC Get 路径）

| 故障检测 | 细分类型 | 典型输出 | 指标（已有） | 建议告警 |
|----------|----------|----------|--------------|----------|
| **`CacheHitInfo`** 五元组 | mem / disk / L2 / remote / miss 计数 | **`GetHitInfo()`** 返回 **`"<mem>/<disk>/<l2>/<remote>/<miss>"`**（`FormatString("%ld/...")`） | **`ResMetricName::OC_HIT_NUM`**（`GetHitInfo()` 原样上报） | **派生指标**：如 `miss/(sum)` 突增、remote 占比突增（网络/局部性变差） |

> 解析告警时建议在线下用脚本将 `OC_HIT_NUM` 拆成 5 个 counter，再算比率；当前代码是 **单字符串指标**。

---

## 5. 与「Worker 故障」文档的衔接

- **启动失败**：仍见 [worker-启动故障-定位定界.md](./archive/worker-启动故障-定位定界.md)（历史归档）。
- **etcd gRPC 细节**：见 [worker-etcd与二级存储-故障检测与告警.md](./worker-etcd与二级存储-故障检测与告警.md)。
- **客户端可见错误码**：见 `kv-client-*`、`sdk-init` 系列。

---

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 初版：按续约、健康检查、内存/线程、线程池、客户端数、缓存命中梳理 |
