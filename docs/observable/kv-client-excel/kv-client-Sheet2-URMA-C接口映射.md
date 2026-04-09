# Sheet2：URMA C API ↔ 数据系统映射（有据部分 + UMDK 缺口说明）

> 与 Excel **`Sheet2_URMA_C_API`** 同主题。本页强调：**能写清的只写代码里出现的返回值/日志**；**未在代码出现的不编 errno**。

## 1. 头文件与状态码来源（外部依据）

- 源码：`#include <ub/umdk/urma/urma_api.h>`（见 `urma_manager.cpp`）。
- **`urma_status_t` / `URMA_SUCCESS` 的完整取值**以 **交付镜像/编译环境中 UMDK 开发包** 为准；公开 URL 对 `urma_api.h` 的在线 raw **不稳定**，本材料 **不逐条抄录枚举**（避免与你们现场版本漂移）。

## 2. 数据系统中的两类「错误载体」

| 类型 | 出现位置 | 含义 |
|------|----------|------|
| **`urma_status_t ret`** | `urma_init`、`urma_query_device`、`urma_rearm_jfc`、`urma_write` 等 | UMDK 返回的业务状态，**不是** Linux `errno` |
| **`errno`** | `urma_get_device_by_name` 失败分支、`urma_create_context` 返回空指针等 | 部分 API **在失败时记录 `errno`**（见日志 `FormatString(..., errno)`） |

因此 Excel/Markdown 列 **「errno」** 在多数行应为 **「不适用」或「见 ret」**；只有代码显式打印 `errno` 的才填。

## 3. bonding / 多端口（RM CTP + bonding 设备）

UB 模式下若配置的设备名不在设备列表中，会尝试匹配名前缀为 **`bonding`** 的设备并 **改写 `urmaDevName`**：

```341:359:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
Status UrmaManager::UrmaGetEffectiveDevice(std::string &urmaDevName)
{
    ...
    list = urma_get_device_list(&devNums);
    if (list == nullptr) {
        RETURN_STATUS_LOG_ERROR(K_RUNTIME_ERROR,
                                FormatString("Got empty[%d] ub device list with errno = %d", devNums, errno));
    }
    int index = CompareDeviceName(urmaDevName, list, devNums);
    ...
    std::string prefixName = "bonding";
    index = CompareDeviceName(prefixName, list, devNums);
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(index >= 0, K_RUNTIME_ERROR, "Cannot get effective bonding device");
    urmaDevName = std::string(list[index]->name);
    return Status::OK();
}
```

**评审要点**：集成方需保证 **`DS_URMA_DEV_NAME` / 环境变量** 与 **`urma_get_device_list` 可见设备名**一致；bonding 仅为 **代码内回退策略**，非所有现场适用。

## 4. 初始化链（`urma_init` → `create_context` → JFC/JFS/JFR）

```263:273:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
Status UrmaManager::UrmaInit()
{
    ...
    urma_status_t ret = urma_init(&urmaInitAttribute);
    if (ret != URMA_SUCCESS) {
        RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to urma init, ret = %d", ret));
    }
```

```417:427:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
    urmaContext_ = urma_create_context(urmaDevice, eidIndex);
    if (urmaContext_) {
        ...
        return Status::OK();
    }
    RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to urma create context, errno = %d", errno));
```

## 5. 完成队列与 poll / wait / ack / rearm（读路径热点）

`PollJfcWait` 中组合使用 **`urma_wait_jfc` / `urma_poll_jfc` / `urma_ack_jfc` / `urma_rearm_jfc`**（事件模式分支），失败时打 **`Failed to poll jfc` / `Failed to wait jfc`** 等日志并映射到 **`K_URMA_ERROR`**：

```819:858:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp
Status UrmaManager::PollJfcWait(const custom_unique_ptr<urma_jfc_t> &jfc, const uint64_t maxTryCount,
                               ...
        cnt = urma_wait_jfc(urmaJfce_, 1, RPC_POLL_TIME, &ev_jfc);
        ...
        cnt = urma_poll_jfc(urmaJfc, numPollCRS, &completeRecords[0]);
        ...
            urma_ack_jfc((urma_jfc_t **)&ev_jfc, &ack_cnt, 1);
            auto status = urma_rearm_jfc(urmaJfc, false);
            if (status != URMA_SUCCESS) {
                RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString("Failed to rearm jfc, status = %d", status));
```

## 6. 数据面 `urma_write` / `urma_read` / `urma_post_jfs_wr`

- `urma_write` / `urma_read` 失败时当前实现映射为 **`K_RUNTIME_ERROR`**（见 `urma_manager.cpp` 对应 `CHECK_FAIL_RETURN_STATUS`）。
- `urma_advise_jfr` 失败：**`Failed to advise jfr`** → **`K_URMA_ERROR`**。

## 7. 用户清单中「当前仓库未调用」的 API

- **`urma_modify_jfs`**：全仓 `grep` **无符号**（2026-04-09 检索）。若后续版本引入，请在 Sheet2 **增行** 并贴调用点。

## 8. 与 Excel 的关系

Excel **Sheet2** 为上述行的 **扁平表**；若评审修改代码，请 **先改源码 → 再跑脚本再生 xlsx**（见 [README.md](./README.md)）。
