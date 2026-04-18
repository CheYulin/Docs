# URMA / UMDK 依赖

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `umdk/src/urma/lib/urma/core/include/urma_opcode.h` | UMDK：`urma_status_t` 枚举 |
| `src/datasystem/common/rdma/urma_manager.cpp` | `UrmaManager`：封装 `ds_urma_*`、连接检查、CQ 轮询、事件处理 |
| `src/datasystem/common/rdma/urma_resource.cpp` | URMA context / jfce / jfc / jfs / jfr 创建与销毁 |
| `src/datasystem/common/rdma/rdma_util.h` | `Event::WaitFor` / `EventWaiter::WaitAny`（数据面等待原语）|
| `src/datasystem/common/rdma/urma_dlopen_util.cpp` | UMDK `urma_*` 动态加载 |
| `src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp` | `PrepareUrmaBuffer` / `FillUrmaBuffer` |
| `src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp` | `UrmaWritePayload` 远端写 |
| `src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp` | `TryReconnectRemoteWorker` |
| `include/datasystem/utils/status.h` | `K_URMA_*` 错误码 |

数据系统通过 `#include <ub/umdk/urma/urma_api.h>` 使用 URMA；以 **构建环境安装的 UMDK 头文件为准**。

---

## 1. UMDK `urma_status_t` 枚举

**来源**：`umdk/src/urma/lib/urma/core/include/urma_opcode.h`

```c
typedef int urma_status_t;
#define URMA_SUCCESS     0
#define URMA_EAGAIN      EAGAIN      // Resource temporarily unavailable
#define URMA_ENOMEM      ENOMEM      // Failed to allocate memory
#define URMA_ENOPERM     EPERM       // Operation not permitted
#define URMA_ETIMEOUT    ETIMEDOUT   // Operation time out
#define URMA_EINVAL      EINVAL      // Invalid argument
#define URMA_EEXIST      EEXIST      // Exist
#define URMA_EINPROGRESS EINPROGRESS
#define URMA_FAIL        0x1000
```

| 枚举 | 值 | 含义 |
|-----|---:|------|
| `URMA_SUCCESS` | 0 | 成功 |
| `URMA_EAGAIN` | `EAGAIN (11)` | 资源暂不可用，可重试 |
| `URMA_ENOMEM` | `ENOMEM (12)` | 内存分配失败 |
| `URMA_ENOPERM` | `EPERM (1)` | 操作不允许 / 权限不足 |
| `URMA_ETIMEOUT` | `ETIMEDOUT (110)` | 操作超时 |
| `URMA_EINVAL` | `EINVAL (22)` | 参数非法 |
| `URMA_EEXIST` | `EEXIST (17)` | 已存在 / 重复 |
| `URMA_EINPROGRESS` | `EINPROGRESS (115)` | 处理中（异步阶段常见） |
| `URMA_FAIL` | `0x1000` | URMA 通用失败（非标准 errno） |

---

## 2. 数据系统 URMA 错误码

`include/datasystem/utils/status.h` 中 RPC / URMA 段 `[1000, 2000)`：

| 码 | 枚举 | 含义 |
|----|------|------|
| 1004 | `K_URMA_ERROR` | URMA 操作失败（驱动、资源、语义失败等）|
| 1005 | `K_RDMA_ERROR` | RDMA 变体 |
| 1006 | `K_URMA_NEED_CONNECT` | 会话需重建 / 重连 |
| 1007 | `K_RDMA_NEED_CONNECT` | RDMA 变体 |
| 1008 | `K_URMA_TRY_AGAIN` | 可重试的瞬时失败 |
| **1009** | `K_URMA_CONNECT_FAILED` | URMA 建连失败（新增，见 [`../../../rfc/2026-04-kvclient-urma-tcp-observability/`](../../../rfc/2026-04-kvclient-urma-tcp-observability/README.md)） |
| **1010** | `K_URMA_WAIT_TIMEOUT` | URMA 完成事件等待超时（新增） |

错误码的分层视图见 [`../../reliability/03-status-codes.md § 2`](../../reliability/03-status-codes.md)。

