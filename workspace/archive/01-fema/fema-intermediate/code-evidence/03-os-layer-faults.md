# 代码证据：OS 层故障检测与定位

## 1. etcd 不可用检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `replica_manager.cpp` | 1190 | IsKeepAliveTimeout |
| `etcd_cluster_manager.cpp` | 897 | Node超时检测 |

### 关键代码片段

```cpp
// replica_manager.cpp:1190
CHECK_FAIL_RETURN_STATUS(!etcdStore_->IsKeepAliveTimeout(), K_RUNTIME_ERROR, "etcd is timeout");

// etcd_cluster_manager.cpp:897
if (accessor->second->IsFailed() || accessor->second->IsTimedOut()) {
    RETURN_STATUS(StatusCode::K_MASTER_TIMEOUT, "Disconnected from remote node " + nodeAddr.ToString());
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_MASTER_TIMEOUT (25) | Master超时 | etcd不可用或节点与etcd断开 |
| K_RUNTIME_ERROR (7) | 运行时错误 | etcd超时 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `etcd is timeout` | etcd保活超时 | 检查etcd集群状态 |
| `Disconnected from remote node xxx` | 节点与etcd断开 | 检查etcd进程和网络 |

### 调用链
```
Worker 运行中
  → etcdStore_->IsKeepAliveTimeout() → true
    → return K_RUNTIME_ERROR ("etcd is timeout")
      → 集群管理功能不可用

Worker 心跳
  → etcdCM_->CheckLocalNodeIsExiting()
    → accessor->second->IsTimedOut() → true
      → return K_MASTER_TIMEOUT ("Disconnected from remote node")
```

---

## 2. mmap 失败检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `object_client_impl.cpp` | 1509, 1807, 2150, 2967 | mmapEntry 获取 |
| `urma_manager.cpp` | 266-274 | UB 匿名内存池分配 |

### 关键代码片段

```cpp
// object_client_impl.cpp:1509
CHECK_FAIL_RETURN_STATUS(mmapEntry != nullptr, StatusCode::K_RUNTIME_ERROR, "Get mmap entry failed");

