# OS / syscall 依赖

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/util/fd_pass.cpp` | `SockRecvFd` / `SockSendFd`（`sendmsg/recvmsg` + `SCM_RIGHTS`）|
| `src/datasystem/common/rpc/unix_sock_fd.cpp` | `UnixSockFd::ErrnoToStatus`（errno → `StatusCode`）|
| `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | ZMQ socket 收发（含 errno 捕获与 metrics）|
| `src/datasystem/common/util/file_util.cpp` | `ReadFile` / `WriteFile`（`pread` / `pwrite` 封装）|
| `src/datasystem/client/mmap_manager.cpp` | `mmap` / `munmap` / `MmapShmUnit` |
| `src/datasystem/common/rdma/urma_manager.cpp` | `mmap(MAP_ANONYMOUS)` UB 匿名池 |

---

## 1. 本项目用到的 syscall 全量清单

| syscall / OS 接口 | 主要位置 | 关联流程 |
|------------------|----------|----------|
| `sendmsg` / `recvmsg` | `common/util/fd_pass.cpp` | Init UDS 传 fd、读路径 SHM 回数 |
| `close` | `fd_pass.cpp`；`client_worker_common_api.cpp` | fd 生命周期 |
| `mmap` / `munmap` | `urma_manager.cpp`（UB 匿名池）；`object_client_impl.cpp`（SHM 映射）| UB 缓冲池、SHM |
| `socket` / `connect` | `client_worker_common_api.cpp` | Init 建连 |
| `usleep(0)` | `urma_manager.cpp::PollJfcWait` | URMA poll 等待（让出 CPU） |
| `memcpy` | `client_worker_base_api.cpp`；`object_client_impl.cpp` | payload / UB 组装 |
| `open` / `pwrite` / `fsync` / `pread` | Worker 侧落盘路径；`file_util.cpp` | MCreate 持久化、L2 缓存 |
| `epoll_wait` / `epoll_ctl` | ZMQ 框架内 | socket 多路复用 |

---

## 2. errno → StatusCode 映射

### 2.1 `UnixSockFd::ErrnoToStatus`

`src/datasystem/common/rpc/unix_sock_fd.cpp`：

| errno | 映射到 | 日志文案 |
|-------|-------|---------|
| `ECONNRESET` | `K_RPC_UNAVAILABLE` | `Connect reset. fd %d. err %s` |
| `EPIPE` | `K_RPC_UNAVAILABLE` | 同上 |
| `EAGAIN` / `EWOULDBLOCK` | `K_TRY_AGAIN` | `Socket receive error. err EAGAIN/...` |
| 其它 | 按上下文映射 `K_UNKNOWN_ERROR / K_RUNTIME_ERROR` | — |

### 2.2 ZMQ 层的 errno 追踪

`zmq_socket_ref.cpp` 在 `rc == -1` 分支记录 errno 到 metric `ZMQ_LAST_ERROR_NUMBER`（Gauge），并按 `zmq_network_errno.h` 判定是否为网络类 → 增加 `ZMQ_NETWORK_ERROR_TOTAL` counter。

详见 [`../05-metrics-and-perf.md § 1`](../05-metrics-and-perf.md)。

---

## 3. fd 传递（SCM_RIGHTS）典型失败

### 3.1 SDK 侧（`PostRegisterClient` / `RecvPageFd`）

`src/datasystem/common/util/fd_pass.cpp::SockRecvFd`：

| 失败 | 返回码 | 日志 |
|------|-------|------|
| `recvmsg` 异常 | `K_UNKNOWN_ERROR` | `Pass fd meets unexpected error: errno` |
| 非法 fd | `K_UNKNOWN_ERROR` | `We receive the invalid fd` |
| 空 fd | （仅 WARNING，不返错）| `may exceed the max open fd limit` |

**特点**：`GetClientFd` 主流程 **不重试**；失败常在后续 `mmap` 阶段暴露为 `K_RUNTIME_ERROR` + `Get mmap entry failed`。

### 3.2 Worker 侧

`SockSendFd` 失败常见于：

- UDS 对端已关闭
- 对方进程 fd 上限
- 权限错误（如 SELinux）

---

## 4. `mmap` 典型失败

### 4.1 客户端 UB 匿名内存池

`urma_manager.cpp::InitMemoryBufferPool` 中 `mmap(MAP_PRIVATE|MAP_ANONYMOUS)` 失败：

- 返回：`K_OUT_OF_MEMORY(6)`
- 日志：`Failed to allocate memory buffer pool for client`
- 责任：L1（平台：容器 / 宿主 / 大页配额）+ L3（SDK 分配策略）

### 4.2 客户端 SHM 映射

`object_client_impl.cpp::MmapShmUnit`：

```cpp
Status ObjectClientImpl::MmapShmUnit(...)
{
    ...
    RETURN_IF_NOT_OK(mmapManager_->LookupUnitsAndMmapFd("", shmBuf));
    mmapEntry = mmapManager_->GetMmapEntryByFd(shmBuf->fd);
    CHECK_FAIL_RETURN_STATUS(mmapEntry != nullptr, StatusCode::K_RUNTIME_ERROR, "Get mmap entry failed");
}
```

失败原因：

- fd 无效或已被关闭
- 未在 mmap 表中注册
- 内核限制（`vm.max_map_count` 等）

---

## 5. 文件 I/O 典型失败

### 5.1 `pread / pwrite`

`src/datasystem/common/util/file_util.cpp`：

- 失败统一返回 `K_IO_ERROR` + errno 细节
- `WriteFile` 有恢复日志：失败后 `WriteFile failed...`，恢复后 `WriteFile success again`

### 5.2 spill 空间不足

`src/datasystem/worker/object_cache/worker_oc_spill.cpp`：

```cpp
RETURN_STATUS(K_NO_SPACE, "No space when WorkerOcSpill::Spill");
```

详细 L2 / 二级存储错误见 [`secondary-storage.md`](secondary-storage.md)。

---

## 6. 关键 syscall 在 FEMA 中的责任域

| 失败类别 | 责任域 | 排查方向 |
|---------|--------|---------|
| `sendmsg / recvmsg` / `SCM_RIGHTS` fd 传递 | **OS** + SDK / Worker 衔接 | 对端进程、权限、ulimit、SELinux |
| `mmap` / `munmap` | **OS** 资源 | 内存配额、大页、`vm.max_map_count` |
| `socket` / `connect` | L1 网络 | 网络策略、DNS、端口 |
| `pread / pwrite / fsync` | L1 磁盘 | 磁盘健康、空间、权限 |
| `epoll_ctl` | 框架层 | ZMQ / bthread 内部问题（见 [`../../reliability/deep-dives/client-lock-rpc-logging.md`](../../reliability/deep-dives/client-lock-rpc-logging.md)） |

---

## 7. 日志关键字

| 关键字 | 场景 | 相关 FM |
|--------|------|---------|
| `recvmsg` / `sendmsg` | fd 传递失败 | FM-006 |
| `mmap` / `invalid fd` | 共享内存映射失败 | FM-016 |
| `Unexpected EOF read` | UDS 对端关闭 | FM-006 |
| `Get mmap entry failed` | SHM mmap 表查不到 | FM-016 |
| `memory buffer pool` | UB 匿名池 mmap 失败 | FM-004 |
| `Connect reset` / `EPIPE` | socket 被重置 | 1002 桶码（详见 `../reliability/06-playbook.md § 2`） |
| `Network unreachable` | ZMQ POLLOUT 不可写 | 同上 |

FEMA 故障编号见 [`../03-fault-mode-library.md`](../03-fault-mode-library.md)。