---

## 3. 数据系统中实际的 URMA error 日志

来自 `urma_manager.cpp` 源码 grep。

### 3.1 初始化与资源创建阶段

- `Failed to urma init, ret = %d`
- `Failed to urma uninit, ret = %d`
- `Failed to urma register log, ret = %d`
- `Failed to urma get device by name, errno = %d`
- `Failed to urma query device, ret = %d`
- `Failed to urma get eid list, errno = %d`
- `Failed to urma create context, errno = %d`
- `Failed to urma create jfce/jfc/jfs/jfr, errno = %d`

代码证据：

```cpp
// urma_manager.cpp:345
urma_init_attr_t urmaInitAttribute = { 0, 0 };
urma_status_t ret = ds_urma_init(&urmaInitAttribute);
if (ret != URMA_SUCCESS) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to urma init, ret = %d", ret));
}
```

### 3.2 CQ / 事件与轮询阶段

- `Failed to poll jfc`
- `Failed to wait jfc, ret = %d`
- `Failed to poll jfc, ret = %d, CR.status = %d`
- `Failed to rearm jfc, status = %d`
- `Polling failed with an error for requestId: %d`

代码证据（`poll jfc` 失败和 CR 状态）：

```cpp
// urma_manager.cpp:793
LOG(ERROR) << FormatString("Failed to poll jfc requestId: %d CR.status: %d", userCtx, crStatus);
failedCompletedReqs[completeRecords[i].user_ctx] = crStatus;

if (!failedCompletedReqs.empty()) {
    RETURN_STATUS(K_URMA_ERROR, "Failed to poll jfc");
}
```

```cpp
// urma_manager.cpp:831
if (cnt < 0) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to poll jfc, ret = %d, CR.status = %d", cnt,
                                                       completeRecords[0].status));
}

auto status = ds_urma_rearm_jfc(urmaJfc, false);
if (status != URMA_SUCCESS) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to rearm jfc, status = %d", status));
}
```

### 3.3 导入 / 握手与数据面阶段

- `Failed to import jfr, ...`
- `Failed to advise jfr`
- `Failed to urma write object ..., ret = %d`
- `Failed to urma read object ..., ret = %d`

### 3.4 连通性检查（非 OS，属 URMA 逻辑）

`CheckUrmaConnectionStable` 返回 `K_URMA_NEED_CONNECT`：

```cpp
// urma_manager.cpp:1294
Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
{
    ...
    if (!res) {
        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
    }
    ...
    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect has disconnected and needs to be reconnected!");
    ...
    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");
}
```

### 3.5 JFS 重建策略（`CR.status=9` ACK timeout）

```cpp
// urma_manager.cpp:57
UrmaErrorHandlePolicy GetUrmaErrorHandlePolicy(int statusCode)
{
    static std::unordered_map<int, UrmaErrorHandlePolicy> urmaErrorHandlePolicyTable = {
        { 9, UrmaErrorHandlePolicy::RECREATE_JFS },
    };
    ...
}
```

```cpp
// urma_manager.cpp:723
const auto statusCode = event->GetStatusCode();
const auto policy = GetUrmaErrorHandlePolicy(statusCode);
...
if (policy == UrmaErrorHandlePolicy::RECREATE_JFS) {
    ...
    LOG_IF_ERROR(connection->ReCreateJfs(*urmaResource_, oldJfs),
                 FormatString("Recreate JFS for requestId: %d failed", requestId));
}
return Status(K_URMA_ERROR, errMsg);
```

---

## 4. 当前代码处理路径（简表）

