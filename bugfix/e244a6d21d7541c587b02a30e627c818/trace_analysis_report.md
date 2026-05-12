# KV GET 请求耗时分析报告

**Trace 文件**: `e244a6d21d7541c587b02a30e627c818`
**采集时间**: 2026-05-10 17:08:38 - 17:16:15
**数据来源**: sdk_long15.log (126条) + worker_long15.log (1911条)

---

## 1. 概览

### 1.1 日志统计

| 文件 | 行数 | 内容描述 |
|------|------|----------|
| `sdk_long15.log` | 126 | Client 视角 - SDK 记录，包含 latency(μs) |
| `worker_long15.log` | 1911 | Worker 视角 - 完整的请求处理链路 |

### 1.2 请求类型分布

| 错误码 | 操作类型 | 含义 | 数量 |
|--------|----------|------|------|
| `1002` | DS_KV_CLIENT_GET | RPC_RECV_TIMEOUT | ~80 |
| `1002` | DS_KV_CLIENT_SET | Create meta to master failed | ~15 |
| `0` | DS_KV_CLIENT_GET | 成功 | ~25 |
| `0` | DS_KV_CLIENT_SET | 成功 | ~6 |

### 1.3 时间段分布

| 时间段 | 特征 |
|--------|------|
| `17:08:38 - 17:08:43` | 密集超时，多 worker 受影响 |
| `17:08:41 - 17:08:42` | 最密集超时区 |
| `17:12:10`, `17:15:15` | 成功请求 |
| `17:16:10 - 17:16:15` | 少量超时和成功混合 |

---

## 1.5 全量 Trace 详细 Breakdown（用户提供）

> 以下为用户提供的精确 breakdown，包含完整的耗时分解：

| # | TraceId | Time | SDK(ms) | CRPC(ms) | QMeta(ms) | Remote Net(ms) | Remote Self(ms) | URMA(ms) | Other(ms) | 异常信息 | St |
|---|---------|------|---------|----------|-----------|----------------|-----------------|----------|-----------|----------|-----|
| 1 | `f040e67b-e4b8-4c...` | 17:08:41.74 | 21.235 | 4.958 | 0.029 | - | 3 | - | 13.3 | Publish失败×1 \| Master失败×1 | 1002 |
| 2 | `2202ec24-d0a8-41...` | 17:08:39.74 | 21.136 | 5.579 | - | 12.5 | 0.777 | - | 2.3 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×7 \| RPCRetry×6 | 1002 |
| 3 | `e2b59e92-375c-4d...` | 17:16:12.13 | 21.088 | 5.455 | - | 4.34 | 1.3 | 0.082 | 4.717 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×8 \| RPCRetry×10 | 1002 |
| 4 | `aa13b159-af84-4f...` | 17:16:12.13 | 20.957 | 5.485 | - | 4.37 | 1.7 | 0.134 | 4.215 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×8 \| RPCRetry×10 | 1002 |
| 5 | `c27a907f-fa1c-4e...` | 17:16:12.13 | 20.943 | 5.45 | - | 4.24 | 4.1 | 0.118 | 1.877 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×6 \| RPCRetry×8 | 1002 |
| 6 | `a67950d8-75e0-44...` | 17:08:42.98 | 20.916 | 6.451 | - | 12.6 | 0.573 | - | 1.2 | RemoteGet失败×2 \| BatchFail×2 \| RPCRetry×2 | 1002 |
| 7 | `fd1bd85e-22f1-41...` | 17:08:43.11 | 20.878 | - | - | - | - | - | 21.2 | RPCRetry×1 \| Obj未找到 | 1002 |
| 8 | `2c3c40ad-892f-43...` | 17:08:38.75 | 20.868 | 4.526 | 0.043 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 9 | `175951fa-7dd0-45...` | 17:08:41.76 | 20.815 | 4.457 | 0.025 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 10 | `77f9427b-19b8-4f...` | 17:08:39.75 | 20.763 | 5.461 | - | 12.2 | 0.95 | - | 2.1 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×3 \| RPCRetry×5 | 1002 |
| 11 | `3bcff0fd-3de3-48...` | 17:08:39.75 | 20.723 | 5.46 | - | 12.6 | 0.61 | - | 2.0 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×3 \| RPCRetry×5 | 1002 |
| 12 | `d5ca3914-6a4d-47...` | 17:08:42.87 | 20.676 | 4.407 | 0.016 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 13 | `b842de20-8099-43...` | 17:08:43.10 | 20.645 | 5.212 | - | 12.9 | 0.336 | - | 2.2 | RemoteGet失败×1 \| BatchFail×1 \| RemoveMeta×4 \| RPCRetry×6 | 1002 |
| 14 | `fa94258b-c7f4-4c...` | 17:08:41.63 | 20.631 | 4.358 | 0.019 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 15 | `68a31eeb-1a8e-41...` | 17:08:41.76 | 20.602 | 4.304 | 0.018 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 16 | `9badbd75-efde-44...` | 17:08:42.85 | 20.594 | 4.258 | 0.018 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 17 | `c35150d0-1e50-4c...` | 17:08:41.74 | 20.587 | - | - | - | - | - | 50.6 | RPCRetry×1 \| Obj未找到 | 1002 |
| 18 | `43ea67a3-5ab2-4b...` | 17:08:41.75 | 20.582 | - | - | 0.3 | 0.302 | - | 41.4 | RPCRetry×1 \| Obj未找到 | 1002 |
| 19 | `cc9fa67b-0b88-47...` | 17:08:41.65 | 20.559 | 4.25 | 0.02 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 20 | `97b4934f-9fb3-49...` | 17:08:41.64 | 20.546 | 4.257 | 0.025 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 21 | `8da1ec4b-8582-42...` | 17:16:10.56 | 20.535 | 5.129 | - | 0.32 | 7.0 | 0.274 | 8.1 | Worker超时 | 1002 |
| 22 | `47d77800-9ba5-4c...` | 17:08:42.86 | 20.526 | 4.235 | 0.019 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 23 | `efdef6ca-7e99-40...` | 17:08:41.74 | 20.511 | - | - | - | - | - | 45.8 | RPCRetry×1 \| Obj未找到 | 1002 |
| 24 | `a3db1b59-7c9f-4a...` | 17:08:41.74 | 20.508 | - | - | - | - | - | 49.0 | RPCRetry×1 \| Obj未找到 | 1002 |
| 25 | `a229830e-963b-49...` | 17:08:39.76 | 20.492 | 5.551 | - | 12.3 | 0.951 | - | 1.7 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×3 \| RPCRetry×5 | 1002 |
| 26 | `7468ad12-42b0-43...` | 17:08:41.64 | 20.469 | 4.18 | 0.014 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 27 | `d504c2dc-6782-4f...` | 17:08:43.12 | 20.469 | 1.483 | - | - | - | - | 19.0 | RPCRetry×1 \| Obj未找到 | 1002 |
| 28 | `8791ef88-e63b-44...` | 17:08:41.62 | 20.442 | 4.155 | 0.022 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 29 | `23a24ad3-1418-4c...` | 17:08:38.75 | 20.416 | 5.526 | - | 12.8 | 0.436 | - | 1.7 | RemoteGet失败×2 \| BatchFail×2 \| RemoveMeta×4 \| RPCRetry×6 | 1002 |
| 30 | `8527b530-580d-4a...` | 17:16:12.13 | 20.404 | 3.488 | - | - | - | - | 16.9 | RPCRetry×2 \| Worker超时 | 1002 |
| 31 | `d92f5663-e197-4b...` | 17:08:41.66 | 20.351 | 4.055 | 0.02 | - | 3 | - | 13.3 | Publish失败×2 \| Master失败×2 | 1002 |
| 32 | `14c4293b-8a2f-42...` | 17:16:12.13 | 20.272 | 3.456 | - | - | - | - | 16.8 | RPCRetry×2 \| Worker超时 | 1002 |
| 33 | `706b2a26-33d5-4c...` | 17:08:38.74 | 20.173 | 19.16 | - | - | - | - | 1.0 | - | 1002 |
| 34 | `4982a887-4084-4b...` | 17:08:42.83 | 20.172 | 4.802 | - | 12.7 | 0.493 | - | 2.1 | RemoteGet失败×1 \| BatchFail×1 \| RemoveMeta×4 \| RPCRetry×6 | 1002 |
| 35 | `96c87c60-6500-44...` | 17:08:38.74 | 20.162 | 19.006 | - | 0.4 | 0.326 | - | 0.5 | - | 1002 |
| 36 | `190f888b-d6c8-40...` | 17:08:38.74 | 20.155 | 20.095 | - | - | - | - | 0.1 | - | 1002 |
| 37 | `14a4d579-49d9-4b...` | 17:08:41.77 | 20.152 | 20.112 | 0.04 | - | - | - | - | - | 1002 |
| 38 | `1a9ff654-2e05-46...` | 17:08:41.76 | 20.151 | 17.705 | - | - | - | - | 2.4 | - | 1002 |
| 39 | `160562d0-3d1d-46...` | 17:08:41.75 | 20.145 | - | - | - | - | - | - | - | 1002 |
| 40 | `94de59a8-564e-47...` | 17:08:41.75 | 20.141 | - | - | - | - | - | - | - | 1002 |
| 41 | `33cc20ca-d7ef-43...` | 17:08:38.74 | 20.138 | 18.991 | - | 0.4 | 0.264 | - | 0.5 | - | 1002 |
| 42 | `29bae7f7-c001-4e...` | 17:08:41.75 | 20.136 | - | - | - | - | - | - | - | 1002 |
| 43 | `2742705b-afe7-49...` | 17:08:41.76 | 20.127 | 17.568 | - | 0.2 | 0.449 | - | 1.9 | - | 1002 |
| 44 | `053beaaf-7ca7-43...` | 17:08:41.76 | 20.123 | 17.918 | - | 0.3 | 0.455 | - | 1.5 | - | 1002 |
| 45 | `a7326c82-3faf-4e...` | 17:08:41.76 | 20.122 | 18.141 | - | 0.3 | 0.287 | - | 1.4 | - | 1002 |
| 46 | `75f00c1b-dbdc-42...` | 17:08:41.74 | 20.111 | - | - | - | - | - | - | - | 1002 |
| 47 | `5b37331e-a3f9-4b...` | 17:08:41.75 | 20.095 | - | - | - | - | - | - | - | 1002 |
| 48 | `b27cc529-49dc-43...` | 17:16:15.63 | 19.970 | 4.413 | - | 3.13 | 3.2 | 0.914 | 11.5 | RemoteGet失败×1 \| BatchFail×1 \| RemoveMeta×4 \| RPCRetry×6 | 0 |
| 49 | `0d2334fa-fa2f-48...` | 17:16:15.63 | 19.900 | 2.38 | - | 0.7 | 0.352 | - | 16.4 | RemoteGet失败×1 \| BatchFail×1 \| RemoveMeta×4 \| RPCRetry×6 | 0 |
| 50 | `353b8c75-244a-4a...` | 17:16:12.13 | 19.890 | 4.425 | - | 4.40 | 6.8 | 0.098 | 1.322 | RemoteGet失败×1 \| BatchFail×1 \| RemoveMeta×4 \| RPCRetry×5 \| **TCP_FALLBACK_REJECTED** | 0 |

