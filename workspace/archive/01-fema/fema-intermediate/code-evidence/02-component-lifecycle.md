# 代码证据：组件生命周期 & Worker 健康检测

## 1. Worker 心跳超时检测（Client侧）

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `client/listen_worker.cpp` | 100-118 | `StartListenWorker` |
| `client/listen_worker.cpp` | 155-160 | `NotifyFirstHeartbeat` |
| `client/listen_worker.cpp` | 192-200 | `CheckHeartbeat` |

### 关键代码片段

```cpp
// listen_worker.cpp:100-118
if (!isUds_) {
    // Unix Domain Socket 模式，检测 socket fd 断开
    RETURN_IF_NOT_OK(udsEventLoop_->AddFdEvent(
        socketFd_, EPOLLIN | EPOLLHUP,
        [this]() {
            LOG(INFO) << "The client detects that the worker is disconnected, socket fd: " << socketFd_;
            workerAvailable_ = false;
            RunAllCallback();
        }, nullptr));
} else {
    // RPC 心跳模式，等待首次心跳
    workerListenedThread_ = Thread(&ListenWorker::CheckHeartbeat, this);
    firstHeartbeatWaitPost_->WaitFor(clientCommonWorker_->connectTimeoutMs_);
    INJECT_POINT("listen_worker.StartListenWorker");
    if (!firstHeartbeatReceived_.load()) {
        return Status(K_CLIENT_WORKER_DISCONNECT, "Cannot receive heartbeat from worker.");  // 行 114
    }
}
```

```cpp
// listen_worker.cpp:192-200
void ListenWorker::CheckHeartbeat()
{
    // ...
    auto clientDeadTimeoutMs = clientCommonWorker_->clientDeadTimeoutMs_;
    while (!stop_) {
        // ...
        if (elapsedMs >= clientDeadTimeoutMs_) {
            LOG(ERROR) << "Heartbeat timeout, clientDeadTimeoutMs: " << clientDeadTimeoutMs_
                       << ", elapsedMs: " << elapsedMs;
            workerAvailable_ = false;
            RunAllCallback();  // 执行所有回调，包括 ProcessWorkerLost
            break;
        }
        // ...
    }
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_CLIENT_WORKER_DISCONNECT (23) | 心跳超时 | 无法收到Worker心跳 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `The client detects that the worker is disconnected, socket fd: xxx` | UDS连接断开 | SDK自动切换到其他Worker |
| `Cannot receive heartbeat from worker.` | 首次心跳未收到 | 检查Worker状态 |
| `Heartbeat timeout, clientDeadTimeoutMs: xxx, elapsedMs: xxx` | 心跳超时 | 执行回调，切换Worker |

### 调用链
```
ListenWorker 首次心跳等待超时
  → return K_CLIENT_WORKER_DISCONNECT
    → object_client_impl.cpp::ProcessWorkerLost()
      → SwitchWorkerNode() 切换到其他Worker
