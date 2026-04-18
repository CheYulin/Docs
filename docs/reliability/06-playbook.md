# 06 · 运维排障 Playbook

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp` | `RETRY_ERROR_CODE`、`HealthCheck`、`MultiPublish` 的重试策略 |
| `src/datasystem/worker/object_cache/worker_oc_service_impl.cpp` | `HealthCheck` → 31 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_multi_publish_impl.cpp` | `RetryCreateMultiMetaWhenMoving` → 32 |
| `src/datasystem/common/rpc/zmq/zmq_msg_queue.h` 等 | 1002 桶码的源头（见 § 2） |
| `src/datasystem/common/metrics/res_metric_collector.cpp` | `resource.log` 采集 |
| `src/datasystem/common/metrics/res_metrics.def` | `resource.log` 字段顺序 |
| `src/datasystem/worker/worker_oc_server.cpp` | `RegisteringWorkerCallbackFunc` 等注册入口 |

---

## § 1. 部署与扩缩容失败排查

### 1.1 分层观测总表（L0 → L5）

排障时不要求先会看 etcd 里 ring 的 CAS、key 修订号等实现细节。按分层从上到下做，上一层能定界就不必下钻。

| 层级 | 谁来看 | 具体观测什么 | 判读要点 |
|------|--------|-------------|----------|
| **L0 业务与编排** | 业务 SRE / 集成方 | 变更时间线（发布单、滚动批次、etcd 维护窗）；业务监控（KV 读写成功率、P99）；进程是否反复重启 | 现象是否与变更窗口对齐 |
| **L1 客户端落盘** | 集成方 | `ds_client_access_<pid>.log`：按 `handleName` 聚合第一列 code；`Init` 失败时看应用日志里的 `Status` / 错误串（冷启动常早于 access 行） | 32 写路径聚集、1001/1002/23 突发、31 与探活 |
| **L2 实例与网络** | 运维 | Worker / Master / 业务 Pod 是否 Running、Ready 探针是否通过；从业务机 `telnet` / `nc` 目标 `ip:port`；云平台安全组 / 网络策略 | 冷启动连不上时优先层 |
| **L3 etcd 与基础设施** | 平台运维 | etcd 配套监控（成员健康、是否有 leader、读写延迟 / 失败率、告警是否触发） | 不必打开 CAS；监控不健康即升级给平台 |
| **L4 Worker / Master 日志** | 平台 / 二线 | 在已锁定节点上拉 ERROR/WARN；可选拉 `resource.log` 看 RPC 池排队、etcd 队列 / 成功率、SHM | 用于确认缩容 / 迁移 / 元数据是否在报错 |
| **L5 实现级深挖** | 研发 | etcd 内 ring 对比、源码路径、抓包 | 仅 L0~L4 仍无结论时启用 |

### 1.2 L1：客户端打开什么文件 / 指标

| 观测物 | 路径或位置 | 怎么用 |
|--------|------------|--------|
| Access log | `{log_dir}/ds_client_access_{pid}.log` 或环境变量覆盖名 | `grep DS_KV_CLIENT_SET` / `GET`，统计第一列 code；对照变更时间 |
| 应用日志 | 业务进程标准输出 / 统一日志平台 | 搜 `Init` 失败、`KVClient`、`StatusCode`、`1001/1002/8/23/25/31/32` |
| 业务监控 | 负载均衡 / APM / 自建看板 | 成功率、P99 是否与单一 code 或单一批次实例相关 |

### 1.3 L3：etcd 看什么、不看什么

| 建议看 | 不建议一线强依赖 |
|--------|------------------|
| 监控大盘：集群是否 quorum、leader 切换、请求错误、延迟突刺 | 手工比对 ring 的 CAS 是否成功（属 L5） |
| 告警：etcd 全挂、单 AZ 网络断 | 理解"控制面卡住时，数据面可能仍部分可读" |

### 1.4 L4：Worker / Master 日志可选关键词

下列仅作线索，不同版本文案可能略有差异；命中后再把片段交给平台 / 研发。