### 1.5.1 Breakdown 字段说明

| 字段 | 含义 | 数据来源 |
|------|------|----------|
| `SDK` | 总端到端延迟 | SDK log latency |
| `CRPC` | Client→Worker 延迟 | Client access time - Worker access time |
| `QMeta` | QueryMeta RPC 耗时 | Master query cost |
| `Remote Net` | Remote Pull 网络传输耗时 | network_residual_us |
| `Remote Self` | Remote Worker 自身处理耗时 | server_exec_us |
| `URMA` | URMA Write 耗时 | urma_post_jetty_send_wr cost |
| `Other` | 其他耗时（含 Worker 内部处理） | ProcessGetObjectRequest 等 |
| `St` | 状态码 | 0=成功, 1002=RPC_RECV_TIMEOUT |

### 1.5.2 关键发现

1. **CRPC=0 的 traces**（如 `c35150d0`, `160562d0`, `94de59a8`）：表示 Client→Worker 延迟为 0 或负值，说明 **ThreadPool 排队导致请求在 Client 侧等待时间超过了 Worker 处理时间**

2. **URMA 耗时有值**（如 `353b8c75` URMA=1.322ms）：表示发生了 URMA Write 实际耗时

3. **Remote Net 很高**（如 `2202ec24` Remote Net=12.5ms）：表示网络传输慢或 Remote Worker 处理慢

4. **异常信息包含 TCP_FALLBACK_REJECTED**（`353b8c75`）：大对象（8MB）URMA 失败后尝试 TCP fallback 但被拒绝

---

## 2. 耗时计算方法

### 2.1 核心公式

**Client → Worker 延迟计算（正确方法）**:
```
Client → Worker = Client access 时间戳 - Worker access 时间戳
```

**说明**:
- Client access 时间: `sdk_long15.log` 中 access 日志的时间戳（Client 发起请求时记录）
- Worker access 时间: `worker_long15.log` 中对应 traceId 的 access 日志时间戳（Worker 开始处理时记录）
- 两者都是 `access_recorder.cpp:219` 记录的时间戳，代表各自侧请求开始的时间

