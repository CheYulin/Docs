# Worker `resource.log` 与官方《日志》附录：定位定界用法

本文对接对外文档 [openYuanrong datasystem 日志（附录）](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/appendix/log_guide.html)，说明 **资源日志**（`resource.log`）里各段指标 **在排障中的含义**，并 **以本仓库源码为准** 标出采集位置与 **字段顺序**。

---

## 1. 如何打开、文件在哪

| 项 | 说明 |
|----|------|
| **开关** | gflag **`log_monitor`**（默认在 [`common_gflag_define.cpp`](../../../src/datasystem/common/util/gflag/common_gflag_define.cpp) 中为 **`true`**）；对外文档若写「默认关闭」，以 **实际部署参数 / 版本** 为准。 |
| **周期** | **`log_monitor_interval_ms`**（默认 10000 ms），见 [`res_metric_collector.cpp`](../../../src/datasystem/common/metrics/res_metric_collector.cpp)。 |
| **导出** | **`log_monitor_exporter=harddisk`** 时写入 **`{log_dir}/resource.log`**（常量 `RESOURCE_LOG_NAME`，见 [`constants.h`](../../../src/datasystem/common/constants.h)）。 |
| **实现入口** | `ResMetricCollector` 定时线程拼接各 handler 返回值，以 **` \| `** 分隔后交给 `HardDiskExporter::Send` 落盘（前缀含时间、pod、`cluster_name` 等，与运行日志格式一致）。 |

---

## 2. 字段顺序：以源码为准

官方附录表格将资源行描述为「shm \| spill \| client nums \| object nums \| …」等，**便于阅读**；**本进程实际输出顺序** 由枚举 **`ResMetricName`** 的定义文件 **[`res_metrics.def`](../../../src/datasystem/common/metrics/res_metrics.def)** 决定（**请勿改动该文件中的顺序**，见文件首行注释）。注册逻辑在 [`worker_oc_server.cpp`](../../../src/datasystem/worker/worker_oc_server.cpp) 的 `RegisteringWorkerCallbackFunc` / `RegisteringMasterCallbackFunc` / `RegisteringThirdComponentCallbackFunc`：未启用的子系统（例如未开 OC/SC、非 Master 节点）对应槽位可能为 **空串** 或占位默认值，表现为连续的 **` \| `**。

下面按 **`res_metrics.def` 顺序** 给出 **定界价值** 与 **代码锚点**（与附录字段名 **大致对应**，不完全逐字相同）。

