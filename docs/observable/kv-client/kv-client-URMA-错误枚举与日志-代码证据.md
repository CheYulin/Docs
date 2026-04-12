# KV Client：URMA 错误枚举与 error 日志（代码证据版）

本页单独回答两个问题：

1. **UMDK/URMA 的错误枚举值有哪些**（以本地头文件为准）  
2. **数据系统当前实际打出的 URMA error 日志有哪些**（以源码检索为准）

---

## 1) UMDK 中 `urma_status_t` 的错误枚举

来源文件：`umdk/src/urma/lib/urma/core/include/urma_opcode.h`

代码证据片段：

```126:135:/home/t14s/workspace/git-repos/umdk/src/urma/lib/urma/core/include/urma_opcode.h
typedef int urma_status_t;
#define URMA_SUCCESS     0
#define URMA_EAGAIN      EAGAIN    // Resource temporarily unavailable
#define URMA_ENOMEM      ENOMEM    // Failed to allocate memory
#define URMA_ENOPERM     EPERM     // Operation not permitted
#define URMA_ETIMEOUT    ETIMEDOUT // Operation time out
#define URMA_EINVAL      EINVAL    // Invalid argument
#define URMA_EEXIST      EEXIST    // Exist
#define URMA_EINPROGRESS EINPROGRESS
#define URMA_FAIL        0x1000 /* 0x1000 */
```

| 枚举 | 值 | 含义 |
|---|---:|---|
| `URMA_SUCCESS` | `0` | 成功 |
| `URMA_EAGAIN` | `EAGAIN (11)` | 资源暂不可用，可重试 |
| `URMA_ENOMEM` | `ENOMEM (12)` | 内存分配失败 |
| `URMA_ENOPERM` | `EPERM (1)` | 操作不允许/权限不足 |
| `URMA_ETIMEOUT` | `ETIMEDOUT (110)` | 操作超时 |
| `URMA_EINVAL` | `EINVAL (22)` | 参数非法 |
| `URMA_EEXIST` | `EEXIST (17)` | 已存在/重复 |
| `URMA_EINPROGRESS` | `EINPROGRESS (115)` | 处理中（异步阶段常见） |
| `URMA_FAIL` | `0x1000` | URMA 通用失败（非标准 errno） |

说明：
- `urma_status_t` 在头文件中是 `int`。
- 上述枚举是 **当前仓库中的 UMDK 头文件定义**，优先级高于外部二手整理。

---

## 2) 数据系统中已确认存在的 URMA error 日志（源码证据）

来源文件：`yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp`

### 2.1 初始化与资源创建阶段

- `Failed to urma init, ret = %d`
- `Failed to urma uninit, ret = %d`
- `Failed to urma register log, ret = %d`
- `Failed to urma get device by name, errno = %d`
- `Failed to urma query device, ret = %d`
- `Failed to urma get eid list, errno = %d`
- `Failed to urma create context, errno = %d`
- `Failed to urma create jfce/jfc/jfs/jfr, errno = %d`

代码证据片段：

```345:360:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
urma_init_attr_t urmaInitAttribute = { 0, 0 };
urma_status_t ret = ds_urma_init(&urmaInitAttribute);
if (ret != URMA_SUCCESS) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to urma init, ret = %d", ret));
}
...
urma_status_t ret = ds_urma_uninit();
if (ret != URMA_SUCCESS) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to urma uninit, ret = %d", ret));
}
```

### 2.2 CQ/事件与轮询阶段

- `Failed to poll jfc`
- `Failed to wait jfc, ret = %d`
- `Failed to poll jfc, ret = %d, CR.status = %d`
- `Failed to rearm jfc, status = %d`
- `Polling failed with an error for requestId: %d`

代码证据片段（`poll jfc` 失败和 CR 状态）：

```793:800:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
LOG(ERROR) << FormatString("Failed to poll jfc requestId: %d CR.status: %d", userCtx, crStatus);
failedCompletedReqs[completeRecords[i].user_ctx] = crStatus;
...
if (!failedCompletedReqs.empty()) {
    RETURN_STATUS(K_URMA_ERROR, "Failed to poll jfc");
}
```

```831:843:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
if (cnt < 0) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to poll jfc, ret = %d, CR.status = %d", cnt,
                                                       completeRecords[0].status));
}
...
auto status = ds_urma_rearm_jfc(urmaJfc, false);
if (status != URMA_SUCCESS) {
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to rearm jfc, status = %d", status));
}
```

### 2.3 导入/握手与数据面阶段

- `Failed to import jfr, ...`
- `Failed to advise jfr`
- `Failed to urma write object ..., ret = %d`
- `Failed to urma read object ..., ret = %d`

### 2.4 连通性检查（非 OS，属于 URMA 逻辑）

- `K_URMA_NEED_CONNECT` 返回：
  - `No existing connection requires creation.`
  - `Urma connect unstable, need to reconnect!`

对应函数：`CheckUrmaConnectionStable(...)`

代码证据片段（返回 `K_URMA_NEED_CONNECT`）：

```1294:1309:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
Status UrmaManager::CheckUrmaConnectionStable(const std::string &hostAddress, const std::string &instanceId)
{
    ...
    if (!res) {
        RETURN_STATUS(K_URMA_NEED_CONNECT, "No existing connection requires creation.");
    }
    ...
    RETURN_STATUS(K_URMA_NEED_CONNECT, "Urma connect unstable, need to reconnect!");
}
```

补充：`CR.status=9`（`URMA_CR_ACK_TIMEOUT_ERR`）当前处理策略

```57:68:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
UrmaErrorHandlePolicy GetUrmaErrorHandlePolicy(int statusCode)
{
    static std::unordered_map<int, UrmaErrorHandlePolicy> urmaErrorHandlePolicyTable = {
        { 9, UrmaErrorHandlePolicy::RECREATE_JFS },
    };
    ...
}
```

```723:739:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
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

## 3) 当前代码里的错误处理路径（简表）

| 场景 | 常见内部码 | 处理方式 |
|---|---|---|
| `urma_*` 调用失败（init/query/create/poll/wait/rearm） | `K_URMA_ERROR(1004)` | 返回错误并打日志 |
| URMA 连接不稳定/无连接 | `K_URMA_NEED_CONNECT(1006)` | 返回“需重连” |
| 部分读写数据面失败 | `K_RUNTIME_ERROR(5)` | 返回运行时错误并打日志 |
| 客户端读路径 UB 准备失败 | 不直接上抛 URMA 码 | warning 后降级 TCP payload |

补充证据（客户端降级日志）：
- 文件：`yuanrong-datasystem/src/datasystem/client/object_cache/client_worker_api/client_worker_base_api.cpp`
- 日志：`Prepare UB Get request failed: ... fallback to TCP/IP payload.`

---

## 4) 使用建议

- 枚举值解释优先查 `umdk/.../urma_opcode.h`。  
- 故障定界优先看 `urma_manager.cpp` 的 error 日志关键词与内部码映射。  
- 遇到 `1006` 先按“重连”路径处理，不要误归类成 OS `connect()` 问题。