### 2.2 实测数据

以 trace `353b8c75-244a-4a6e-b6c5-979dd78de07d` 为例：

| 角色 | 时间戳 | 操作 |
|------|--------|------|
| Client (SDK) | `17:16:12.139093` | DS_KV_CLIENT_GET |
| Worker | `17:16:12.134832` | DS_POSIX_GET |
| **差值** | **4.261ms** | = Client→Worker |

验证：`SDK latency (19890μs) - Worker totalCost (15465μs) = 4425μs ≈ 4.425ms` ≈ 4.261ms ✓

| TraceId | Client Access | Worker Access | Client→Worker 耗时 | SDK Latency | Worker totalCost |
|---------|---------------|---------------|-------------------|-------------|------------------|
| `353b8c75` | 12.139093 | 12.134832 | **4.26ms** | 19890μs | 15465μs |
| `2202ec24` | (见 worker log) | 39.721753 | **~4ms** | 21136μs | 17063μs |

**观察**: Client → Worker 耗时约 **4-8ms**，主要受 ZMQ Stub→Server 网络传输和队列排队影响。

---

## 3. 耗时分解

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        KV GET 请求耗时分解                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Client → Worker  (ZMQ Stub → ZMQ Server)                             │
│       │  (SDK latency - Worker totalCost)                              │
│       └── 实测: 5.5-7.8ms                                             │
│                                                                         │
│  Worker → Meta (QueryMeta RPC)                                          │
│       │  (Master query cost)                                          │
│       ├── 正常: 0.3ms                                                  │
│       └── 瓶颈: 11ms (稳定)                                            │
│                                                                         │
│  Worker → Data Worker (Remote Pull via URMA)                           │
│       │  (Remote done cost)                                           │
│       ├── 正常: 0.3-1ms                                               │
│       ├── 慢:   3-13ms                                                │
│       └── 极慢: 40-50ms (线程池排队)                                   │
│                                                                         │
│  Worker 内部处理 (totalCost 分解)                                      │
│       ├── ProcessGetObjectRequest (主逻辑)                              │
│       ├── QueryMeta: 0.3-11ms                                          │
│       ├── RemotePull: 0.3-13ms                                          │
│       │                                                                │
│       ├── URMA Write: ~1ms (deadline)                                 │
│       │     └── 大对象 (8MB) 走 TCP fallback 受限于 1MB 限制           │
│       │                                                                │
│       ├── URMA Wait: poll 等待 + nanosleep                            │
│       │     └── Worker 线程池 idle/total/wait 状态                     │
│       │                                                                │
│       └── 线程池等待 (sleep): wait 线程多时导致 40-50ms 延迟          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Worker → Data Worker (Remote Pull) 详细分解

**Remote Pull 耗时统计** (77 条记录):

| 指标 | 值 |
|------|-----|
| 平均 | 5.07ms |
| 最小 | 0.51ms |
| 最大 | 13.29ms |
| >10ms (慢) | 19 条 |

**Remote Pull = URMA Write + URMA Wait**:

```
Remote Pull 流程:
1. Worker 向目标 Worker 发起 Remote Pull 请求
2. 目标 Worker 执行: UrmaWritePayload() 写数据
3. 源 Worker 等待: UrmaManager::WaitToFinish() + nanosleep poll
4. Remote done cost = URMA write time + URMA wait time
```

### 3.2 URMA Write 耗时

**日志中的 URMA write deadline**:

```
urma write deadline exceeded: 1.18ms
```

**大对象问题**:
- 数据大小: 8388608 bytes (8MB)
- TCP fallback 限制: 1048576 bytes (1MB)
- 结果: **8MB 数据无法走 TCP fallback，只能等 URMA 完成**

**URMA Write 超时记录** (4 条):

| Trace | Worker IP | URMA Write Deadline | 数据大小 |
|-------|-----------|---------------------|----------|
| `52b840ac` | 192.168.219.122 | 1.18ms | 8MB |
| `353b8c75` | 192.168.219.122 | 1.10ms | 8MB |

### 3.3 URMA Wait 耗时 (线程池等待)

**URMA Wait 机制** (`UrmaManager::WaitToFinish`):
- 使用 poll + nanosleep 循环等待 RDMA 完成事件
- poll 超时后会 nanosleep 再试
- 日志中体现为 `threadPool` 状态

**线程池状态分析** (12 条记录):

| idle | total | wait | 状态描述 |
|------|-------|------|----------|
| 10-15 | 14-19 | 10-14 | **高负载，排队严重** |
| 4-5 | 16 | 0-1 | 正常负载 |

**典型高负载 Worker** (`192.168.210.131`):

```
[Get] Receive, threadPool: idle(12), total(19), wait(10), elapsed: 38.000ms, remainingTime: 7.000ms
[Get] Done, totalCost: 50.617ms, inflightRemoteGet: 0 exceed 3ms: {ProcessGetObjectRequest: 50 ms; }
```

**分析**:
- `wait(10)` 表示有 10 个请求在等待线程处理
- `elapsed: 38ms` 表示请求已经等待了 38ms
- `totalCost: 50ms` 说明 Worker 处理本身只需要 50ms，但前面排队导致总延迟高

### 3.4 线程池等待导致 40-50ms 延迟的 Trace

| Trace ID | Worker IP | totalCost | wait 线程数 | 主要耗时 |
|----------|-----------|-----------|-------------|----------|
| `c35150d0` | 192.168.210.131 | 50.6ms | wait(10) | ProcessGetObjectRequest: 50ms |
| `a3db1b59` | 192.168.210.131 | 49.0ms | wait(10) | ProcessGetObjectRequest: 49ms |
| `efdef6ca` | 192.168.210.131 | 45.8ms | wait(9) | ProcessGetObjectRequest: 45ms |
| `43ea67a3` | 192.168.210.131 | 42.0ms | wait(8) | ProcessGetObjectRequest: 42ms |
| `460c1972` | 192.168.210.131 | 46.2ms | wait(10) | ProcessGetObjectRequest: 46ms |
| `113b4fde` | 192.168.210.131 | 46.3ms | wait(10) | ProcessGetObjectRequest: 46ms |
| `6eeee841` | 192.168.210.131 | 46.1ms | wait(9) | ProcessGetObjectRequest: 46ms |

---

## 4. 瓶颈分析

### 4.1 Client → Worker (ZMQ Stub → ZMQ Server)

**实测耗时**: 5.5-7.8ms

**计算方式**: SDK latency - Worker totalCost

