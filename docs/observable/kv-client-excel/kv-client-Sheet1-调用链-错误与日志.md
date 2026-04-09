# Sheet1：KV Client 调用链 — 错误码与日志（Init / MCreate / MSet / MGet）

> 与 Excel **`Sheet1_调用链`** 同内容，本页补充 **代码证据** 与 **时序图锚点**，供兄弟团队校验。

**仓库**：`yuanrong-datasystem`（下述路径均相对该仓库根）  
**时序图**：`vibe-coding-files/docs/flows/sequences/kv-client/`

---

## 1. 总表（与 Excel 一致，可逐行核对）

| 接口 | 子阶段/步骤 | 调用关系(摘要) | 传输/形态 | 主要失败 Status(示例) | 典型日志或消息 | 代码证据 | 时序图/文档 |
|------|-------------|----------------|-----------|------------------------|----------------|----------|-------------|
| Init | 凭证与入口 | `KVClient::Init` → `ObjectClientImpl::Init` | — | `K_INVALID` 等 | CreateClientCredentials | `kv_client.cpp`; `object_client_impl.cpp` | sdk-init-定位定界.md |
| Init | Client↔Worker 控制面 | `InitClientWorkerConnect` → `RegisterClient` | TCP(ZMQ)+UDS | `1002`/`23` | Register failed; heartbeat | `client_worker_common_api.cpp`; `worker_service_impl.cpp` | sdk-init §4 |
| Init | UB 传输初始化 | `UrmaManager::Init` | UB/URMA | `1004`/`K_URMA_*` | Failed to urma init; bonding | `urma_manager.cpp` | 见 Sheet2 |
| MCreate | 前置校验 | `MultiCreate` 入参 | — | `K_INVALID` | batch/size | `object_client_impl.cpp` | kv_client_e2e_flow.puml |
| MCreate | MultiCreate RPC | `LOCAL_WORKER->MultiCreate` | TCP 到入口 Worker | `1002` 等 | Authenticate / signature | `client_worker_local_api.cpp` | 与读路径 ① 同类 |
| MCreate | SHM 路径 | `MutiCreateParallel` / mmap | 同节点 SHM | `K_RUNTIME_ERROR`/`1002` | fd/mmap | `object_client_impl.cpp` | 读路径 ⑥ |
| MSet | 前置 | buffer 校验 | — | `K_INVALID`/`K_OC_ALREADY_SEALED` | sealed | `object_client_impl.cpp` MSet | e2e 写分区 |
| MSet | MultiPublish | `RetryOnError` | TCP+UB/payload | `1002`/`32`/`6` | scaling / publish error | `client_worker_remote_api.cpp` | scaling 序列图 |
| MSet | Worker→Master | 元数据提交 | Worker→Master RPC | `K_SCALING` 等 | scaling / master fail | `worker_oc_service_multi_publish_impl.cpp` | kv-场景写 |
| MSet | Worker→Worker UB | `UrmaWritePayload` | UB | `1004`/`K_RUNTIME_ERROR` | advise jfr / write | `urma_manager.cpp`; `worker_worker_oc_service_impl.cpp` | 与读 ④⑤ 对称 |
| MGet/Get | 前置 | `GetAvailableWorkerApi` | — | `1002` | 切流 | `object_client_impl.cpp` Get | switch_worker 序列图 |
| MGet/Get | Get RPC | `stub_->Get` | TCP 控制面 | `1001`/`1002`/`19` | RPC timeout | `client_worker_remote_api.cpp` | read_path ① |
| MGet/Get | UB 准备 | `PrepareUrmaBuffer` | UB 可降级 | WARNING / `5` | fallback TCP payload | `client_worker_base_api.cpp` | 读接口 UB 专节 |
| MGet/Get | 远端拉取 | `GetObjectFromRemote…` | UB/TCP 数据面 | `6`/`3`/`1002` | remote failed | `worker_oc_service_get_impl.cpp` | read_path ②③④⑤ |
| MGet/Get | SHM 回传 | `GetClientFd` / mmap | 同节点 SHM | `K_RUNTIME_ERROR`/`1002` | mmap | `object_client_impl.cpp` | read_path ⑥ |

---

## 2. 关键代码片段（入口）

### 2.1 `KVClient::Init` → `ObjectClientImpl::Init`

```66:72:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/kv_cache/kv_client.cpp
Status KVClient::Init()
{
    TraceGuard traceGuard = Trace::Instance().SetTraceUUID();
    bool needRollbackState;
    auto rc = impl_->Init(needRollbackState, true);
    impl_->CompleteHandler(rc.IsError(), needRollbackState);
    return rc;
}
```

```345:366:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::Init(bool &needRollbackState, bool enableHeartbeat)
{
    ...
    RETURN_IF_NOT_OK(InitClientWorkerConnect(enableHeartbeat, false));
    return Status::OK();
}
```

### 2.2 `MCreate`：本地 Worker `MultiCreate` + 条件 SHM

```1155:1182:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::MultiCreate(...){
    ...
    bool canUseShm = workerApi_[LOCAL_WORKER]->shmEnabled_ && dataSizeSum >= workerApi_[LOCAL_WORKER]->shmThreshold_;
    if (canUseShm || !skipCheckExistence) {
        RETURN_IF_NOT_OK(workerApi_[LOCAL_WORKER]->MultiCreate(skipCheckExistence, multiCreateParamList, version,
                                                               exists, useShmTransfer));
    } else {
        ...
    }
```

### 2.3 `MSet`：`MultiPublish`

```2180:2202:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::MSet(const std::vector<std::shared_ptr<Buffer>> &buffers)
{
    ...
    RETURN_IF_NOT_OK(workerApi->MultiPublish(bufferInfoList, publishParam, rsp));
    return HandleShmRefCountAfterMultiPublish(buffers, rsp);
}
```

### 2.4 `Get` / `MGet`：`GetBuffersFromWorker` 前置

```1568:1596:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::Get(const std::vector<std::string> &objectKeys, int64_t subTimeoutMs,
                             std::vector<Optional<Buffer>> &buffers, bool queryL2Cache, bool isRH2DSupported)
{
    ...
    RETURN_IF_NOT_OK(GetAvailableWorkerApi(workerApi, raii));
    ...
    Status rc = GetBuffersFromWorker(workerApi, getParam, objectBuffers);
    ...
}
```

---

## 3. 校验清单（给评审兄弟）

1. **Init**：是否覆盖你们环境 **USE_URMA** 与 **纯 TCP** 两套启动差异。  
2. **MCreate**：是否认可「**MultiCreate 始终走 LOCAL_WORKER API 对象**」这一事实（与「切流后 Get 可走远端 Worker」不同）。  
3. **MSet/MGet**：Worker→Worker 的 UB 与 **TCP 控制面** 是否要在表中再拆一列「**仅 payload**」——若需要，可在 Excel 加列后同步改本 Markdown。