```

---

## 2. Worker 退出检测（HealthCheck）

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `worker/object_cache/worker_oc_service_impl.cpp` | 355-375 | `HealthCheck` |
| `worker/object_cache/worker_oc_service_impl.cpp` | 369-372 | `CheckLocalNodeIsExiting` |

### 关键代码片段

```cpp
// worker_oc_service_impl.cpp:355-375
Status WorkerOCServiceImpl::HealthCheck(const HealthCheckRequestPb &req, HealthCheckReplyPb &resp)
{
    INJECT_POINT("worker.HealthCheck.begin");
    ReadLock noRecon;
    auto rc = ValidateWorkerState(noRecon, reqTimeoutDuration.CalcRemainingTime());
    if (rc.IsError()) {
        LOG(WARNING) << rc;
        return rc;
    }
    if (not req.client_id().empty()) {
        std::string tenantId;
        RETURN_IF_NOT_OK_PRINT_ERROR_MSG(worker::Authenticate(akSkManager_, req, tenantId), "Authenticate failed.");
    }
    (void)resp;
    if (etcdCM_ != nullptr && etcdCM_->CheckLocalNodeIsExiting()) {
        constexpr int logInterval = 60;
        LOG_EVERY_T(INFO, logInterval) << "[HealthCheck] Worker is exiting now";  // 行 371
        RETURN_STATUS(StatusCode::K_SCALE_DOWN, "Worker is exiting now");  // 行 372
    }
    return Status::OK();
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_SCALE_DOWN (31) | Worker退出中 | Worker正在退出，停止接收新请求 |
| K_SCALING (32) | 集群扩缩容中 | 集群正在扩缩容 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `[HealthCheck] Worker is exiting now` | Worker正在退出 | SDK等待Worker重新注册 |
| `K_SCALE_DOWN, Worker is exiting now` | 缩容退出 | 自动切换 |

### 调用链
```
Client 心跳请求
  → WorkerOCServiceImpl::HealthCheck
    → etcdCM_->CheckLocalNodeIsExiting() → true
      → return K_SCALE_DOWN ("Worker is exiting now")
        → Client 收到 K_SCALE_DOWN
          → 等待或切换Worker
```

---

## 3. 扩缩容 meta_is_moving 检测

### 代码路径
| 文件 | 说明 |
|------|------|
| `protos/master_object.proto` | meta_is_moving 字段定义 |
| `service/worker_oc_service_multi_publish_impl.cpp` | 扩缩容拒绝处理 |

### 关键代码片段

```protobuf
// master_object.proto
message CreateMultiMetaReqPb {
    repeated ObjectBaseInfoPb metas = 1;
    string address = 2;
    bool meta_is_moving = 4;  // 元数据正在迁移中
}

message MultiPublishReqPb {
    // ...
    bool meta_is_moving = 5;  // 元数据正在迁移中
}

message CreateMultiMetaPhaseTwoReqPb {
    repeated string object_keys = 1;
    string address = 2;
    bool meta_is_moving = 3;  // 元数据正在迁移中
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_SCALING (32) | 集群扩缩容中 | 拒绝服务，等待扩缩容完成 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `meta_is_moving = true` | 集群正在扩缩容 | 业务侧等待 + 重试 |
| `The cluster is scaling` | 扩缩容拒绝 | 等待后重试 |

---

## 4. etcd 心跳超时检测（Worker侧）

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `etcd_cluster_manager.cpp` | 897 | Node超时检测 |
| `replica_manager.cpp` | 1190 | IsKeepAliveTimeout |

### 关键代码片段

```cpp
// etcd_cluster_manager.cpp:897
if (accessor->second->IsFailed() || accessor->second->IsTimedOut()) {
    RETURN_STATUS(StatusCode::K_MASTER_TIMEOUT, "Disconnected from remote node " + nodeAddr.ToString());
}

// replica_manager.cpp:1190
CHECK_FAIL_RETURN_STATUS(!etcdStore_->IsKeepAliveTimeout(), K_RUNTIME_ERROR, "etcd is timeout");
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_MASTER_TIMEOUT (25) | Master超时 | etcd不可用或节点与etcd断开 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `Disconnected from remote node xxx` | 节点与etcd断开 | 检查etcd集群状态 |
| `etcd is timeout` | etcd保活超时 | 检查etcd进程和网络 |

---

## 5. SDK进程异常退出检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `client/listen_worker.cpp` | 103 | socket fd 断开回调 |

### 关键代码片段

```cpp
// listen_worker.cpp:103
LOG(INFO) << "The client detects that the worker is disconnected, socket fd: " << socketFd_;
workerAvailable_ = false;
RunAllCallback();  // 执行所有回调，包括 ProcessWorkerLost
```

### 恢复机制

| 故障模式 | 恢复方法 | 代码位置 |
|---------|---------|---------|
| K_CLIENT_WORKER_DISCONNECT | SDK自动切换到其他Worker | object_client_impl.cpp::SwitchWorkerNode |
| K_SCALE_DOWN | SDK等待Worker重新注册 | object_client_impl.cpp::ProcessWorkerLost |
| K_SCALING | 等待扩缩容完成 | 业务侧重试 |

---

## 6. 参数配置说明

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `node_timeout_s` | 60s | Worker节点超时时间 |
| `client_dead_timeout_s` | 120s | Client死亡超时时间 |
| `connectTimeoutMs` | - | 建链超时时间 |

---

## 7. 代码验证汇总

| 故障检测点 | 文件位置 | 行号 | 验证状态 | 日志关键字 |
|-----------|---------|------|---------|-----------|
| StartListenWorker | listen_worker.cpp | 100-118 | ✅ 已验证 | `Cannot receive heartbeat from worker` |
| CheckHeartbeat | listen_worker.cpp | 192-200 | ✅ 已验证 | `Heartbeat timeout, clientDeadTimeoutMs` |
| HealthCheck | worker_oc_service_impl.cpp | 355-375 | ✅ 已验证 | `[HealthCheck] Worker is exiting now` |
| CheckLocalNodeIsExiting | worker_oc_service_impl.cpp | 369-372 | ✅ 已验证 | `K_SCALE_DOWN, Worker is exiting now` |
| etcd超时检测 | replica_manager.cpp | 1190 | ✅ 已验证 | `etcd is timeout` |
| 节点断开检测 | etcd_cluster_manager.cpp | 897 | ✅ 已验证 | `Disconnected from remote node` |