**涉及 Worker IP**:
- `192.168.199.160`: ~5.5ms
- `192.168.210.131`: ~7.8ms

**"queue is empty within allowed time: 2-20ms" 含义**:
- 这是 **ZMQ Server 内部队列等待时间**
- 表示 Worker ZMQ Server 处理速度跟不上请求速度
- 不是网络延迟，而是 Worker 处理瓶颈

### 4.2 Worker → Master (QueryMeta) 瓶颈

**现象**: QueryMeta RPC 耗时稳定在 11ms

```
Worker to master rpc QueryMeta: 11 ms
```

**涉及 Worker IP**:
- `192.168.199.160`
- `192.168.210.131`
- `192.168.235.151`

### 4.3 Worker → Data Worker (Remote Pull) 瓶颈

**Remote Pull 耗时波动大**:

| 耗时 | 数量 | 说明 |
|------|------|------|
| 0.3-1ms | ~80 | 正常 |
| 3-13ms | ~15 | 慢请求 |
| 40-50ms | ~10 | 严重慢请求 |

**严重慢请求集中在**: `192.168.210.131`

### 4.4 ZMQ RPC FRAMEWORK SLOW 详细分解

**日志**: `worker_long15.log` 中有 **26 条** `[ZMQ_RPC_FRAMEWORK_SLOW]` 日志

**FRAMEWORK 分解公式**:
```
e2e = client_req + remote_processing + client_rsp
     = client_req + (server_req_q + server_exec + server_rsp_q + network_residual) + client_rsp
```

**耗时统计** (26 traces):

| 指标 | 平均 | 最大 | 单位 |
|------|------|------|------|
| framework_us | 5.8ms | 9.9ms | - |
| remote_processing_us | 3.6ms | 9.9ms | **主要耗时** |
| server_rsp_queue_us | 0.7ms | 3.2ms | **瓶颈点** |
| network_residual_us | 3.0ms | 6.7ms | URMA 传输 |

**瓶颈分类** (按主要耗时组件):

| 瓶颈类型 | 数量 | Trace 示例 | 特征 |
|----------|------|------------|------|
| **server_rsp_queue** | 8 | `067d158c`, `353b8c75` | server_rsp_q > 1000us |
| **network_residual** | 10 | `b27cc529`, `5ff31bce` | network > 3000us |
| **remote_processing** | 3 | `e1011db8`, `bec0e921` | remote_process > 5000us |
| **其他** | 7 | `d2e6a427`, `c35117ee` | 混合瓶颈 |

**典型 ZMQ_RPC_FRAMEWORK_SLOW 案例**:

#### 案例 1: server_rsp_queue 瓶颈 (3151us)

```
trace_id=067d158c-59a5-4fee-9812-dca4dcaeb850
  framework_us=8258
    remote_processing_us=8244
      server_req_queue_us=1478    ← 队列等待
      server_exec_us=16
      server_rsp_queue_us=2857    ← 主要瓶颈
      network_residual_us=3892
```

#### 案例 2: network_residual 瓶颈 (TCP 传输慢)

```
trace_id=b27cc529-49dc-43c8-ae2b-36f2b0760112
  framework_us=9857
    remote_processing_us=9858
      server_req_queue_us=2600
      server_exec_us=38
      server_rsp_queue_us=492
      network_residual_us=6726     ← 主要瓶颈 (TCP 传输 6.7ms)
```

### 4.4.1 ZMQ RPC FRAMEWORK 与 URMA 的关系

**重要区分**:
- `network_residual_us` = **TCP 传输时间**（框架层面）
- `URMA_ELAPSED_TOTAL` = **URMA RDMA write 实际耗时**（独立日志）

**两者的关系**:
```
remote_processing = server_req_q + server_exec + server_rsp_q + network_residual (TCP)
                                                    ↑
                                                    ↓
                                            但数据实际通过 URMA RDMA 传输
```

**URMA ELAPSED TOTAL 统计** (25 条):

| 指标 | 值 |
|------|-----|
| 平均 | 2.40ms |
| 最小 | 1.10ms |
| 最大 | 4.78ms |
| 数据大小 | 8MB (8388608 bytes) |

**关键发现**:
- URMA write 本身只需 1-5ms (8MB 数据)
- `network_residual` 包含 TCP 重试、握手等开销，比 URMA 慢
- 说明瓶颈在 TCP 层面的频繁重试，而非 URMA 本身

### 4.4.2 server_rsp_queue 瓶颈分析

- `server_rsp_queue` = Worker 处理完请求后，在 ZMQ Server 响应队列中的等待时间
- 数值高说明 Worker ZMQ Server 处理能力不足，请求堆积
- 与 "queue is empty within allowed time" 错误直接相关

### 4.4.3 network_residual 瓶颈分析

- `network_residual` = **TCP 传输时间**（不是 URMA）
- 6-7ms 的 TCP 传输时间说明 TCP 层频繁重试或等待
- 可能与 TCP拥塞控制、大对象分包有关

### 4.5 慢请求 Worker 分布

```
192.168.210.131:
  - 5个请求耗时 42-50ms
  - threadPool 状态: idle(12-15), total(19), wait(10-14)
  - 存在明显的线程池排队

192.168.199.160:
  - 多个请求 15ms+
  - Remote pull 出现 13ms 延迟
```

---

## 4. 典型错误 Trace 详解

### 4.1 Trace 1: Remote Pull 慢 (15ms)

**TraceId**: `2202ec24-d0a8-417e-b95b-07e675e4be70`
**Worker**: `192.168.199.160`
**Object**: `kv_test_37_11_354449809551380_0`

```
时间                   事件                                                      耗时
-------------------------------------------------------------------------------------
17:08:39.721753       Query metadata from master: 192.168.182.59:31402          -
17:08:39.722050       [Get] Master query done, targets: 1, hits: 1               0.310ms
17:08:39.735347       [Get] Remote done, path: UB, cost: 13.257ms                 13.257ms  ← 瓶颈
17:08:39.737274       [Get] Done, totalCost: 15.560ms                            15.560ms
```

**瓶颈分析**:
- Master query: 0.31ms (正常)
- Remote pull: 13.257ms (慢)
- 总耗时: 15.560ms

### 4.2 Trace 2: Worker 线程池排队 (50ms)

**TraceId**: `c35150d0-1e50-4c8b-8bc3-9c59187d8957`
**Worker**: `192.168.210.131`
**Object**: `kv_test_22_15_81278517098707_0`

