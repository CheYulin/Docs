# FMEA 中间分析：URMA 层故障模式

## 1. URMA 层故障概述

URMA 层负责 UB (Unified Bay) 数据面的数据传输，包括 JFC/JFS/JFR/CQ 等核心组件。

## 2. URMA 层故障模式详表

| FM编号 | 故障模式 | 边界域 | StatusCode | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 关键日志 |
|-------|---------|--------|------------|---------|---------|------------|--------|---------|
| FM-003 | UB 初始化失败 | URMA | 1004 | ds_urma_init 失败、驱动 so 未加载、/usr/lib64/urma 缺失 | 整个 UB 传输不可用 | 是 | Ⅰ类 | `Failed to urma init` |
| FM-005 | FastTransport/import jfr 失败 | URMA | 1004 | jfr import 失败、token 不匹配、Fast transport handshake failed | UB 远端传输建立失败 | 是 | Ⅱ类 | `Fast transport handshake failed` |
| FM-010 | UB write/read 失败 | URMA | 5/1004 | urma_write/read 调用失败、SQ/RQ 错误 | 数据写入/读取失败 | 是 | Ⅱ类 | `Failed to urma write/read` |
| FM-011 | CQ poll/wait/rearm 失败 | URMA | 1004 | poll_jfc 失败、wait_jfc 超时、rearm 失败 | 事件通知机制失效 | 是 | Ⅱ类 | `Failed to wait jfc` / `poll jfc` |
| FM-012 | UB 连接需重建 | URMA | 1006 | 连接不稳、实例不匹配、remoteInstanceId 变化 | 需重新建连，短时业务中断 | 是 | Ⅲ类 | `URMA_NEED_CONNECT` |
| FM-013 | JFS 重建策略 | URMA | 1004/1008 | JFS 状态异常、RECREATE_JFS 错误码 | SQ 不可用，写操作失败 | 是 | Ⅱ类 | `URMA_RECREATE_JFS` |
| FM-020 | UB 直发失败 | URMA | 依封装 | Send buffer via UB 失败、Jetty 不足 | 降级到 TCP/IP payload | 部分 | Ⅲ类 | `Failed to send buffer via UB` |

## 3. URMA 层关键代码路径

### 3.1 URMA 初始化
```
文件: urma_manager.cpp::Init
故障点: UrmaInit / UrmaGetDeviceByName
错误码: 1004
日志: Failed to urma init / Failed to get device
```

### 3.2 URMA 连接稳定性检测
```
文件: urma_manager.cpp::CheckUrmaConnectionStable
故障点: 连接不稳/实例不匹配
错误码: 1006
日志: URMA_NEED_CONNECT / remoteInstanceId
```

### 3.3 CQ Poll/Wait/Rearm
```
文件: urma_manager.cpp
故障点: urma_poll_jfc / urma_wait_jfc / urma_rearm_jfc
错误码: 1004
日志: Failed to wait jfc / poll jfc
```

### 3.4 JFS 重建
```
文件: urma_manager.cpp::GetUrmaErrorHandlePolicy
故障点: status code 9 → RECREATE_JFS
错误码: 1004/1008
日志: URMA_RECREATE_JFS
```

### 3.5 远端重连
```
文件: worker_oc_service_get_impl.cpp::TryReconnectRemoteWorker
故障点: 1006 → 重连 → TRY_AGAIN
错误码: 1008
日志: Reconnect success
```

## 4. URMA 层错误码映射

| URMA 接口 | 错误返回值 | errno | 故障原因 |
|----------|----------|-------|---------|
| urma_init | URMA_FAIL | N/A | 驱动 so 文件 dlopen 失败 |
| urma_create_context | NULL | EINVAL/EIO/N/A | 参数校验错误、sysfs 读取失败 |
| urma_create_jfc | NULL | EINVAL/N/A | jfc 深度超限、udma 接口失败 |
| urma_create_jfs | NULL | EINVAL/N/A | 传输模式非法、SQ buf 分配失败 |
| urma_create_jfr | NULL | EINVAL/N/A | jfr 深度超限、index queue buf 分配失败 |
| urma_import_jfr | NULL | UDMA 返回错误码 | 建链交换信息失败 |
| urma_poll_jfc | -1 | UDMA_INTER_ERR | cqe 为空、cqe 解析失败 |
| urma_wait_jfc | -1 | ERR_PTR(512) | UDMA 中断未上报、wait 被中断 |
| urma_write | URMA_EINVAL | UDMA 异常返回值 | 参数检查错误 |
| urma_read | URMA_EINVAL | UDMA 返回值 | 参数检查错误 |

## 5. URMA 层故障检测方法

| 预期检测方法 | 版本现状 |
|------------|---------|
| URMA 连接心跳检测 | ✅ 已实现 - CheckUrmaConnectionStable |
| CQ 空轮询检测 | ✅ 已实现 - urma_poll_jfc 返回值检测 |
| JFS 状态异常检测 | ✅ 已实现 - RECREATE_JFS 策略 |
| 设备列表检测 | ✅ 已实现 - lsmod / urma_admin show -a |

## 6. URMA 层故障处理方法

| 故障模式 | 预期处理 | 版本现状 |
|---------|---------|---------|
| URMA 初始化失败 | 告警 + 降级到 TCP | ⚠️ 需人工介入 |
| CQ poll 失败 | 重试 + 重建 CQ | ✅ 已实现 |
| JFS 重建 | 自动重建 JFS | ✅ 已实现 |
| 连接需重建 | 自动重连 | ✅ 已实现 - TryReconnectRemoteWorker |

## 7. 改进建议

| 优先级 | 改进项 | 说明 |
|-------|-------|-----|
| P0 | URMA 故障自愈 | 当前部分 URMA 故障需要人工介入 |
| P1 | CQ 异常提前检测 | 应在 poll 失败前检测异常趋势 |
| P2 | 多路径 UB 降级 | 支持 UB 多端口 bonding 降级 |
