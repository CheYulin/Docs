# Issue: URMA Write 场景下 Arena 分配器触发同步 fallocate 导致 12ms 延迟

## 概述

在 URMA Write 场景中，即使数据内存已预先注册给 URMA，Worker 在处理 GET 请求时仍然因为 Arena 分配器的 mmap 后端扩展（fallocate）导致 **12ms** 的阻塞延迟。

## Trace 信息

| 项目 | 值 |
|------|-----|
| TraceId | `66b7bcb9-ce5a-4582-9daf-799c7da765a8` |
| 时间 | 2026-05-11 00:08:07 |
| Worker IP | 192.168.219.67 |
| Master IP | 192.168.35.22 |
| Data Worker IP | 192.168.52.198 |
| 对象大小 | 8388608 bytes (8MB) |
| 总耗时 | 15.463ms |

## 时间线分析

| 时间 | 耗时 | 事件 |
|------|------|------|
| 00:08:07.971646 | 0ms | Worker 收到 GET 请求 |
| 00:08:07.972107 | 0.46ms | Master 查询完成 |
| 00:08:07.972122 | 0.48ms | **开始 Arena 分配内存** |
| 00:08:07.972126 | 0.48ms | ShmUnit AllocateMemory |
| 00:08:07.984976 | 12.3ms | **fallocate fd:90** (2MB 扩展) |
| 00:08:07.985021 | 12.4ms | Arena 2 分配完成 (实际分配 10MB) |
| 00:08:07.985051 | 12.4ms | Remote Pull 开始 |
| 00:08:07.986147 | 13.5ms | remainTimeMs=**0** (已超时) |
| 00:08:07.986351 | 13.7ms | **URMA Wait 超时** (1.063ms deadline) |
| 00:08:07.986363 | 13.7ms | **TCP Fallback 被拒** (8MB > 1MB limit) |
| 00:08:07.986223 | 13.7ms | 释放已分配内存 |

## 瓶颈分析

### 1. Arena 分配耗时 12ms

```
arena.cpp:151 | [Allocator] Arena 2 allocate require size: 8388672, real size: 10485760
```

- 请求大小: 8,388,672 bytes
- 实际分配: **10,485,760 bytes** (Arena 预分配机制)
- 耗时: **12ms** (占总处理时间 15ms 的 **80%**)

### 2. fallocate 调用

```
mem_mmap.cpp:133 | fallocate fd:90, offsetInMmap:27504541696, offset:8388672, length:2097088
```

- 扩展大小: **2,097,088 bytes** (~2MB)
- 耗时: 约 **13ms** (984976→985021)

### 3. 问题根因

即使数据内存已注册给 URMA，Arena 分配器的 mmap 后端存储仍需扩展：
- Arena 分配器使用 mmap 文件作为后端
- 分配新内存时需要扩展 mmap 文件
- `fallocate()` 是同步阻塞调用
- 在内存压力下 (`memOccupied=27.5GB`, threshold=58GB) 扩展变慢

### 4. 后续失败链

```
AllocateMemory (12ms) → Remote Pull → URMA Wait 超时 (1.063ms) → TCP Fallback 被拒 (8MB > 1MB) → 释放内存
```

## 关键日志摘录

### Arena 分配
```
worker_oc_eviction_manager.cpp:974 | Allocate memory for kv_test_4_5_379623856699223_0, size = 8388672, memOccupied = 27502133440, memThreshold = 57982058496
arena.cpp:151 | [Allocator] Arena 2 allocate require size: 8388672, real size: 10485760, offset: 27504541696
```

### fallocate 调用
```
mem_mmap.cpp:133 | fallocate fd:90, offsetInMmap:27504541696, offset:8388672, length:2097088
arena.cpp:818 | CommitHook arena 2
```

### URMA 失败
```
urma_manager.cpp:852 | [URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr cost 1.06303ms, status: RPC deadline exceeded
worker_worker_oc_service_impl.cpp:839 | Worker-to-worker TCP fallback payload rejected, fallback tcp payload rejected by limiter: worker->worker payload 8388608 bytes is not smaller than the limit 1048576 bytes
```

## 根因假设

1. **Arena 预分配机制**: Arena 分配器采用预分配策略，8MB 请求实际分配 10MB
2. **mmap 后端扩展**: Arena 的 mmap 后端存储需要 `fallocate()` 扩展文件
3. **同步阻塞**: `fallocate()` 是同步系统调用，在高内存压力下可能耗时较长
4. **CommitHook 触发**: `arena.cpp:818 CommitHook arena 2` 在分配后触发，可能涉及额外的 mmap 操作

## 建议排查方向

1. **分析 `arena.cpp:818` CommitHook**: 确认是否在关键路径上有不必要的 mmap 扩展
2. **检查 Arena 预分配策略**: 能否优化避免预分配过大
3. **考虑异步 fallocate**: 将 mmap 扩展改为异步或后端线程处理
4. **评估 Arena 初始化**: 能否预先分配足够的后端存储，避免运行时扩展

## 影响

- 单次 GET 请求增加 **12ms** 延迟
- 在批量请求场景下影响放大
- 可能导致请求超时 (`remainTimeMs=0`)