- **缩容 / 迁移**：`scale down`、`voluntary scale`、`migrate`、`Scale down failed`、`task id has expired`
- **容量与放弃**：`no available nodes`、`Give up voluntary`
- **元数据繁忙**（与客户端 32 呼应）：`scaling`、`meta`、`moving`

### 1.5 冷启动专题（业务进程集成 SDK 与 Worker 首连）

| FEMA 编号 | 场景 | 对冷启动的含义 |
|-----------|------|----------------|
| 1 / 4 | 本机有 Worker | 通常连本机端口，路径最短 |
| 2 / 5 / 6 | 本机无 Worker | **合法形态**：必须连远端或服务发现；忌 `localhost` |
| 3 | 仅 Worker 部署 | Worker Ready 应早于业务起，否则 `Init` 易失败 |

冷启动观测顺序：

| 步骤 | 观测 | 操作 |
|------|------|------|
| 1 | 业务进程是否因 Init 退出 / 重启 | 看编排事件、应用退出码、启动日志里 `Init` 返回的 Status |
| 2 | 目标 Worker 是否就绪 | K8s Ready / 进程存活；从业务机 `nc -vz ip port` |
| 3 | 地址是否配错 | 配置中心或环境变量：本机无 Worker 时不能写本机地址；服务发现是否返回空 / 旧 IP |
| 4 | 超时是否过短 | 跨机首连时 `connectTimeoutMs` 是否明显低于网络 RTT × 重试余量；注意 `RPC_MINIMUM_TIMEOUT = 500 ms` 是硬下限 |
| 5 | 仍失败 | 带上 Status 全文 + 时间线升级 |

### 1.6 与"有机故障"的区分

| 维度 | 有机故障 | 运维 / 部署类 |
|------|----------|---------------|
| 时间 | 与发布无必然关系 | 与变更工单、滚动、维护窗强相关 |
| 控制面 | etcd 多可用 | etcd 监控异常时，优先按 L3 处理，不先猜 ring 细节 |
| 客户端 | 23 / 1001 / 1002 突发 | 多见 32、31、25；或 Init 即失败（见 § 1.5） |

### 1.7 运行中变更：按可观测信号推进

| 步骤 | 对应层 | 动作 |
|------|--------|------|
| 1 | L0 | 记录变更开始 / 结束时间、受影响 AZ / 集群 / 批次；看 KV 成功率、P99 |
| 2 | L3 | 看 etcd 监控：quorum、leader、错误率 / 延迟。**若 etcd 整体故障**：预期扩缩容 / 隔离卡住；优先恢复 etcd |
| 3 | L1 | `32` 在写接口上是否增多 → 元数据侧繁忙或变更中；`25 / 1001 / 1002 / 23` → 按 § 2 做链路侧排查；`31` 与 `HealthCheck` → LB 应摘掉正在退出的后端 |
| 4 | L2+L4 | Pod / 进程是否 CrashLoop、OOM、探针失败；在涉事 Worker/Master 上按关键词拉 ERROR/WARN，时间戳对齐变更 |
| 5 | L5 | 仍无结论：工单附上监控截图 + access 聚合 + 日志片段 |

### 1.8 FEMA 编号对应

| FEMA | 场景 | 一线侧重观测 |
|-------|------|--------------|
| 7 / 8 | 业务扩缩容 | 业务实例与 Worker 拓扑、23、监控 |
| 9 / 10 | Worker 扩缩容 | etcd 监控、32 / 31、Worker 日志关键词 |
| 4~6 | 跨节点读 | 路由 / 服务发现是否仍指向已下线后端 |
| 1~3 | 业务 + Worker 部署 | 冷启动、Ready 探针、端口可达 |

---

## § 2. 区分 1002 (`K_RPC_UNAVAILABLE`) 与 URMA 瞬时失效

### 2.1 先分清两层

