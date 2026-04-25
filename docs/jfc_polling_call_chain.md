# JFC Polling 接口调用链

## 1. 概述

**JFC** = Jetty Flow Completion (轮询完成队列)

**Polling 模式** = 非阻塞方式主动查询完成的 Completion Record (CR)

## 2. DataSystem 中调用位置

### 调用链

```
ds_urma_poll_jfc()  包装层 (urma_dlopen_util.cpp:312)
  └── urma_poll_jfc()  实际接口 (动态加载)
        └── dp_ops->poll_jfc()  函数指针
              └── bondp_poll_jfc()  或其他实现
```

### 具体行号

| 文件 | 行号 | 说明 |
|------|------|------|
| `yuanrong-datasystem/src/datasystem/common/rdma/urma_dlopen_util.h` | 65 | 函数声明 |
| `yuanrong-datasystem/src/datasystem/common/rdma/urma_dlopen_util.cpp` | 310-313 | 封装实现（动态加载调用） |
| `yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp` | 881 | Event 模式获取 CR |
| `yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp` | 906 | Polling 模式循环获取 |

## 3. 函数签名

### ds_urma_poll_jfc (DataSystem 封装)

```cpp
// urma_dlopen_util.h:65
int ds_urma_poll_jfc(urma_jfc_t *jfc, int max_cr, urma_cr_t *complete_records);

// urma_dlopen_util.cpp:310-313
int ds_urma_poll_jfc(urma_jfc_t *jfc, int max_cr, urma_cr_t *complete_records)
{
    return CallRet<UrmaLibType::URMA, int, decltype(&ds_urma_poll_jfc)>(
        "urma_poll_jfc", -1, jfc, max_cr, complete_records);
}
```

### urma_poll_jfc (底层接口)

```c
// umdk/src/urma/lib/urma/core/urma_dp_api.c:210-220
int urma_poll_jfc(urma_jfc_t *jfc, int cr_cnt, urma_cr_t *cr)
{
    urma_ops_t *dp_ops = get_ops_by_urma_jfc(jfc);
    if (dp_ops == NULL || dp_ops->poll_jfc == NULL || cr == NULL || cr_cnt < 0) {
        URMA_LOG_ERR("Invalid parameter.\n");
        return -1;
    }
    int ret;
    PERF_PROFILING_START(UB_POLL_JFC);
    ret = dp_ops->poll_jfc(jfc, cr_cnt, cr);
    PERF_PROFILING_END(UB_POLL_JFC);
    return ret;
}
```

## 4. urma_manager.cpp 调用详情

### 第 881 行 - Event 模式获取 CR

```cpp
// yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp:879-886
// Got the event, now get CR for the event
// Event mode can poll one CR at a time
cnt = ds_urma_poll_jfc(urmaJfc, numPollCRS, &completeRecords[0]);
INJECT_POINT("UrmaManager.CheckCompletionRecordStatus", [&completeRecords]() {
    completeRecords[0].status = URMA_CR_REM_ACCESS_ABORT_ERR;
    return Status::OK();
});
if (cnt < 0) {
    // 错误处理
}
```

### 第 906 行 - Polling 模式循环获取

```cpp
// yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp:904-911
// trys maxTryCount times to get an event
for (uint64_t i = 0; i < maxTryCount; ++i) {
    cnt = ds_urma_poll_jfc(urmaJfc, numPollCRS, completeRecords);
    if (cnt == 0) {
        // If there is nothing to poll, just sleep.
        // Note that it takes on average 50us to wake up with usleep(0), due to OS timerslack settings.
        usleep(0);
    } else if (cnt < 0) {
        // 错误处理
    }
}
```

## 5. 调用上下文

这两个调用都在 `UrmaManager::CheckCompletionRecordStatus()` 函数中，用于检查 RDMA 操作是否完成。

### 函数原型

```cpp
Status UrmaManager::CheckCompletionRecordStatus(
    urma_jfc_t *urmaJfc,
    int maxTryCount,
    int numPollCRS,
    std::vector<urma_cr_t> *completeRecords)
```

## 6. 返回值说明

| 返回值 | 含义 |
|--------|------|
| 0 | 没有完成的记录（CQ 为空） |
| > 0 | 实际获得的 CR 数量 |
| < 0 | 表示错误 |

## 7. 其他模块调用（参考）

### UMQ UB 模块

```c
// umdk/src/urpc/umq/umq_ub/core/private/umq_ub.c

// 发送完成轮询 (多处调用)
int tx_cr_cnt = umq_symbol_urma()->urma_poll_jfc(
    queue->jfs_jfc[UB_QUEUE_JETTY_IO], UMQ_POST_POLL_BATCH, cr);

// 接收完成轮询
int rx_cr_cnt = umq_symbol_urma()->urma_poll_jfc(
    queue->jfr_ctx[UB_QUEUE_JETTY_IO]->jfr_jfc, UMQ_POST_POLL_BATCH, cr);
```

### Bond 模式聚合

```c
// umdk/src/urma/lib/urma/bond/bondp_datapath.c:968
// Bond 模式会聚合多个物理 JFC，轮询时遍历每个物理 JFC
int pcr_cnt = urma_poll_jfc(bdp_jfc->p_jfc[idx], pcr_cnt_max, pcr_buf);
```

## 8. 相关文件路径

```
yuanrong-datasystem/
├── src/datasystem/common/rdma/
│   ├── urma_manager.cpp          # 调用方
│   ├── urma_dlopen_util.cpp      # 封装层
│   └── urma_dlopen_util.h        # 声明
└──

umdk/
├── src/urma/lib/urma/core/
│   └── urma_dp_api.c             # 底层实现
└──
```