| 顺序 | 指标（`ResMetricName`） | 附录中的常见叫法 | 源码采集 | 定位定界怎么用 |
|------|-------------------------|------------------|----------|----------------|
| 1 | `SHARED_MEMORY` | shm_info | `memory::Allocator::Instance()->GetMemoryStatistics()` | **共享内存 / 分配器** 使用率突增、贴上限 → 易触发 **驱逐、分配失败、长尾**；与客户端 **1001/1002/8**、业务 TP99 一并看时间线。 |
| 2 | `SPILL_HARD_DISK` | spill_disk_info | `object_cache::WorkerOcSpill::Instance()->GetSpillUsage()` | **Spill 磁盘** 用量与比例；高负载或冷数据落盘时与 **时延**、磁盘 IO 相关。 |
| 3 | `ACTIVE_CLIENT_COUNT` | client nums | `ClientManager::Instance().GetClientCount()` | **已建连客户端数**；与 **预期实例数、滚动发布批次** 对账；异常飙高/不掉 → **连接泄漏或缩容未断净** 线索。 |
| 4 | `OBJECT_COUNT` | object nums | `objCacheClientWorkerSvc_->GetTotalObjectCount()`（仅 **`EnableOCService()`**） | **Object Cache 对象个数**；仅 **KV/Object 等 OC 路径** 有意义；纯 KV 且未走 OC 时该槽可能无注册或为空。 |
| 5 | `OBJECT_SIZE` | object total datasize | `GetTotalObjectSize()`（同上） | **缓存对象总字节**；与 **SHM 使用率** 交叉看是否 **容量型** 而非网络型问题。 |
| 6 | `WORKER_OC_SERVICE_THREAD_POOL` | WorkerOcService threadpool | `GetRpcServicesUsage("WorkerOCService")` | **RPC 线程池** `idle/current/max/waiting/rate`：**waiting 堆积、rate 长期顶满** → **服务端过载或慢依赖**，对应客户端 **TP99 升、超时**。 |
| 7 | `WORKER_WORKER_OC_SERVICE_THREAD_POOL` | WorkerWorkerOcService threadpool | `GetRpcServicesUsage("WorkerWorkerOCService")` | **Worker↔Worker** 方向；**跨机元数据/数据拉取** 变慢时可对照 **远端读、切流** 场景。 |
| 8 | `MASTER_WORKER_OC_SERVICE_THREAD_POOL` | MasterWorkerOcService threadpool | `GetRpcServicesUsage("MasterWorkerOCService")` | **Master↔Worker**；与 **扩缩容、元数据迁移（32/31/25）** 同时间线对照。 |
| 9 | `MASTER_OC_SERVICE_THREAD_POOL` | MasterOcService threadpool | `GetRpcServicesUsage("MasterOCService")` | Master 侧 OC 处理池；控制面繁忙时辅助判断 **是否 Master 侧排队**。 |
| 10 | `ETCD_QUEUE` | write ETCD queue | Master 上 `GetETCDAsyncQueueUsage()`；非 Master 为 `0/0/0` | **异步写 etcd 队列** 积压 → **控制面写路径受阻**；与 **`requestout.log` 中 DS_ETCD**、**etcd 大盘**、客户端 **32/25** 一起读。 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | ETCDrequest success rate | `etcdStore_->GetEtcdRequestSuccessRate()` | **etcd 请求成功率** 下降 → **优先定界基础设施**（与 Playbook / ops 文档中的 **L3 etcd** 一致）。 |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | OBSrequest success rate | `persistenceApi_->GetL2CacheRequestSuccessRate()`（**L2 为 OBS** 时注册） | **二级存储 OBS** 成功率；读失败、恢复慢时看 **数据面 / 持久化** 是否异常。 |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | Master AsyncTask threadpool | `GetMasterAsyncPoolUsage()` | Master **异步任务池**；与 **元数据任务堆积**、扩缩容卡顿相关。 |
| 14 | `STREAM_COUNT` | （附录表未单列；属流缓存） | `streamCacheClientWorkerSvc_->GetTotalStreamCount()`（**EnableSCService()**） | **Stream 条数**；流缓存场景下看 **资源与泄漏**。 |
| 15–18 | `WORKER_SC_SERVICE_THREAD_POOL` 等 | （SC 相关 threadpool） | `ClientWorkerSCService` / `WorkerWorkerSCService` / Master SC | **Stream Cache** RPC 池；**SC 专用**，与 OC/KV 路径区分。 |
| 19 | `STREAM_REMOTE_SEND_SUCCESS_RATE` | （远端发送成功率） | `GetSCRemoteSendSuccessRate()` | **SC 跨节点发送** 成功率；低 → **网络或下游 Worker** 问题线索。 |
| 20 | `SHARED_DISK` | （共享盘用量；附录有时并入 spill/资源描述） | `Allocator::GetSharedDiskStatistics()` | **共享磁盘** 维度用量；与 **落盘、二级路径** 一起看。 |
| 21 | `SC_LOCAL_CACHE` | （SC 本地缓存用量） | `GetUsageMonitor().GetLocalMemoryUsed()` | **SC 本地内存**；与 **Stream 内存配置**、OOM 风险相关。 |
| 22 | `OC_HIT_NUM` | Cache Hit Info | `objCacheClientWorkerSvc_->GetHitInfo()` → `CacheHitInfo::GetHitInfo()` | 格式 **`mem/disk/l2/remote/miss`**（见 [`cache_hit_info.cpp`](../../../src/datasystem/worker/object_cache/cache_hit_info.cpp)）。**`remote` 占比高** → **多跳远端读** 多，易拉高 **TP99**；**`miss` 突增** → **冷启动、驱逐、或 key 分布变化**；需与 **access log、业务 QPS** 对齐看 **增量** 而非单点绝对值。 |

---

## 3. 与其它日志的关系（附录四类）

| 日志 | 定界侧重点 |
|------|------------|
| **运行日志** `datasystem_worker.*.log` | 具体 **ERROR/WARN**、栈、组件内部状态；资源行 **不替代** 文本日志。 |
| **访问日志** `access.log`（Worker POSIX） | **单次请求** 成功/失败、耗时、action；与 **resource 周期线** 对齐时间轴。 |
| **请求第三方** `requestout.log` | **每次** 调 etcd/OBS 等一条；适合算 **失败率、延迟**；`resource` 里的 **ETCD 成功率、队列** 是 **聚合快照**。 |
| **客户端** `ds_client_access_*.log` | SDK **KV/Object** 视角；与 Worker 侧 **client nums、threadpool、SHM** 交叉，做 **Client↔Worker** 定界。 |

---

## 4. 推荐读法（避免误读）

1. **先看时间线**：变更窗、告警时刻前后 **多行 resource** 是否 **趋势变化**（单点跳变可能是采集边界）。  
2. **再与 access / requestout 对齐**：例如 **TP99 升** 时 **waitingTaskNum** 是否同步升、**etcd 成功率** 是否掉。  
3. **OC / SC / 纯 KV**：确认部署是否 **`EnableOCService` / `EnableSCService`**（与 [`worker_oc_server.cpp`](../../../src/datasystem/worker/worker_oc_server.cpp) 中 `RegisterCollectHandler` 分支一致），避免对 **空槽位** 误解释。  
4. **Hit 计数为累计值**：`CacheHitInfo` 为 **atomic 累加**（见 [`cache_hit_info.h`](../../../src/datasystem/worker/object_cache/cache_hit_info.h)），排障时更可靠的是 **相邻两行差分 / 与监控 QPS 对比**，而不是单行绝对值。

---

## 5. 修订记录

- 初版：对齐官方日志附录与源码 **`res_metrics.def` + `WorkerOCServer::Registering*CallbackFunc`**，写入 kv_client_triage **details**，供 Playbook / All-in-One **Worker 侧观测**引用。