| 码 | 含义 |
|----|------|
| 1002 `K_RPC_UNAVAILABLE` | RPC / 消息通道不可用或未在时限内就绪：ZMQ 连接、等待对端、网关转发失败、部分 socket 错误等 |
| 1004 `K_URMA_ERROR` | URMA / UB 数据路径错误 |
| 1006 `K_URMA_NEED_CONNECT` | URMA 会话需重建 / 重连 |
| 1008 `K_URMA_TRY_AGAIN` | URMA 瞬时 / 可重试 |

**URMA 瞬时失效在码表上优先看 1008（及 1006 / 1004），而不是默认当成 1002。** 若只看到 1002，往往说明失败被归类在 ZMQ/TCP 传输层或被映射成 UNAVAILABLE（见 § 2.2），**不能从码上直接等价成"UB 坏了"**。

### 2.2 按 `respMsg` 关键词分流

`access log` 最后一列 `Status::GetMsg()` 常见关键词 → 子类：

| respMsg 关键词 | 子类 | 源码位置 |
|----------------|------|----------|
| `has not responded within the allowed time` | ZMQ 阻塞收包，底层 `K_TRY_AGAIN` 被改写 | `common/rpc/zmq/zmq_msg_queue.h::ClientReceiveMsg` |
| `Remote service is not available within allowable %d ms` | 建连 / 等待对端超时 | `common/rpc/zmq/zmq_stub_conn.cpp` |
| `Timeout waiting for SockConnEntry wait` | 等待连接超时 | `common/rpc/zmq/zmq_stub_conn.cpp` |
| `Network unreachable` | 心跳发送时 `POLLOUT` 不可写 | `common/rpc/zmq/zmq_stub_conn.cpp` |
| `Connect reset. fd %d. err ...` | `UnixSockFd` socket reset | `common/rpc/unix_sock_fd.cpp::ErrnoToStatus` |
| `Can not create connection to worker for shm fd transfer` | 必须走 SHM/UDS 传 fd 却建失败 | `client/client_worker_common_api.cpp` |
| `The service is currently unavailable` | 网关 / Frontend 处理失败 | `zmq_stub_conn.cpp::ReportErrorToClient` |

### 2.3 实操分流顺序

1. **看码**：存在 1008 / 1006 / 1004 时，优先按 URMA 专题处理，不要先当普通断网。
2. **看 `respMsg` 关键词**（如 § 2.2 表格）。
3. **看路径**：当前请求是否走 UB 读（`Get` + URMA buffer）还是纯 ZMQ payload；UB 路径失败更常先体现为 1004 / 1008。
4. **看 Worker 同时间点**：`DS_POSIX_GET` / UB 相关日志、是否 TCP 降级、是否 `K_URMA_NEED_CONNECT` 重试成功。
5. **仍糊**：用 bpftrace / strace / 网卡与 UB 端口指标做时间关联；单靠 1002 无法定界到"URMA 瞬时"。

---

## § 3. 31 / 32 的客户端可见性

### 3.1 结论速查

| 码 | 客户端能否收到 | 典型入口 | 客户端是否按该码自动重试 |
|----|----------------|----------|--------------------------|
| `K_SCALE_DOWN` (31) | **能**（显式 RPC 返回） | `HealthCheck`：Worker 判定本节点正在退出 | **否**（`stub_->HealthCheck` 无 `RetryOnError`） |
| `K_SCALE_DOWN` | **能**（若走迁移 RPC） | `MigrateDataDirect` 等迁移路径上 Worker 返回 | 视调用方；默认 `RETRY_ERROR_CODE` 不含 31 |
| `K_SCALING` (32) | **分路径** | Worker MultiPublish / 元数据 2PC：`CreateMultiMeta*` 在 `meta_is_moving` 退出循环后返回 | **仅 MultiPublish** 把 32 列入重试；Get / Publish / Create 默认 `RETRY_ERROR_CODE` 不含 32 |
| `K_SCALING` | **Get 批量语义下易"怪"** | Worker 把 32 放进 `GetRspPb.last_rc` 而非 RPC 层失败 | `Get` 的 lambda 只对 `IsRpcTimeoutOrTryAgain` + 部分 OOM 触发重试；`last_rc == K_SCALING` 会返回 OK 结束重试，**顶层 `Get()` 仍可能返回 `Status::OK()`**，错误落在 per-object 状态 |