```
时间                   事件                                                      耗时
-------------------------------------------------------------------------------------
17:08:41.721306       Query metadata from master: 192.168.215.52:31402           -
17:08:41.732407       [RPC Retry]: queue is empty within allowed time: 11ms       11ms
17:08:41.732433       Query from master failed                                    -
17:08:41.771871       [Get] Receive, threadPool: idle(12), total(19), wait(10)   -
                        elapsed: 38.000ms, remainingTime: 7.000ms                   38ms  ← 排队
17:08:41.771895       [Get] Done, totalCost: 50.617ms                            50.617ms
```

**瓶颈分析**:
- Worker 线程池满载: total=19, wait=10-14
- 请求在队列中等待 38ms
- 这不是单个请求的瓶颈，而是系统级排队

### 4.3 Trace 3: QueryMeta 11ms 瓶颈

**TraceId**: `1b5e3e17-9657-4148-93bd-49f78846c99e`
**Worker**: `192.168.199.160`
**Object**: `kv_test_9_0_354482104440298_0`

```
时间                   事件                                                      耗时
-------------------------------------------------------------------------------------
17:08:40.211904       Query metadata from master: 192.168.210.209:31402           -
17:08:40.223005       [RPC Retry]: queue is empty within allowed time: 11ms       11ms  ← 瓶颈
17:08:40.223026       Query from master failed                                    -
17:08:40.223073       [Get] Done, totalCost: 11.209ms                            11.209ms
```

**瓶颈分析**:
- 瓶颈在 Worker → Master 的 RPC 链路
- 11ms 固定耗时说明 Master 处理或网络存在固定延迟

---

## 5. 代码链路分析

### 5.1 KV GET 完整调用链

```
Client.Get()
  └── ClientWorkerRemoteApi::Get()           [CLIENT_RPC_GET_LATENCY]
        └── WorkerOcServiceGetImpl::ProcessGetObjectRequest()
              ├── PreProcessGetObject()
              │     └── QueryMetadataFromMaster()  [WORKER_RPC_QUERY_META_LATENCY]
              │           └── WorkerRemoteMasterOCApi::QueryMeta()
              └── GetObjectFromRemoteOnLock()
                    └── PullObjectDataFromRemoteWorker()
                          └── WorkerRemoteWorkerOCApi::GetObjectRemote()
                                [WORKER_RPC_REMOTE_GET_OUTBOUND_LATENCY]
                                └── WorkerWorkerOCServiceImpl::GetObjectRemote()
                                      [WORKER_RPC_REMOTE_GET_INBOUND_LATENCY]
                                      └── GetObjectRemoteImpl()
                                            └── UrmaWritePayload()  [WORKER_URMA_WRITE_LATENCY]
```

### 5.2 关键代码位置

| 阶段 | 文件 | 函数 |
|------|------|------|
| GET 入口 | `worker_oc_service_get_impl.cpp:309` | `ProcessGetObjectRequest()` |
| Query Meta | `worker_master_oc_api.cpp:255` | `WorkerRemoteMasterOCApi::QueryMeta()` |
| Remote Pull | `worker_worker_oc_api.cpp:69` | `WorkerRemoteWorkerOCApi::GetObjectRemote()` |
| URMA Write | `worker_request_manager.cpp:430` | `UbWriteHelper()` |
| URMA Wait | `urma_manager.cpp:833` | `UrmaManager::WaitToFinish()` |

---

## 6. 问题定位

### 6.1 主要瓶颈点

| 瓶颈 | 耗时 | 建议排查方向 |
|------|------|-------------|
| **Client → Worker** | 5.5-7.8ms | ZMQ Server 处理能力不足、请求堆积 |
| Worker → Master RPC | 11ms | Master 负载、网络抖动 |
| Remote Pull | 0.5-13ms | 目标 Worker 负载、URMA 链路 |
| 线程池排队 | 38ms+ | 系统容量不足、请求堆积 |

### 6.2 关键节点 IP

| IP | 角色 | 观察 |
|----|------|------|
| `192.168.102.112` | Master | 处理 QueryMeta |
| `192.168.199.160` | Worker | 多个 15ms+ 请求 |
| `192.168.210.131` | Worker | 严重线程池排队，5个 42-50ms 请求 |
| `192.168.210.209` | Worker/Data | Remote pull 目标 |
| `192.168.168.252` | Worker/Data | Remote pull 目标 |

### 6.3 错误模式

1. **`queue is empty within allowed time: 2-20ms`**
   - 这是 **ZMQ Server 内部队列等待**
   - 表示 ZMQ Server 处理速度跟不上请求速度
   - 不是网络延迟，是 Worker 处理瓶颈

2. **`RPC unavailable` + `RPC deadline exceeded`**
   - 远程调用失败
   - 通常伴随重试

3. **`Can't find object`**
   - Meta 查询失败或对象已被 evict

---

## 7. 建议

### 7.1 短期优化

1. **增加 Worker 线程池大小**
   - 当前: total=19
   - 建议: 观察期峰值，调整至 32-64

2. **优化 Master QueryMeta 延迟**
   - 当前稳定 11ms
   - 检查 Master 负载和网络

3. **排查 `192.168.210.131` 负载**
   - 5个 42-50ms 请求集中于此
   - 可能是热点或负载不均

### 7.2 长期优化

1. **增加 Worker 实例，分担负载**
2. **优化 URMA Write/Wait 链路**
3. **调整 ZMQ 超时参数**
4. **增加请求重试指数退避**

---

## 8. 附录: 全量 Slow Trace IDs

| TraceId | Worker IP | totalCost | 主要耗时 |
|---------|-----------|-----------|----------|
| `2202ec24-d0a8-417e-b95b-07e675e4be70` | 192.168.199.160 | 15.560ms | Remote pull 13ms |
| `3bcff0fd-3de3-48cc-9275-622d9b2f1aa3` | 192.168.199.160 | 15.267ms | Remote pull 13ms |
| `77f9427b-19b8-4f92-b71f-f1e094efa22f` | 192.168.199.160 | 15.306ms | Remote pull 13ms |
| `c35150d0-1e50-4c8b-8bc3-9c59187d8957` | 192.168.210.131 | 50.617ms | 线程池排队 38ms |
| `a3db1b59-7c9f-4a98-8968-8de51fe592e0` | 192.168.210.131 | 49.015ms | 线程池排队 38ms |
| `efdef6ca-7e99-4004-8906-e1c2179aac25` | 192.168.210.131 | 45.804ms | 线程池排队 33ms |
| `43ea67a3-5ab2-4bab-88be-69d9f040b5ee` | 192.168.210.131 | 42.020ms | 线程池排队 38ms |
| `460c1972-6e1d-4d63-b5d1-357c166e1bf7` | 192.168.210.131 | 46.190ms | 线程池排队 38ms |
| `1b5e3e17-9657-4148-93bd-49f78846c99e` | 192.168.199.160 | 11.209ms | QueryMeta 11ms |
| `afd0b682-9b8b-447d-bc75-2dc18eab17a3` | 192.168.199.160 | 11.184ms | QueryMeta 11ms |

