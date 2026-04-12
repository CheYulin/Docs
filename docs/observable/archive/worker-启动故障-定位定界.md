# Worker 启动故障定位定界

本文专门覆盖 Worker 从进程启动到服务就绪阶段的故障定位与责任边界，目标是：
- 快速判断故障卡在哪一层（配置 / 网络 / etcd / 存储 / 数据系统内部）
- 给出可直接检索的日志关键词
- 给出“错误码 + 证据 + 责任”定界话术

配套：
- `docs/observable/sdk-init-定位定界.md`
- `docs/observable/kv-场景-故障分类与责任边界.md`

---

## 1. 启动主链路（代码证据）

Worker 启动主流程：

```282:323:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/worker.cpp
Status Worker::InitWorker(...)
{
    ...
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(LoadAllSecretKeys(), "Load secret keys failed.");
    ...
    RETURN_IF_NOT_OK(options.LoadParameters());
    worker_ = std::make_unique<WorkerOCServer>(...);
    ...
    SHUTDOWN_IF_NOT_OK(worker_->Init());
    SHUTDOWN_IF_NOT_OK(worker_->Start());
    SHUTDOWN_IF_NOT_OK(WorkerPostProcessing());
    ...
    LOG(INFO) << "Worker start success";
}
```

`WorkerOCServer::Init` 关键阶段：
- 校验 etcd/metastore 地址
- `EtcdStore::Init` + `Authenticate`
- `EtcdClusterManager::Init`
- `ClientManager::Init`
- `CreateAllServices`
- `InitReplicaManager`
- `InitializeAllServices`

证据：

```858:916:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/worker_oc_server.cpp
CHECK_FAIL_RETURN_STATUS(ValidateEtcdOrMetastoreAddress(), K_RUNTIME_ERROR,
                         "Neither etcd_address nor metastore_address is specified");
...
RETURN_IF_NOT_OK_PRINT_ERROR_MSG(etcdCM_->Init(clusterInfo), "etcd cluster manager init failed");
...
RETURN_IF_NOT_OK_PRINT_ERROR_MSG(InitReplicaManager(), "replica manager init failed");
...
RETURN_IF_NOT_OK(InitializeAllServices(clusterInfo));
LOG(INFO) << "Worker init success.";
```

---

## 2. 启动阶段常见错误码与日志

| 阶段 | 常见错误码 | 典型日志/消息 | 初判责任域 |
|------|------------|---------------|------------|
| 参数/配置 | `K_RUNTIME_ERROR` / `K_INVALID` | `Neither etcd_address nor metastore_address is specified`、`parse worker flags failed` | L0（集成方，部署配置） |
| 密钥加载 | `K_RUNTIME_ERROR` | `Load secret keys failed.` | L0（集成方）/L3（数据系统）（密钥与程序配置） |
| etcd 初始化/认证 | `K_RPC_UNAVAILABLE`/`K_MASTER_TIMEOUT`/运行时错误 | `etcd cluster manager init failed`、第三方访问失败 | L2（三方件）为主（中台） |
| 集群参数校验 | `K_INVALID` | `node_dead_timeout_s must be greater...`、`node_timeout_s ... heartbeat_interval_ms` | L0（集成方，参数） |
| UDS/本地资源 | `K_RUNTIME_ERROR` | UDS bind/目录权限相关（`WorkerServiceImpl::Init`） | L1（平台与网络，OS/容器） |
| 服务装配 | `K_RUNTIME_ERROR` 等 | `replica manager init failed`、`InitializeAllServices` 失败 | L3（数据系统） |

---

## 3. Worker 日志信号与含义（可直接 grep）

- `Worker non-default flags:`  
  启动参数快照，先确认是否配置错误。

- `Load secret keys failed`  
  密钥/证书路径或权限问题。

- `Using external etcd:` / `Using metastore as etcd replacement:`  
  启动选择了哪个控制面后端。

- `etcd cluster manager init failed`  
  控制面初始化失败（重点看 etcd 可用性与认证）。

- `replica manager init failed`  
  副本管理初始化失败，偏数据系统内部。

- `Worker init success.`  
  `WorkerOCServer::Init` 完成。

- `Worker start success`  
  整个 `InitWorker` 流程完成，服务可对外。

---

## 4. 启动故障排查路径（执行顺序）

1. **确认卡点**  
   看最后一条启动日志，判断停在 `InitWorker` 还是 `WorkerOCServer::Init`。

2. **先看配置类**  
   参数合法性（etcd/metastore 地址、超时参数、log 目录等）。

3. **看控制面（etcd）**  
   若出现 `etcd cluster manager init failed`：
   - 对齐 etcd 集群健康
   - 查认证配置与连通性
   - 查 watch/keepalive 是否建立

4. **看本地资源与 OS**  
   UDS 目录、端口监听、fd 限额、磁盘权限、容器资源。

5. **看数据系统内部模块**  
   `InitReplicaManager` / `InitializeAllServices` 失败路径。

---

## 5. 定界表格（启动故障）

| 场景信号 | 首选证据 | 非数据系统责任 | 数据系统内优先模块 |
|------|----------|----------------|---------------------|
| 地址缺失/参数非法 | 启动日志 + flags 快照 | L0（集成方，部署） | `Worker::InitWorker` 参数加载 |
| etcd 初始化失败 | `etcd cluster manager init failed` + etcd 健康数据 | L2（三方件，中台） | `EtcdStore` / `EtcdClusterManager::Init` |
| UDS bind/目录权限失败 | 本地系统日志 + Worker bind 日志 | L1（平台与网络，OS/容器） | `WorkerServiceImpl::Init` |
| 副本/服务初始化失败 | `replica manager init failed` / `InitializeAllServices` | - | `WorkerOCServer` 服务装配链 |
| 启动后频繁重启 | 启动日志时间窗 + 资源指标 | L1（平台与网络）/L0（集成方）常见 | 需结合具体失败点定位 |

---

## 6. 定界话术模板（可直接复用）

- **配置问题（L0（集成方））**  
  “Worker 启动失败发生在参数校验阶段，日志出现 `<具体参数错误>`，未进入服务初始化链，优先定界为部署配置问题。”

- **etcd 控制面问题（L2（三方件））**  
  “Worker 启动在 `etcdCM_->Init` 阶段失败，日志为 `etcd cluster manager init failed`，同时间窗 etcd 健康异常，优先定界为中台控制面问题。”

- **OS/容器资源问题（L1（平台与网络））**  
  “Worker 启动在本地资源阶段失败（UDS bind/权限/fd），请求尚未进入业务处理链，优先定界为 OS/容器资源问题。”

- **数据系统内部问题（L3（数据系统））**  
  “控制面与本地资源检查通过后，失败出现在 `InitReplicaManager/InitializeAllServices`，优先定界为数据系统内部服务装配或初始化链问题。”