### 3.2 服务端产生位置（证据）

**K_SCALE_DOWN**（`worker/object_cache/worker_oc_service_impl.cpp:314-333`）：

```cpp
Status WorkerOCServiceImpl::HealthCheck(const HealthCheckRequestPb &req, HealthCheckReplyPb &resp)
{
    if (etcdCM_ != nullptr && etcdCM_->CheckLocalNodeIsExiting()) {
        constexpr int logInterval = 60;
        LOG_EVERY_T(INFO, logInterval) << "[HealthCheck] Worker is exiting now";
        RETURN_STATUS(StatusCode::K_SCALE_DOWN, "Worker is exiting now");
    }
    return Status::OK();
}
```

**K_SCALING**（`worker/object_cache/service/worker_oc_service_multi_publish_impl.cpp:550-565`）：

```cpp
while (true) {
    RETURN_IF_NOT_OK(api->CreateMultiMeta(req, rsp, false));
    if (rsp.info().empty()) return Status::OK();
    if (rsp.meta_is_moving()) {
        rsp.Clear();
        std::this_thread::sleep_for(std::chrono::milliseconds(RETRY_INTERNAL_MS_META_MOVING));
        continue;
    }
    return Status(K_SCALING, "The cluster is scaling, please try again.");
}
```

当前在 `worker/object_cache` 下 grep 不到 Get 主路径直接 `return Status(K_SCALING, ...)`；32 的稳定来源主要是 MultiPublish 元数据路径。若线上 Get 出现 32，需结合是否 per-object `last_rc` 或其它模块 / 版本再查。

### 3.3 客户端行为（证据）

**默认重试集合**（`client/object_cache/client_worker_api/client_worker_remote_api.cpp:36-38`）：

```cpp
const std::unordered_set<StatusCode> RETRY_ERROR_CODE{
    K_TRY_AGAIN, K_RPC_CANCELLED, K_RPC_DEADLINE_EXCEEDED,
    K_RPC_UNAVAILABLE, K_OUT_OF_MEMORY };
```

**Get 的 lambda**（`client_worker_remote_api.cpp:316-321`）：仅 `IsRpcTimeoutOrTryAgain` 与特定 OOM 触发重试，`last_rc == K_SCALING` 时返回 OK 结束重试。

**MultiPublish**（`client_worker_remote_api.cpp:424-436`）：显式把 `K_SCALING` 纳入重试集合。

**HealthCheck**：无 `RetryOnError`，`K_SCALE_DOWN` 原样返回。集成方调用 `KVClient::HealthCheck()` 可稳定拿到 31：

```cpp
// tests/st/client/kv_cache/kv_client_voluntary_scale_down_test.cpp:1253
ASSERT_EQ(client0_->HealthCheck().GetCode(), StatusCode::K_SCALE_DOWN);
```

### 3.4 与 access log 的对应

- access log 的 `code` 来自 `Status::GetCode()` 在 KV 路径 `Record` 时的值。
- `HealthCheck` 若单独埋点，可稳定看到 31。
- `KVClient::Get` 若在 `object_client_impl` 层把整次调用标成成功，而 per-object 含 32，则 `DS_KV_CLIENT_GET` 行可能仍是 0，与"32 | 扩缩容"直观预期不一致。**需要看 object 级错误是否被汇总成顶层失败。**

### 3.5 产品语义与集成方建议

扩缩容对业务侧的目标是 **不中断**；31 / 32 **不是** "用户要执行某种操作"的 API 契约。

| 角色 | 建议 |
|------|------|
| 业务 / 终端用户 | 无需为 31 / 32 设计专门业务流程或提示文案；读写应依赖幂等、超时、多副本路由 |
| 集成 / 运维 | **31**：`HealthCheck` 探活命中时，让 LB / 服务发现不再把新请求打到正在退出的节点。**32**：写路径 SDK 已对 MultiPublish 内置重试；业务侧重在超时与幂等，勿把 32 当容量告警。Get 路径上 32 可能只在 PB `last_rc`，以 per-object 状态为准 |

