# client local worker 故障 / worker选择 / 预建链代码摘录

## 1) worker 选择策略（默认同节点优先）

来源：`yuanrong-datasystem/include/datasystem/utils/service_discovery.h`

```cpp
enum class ServiceAffinityPolicy : uint8_t {
    PREFERRED_SAME_NODE = 0,
    REQUIRED_SAME_NODE = 1,
    RANDOM = 2,
};

struct ServiceDiscoveryOptions {
    std::string hostIdEnvName = "";
    ServiceAffinityPolicy affinityPolicy = ServiceAffinityPolicy::PREFERRED_SAME_NODE;
};
```

来源：`yuanrong-datasystem/src/datasystem/client/service_discovery.cpp`

```cpp
Status ServiceDiscovery::SelectWorker(std::string &workerIp, int &workerPort, bool *isSameNode)
{
    RETURN_IF_NOT_OK(this->ObtainWorkers());
    std::string pickedAddr;
    {
        std::shared_lock<std::shared_timed_mutex> lock(workerHostPortMutext_);
        if (activeWorkerInfo_.empty()) {
            return Status(K_RUNTIME_ERROR, "No available worker available is detected.");
        }

        if (affinityPolicy_ == ServiceAffinityPolicy::RANDOM) {
            pickedAddr = SelectWorkerAddr(activeWorkerInfo_, randomData_.get());
        } else {
            auto sameHostWorkers = FilterSameHostWorkers(activeWorkerInfo_, hostId_);
            if (affinityPolicy_ == ServiceAffinityPolicy::REQUIRED_SAME_NODE) {
                CHECK_FAIL_RETURN_STATUS(!hostId_.empty(), K_INVALID,
                                         "Failed to obtain sdk host_id from hostIdEnvName.");
                CHECK_FAIL_RETURN_STATUS(!sameHostWorkers.empty(), K_RUNTIME_ERROR,
                                         "No available same-node worker is detected.");
                pickedAddr = SelectWorkerAddr(sameHostWorkers, randomData_.get());
            } else {
                pickedAddr = sameHostWorkers.empty() ? SelectWorkerAddr(activeWorkerInfo_, randomData_.get())
                                                     : SelectWorkerAddr(sameHostWorkers, randomData_.get());
            }
        }
    }
    RETURN_IF_NOT_OK(ParseWorkerAddr(pickedAddr, workerIp, workerPort));
    return Status::OK();
}
```

## 2) local worker 异常时处理 / 切换

来源：`yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp`

```cpp
void ObjectClientImpl::ProcessWorkerLost()
{
    if (clientStateManager_->GetState() & (uint16_t)ClientState::EXITED) {
        return;
    }
    ProcessWorkerTimeout();
    auto &workerApi = workerApi_[LOCAL_WORKER];
    Status s = workerApi->ReconnectWorker(ids);
    if (s.IsError()) {
        LOG(ERROR) << "[Reconnect] Reconnect local worker failed, error message: " << s.ToString();
        return;
    }
    listenWorker_[LOCAL_WORKER]->SetWorkerAvailable(true);
    {
        std::lock_guard<std::mutex> lock(switchNodeMutex_);
        if (currentNode_ == LOCAL_WORKER) {
            MarkWorkerAvailableLocked();
        }
    }
}

void ObjectClientImpl::MarkNoSwitchableWorkerLocked()
{
    LOG(WARNING) << "[Switch] No switchable worker available, enable fail-fast.";
    workerSwitchState_ = WorkerSwitchState::NO_SWITCHABLE_WORKER;
    switchInProgress_ = false;
    ++switchGeneration_;
}

Status ObjectClientImpl::NoSwitchableWorkerStatus() const
{
    return { K_RPC_UNAVAILABLE, "no switchable worker available" };
}
```

## 3) 预建链（heartbeat后触发 fast transport / URMA 握手）

来源：`yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp`

```cpp
Status ObjectClientImpl::InitClientRuntimeAt(WorkerNode node, bool initWithWorker, bool isLocalWorker)
{
    auto &workerApi = workerApi_[node];
    ...
    RETURN_IF_NOT_OK(InitListenWorkerAt(node, isLocalWorker));
    workerApi->TryFastTransportAfterHeartbeat();
    ...
    return Status::OK();
}
```

来源：`yuanrong-datasystem/src/datasystem/client/client_worker_common_api.cpp`

```cpp
void ClientWorkerRemoteCommonApi::TryFastTransportAfterHeartbeat()
{
    if (!pendingFtHandshake_.has_value()) {
        return;
    }
    auto ctx = std::move(*pendingFtHandshake_);
    pendingFtHandshake_.reset();
    auto rc = FastTransportHandshake(ctx.timeoutMs, ctx.workerVersion, ctx.rsp);
    if (rc.IsError()) {
        FLAGS_enable_urma = false;
        LOG(ERROR) << "Fast transport handshake failed, fall back to TCP/IP communication. Detail: " << rc.ToString();
    }
}

Status ClientWorkerRemoteCommonApi::FastTransportHandshake(
    int32_t timeoutMs, uint32_t workerVersion, const RegisterClientRspPb &rsp)
{
    // This only warms up local URMA hardware resources and memory pools.
    // The actual remote connection is established later during the handshake.
    SetClientFastTransportMode(rsp.fast_transport_mode(), fastTransportMemSize_);
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(InitializeFastTransportManager(), "Fast transport init failed");

    if (IsShmEnable()) {
        FLAGS_enable_urma = false;
        return Status::OK();
    }
    ...
    return Status::OK();
}
```

## 4) URMA下 ReconcileShmRef 使用 currentNode（修复点）

来源：`yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp`

```cpp
void ObjectClientImpl::ShmRefReconcileThreadFunc()
{
    ...
    std::shared_ptr<IClientWorkerApi> reconcileWorkerApi;
    {
        std::lock_guard<std::mutex> lock(switchNodeMutex_);
        WorkerNode reconcileWorker = LOCAL_WORKER;
#ifdef USE_URMA
        if (IsUrmaEnabled()) {
            reconcileWorker = currentNode_;
        }
#endif
        if (workerApi_.size() > static_cast<size_t>(reconcileWorker)) {
            reconcileWorkerApi = workerApi_[reconcileWorker];
        }
        if (reconcileWorkerApi == nullptr && workerApi_.size() > static_cast<size_t>(LOCAL_WORKER)) {
            reconcileWorkerApi = workerApi_[LOCAL_WORKER];
        }
    }
    ...
}
```