---

## 附录 A: 全量 Trace 列表 (107条)

| # | Trace ID | SDK延迟(us) | Worker Cost(ms) | C->W延迟(us) | Meta(ms) | Remote(ms) | 错误 | 队列超时(ms) |
|---|----------|-------------|------------------|--------------|-----------|------------|------|--------------|
| 1 | `160562d0-3d1d-4619-85b9-d9ad3b940f90` | 20145 | - | 20145 | - | - | RPC_RECV_TIMEOUT | 20 |
| 2 | `94de59a8-564e-47c3-94dd-59d76e35de25` | 20141 | - | 20141 | - | - | RPC_RECV_TIMEOUT | 20 |
| 3 | `29bae7f7-c001-4ef4-90a6-5db4608e5e98` | 20136 | - | 20136 | - | - | RPC_RECV_TIMEOUT | 20 |
| 4 | `75f00c1b-dbdc-4218-b276-f42e4b864681` | 20111 | - | 20111 | - | - | RPC_RECV_TIMEOUT | 20 |
| 5 | `5b37331e-a3f9-4bf9-a8db-9b0ac9148c34` | 20095 | - | 20095 | - | - | RPC_RECV_TIMEOUT | 20 |
| 6 | `190f888b-d6c8-409c-8620-5c8e4b3774fe` | 20155 | 0.1 | 20092 | - | - | RPC_RECV_TIMEOUT | 20 |
| 7 | `706b2a26-33d5-4c99-9f0a-98ef0b9aa221` | 20173 | 1.0 | 19155 | - | - | RPC_RECV_TIMEOUT | 20 |
| 8 | `96c87c60-6500-4477-a522-5e7f3a62cf09` | 20162 | 1.2 | 18999 | 0.4 | 0.6 | RPC_RECV_TIMEOUT | 20 |
| 9 | `33cc20ca-d7ef-432f-96ba-c3edbe0b41b3` | 20138 | 1.2 | 18987 | 0.4 | 0.7 | RPC_RECV_TIMEOUT | 20 |
| 10 | `a7326c82-3faf-4e67-85c8-7823caa907b3` | 20122 | 2.0 | 18135 | 0.3 | 0.6 | RPC_RECV_TIMEOUT | 20 |
| 11 | `053beaaf-7ca7-43ca-96b4-b300c2bef3b2` | 20123 | 2.2 | 17917 | 0.3 | 0.8 | RPC_RECV_TIMEOUT | 20 |
| 12 | `1a9ff654-2e05-463d-9077-2cde88963a36` | 20151 | 2.4 | 17704 | 0.0 | - | RPC_RECV_TIMEOUT | 20 |
| 13 | `2742705b-afe7-49c1-97d0-9cbdf41804ea` | 20127 | 2.6 | 17564 | 0.5 | 0.7 | RPC_RECV_TIMEOUT | 20 |
| 14 | `3b2f5e81-a54b-45d1-a62a-2cdc1facd8af` | 18798 | 2.2 | 16613 | 0.4 | 0.9 | - | - |
| 15 | `e44ef2e2-18e2-4afa-ba7a-aab1b118714c` | 15175 | 2.3 | 12909 | 0.5 | 0.8 | - | - |
| 16 | `398100df-21d6-4546-bcb9-c36058bc508e` | 16678 | 6.5 | 10149 | 2.7 | 3.5 | - | - |
| 17 | `7af75b0d-0096-41bb-a231-d46fd8b2323b` | 16039 | 6.1 | 9935 | 5.1 | 0.9 | - | - |
| 18 | `ccf6289f-23eb-4211-9f3a-05250678117d` | 15936 | 6.1 | 9827 | 2.3 | 3.4 | - | - |
| 19 | `d2e6a427-5282-4389-8c4a-7767ae021a33` | 15822 | 6.1 | 9749 | 3.3 | 2.6 | - | - |
| 20 | `43878f53-b417-472b-8913-7a06b8f90a85` | 15650 | 6.2 | 9479 | 2.1 | 3.7 | - | - |
| 21 | `c35117ee-900a-4812-a47b-4404271c2a7d` | 17176 | 8.1 | 9126 | 2.5 | 5.2 | - | - |
| 22 | `b62632eb-7984-44c8-8c34-39c8ee3dcba0` | 16204 | 7.5 | 8751 | 4.6 | 2.6 | - | - |
| 23 | `bc7e93f4-b9d9-4fce-95d3-dc8f841684f2` | 16430 | 7.7 | 8731 | - | - | - | - |
| 24 | `edf7a2eb-2440-4ddf-a722-725a97198b12` | 15076 | 6.5 | 8618 | 2.6 | 3.6 | - | - |
| 25 | `57a7b432-7db7-473e-80da-3e3284353d80` | 17667 | 9.2 | 8451 | 7.6 | 1.4 | - | - |
| 26 | `dfc12da0-3b38-4278-8f96-cfae540f81ab` | 19180 | 11.2 | 7963 | - | - | RPC_RECV_TIMEOUT | 6 |
| 27 | `a7f220c3-e851-4006-8257-63c12dc68c1c` | 19153 | 11.2 | 7922 | - | - | RPC_RECV_TIMEOUT | 6 |
| 28 | `405424e9-6f3d-4be1-8a14-4d189e50500d` | 19088 | 11.2 | 7864 | - | - | RPC_RECV_TIMEOUT | 6 |
| 29 | `7230cc76-cd75-44bf-838f-06f5804e4eba` | 19057 | 11.2 | 7863 | - | - | RPC_RECV_TIMEOUT | 6 |
| 30 | `9c771293-822f-466f-9efd-3748087fc642` | 19045 | 11.2 | 7846 | - | - | RPC_RECV_TIMEOUT | 6 |
| 31 | `1b427fb5-579c-425b-bcdc-8c5cecc15d37` | 19003 | 11.2 | 7842 | - | - | RPC_RECV_TIMEOUT | 6 |
| 32 | `1b5e3e17-9657-4148-93bd-49f78846c99e` | 19041 | 11.2 | 7832 | - | - | RPC_RECV_TIMEOUT | 6 |
| 33 | `9806bcb2-deab-4feb-9231-599eb2cd5c6d` | 19029 | 11.2 | 7816 | - | - | RPC_RECV_TIMEOUT | 6 |
| 34 | `9ec916e1-45cc-431d-a568-cb12f14d46b6` | 18985 | 11.2 | 7814 | - | - | RPC_RECV_TIMEOUT | 6 |
| 35 | `10044655-80ac-47d0-a2a7-638472c9816c` | 19055 | 11.2 | 7813 | - | - | RPC_RECV_TIMEOUT | 6 |
| 36 | `4626b74b-272f-41d5-8b89-0188208588d9` | 18981 | 11.2 | 7808 | - | - | RPC_RECV_TIMEOUT | 6 |
| 37 | `dda7f54d-f7f2-4e0a-afe4-fe4a61cbac55` | 18954 | 11.2 | 7774 | - | - | RPC_RECV_TIMEOUT | 6 |
| 38 | `b4186dd5-eac8-4f43-89ef-8170343a6835` | 18921 | 11.2 | 7750 | - | - | RPC_RECV_TIMEOUT | 6 |
| 39 | `ae0521af-d0b2-40a4-9b74-9cdcff072676` | 18890 | 11.1 | 7749 | - | - | RPC_RECV_TIMEOUT | 6 |
| 40 | `e5e4ece4-4eca-4c30-a5f1-e8cbe5bd0d47` | 18925 | 11.2 | 7743 | - | - | RPC_RECV_TIMEOUT | 6 |
| 41 | `1398d482-ae88-4ed9-9fab-7e69ad1b1980` | 18914 | 11.2 | 7738 | - | - | RPC_RECV_TIMEOUT | 6 |
| 42 | `b14bbc25-7459-4df5-9350-fae0295f00a9` | 18910 | 11.2 | 7728 | - | - | RPC_RECV_TIMEOUT | 6 |
| 43 | `afd0b682-9b8b-447d-bc75-2dc18eab17a3` | 18901 | 11.2 | 7717 | - | - | RPC_RECV_TIMEOUT | 6 |
| 44 | `01de3a3e-222f-4b24-8608-d753db9f8835` | 18961 | 11.3 | 7710 | - | - | RPC_RECV_TIMEOUT | 6 |
| 45 | `0c369da0-e1a7-4568-b8ff-aa025757511e` | 18898 | 11.2 | 7698 | - | - | RPC_RECV_TIMEOUT | 6 |
| 46 | `1b038c17-8579-4f84-9b7c-e26c3432a28e` | 18875 | 11.2 | 7697 | - | - | RPC_RECV_TIMEOUT | 6 |
| 47 | `1ac4be65-d5ee-46d4-aca7-473dc6826cfe` | 18935 | 11.2 | 7694 | - | - | RPC_RECV_TIMEOUT | 3 |
| 48 | `d9776dba-a14e-42b0-846b-21a9cfd84a1f` | 18867 | 11.2 | 7686 | - | - | RPC_RECV_TIMEOUT | 6 |
| 49 | `20f0d571-db28-4239-8932-a4aebc8469a8` | 18806 | 11.2 | 7638 | - | - | RPC_RECV_TIMEOUT | 6 |
| 50 | `04652d03-eb8e-42b9-bc32-fe217464c0d4` | 19131 | 11.8 | 7287 | - | - | RPC_RECV_TIMEOUT | 6 |
| 51 | `5ff31bce-f735-4bf5-aa5e-ba6409a82629` | 18304 | 11.2 | 7070 | 4.8 | 0.6 | - | - |
| 52 | `a67950d8-75e0-44e1-b4ff-b5a6d8f08e90` | 20916 | 14.5 | 6450 | 0.4 | 13.2 | RPC_RECV_TIMEOUT | 5 |
| 53 | `bec0e921-0890-4f1e-9aa0-f7e0dd162a73` | 15683 | 9.4 | 6237 | 8.0 | 1.3 | - | - |
| 54 | `bf7d6075-ff14-4d03-a03a-342694e09cb7` | 15179 | 9.0 | 6170 | 5.0 | 3.8 | - | - |
| 55 | `2202ec24-d0a8-417e-b95b-07e675e4be70` | 21136 | 15.6 | 5576 | 0.3 | 13.3 | RPC_RECV_TIMEOUT | 4 |
| 56 | `a229830e-963b-49ce-8a8f-0e2f0ba12b9c` | 20492 | 14.9 | 5546 | 0.4 | 13.2 | RPC_RECV_TIMEOUT | 4 |
| 57 | `23a24ad3-1418-4c10-b30b-165184456943` | 20416 | 14.9 | 5526 | 0.4 | 13.2 | RPC_RECV_TIMEOUT | 4 |
| 58 | `aa13b159-af84-4fc5-bffb-78d645c00cd6` | 20957 | 15.5 | 5481 | 7.6 | 6.1 | RPC_RECV_TIMEOUT | 4 |
| 59 | `77f9427b-19b8-4f92-b71f-f1e094efa22f` | 20763 | 15.3 | 5457 | 0.4 | 13.2 | RPC_RECV_TIMEOUT | 4 |
| 60 | `3bcff0fd-3de3-48cc-9275-622d9b2f1aa3` | 20723 | 15.3 | 5456 | 0.3 | 13.2 | RPC_RECV_TIMEOUT | 4 |
| 61 | `e2b59e92-375c-4d8d-a29d-5d51b39667ef` | 21088 | 15.6 | 5449 | 7.8 | 6.1 | RPC_RECV_TIMEOUT | 4 |
| 62 | `c27a907f-fa1c-4ea6-8c7f-0b54b2d9a73a` | 20943 | 15.5 | 5447 | 7.7 | 6.1 | RPC_RECV_TIMEOUT | 4 |
| 63 | `7486e7e0-86c4-49cb-9b83-2c75cadd0d78` | 15286 | 9.9 | 5371 | 7.9 | 1.7 | - | - |
| 64 | `b842de20-8099-4348-ac24-da15488c54b1` | 20645 | 15.4 | 5205 | 0.4 | 13.3 | RPC_RECV_TIMEOUT | 3 |
| 65 | `8da1ec4b-8582-42ad-a6a5-8552d6cbfeeb` | 20535 | 15.4 | 5132 | 8.0 | 7.3 | RPC_RECV_TIMEOUT | 20 |
| 66 | `4982a887-4084-4bb3-84f9-cfd0f79d2c30` | 20172 | 15.4 | 4793 | 0.4 | 13.2 | RPC_RECV_TIMEOUT | 3 |
| 67 | `353b8c75-244a-4a6e-b6c5-979dd78de07d` | 19890 | 15.5 | 4421 | 6.9 | 8.3 | - | - |
| 68 | `b27cc529-49dc-43c8-ae2b-36f2b0760112` | 19970 | 15.6 | 4407 | 10.0 | 4.1 | - | - |
| 69 | `fafb0eda-ef70-4052-9c6b-b74980d506fc` | 19475 | 15.5 | 3972 | - | - | - | - |
| 70 | `52b840ac-f4f6-4b63-95b7-cd0b7fd884a4` | 19831 | 16.0 | 3839 | 7.4 | 8.2 | RPC_RECV_TIMEOUT | 2 |
| 71 | `9f2d5b0e-b908-4e22-b0ec-3ada687ac7f8` | 19560 | 15.8 | 3759 | 7.9 | 6.1 | RPC_RECV_TIMEOUT | 2 |
| 72 | `067d158c-59a5-4fee-9812-dca4dcaeb850` | 19572 | 15.8 | 3758 | 8.3 | 6.1 | RPC_RECV_TIMEOUT | 2 |
| 73 | `8527b530-580d-4a55-b12d-dfd62c7497c0` | 20404 | 16.9 | 3480 | - | - | RPC_RECV_TIMEOUT | 2 |
| 74 | `14c4293b-8a2f-425e-bec2-cdde3cf08b1d` | 20272 | 16.8 | 3453 | - | - | RPC_RECV_TIMEOUT | 2 |
| 75 | `163db6ec-a083-43aa-8290-b70c6262c84f` | 17698 | 14.4 | 3275 | 1.1 | 12.2 | - | - |
| 76 | `a67b706f-b15b-46c9-8d26-c8f07c8b3747` | 16020 | 12.8 | 3229 | 9.2 | 3.4 | - | - |
| 77 | `4e927d31-fb1c-4288-a29d-e22b1f43088e` | 17877 | 14.8 | 3087 | 0.6 | 13.2 | - | - |
| 78 | `b61f5f07-15a4-497e-90a0-26c8f05e0e88` | 17310 | 14.5 | 2836 | 0.4 | 13.3 | - | - |
| 79 | `c0557d7b-53bf-4a61-914b-df3625def437` | 17489 | 14.7 | 2798 | 0.3 | 13.2 | - | - |
| 80 | `d0e999e2-a55b-41d0-a24e-72efa7971625` | 18176 | 15.4 | 2755 | - | - | - | - |
| 81 | `23748462-33a2-410f-b534-e0d898180eec` | 17215 | 14.5 | 2735 | 0.3 | 13.2 | - | - |
| 82 | `8edaf162-5779-44e0-8e38-3d8721356930` | 17170 | 14.5 | 2695 | 1.2 | 12.2 | - | - |
| 83 | `5acd51c4-e658-4fb5-bb08-20e8598ef54c` | 17734 | 15.1 | 2672 | 0.4 | 13.3 | - | - |
| 84 | `ed39132f-3036-4c1c-ba2f-d8fc4f318730` | 17399 | 14.8 | 2648 | 0.3 | 13.2 | - | - |
| 85 | `a5577468-f159-4da1-8529-37963b3f8a83` | 17169 | 14.5 | 2638 | 0.4 | 13.2 | - | - |
| 86 | `0d2334fa-fa2f-480b-aa8c-7c09373cad0f` | 19900 | 17.5 | 2376 | 0.6 | 1.1 | - | - |
| 87 | `e7be7172-7aa7-4996-8570-65a58566f474` | 18149 | 15.8 | 2323 | 0.4 | 1.3 | - | - |
| 88 | `9510dfb9-e882-4b85-9ed8-4e0f0a0aca42` | 18274 | 16.2 | 2031 | 0.3 | 0.8 | - | - |
| 89 | `90ca7912-b234-44ed-be29-e15c88b995ee` | 15461 | 13.5 | 1916 | 0.4 | 0.7 | - | - |
| 90 | `676f34cf-47cd-4f9e-b3c5-8eb1e905f07c` | 17764 | 15.9 | 1865 | 0.4 | 0.8 | - | - |
| 91 | `88f078c3-1abb-4313-bbae-e94a3135a3f0` | 17786 | 16.0 | 1795 | 0.3 | 0.8 | - | - |
| 92 | `d3dc1b1d-c730-480d-9ac2-bf810d31cccc` | 17697 | 16.0 | 1655 | - | - | - | - |
| 93 | `e0636df5-4781-40ed-a2f0-efa72450f354` | 16148 | 14.5 | 1653 | 0.3 | 13.3 | - | - |
| 94 | `82c4c87e-2962-42ca-a927-eafe16944343` | 16569 | 15.0 | 1577 | 0.4 | 13.2 | - | - |
| 95 | `0e015acf-9761-4212-9e11-91f0acb23f8d` | 18791 | 17.3 | 1528 | - | - | RPC_RECV_TIMEOUT | 6 |
| 96 | `d504c2dc-6782-4f18-84ab-88caf7d1347e` | 20469 | 19.0 | 1477 | - | - | - | - |
| 97 | `afa0d43a-acb0-42be-96b4-3d1e903ffba9` | 15662 | 15.4 | 306 | 0.5 | 0.6 | - | - |
| 98 | `77465a33-3609-4134-b4a0-05f89b7b64a7` | 16309 | 16.0 | 293 | 0.0 | - | - | - |
| 99 | `fd1bd85e-22f1-4180-8b3a-5190a0f360f8` | 20878 | 21.2 | -307 | - | - | RPC_RECV_TIMEOUT | 4 |
| 100 | `43ea67a3-5ab2-4bab-88be-69d9f040b5ee` | 20582 | 42.0 | -21438 | 0.3 | 0.6 | RPC_RECV_TIMEOUT | 8 |
| 101 | `efdef6ca-7e99-4004-8906-e1c2179aac25` | 20511 | 45.8 | -25293 | - | - | RPC_RECV_TIMEOUT | 8 |
| 102 | `e019f870-09ef-4cca-836e-d762ddea0433` | 18886 | 45.3 | -26409 | - | - | RPC_RECV_TIMEOUT | 6 |
| 103 | `460c1972-6e1d-4d63-b5d1-357c166e1bf7` | 19070 | 46.2 | -27120 | - | - | RPC_RECV_TIMEOUT | 6 |
| 104 | `113b4fde-3b50-427a-a90a-13e617792303` | 19127 | 46.3 | -27177 | - | - | RPC_RECV_TIMEOUT | 6 |
| 105 | `6eeee841-a574-4f81-94c7-c2f78fa47b5c` | 18896 | 46.1 | -27234 | - | - | RPC_RECV_TIMEOUT | 6 |
| 106 | `a3db1b59-7c9f-4a98-8968-8de51fe592e0` | 20508 | 49.0 | -28507 | - | - | RPC_RECV_TIMEOUT | 8 |
| 107 | `c35150d0-1e50-4c8b-8bc3-9c59187d8957` | 20587 | 50.6 | -30030 | - | - | RPC_RECV_TIMEOUT | 8 |

---

*报告生成时间: 2026-05-10 22:50*