---

## § 4. Worker `resource.log` 字段解读

### 4.1 怎么打开、文件在哪

| 项 | 说明 |
|----|------|
| **开关** | gflag `log_monitor`（默认在 `common_gflag_define.cpp` 中为 `true`） |
| **周期** | `log_monitor_interval_ms`（默认 10000 ms） |
| **导出** | `log_monitor_exporter=harddisk` 时写入 `{log_dir}/resource.log`（常量 `RESOURCE_LOG_NAME`） |
| **实现入口** | `ResMetricCollector` 定时线程拼接各 handler 返回值，以 ` \| ` 分隔后交给 `HardDiskExporter::Send` 落盘 |

### 4.2 字段顺序：以源码为准

本进程实际输出顺序由枚举 `ResMetricName` 的定义文件 `common/metrics/res_metrics.def` 决定（**请勿改动该文件中的顺序**）。注册逻辑在 `worker_oc_server.cpp` 的 `RegisteringWorkerCallbackFunc` / `RegisteringMasterCallbackFunc` / `RegisteringThirdComponentCallbackFunc`：未启用的子系统（如未开 OC/SC、非 Master 节点）对应槽位为空串或占位默认值，表现为连续的 ` \| `。

| 顺序 | `ResMetricName` | 常见叫法 | 源码采集 | 定界怎么用 |
|------|-----------------|----------|----------|------------|
| 1 | `SHARED_MEMORY` | shm_info | `memory::Allocator::Instance()->GetMemoryStatistics()` | 共享内存 / 分配器使用率突增、贴上限 → 易触发驱逐、分配失败、长尾；与客户端 1001/1002/8、业务 TP99 一并看时间线 |
| 2 | `SPILL_HARD_DISK` | spill_disk_info | `WorkerOcSpill::Instance()->GetSpillUsage()` | Spill 磁盘用量与比例；高负载或冷数据落盘时与时延、磁盘 IO 相关 |
| 3 | `ACTIVE_CLIENT_COUNT` | client nums | `ClientManager::Instance().GetClientCount()` | 已建连客户端数；与预期实例数、滚动发布批次对账；异常飙高 / 不掉 → 连接泄漏或缩容未断净 |
| 4 | `OBJECT_COUNT` | object nums | `objCacheClientWorkerSvc_->GetTotalObjectCount()`（仅 `EnableOCService()`） | Object Cache 对象个数；纯 KV 且未走 OC 时该槽可能无注册或为空 |
| 5 | `OBJECT_SIZE` | object total datasize | `GetTotalObjectSize()`（同上） | 缓存对象总字节；与 SHM 使用率交叉看是否容量型而非网络型问题 |
| 6 | `WORKER_OC_SERVICE_THREAD_POOL` | WorkerOcService threadpool | `GetRpcServicesUsage("WorkerOCService")` | RPC 线程池 `idle/current/max/waiting/rate`：waiting 堆积、rate 长期顶满 → 服务端过载或慢依赖，对应客户端 TP99 升、超时 |
| 7 | `WORKER_WORKER_OC_SERVICE_THREAD_POOL` | WorkerWorkerOcService threadpool | `GetRpcServicesUsage("WorkerWorkerOCService")` | Worker ↔ Worker 方向；跨机元数据 / 数据拉取变慢时对照远端读、切流场景 |
| 8 | `MASTER_WORKER_OC_SERVICE_THREAD_POOL` | MasterWorkerOcService threadpool | `GetRpcServicesUsage("MasterWorkerOCService")` | Master ↔ Worker；与扩缩容、元数据迁移（32 / 31 / 25）同时间线对照 |
| 9 | `MASTER_OC_SERVICE_THREAD_POOL` | MasterOcService threadpool | `GetRpcServicesUsage("MasterOCService")` | Master 侧 OC 处理池；控制面繁忙时辅助判断是否 Master 侧排队 |
| 10 | `ETCD_QUEUE` | write ETCD queue | Master 上 `GetETCDAsyncQueueUsage()`；非 Master 为 `0/0/0` | 异步写 etcd 队列积压 → 控制面写路径受阻；与 `requestout.log` 中 `DS_ETCD`、etcd 大盘、客户端 32/25 一起读 |
| 11 | `ETCD_REQUEST_SUCCESS_RATE` | ETCD request success rate | `etcdStore_->GetEtcdRequestSuccessRate()` | etcd 请求成功率下降 → 优先定界基础设施 |
| 12 | `OBS_REQUEST_SUCCESS_RATE` | OBS request success rate | `persistenceApi_->GetL2CacheRequestSuccessRate()`（L2 为 OBS 时） | 二级存储 OBS 成功率；读失败、恢复慢时看数据面 / 持久化是否异常 |
| 13 | `MASTER_ASYNC_TASKS_THREAD_POOL` | Master AsyncTask threadpool | `GetMasterAsyncPoolUsage()` | Master 异步任务池；与元数据任务堆积、扩缩容卡顿相关 |
| 14 | `STREAM_COUNT` | — | `streamCacheClientWorkerSvc_->GetTotalStreamCount()`（`EnableSCService()`） | Stream 条数；流缓存场景下看资源与泄漏 |
| 15-18 | `WORKER_SC_SERVICE_THREAD_POOL` 等 | SC 相关 threadpool | `ClientWorkerSCService` / `WorkerWorkerSCService` / Master SC | Stream Cache RPC 池；SC 专用 |
| 19 | `STREAM_REMOTE_SEND_SUCCESS_RATE` | — | `GetSCRemoteSendSuccessRate()` | SC 跨节点发送成功率；低 → 网络或下游 Worker 问题线索 |
| 20 | `SHARED_DISK` | — | `Allocator::GetSharedDiskStatistics()` | 共享磁盘维度用量；与落盘、二级路径一起看 |
| 21 | `SC_LOCAL_CACHE` | — | `GetUsageMonitor().GetLocalMemoryUsed()` | SC 本地内存；与 Stream 内存配置、OOM 风险相关 |
| 22 | `OC_HIT_NUM` | Cache Hit Info | `objCacheClientWorkerSvc_->GetHitInfo()` → `CacheHitInfo::GetHitInfo()` | 格式 `mem/disk/l2/remote/miss`：`remote` 占比高 → 多跳远端读多，易拉高 TP99；`miss` 突增 → 冷启动、驱逐、或 key 分布变化；需与 access log、业务 QPS 对齐看 **增量** 而非单点绝对值 |