| 场景 | 内部码 | 处理方式 |
|------|--------|----------|
| `ds_urma_*` 调用失败（init / query / create / poll / wait / rearm）| `K_URMA_ERROR(1004)` | 返回错误并打日志 |
| URMA 连接不稳定 / 无连接 | `K_URMA_NEED_CONNECT(1006)` | 返回"需重连"；外层 `TryReconnectRemoteWorker` 转 `K_TRY_AGAIN` 后重试 |
| URMA wait 超时 | `K_URMA_WAIT_TIMEOUT(1010)`（新）| `Event::WaitFor` 超时返回；不再与 `K_RPC_DEADLINE_EXCEEDED` 混淆 |
| URMA 建连失败 | `K_URMA_CONNECT_FAILED(1009)`（新）| 显式区分于其它 1004 场景 |
| 部分读写数据面失败 | `K_RUNTIME_ERROR(5)` | 返回运行时错误并打日志 |
| 客户端读路径 UB 准备失败 | 不直接上抛 URMA 码 | WARNING 后降级 TCP payload |

### 4.1 UB 降级（核心行为）

```cpp
// src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp
void ClientWorkerBaseApi::PrepareUrmaBuffer(...)
{
    if (IsUrmaEnabled() && !shmEnabled_) {
        Status ubRc = UrmaManager::Instance().GetMemoryBufferHandle(ubBufferHandle);
        ...
        if (ubRc.IsError()) {
            LOG(WARNING) << "Prepare UB Get request failed: " << ubRc.ToString()
                         << ", fallback to TCP/IP payload.";
            ubBufferHandle.reset();
            ...
        }
    }
}
```

**含义**：客户端 UB 缓冲准备失败时**不向上返回错误**；改走 TCP payload，**功能仍可能成功但性能可能退化**。定位时看 WARNING 而非 Status 码。

---

## 5. URMA 三码的重连语义（与 reliability 对照）

```text
K_URMA_NEED_CONNECT (1006)
    → TryReconnectRemoteWorker → transport exchange
    → 成功后返回 K_TRY_AGAIN("Reconnect success")
    → 外层 RetryOnError 继续重试
K_URMA_TRY_AGAIN (1008)  瞬时可恢复，RECREATE_JFS 等策略
K_URMA_ERROR    (1004)   持久错误；驱动 / 资源 / 语义失败
```

详细证据链见 [`../../reliability/04-fault-tree.md § 2.2`](../../reliability/04-fault-tree.md)。

---

## 6. 上下游语义要求（URMA 与 TCP 并存时）

### 6.1 路径选择

| 条件 | 路径 |
|------|------|
| `shmEnabled_ == true` | 客户端走本机 SHM，不走 UB |
| `shmEnabled_ == false && USE_URMA` | 客户端 UB；UB 池准备失败 WARNING → TCP payload |
| `!USE_URMA` | TCP payload |

### 6.2 跨机远端读

- 客户端 `PrepareUrmaBuffer` 成功 → 请求带 `urma_info`
- Worker 侧 `CheckUrmaConnectionStable` 确认连接 → `UrmaWritePayload` 写对端 SHM → `rsp.data_source = DATA_ALREADY_TRANSFERRED`
- 客户端 `FillUrmaBuffer` 把 UB 内存封进 `payloads`

### 6.3 请求时连接状态检查

`CheckUrmaConnectionStable` 对 `(hostAddress, instanceId)` 做检查：

- 无连接 → `K_URMA_NEED_CONNECT, "No existing connection requires creation."`
- instanceId 不匹配 → `K_URMA_NEED_CONNECT, "Urma connect has disconnected and needs to be reconnected!"`
- 其它不稳定 → `K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!"`

三条日志可直接 grep 定位。

---

## 7. 使用建议

- 枚举值解释优先查 `umdk/.../urma_opcode.h`
- 故障定界优先看 `urma_manager.cpp` 的 error 日志关键词与内部码映射
- 遇到 `1006` 先按"重连"路径处理，不要误归类成 OS `connect()` 问题
- **bonding 多端口**：代码在 UB 模式下若配置设备名不在列表中，会尝试匹配 `bonding` 前缀设备

---

## 8. 外部资料

- [openeuler-mirror/umdk](https://github.com/openeuler-mirror/umdk)（含 `urma.spec`、头文件树）
- [Gitee openEuler umdk PR 讨论](https://gitee.com/openeuler/umdk/pulls/1.diff?skip_mobile=true)

本材料**不臆造** `urma_*` 的逐条 errno；代码未记录处标注"查 UMDK 头文件与厂商手册"。