// urma_manager.cpp:266-274 (客户端 UB 匿名内存池)
auto hostAllocFunc = [this](void **ptr, size_t maxSize) -> Status {
    memoryBuffer_ = mmap(nullptr, maxSize, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    *ptr = memoryBuffer_;
    if (memoryBuffer_ == MAP_FAILED) {
        RETURN_STATUS(K_OUT_OF_MEMORY, "Failed to allocate memory buffer pool for client");
    }
    RETURN_IF_NOT_OK(RegisterSegment(reinterpret_cast<uint64_t>(*ptr), maxSize));
    return Status::OK();
};
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_RUNTIME_ERROR (7) | 运行时错误 | mmap entry 获取失败 |
| K_OUT_OF_MEMORY (6) | 内存不足 | UB 内存池分配失败 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `Get mmap entry failed` | mmap entry 获取失败 | 检查共享内存状态 |
| `Failed to allocate memory buffer pool for client` | UB内存池分配失败 | 检查内存是否充足 |

---

## 3. RPC 超时检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `worker_oc_service_get_impl.cpp` | 153-157 | RPC超时判断 |

### 关键代码片段

```cpp
// worker_oc_service_get_impl.cpp:153-157
if (elapsed >= timeout) {
    LOG(ERROR) << "RPC timeout. time elapsed " << elapsed << ", subTimeout:" << subTimeout
               << ", get threads Statistics: " << threadPool_->GetStatistics();
    LOG_IF_ERROR(serverApi->SendStatus(Status(K_RUNTIME_ERROR, "Rpc timeout")), "Send status failed");
} else {
    reqTimeoutDuration.Init(timeout - elapsed);
    // ...
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_RUNTIME_ERROR (7) | 运行时错误 | RPC超时 |
| K_RPC_DEADLINE_EXCEEDED (19) | RPC超时 | RPCdeadline exceeded |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `RPC timeout. time elapsed xxx, subTimeout:xxx` | RPC超时 | 检查网络和Worker状态 |
| `Process Get done, clientId: xxx, objectKeys: xxx, subTimeout: xxx` | 正常完成 | - |

---

## 4. ZMQ 连接异常检测

### 代码路径
| 文件 | 行号 | 函数 |
|------|------|------|
| `urma_manager.cpp` | 1385-1413 | CheckUrmaConnectionStable |

### 关键代码片段

```cpp
// urma_manager.cpp:1385-1413 - ZMQ/UDS 连接检测
Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
{
    TbbUrmaConnectionMap::const_accessor constAccessor;
    auto res = urmaConnectionMap_.find(constAccessor, hostAddress);
    if (!res) {
        LOG_FIRST_AND_EVERY_N(WARNING, K_URMA_WARNING_LOG_EVERY_N)
            << "[URMA_NEED_CONNECT] No existing connection for remoteAddress: " << hostAddress;
        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
    }
    // ...
}
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_URMA_NEED_CONNECT (1006) | 连接需重建 | ZMQ连接不存在或不稳定 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `[URMA_NEED_CONNECT] No existing connection` | ZMQ连接不存在 | 新建连接 |
| `[URMA_NEED_CONNECT] Connection stale` | ZMQ连接过时需重建 | 重建连接 |

---

## 5. 文件 IO 错误检测

### 代码路径
| 文件 | 说明 |
|------|------|
| `file_util.cpp` | pread/pwrite IO错误 |
| `worker_oc_spill.cpp` | spill空间不足 |

### 关键代码片段

```cpp
// file_util.cpp - pread/pwrite 返回值检测
// IO错误 → K_IO_ERROR (7)

// worker_oc_spill.cpp - spill空间不足
// 空间不足 → K_NO_SPACE (13)
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_IO_ERROR (7) | IO错误 | 文件读写失败 |
| K_NO_SPACE (13) | 空间不足 | 磁盘空间满 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `K_IO_ERROR` | IO错误 | 检查磁盘状态 |
| `No space` | 空间不足 | 清理磁盘或扩容 |

---

## 6. Network Loss / SCM_RIGHTS fd 传递异常

### 代码路径
| 文件 | 说明 |
|------|------|
| `unix_sock_fd.cpp::ErrnoToStatus` | ECONNRESET/EPIPE 检测 |
| `client_worker_common_api.cpp` | mustUds && !isConnectSuccess |

### 关键代码片段

```cpp
// unix_sock_fd.cpp::ErrnoToStatus
// ECONNRESET/EPIPE → 连接重置

// client_worker_common_api.cpp
// mustUds && !isConnectSuccess → 共享内存通道建立失败
```

### 错误码映射
| 错误码 | 名称 | 说明 |
|--------|------|------|
| K_CLIENT_WORKER_DISCONNECT (23) | 连接断开 | fd传递失败 |
| K_URMA_NEED_CONNECT (1006) | 连接需重建 | SCM_RIGHTS传递失败 |

### 定位定界日志
| 日志关键字 | 含义 | 处理建议 |
|-----------|------|---------|
| `Connect reset` | 连接重置 | 检查网络状态 |
| `invalid fd` | 无效fd | 检查共享内存状态 |
| `shm fd transfer` | fd传递失败 | 重连重建通道 |

---

## 7. 恢复机制汇总

| 故障模式 | 错误码 | 恢复方法 | 代码位置 |
|---------|--------|---------|---------|
| etcd 超时 | 25/7 | 等待 + 路由更新 | replica_manager.cpp |
| mmap 失败 | 7/6 | 降级到 TCP | fast_transport_manager_wrapper.cpp |
| RPC 超时 | 7/19 | 重试 + 降级到 L2Cache | worker_oc_service_get_impl.cpp |
| ZMQ 连接异常 | 1006 | 重建连接 | TryReconnectRemoteWorker |
| 文件 IO 错误 | 7/13 | 记录日志 + 降级 | file_util.cpp |

---

## 8. 故障域定位表

| 故障域 | 错误码范围 | 典型日志关键字 |
|--------|-----------|---------------|
| **用户错误** | 2-3 | `Invalid` / `Key not found` |
| **OS层** | 6-7, 13, 19-20, 25, 1001 | `etcd is timeout` / `RPC timeout` / `No space` / `Get mmap entry failed` |
| **URMA层** | 1004, 1006, 1008 | `[URMA_NEED_CONNECT]` / `[URMA_RECREATE_JFS]` / `Failed to urma init` |
| **组件层** | 23, 31, 32 | `Cannot receive heartbeat` / `Worker is exiting now` / `The cluster is scaling` |
| **内部错误** | 19 | `data inconsistent` / `UB payload overflow` |

---

## 9. 代码验证汇总

| 故障检测点 | 文件位置 | 行号 | 验证状态 | 日志关键字 |
|-----------|---------|------|---------|-----------|
| etcd超时 | replica_manager.cpp | 1190 | ✅ 已验证 | `etcd is timeout` |
| 节点断开 | etcd_cluster_manager.cpp | 897 | ✅ 已验证 | `Disconnected from remote node` |
| mmap失败 | object_client_impl.cpp | 1509, 1807, 2150 | ✅ 已验证 | `Get mmap entry failed` |
| 首心跳超时 | listen_worker.cpp | 114 | ✅ 已验证 | `Cannot receive heartbeat from worker` |
| Worker退出 | worker_oc_service_impl.cpp | 371 | ✅ 已验证 | `[HealthCheck] Worker is exiting now` |
| URMA_NEED_CONNECT | urma_manager.cpp | 1385-1413 | ✅ 已验证 | `[URMA_NEED_CONNECT] No existing connection` |
| TryReconnect | worker_oc_service_get_impl.cpp | 947 | ✅ 已验证 | `[URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered` |
| UB降级TCP | client_worker_base_api.cpp | 118, 132 | ✅ 已验证 | `fallback to TCP/IP payload` |
| SHM_metrics | kv_metrics.cpp | 70 | ✅ 已验证 | `worker_shm_ref_table_bytes` |