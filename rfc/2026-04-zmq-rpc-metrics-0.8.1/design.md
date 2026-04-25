# Design: ZMQ RPC Metrics ENABLE_PERF=false 修复方案

## 1. 问题

### 1.1 现象

当 `ENABLE_PERF=false` 时：
- `GetLapTime()` 返回 0，不记录 tick
- `GetTotalTime()` 返回 0
- ZMQ RPC metrics 无法分段时间

### 1.2 影响

无法通过 metrics 自证清白：
- network 延迟（`zmq_server_queue_wait_latency`）
- RPC framework 回复时间（`zmq_server_reply_latency`）

## 2. 修复方案

### 2.1 新增函数

```cpp
// zmq_common.h

// 始终记录 tick，不受 ENABLE_PERF 控制
inline uint64_t RecordTick(MetaPb &meta, const char *tickName)
{
    auto ts = TimeSinceEpoch();
    auto n = meta.ticks_size();
    uint64_t diff = n > 0 ? (ts - meta.ticks(n - 1).ts()) : 0;
    TickPb tick;
    tick.set_ts(ts);
    tick.set_tick_name(tickName);
    meta.mutable_ticks()->Add(std::move(tick));
    return diff;
}

// 始终计算总时间，不受 ENABLE_PERF 控制
inline uint64_t GetTotalElapsedTime(MetaPb &meta)
{
    auto n = meta.ticks_size();
    if (n > 0) {
        return meta.ticks(n - 1).ts() - meta.ticks(0).ts();
    }
    return 0;
}
```

### 2.2 修改后的 GetLapTime/GetTotalTime

```cpp
// GetLapTime：保持原有行为，ENABLE_PERF 关闭时返回 0
inline uint64_t GetLapTime(MetaPb &meta, const char *tickName)
{
#ifdef ENABLE_PERF
    return RecordTick(meta, tickName);
#else
    (void)meta;
    (void)tickName;
    return 0;
#endif
}

// GetTotalTime：保持原有行为，ENABLE_PERF 关闭时返回 0
inline uint64_t GetTotalTime(MetaPb &meta)
{
#ifdef ENABLE_PERF
    return GetTotalElapsedTime(meta);
#else
    (void)meta;
    return 0;
#endif
}
```

### 2.3 修改 metrics 记录函数

将原来使用 `GetLapTime` 的地方改为使用 `RecordTick`：

| 文件 | 原调用 | 新调用 |
|------|--------|--------|
| `zmq_service.cpp` | `GetLapTime(meta, TICK_SERVER_DEQUEUE)` | `RecordTick(meta, TICK_SERVER_DEQUEUE)` |
| `zmq_service.cpp` | `GetLapTime(meta, TICK_SERVER_EXEC_END)` | `RecordTick(meta, TICK_SERVER_EXEC_END)` |
| `zmq_stub_conn.cpp` | `GetLapTime(meta, TICK_CLIENT_SEND)` | `RecordTick(meta, TICK_CLIENT_SEND)` |
| `zmq_stub_impl.h` | `GetTotalTime(meta)` | `GetTotalElapsedTime(meta)` |

### 2.4 时间单位转换

`TimeSinceEpoch()` 返回纳秒 (ns)，metrics histogram 以微秒 (us) 为单位：

```cpp
// ns → us 转换
.Observe((serverDequeuTs - serverRecvTs) / 1000);
```

## 3. 改动文件清单

| 文件 | 改动类型 |
|------|---------|
| `zmq_common.h` | 新增 `RecordTick()`、`GetTotalElapsedTime()` |
| `zmq_service.cpp` | `GetLapTime`→`RecordTick`；ns→us 转换 |
| `zmq_stub_conn.cpp` | `GetLapTime`→`RecordTick` |
| `zmq_stub_impl.h` | `GetTotalTime`→`GetTotalElapsedTime` |
| `kv_metrics.h/cpp` | 新增 7 个 Queue Flow Latency metrics |

## 4. 兼容性

- `ENABLE_PERF=true`：行为不变
- `ENABLE_PERF=false`：
  - `GetLapTime()`/`GetTotalTime()` 仍返回 0（保持原有行为）
  - 但 `RecordTick()`/`GetTotalElapsedTime()` 可正常记录/计算
  - RPC tracing metrics 正常工作

## 5. 相关 Tick 定义

| Tick 名称 | 进程 | 用途 |
|-----------|------|------|
| `CLIENT_ENQUEUE` | Client | 入口时间戳 |
| `CLIENT_TO_STUB` | Client | 进入 ZmqFrontend |
| `CLIENT_SEND` | Client | Socket 发送完成 |
| `CLIENT_RECV` | Client | 收到响应 |
| `SERVER_RECV` | Server | Socket 接收完成 |
| `SERVER_DEQUEUE` | Server | 队列出队 |
| `SERVER_EXEC_END` | Server | 业务处理完成 |
| `SERVER_SEND` | Server | 回复已入队 |