### 4.3 与其它日志的关系

| 日志 | 定界侧重点 |
|------|------------|
| 运行日志 `datasystem_worker.*.log` | 具体 ERROR/WARN、栈、组件内部状态；资源行不替代文本日志 |
| 访问日志 `access.log`（Worker POSIX） | 单次请求成功 / 失败、耗时、action；与 resource 周期线对齐时间轴 |
| 请求第三方 `requestout.log` | 每次调 etcd / OBS 等一条；适合算失败率、延迟 |
| 客户端 `ds_client_access_*.log` | SDK KV / Object 视角；与 Worker 侧 `client nums`、threadpool、SHM 交叉做 Client ↔ Worker 定界 |

### 4.4 推荐读法（避免误读）

1. 先看时间线：变更窗、告警时刻前后多行 resource 是否趋势变化（单点跳变可能是采集边界）。
2. 再与 access / requestout 对齐：如 TP99 升时 `waitingTaskNum` 是否同步升、etcd 成功率是否掉。
3. OC / SC / 纯 KV：确认部署是否 `EnableOCService` / `EnableSCService`，避免对空槽位误解释。
4. Hit 计数为累计值：排障时更可靠的是相邻两行差分 / 与监控 QPS 对比，而不是单行绝对值。

官方《日志》附录：[openYuanrong datasystem 日志](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/appendix/log_guide.html)（外部字段顺序为阅读便利，实际顺序以源码 `res_metrics.def` 为准）。
