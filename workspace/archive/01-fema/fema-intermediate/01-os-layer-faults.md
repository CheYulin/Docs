# FMEA 中间分析：OS 层故障模式

## 1. OS 层故障概述

OS 层负责 socket/TCP/ZMQ/UDS/mmap/文件/syscalls，是 KVCache 与底层硬件/网络的桥梁。

## 2. OS 层故障模式详表

| FM编号 | 故障模式 | 边界域 | StatusCode | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 关键日志 |
|-------|---------|--------|------------|---------|---------|------------|--------|---------|
| FM-001 | Init Register/ZMQ 不可达 | OS | 1001/1002 | ZMQ 初始化失败、socket 创建失败、端口占用 | 业务实例无法注册到 Worker | 是 | Ⅱ类 | `Register client failed` |
| FM-002 | RPC 半开连接抖动 | OS | 1002/19 | 网络闪断、心跳超时、POLLOUT 事件丢失 | 数据传输不稳定，重试增加延迟 | 是 | Ⅱ类 | `try again` / `timeout` |
| FM-004 | 客户端 UB 匿名内存池 mmap 失败 | OS | 6 | 系统内存不足、mmap anon 失败、地址空间耗尽 | UB 传输无法分配内存，业务中断 | 是 | Ⅰ类 | `K_OUT_OF_MEMORY` |
| FM-006 | SCM_RIGHTS fd 传递异常 | OS | 5/10 | fd 数值非法、SCM_RIGHTS 传递失败、Unexpected EOF | 共享内存通道建立失败 | 是 | Ⅱ类 | `invalid fd` / `Unexpected EOF` |
| FM-007 | Get 请求未达/ZMQ 超时 | OS | 1001/1002/19 | ZMQ 消息队列满、接收超时、连接断开 | Get 操作失败，业务卡顿 | 是 | Ⅱ类 | `Start to send rpc to get object` |
| FM-008 | Directory QueryMeta 失败 | OS | 5 | Master 节点不可达、RPC 超时、元数据损坏 | 目录查询失败，无法定位数据 | 是 | Ⅱ类 | `Query from master failed` |
| FM-009 | W1→W3 拉对象数据失败 | OS | 依封装 | 远端 Worker 故障、网络丢包、TCP 重传超时 | 远端读取失败，业务中断 | 是 | Ⅱ类 | `Get from remote failed` |
| FM-016 | 客户端 SHM mmap 失败 | OS | 依 ToString | mmap entry 获取失败、地址映射冲突 | 共享内存访问失败 | 是 | Ⅱ类 | `Get mmap entry failed` |
| FM-018 | etcd 不可用 | OS(etcd) | 1002等 | etcd 集群全部节点故障、网络分区、磁盘 IO 满 | 控制面失效，无法路由和选主 | 是 | Ⅰ类 | `etcd is unavailable` |
| FM-019 | Publish/MultiPublish 超时 | OS | 1001/1002/19 | ZMQ 发送超时、远程节点无响应、队列满 | 发布操作失败，数据不一致风险 | 是 | Ⅱ类 | `Start to send rpc to publish object` |

## 3. OS 层关键代码路径

### 3.1 ZMQ 连接建立
```
文件: zmq_stub_conn.cpp
故障点: 建连/等待/心跳 POLLOUT
错误码: 1002
日志: Network unreachable / timeout waiting for SockConnEntry
```

### 3.2 Unix Socket fd 交换
```
文件: unix_sock_fd.cpp::ErrnoToStatus
故障点: ECONNRESET/EPIPE
错误码: 1002
日志: Connect reset
```

### 3.3 Client Worker 共享内存
```
文件: client_worker_common_api.cpp
故障点: mustUds && !isConnectSuccess
错误码: 1002
日志: shm fd transfer
```

### 3.4 文件 IO
```
文件: file_util.cpp::pread/pwrite
故障点: IO 错误
错误码: 7
日志: K_IO_ERROR
```

### 3.5 Spill 空间
```
文件: worker_oc_spill.cpp
故障点: spill 空间不足
错误码: 13
日志: No space
```

## 4. OS 层故障检测方法

| 预期检测方法 | 版本现状 |
|------------|---------|
| 心跳超时告警 (Worker Heartbeat) | ✅ 已实现 - listen_worker.cpp 检测心跳超时 |
| ZMQ 连接状态监控 | ✅ 已实现 - POLLOUT 事件检测 |
| mmap 失败错误码捕获 | ✅ 已实现 - K_OUT_OF_MEMORY |
| fd 有效性校验 | ✅ 已实现 - ErrnoToStatus 转换 |
| etcd 健康检查 | ✅ 已实现 - etcd_cluster_manager.cpp |

## 5. OS 层故障处理方法

| 故障模式 | 预期处理 | 版本现状 |
|---------|---------|---------|
| ZMQ 不可达 | 重试 + 告警 | ✅ 重试机制 - RetryOnError |
| mmap 失败 | 降级到 TCP、告警 | ⚠️ 部分降级 - FM-014 UB fallback |
| SCM_RIGHTS 失败 | 重连 + 重建通道 | ✅ 已实现 - TryReconnectRemoteWorker |
| etcd 不可用 | 切主 + 路由更新 | ✅ 已实现 - K_MASTER_TIMEOUT 处理 |

## 6. 改进建议

| 优先级 | 改进项 | 说明 |
|-------|-------|-----|
| P0 | etcd 故障自愈 | 当前 etcd 完全不可用时无自动恢复，需人工介入 |
| P1 | ZMQ 半开连接检测 | 现有 POLLOUT 检测无法区分半开连接，需优化 |
| P2 | mmap 失败降级路径 | 应确保 mmap 失败时能稳定降级到 TCP |
