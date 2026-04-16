# ZMQ TCP/RPC Metrics 定界可观测方案

**仓库**：`yuanrong-datasystem`（分支 `metrics`，已包含 PR #584 metrics commit `20ce4860`）  
**依赖**：`datasystem::metrics` 轻量级框架（Counter / Gauge / Histogram + 周期 LOG(INFO) 输出）  
**关联**：URMA/TCP 定界修复需求（同目录 `urma-tcp-定界修复需求/`）

---

## 一、背景与目标

### 问题

当前 RPC 框架（基于 ZMQ）存在两类可观测性缺陷：

**A. 故障定界缺失**：
1. `zmq_msg_send` / `zmq_msg_recv` 失败无计数指标，无法从 metrics 维度发现通信故障。
2. errno 信息逐层丢失，上层多次 StatusCode 重映射后原始故障信息湮没。
3. ZMQ Monitor 事件无指标，disconnect / handshake 事件仅日志且有限频。

**B. 性能定界缺失（"自证清白"）**：
1. RPC 框架无法证明自身不是性能瓶颈——没有独立于 PerfPoint 的 zmq I/O 时延指标。
2. 序列化/反序列化耗时没有在 metrics 体系中暴露，无法与 zmq socket I/O 时延对比。
3. 当整体 RPC 延迟高时，无法快速判定瓶颈在"zmq socket 读写"还是"RPC 框架处理"。

### 目标

利用已合入的 `datasystem::metrics` 框架，**同时解决故障定界和性能定界**：

- **故障定界**：失败计数 + errno 追踪，10 秒内判定故障层
- **性能定界**：zmq I/O 时延 Histogram，一眼判断瓶颈在 socket 层还是框架层
- **RPC 框架自证清白**：`zmq.io.*_us avg >> zmq.rpc.ser/deser_us avg` 时，瓶颈在 socket/网络，非框架
- **不修改错误码**，不改 StatusCode 枚举

### 约束

| 约束 | 说明 |
|------|------|
| **只用 metrics，不用 PerfPoint** | 新增度量全部使用 `datasystem::metrics` 框架；已有 PerfPoint 保持不动 |
| **最小化热路径分支** | 成功路径的 Histogram 打点使用无分支的 inline 计时；失败路径 Counter 打点在 `rc == -1` 分支内 |
| **不依赖跨机器时钟** | 所有时延度量使用本机 `steady_clock`（单调时钟）；跨机器分析使用 delta 模式对比，不比较绝对时间戳 |
| **成功路径的 Histogram 开销可量化** | 每次 Observe ≈ 2 次 `steady_clock::now()` + 4 次 `atomic relaxed`，约 70-100ns |

---

## 二、Metrics 框架能力分析（基于当前分支实际代码）

### 2.1 API 摘要

```cpp
namespace datasystem::metrics {
Status Init(const MetricDesc *descs, size_t count); // 全量替换式注册
void Start();  // 启动周期输出线程（受 FLAGS_log_monitor 控制）
void Stop();

Counter GetCounter(uint16_t id);    // .Inc(delta=1)  — fetch_add relaxed
Gauge GetGauge(uint16_t id);        // .Set / .Inc / .Dec
Histogram GetHistogram(uint16_t id); // .Observe(val)  — count+sum+max+periodMax

// ScopedTimer: 构造时 now()，析构时 now() + Observe(elapsed_us)
ScopedTimer(uint16_t id);

std::string DumpSummaryForTest(int intervalMs = 10000);
void ResetForTest();
}
```

### 2.2 热路径开销精确分析

**`Histogram::Observe()` 的实际操作**：

```cpp
void Histogram::Observe(uint64_t value) const {
    if (Valid(id_, MetricType::HISTOGRAM)) {   // ① 1次分支（branch predictor 命中率 ~100%）
        slot.u64Value.fetch_add(1, relaxed);   // ② 1次 atomic add (~5ns)
        slot.sum.fetch_add(value, relaxed);    // ③ 1次 atomic add (~5ns)
        UpdateMax(slot.max, value);            // ④ 1次 atomic load + 条件 CAS (~5-10ns)
        UpdateMax(slot.periodMax, value);      // ⑤ 1次 atomic load + 条件 CAS (~5-10ns)
    }
}
```

**单次 ScopedTimer 总开销**：
- 构造：1 × `steady_clock::now()` ≈ 20-25ns（vDSO，无系统调用）
- 析构：1 × `steady_clock::now()` + 1 × `Observe()` ≈ 25 + 25 = 50ns
- **合计 ≈ 70-100ns/call**

**对比 zmq_msg_send/recv 典型时延**：
- 本机 IPC（inproc）：~1-5μs
- 本机 TCP loopback：~10-50μs
- 跨机 TCP：~100μs - 数十ms
- **Histogram 开销占比：0.002% ~ 10%（inproc 极端场景）**

**对比已有 PerfPoint 开销**（`#ifdef ENABLE_PERF` 时）：
- PerfPoint：2 × `steady_clock::now()` + `PerfManager::Add()`（3 atomic + 2 CAS）≈ 90-120ns
- **metrics Histogram 与 PerfPoint 开销同量级**，如果已有 PerfPoint，边际增量很小

### 2.3 关键设计特征

| 特征 | 对本方案的影响 |
|------|--------------|
| `Valid()` 内部校验 | 未 Init 时自动降级为 no-op，不会 crash |
| `Init()` 全量替换 | 所有模块 MetricDesc 需合并，或约定不同 ID 段 |
| Summary 有 Total + Delta | delta 正好是定界所需：`+0` = 正常，`+N` = 有异常 |
| Histogram 输出 count/avg/max | avg 看趋势，max 看毛刺，count 看吞吐 |
| `FLAGS_log_monitor` 开关 | 控制周期输出线程，metric 值照常累加 |

---

## 三、设计原则

1. **失败路径 Counter 零成功路径开销**。所有 Counter.Inc() 仅在 `rc == -1` 分支内触发。
2. **性能 Histogram 在成功路径有且仅有 ~70ns 开销**。使用 inline 计时（2× `steady_clock::now()` + 1× `Histogram::Observe`），无额外分支。
3. **不依赖跨机器时钟**。每台机器独立采集 `steady_clock` 时延，跨机器用 delta 模式对比，不比较绝对时间戳。时钟偏差只影响跨机器日志时间戳对齐，不影响本机 Histogram 精度。
4. **Layer 2 连接管理只采集低频异常事件**。
5. **Layer 3 队列拥塞复用已有 `CheckHWMRatio` 日志**。

---

## 四、架构：三层指标

```
┌──────────────────────────────────────────────────────────────────┐
│  已有信号: 消息队列 (zmq_service.cpp CheckHWMRatio)                │
│  → 已有 LOG(WARNING) 60%/80%/100%，不加新指标                      │
│  定界：本端队列拥塞 / 对端消费慢                                    │
├──────────────────────────────────────────────────────────────────┤
│  Layer 2: 连接管理异常事件 (低频路径)                               │
│  → gateway 重建、monitor disconnect/handshake_fail                 │
│  定界：连接不稳定 / peer 被判死                                    │
├──────────────────────────────────────────────────────────────────┤
│  Layer 1: ZMQ Socket 读写 — 故障 Counter + 时延 Histogram          │
│  → 故障 Counter: 仅失败路径 (zmq_socket_ref.cpp)                   │
│  → 时延 Histogram: zmq I/O + 序列化/反序列化 (每次调用)            │
│  定界：性能自证清白 + zmq I/O 故障                                 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 五、Metric 清单（共 13 个）

### 5.1 故障定界 Counter/Gauge（仅失败路径，成功路径零开销）

> 采集位置：`zmq_socket_ref.cpp` / `zmq_stub_conn.cpp` / `zmq_monitor.cpp`

| # | Metric Name | Type | ID | 触发条件 | 路径 |
|---|-------------|------|----|---------|------|
| 1 | `zmq_send_failure_total` | Counter | 100 | `SendMsg` 返回 -1 且 errno 非 EAGAIN/EINTR | 失败 |
| 2 | `zmq_receive_failure_total` | Counter | 101 | `RecvMsg` 返回 -1 且 errno 非 EAGAIN/EINTR | 失败 |
| 3 | `zmq_send_try_again_total` | Counter | 102 | `SendMsg` errno == EAGAIN | 失败 |
| 4 | `zmq_receive_try_again_total` | Counter | 103 | `RecvMsg` errno == EAGAIN 且 blocking 模式 | 失败 |
| 5 | `zmq_network_error_total` | Counter | 104 | errno 属于网络类 | 失败 |
| 6 | `zmq_last_error_number` | Gauge | 105 | 最近一次硬失败的 errno | 失败 |
| 7 | `zmq_gateway_recreate_total` | Counter | 106 | gateway 重建成功 | 低频 |
| 8 | `zmq_event_disconnect_total` | Counter | 107 | `OnEventDisconnected` | 低频 |
| 9 | `zmq_event_handshake_failure_total` | Counter | 108 | handshake 失败 | 低频 |

### 5.2 性能定界 Histogram（"自证清白"，成功路径每次 ~70ns）

> 采集位置：`zmq_socket_ref.cpp`（I/O 层）+ `zmq_common.h`（序列化层）  
> **每次调用均采集**，不区分成功/失败，提供完整时延分布

| # | Metric Name | Type | ID | 度量对象 | 开销 |
|---|-------------|------|----|---------|------|
| 10 | `zmq_send_io_latency` | Histogram | 110 | `zmq_msg_send` 系统调用耗时 | ~70ns/call |
| 11 | `zmq_receive_io_latency` | Histogram | 111 | `zmq_msg_recv` 系统调用耗时 | ~70ns/call |
| 12 | `zmq_rpc_serialize_latency` | Histogram | 112 | Protobuf 序列化 (`SerializeToArray`) 耗时 | ~70ns/call |
| 13 | `zmq_rpc_deserialize_latency` | Histogram | 113 | Protobuf 反序列化 (`ParseFromArray`) 耗时 | ~70ns/call |

> **为什么需要 4 个 Histogram？**
>
> 仅有 zmq I/O 时延无法完成"自证清白"——需要 RPC 框架自身的时延做对比。
> 序列化/反序列化是 RPC 框架在热路径上的**唯一核心开销**（路由/队列在独立线程，不在调用线程关键路径上）。
> 4 个 Histogram 让运维可以直接从 summary 对比：
> - `zmq_send_io_latency avg=500us` vs `zmq_rpc_serialize_latency avg=15us` → **socket I/O 占比 97%，RPC 框架清白**

### 5.3 开销总结

| 路径类型 | 每次 RPC 的 metric 操作 | 总开销 |
|---------|----------------------|-------|
| **成功路径** | 4 × Histogram.Observe（send_us + recv_us + ser_us + deser_us） | **~280ns** |
| **失败路径** | 成功路径 + 1-4 × Counter.Inc + 1 × Gauge.Set | +50-100ns |
| **连接事件** | 1 × Counter.Inc | ~10ns |

> **280ns per RPC**，对比典型 zmq TCP RPC 端到端 ~200μs，**额外开销 0.14%**。
> 对比已有 PerfPoint（~200ns per RPC when ENABLE_PERF），**边际增量仅 ~80ns**。

---

## 六、性能自证清白方法论

### 6.1 核心对比指标

```
每个 metrics 周期（默认 10s）输出：

zmq_send_io_latency,count=+5000,avg=120us,max=3500us   ← socket 发送：平均 120μs
zmq_receive_io_latency,count=+5000,avg=450us,max=12000us   ← socket 接收：平均 450μs（含 blocking 等待）
zmq_rpc_serialize_latency,count=+5000,avg=12us,max=85us       ← 序列化：平均 12μs
zmq_rpc_deserialize_latency,count=+5000,avg=8us,max=60us      ← 反序列化：平均 8μs
```

**自证公式**：
```
RPC 框架在调用线程的额外开销 = ser_us + deser_us
Socket I/O 开销 = send_us + recv_us
RPC 框架占比 = (ser + deser) / (send + recv + ser + deser)
              = (12 + 8) / (120 + 450 + 12 + 8)
              = 20 / 590 = 3.4%
→ RPC 框架仅占 3.4%，瓶颈明确在 socket I/O 层
```

### 6.2 跨机器分析（不依赖时钟同步）

不同机器时钟可能有几 ms 偏差，因此**不比较跨机器的绝对时间戳**。使用以下方法：

**方法 A：各节点独立 Histogram 对比**

```
机器 A（client）:
  zmq_send_io_latency:  avg=50us      ← 本机发送快
  zmq_receive_io_latency:  avg=8000us    ← 等应答慢 → 瓶颈在对端或网络

机器 B（server）:
  zmq_receive_io_latency:  avg=30us      ← 收到快
  zmq_send_io_latency:  avg=40us      ← 发送快
  zmq_rpc_serialize_latency:  avg=10us      ← 序列化快
  → Server 侧 I/O + 框架都快，瓶颈在 A→B 网络或 B 业务逻辑
```

**方法 B：Delta 模式检测时间点**

不看绝对时间戳，只看 **delta 跳变的周期号 (cycle)**：
- 如果 A 的 `zmq_receive_io_latency max` 在 cycle=5 突然飙升
- B 的 `zmq_send_failure_total` 也在 cycle=5 附近突增
- → 同一时段，网络故障同时影响两端

> 周期号是本机 `metrics::Start()` 后的计数器，与时钟无关，**跨机器对齐靠 cycle 号或日志行号区间**。

### 6.3 定界决策树

```
  整体 RPC 延迟高？
        │
        ├── zmq_receive_io_latency avg 高 (>1ms)?
        │       │
        │       ├── zmq_send_failure_total/recv.fail > 0? → 网卡/网络故障
        │       │
        │       └── 全 +0 → 对端慢或网络延迟大
        │
        ├── zmq_rpc_serialize_latency avg 高 (>100us)?
        │       → 序列化瓶颈（消息体过大）
        │
        ├── zmq_rpc_deserialize_latency avg 高?
        │       → 反序列化瓶颈
        │
        └── 全部 avg 低?
                → 瓶颈不在 RPC 框架/zmq 层
                → 检查业务逻辑、队列 HWM 日志
```

---

## 七、定界场景矩阵（故障 + 性能）

| 场景 | zmq I/O Histogram | 序列化 Histogram | 故障 Counter | Layer 2 | 结论 |
|------|-------------------|-----------------|-------------|---------|------|
| **网卡故障** | `send_us/recv_us max` 飙升 | 正常 | `net_error`↑ `last_errno`=113 | `evt.disconn`↑ `gw_recreate`↑ | 底层网络故障 |
| **对端 hang** | `recv_us avg` 极高(秒级) | 正常 | `recv.eagain`↑ | `gw_recreate`↑ | 对端处理慢 |
| **网络延迟抖动** | `send_us/recv_us max` 有毛刺 | 正常 | 全 +0 | 正常 | 网络质量差 |
| **消息体过大** | I/O 高 | `ser_us/deser_us avg` 高 | 全 +0 | 正常 | 需要优化消息体 |
| **HWM 背压** | `send_us max` 偶尔高 | 正常 | `send.eagain`↑↑ | 正常 | ZMQ 发送队列满 |
| **本端业务慢** | 全部 avg 低 | 全部 avg 低 | 全 +0 | 全 +0 | worker 线程/业务逻辑瓶颈 |
| **RPC 框架瓶颈** | I/O 低 | `ser/deser avg` 高 | 全 +0 | 正常 | **需优化框架**（极少见场景） |

---

## 八、实施计划

### 8.1 新建 `zmq_metrics_def.h`

```cpp
// src/datasystem/common/rpc/zmq/zmq_metrics_def.h
#pragma once
#include <cerrno>
#include "datasystem/common/metrics/metrics.h"

namespace datasystem {
enum ZmqMetricId : uint16_t {
    // 故障定界 (仅失败路径)
    ZMQ_M_SEND_FAIL     = 100,
    ZMQ_M_RECV_FAIL     = 101,
    ZMQ_M_SEND_EAGAIN   = 102,
    ZMQ_M_RECV_EAGAIN   = 103,
    ZMQ_M_NET_ERROR     = 104,
    ZMQ_M_LAST_ERRNO    = 105,
    ZMQ_M_GW_RECREATE   = 106,
    ZMQ_M_EVT_DISCONN   = 107,
    ZMQ_M_EVT_HS_FAIL   = 108,
    // 性能定界 (每次调用)
    ZMQ_M_IO_SEND       = 110,
    ZMQ_M_IO_RECV       = 111,
    ZMQ_M_SER            = 112,
    ZMQ_M_DESER          = 113,
};

inline bool IsNetworkErrno(int e) {
    return e == ECONNREFUSED || e == ECONNRESET || e == ECONNABORTED ||
           e == EHOSTUNREACH || e == ENETUNREACH || e == ENETDOWN ||
           e == ETIMEDOUT || e == EPIPE || e == ENOTCONN;
}

inline const metrics::MetricDesc ZMQ_METRIC_DESCS[] = {
    {ZMQ_M_SEND_FAIL,   "zmq_send_failure_total",     metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_RECV_FAIL,   "zmq_receive_failure_total",     metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_SEND_EAGAIN, "zmq_send_try_again_total",   metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_RECV_EAGAIN, "zmq_receive_try_again_total",   metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_NET_ERROR,   "zmq_network_error_total",     metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_LAST_ERRNO,  "zmq_last_error_number",    metrics::MetricType::GAUGE,     ""},
    {ZMQ_M_GW_RECREATE, "zmq_gateway_recreate_total",   metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_EVT_DISCONN, "zmq_event_disconnect_total",   metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_EVT_HS_FAIL, "zmq_event_handshake_failure_total",   metrics::MetricType::COUNTER,   "count"},
    {ZMQ_M_IO_SEND,     "zmq_send_io_latency",    metrics::MetricType::HISTOGRAM, "us"},
    {ZMQ_M_IO_RECV,     "zmq_receive_io_latency",    metrics::MetricType::HISTOGRAM, "us"},
    {ZMQ_M_SER,          "zmq_rpc_serialize_latency",    metrics::MetricType::HISTOGRAM, "us"},
    {ZMQ_M_DESER,        "zmq_rpc_deserialize_latency",  metrics::MetricType::HISTOGRAM, "us"},
};
constexpr size_t ZMQ_METRIC_DESCS_COUNT = sizeof(ZMQ_METRIC_DESCS) / sizeof(ZMQ_METRIC_DESCS[0]);
}  // namespace datasystem
```

### 8.2 改动 `zmq_socket_ref.cpp`（I/O 计时 + 故障 Counter）

**改动后 `RecvMsg`**：

```cpp
#include "datasystem/common/rpc/zmq/zmq_metrics_def.h"

Status ZmqSocketRef::RecvMsg(ZmqMessage &msg, ZmqRecvFlags flags)
{
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(sock_ != nullptr, K_INVALID, "Null reference pointer");
    auto t0 = std::chrono::steady_clock::now();
    int rc = zmq_msg_recv(msg.GetHandle(), sock_, static_cast<int>(flags));
    auto t1 = std::chrono::steady_clock::now();
    metrics::GetHistogram(ZMQ_M_IO_RECV).Observe(
        static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count()));
    if (rc == -1) {
        int e = errno;
        if (e == EAGAIN) {
            if (flags == ZmqRecvFlags::NONE) {
                metrics::GetCounter(ZMQ_M_RECV_EAGAIN).Inc();
            }
        } else if (e != EINTR) {
            metrics::GetCounter(ZMQ_M_RECV_FAIL).Inc();
            metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(e);
            if (IsNetworkErrno(e)) {
                metrics::GetCounter(ZMQ_M_NET_ERROR).Inc();
            }
            LOG(WARNING) << FormatString("[ZMQ_RECV_FAIL] errno=%d(%s)", e, zmq_strerror(e));
        }
        return ZmqErrnoToStatus(e, "ZMQ recv msg unsuccessful", K_RPC_UNAVAILABLE);
    }
    static const auto maxInt = std::numeric_limits<int>::max();
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(rc == maxInt || static_cast<size_t>(rc) == msg.Size(), K_RUNTIME_ERROR,
                                         FormatString("Expect both values are equal. msg(%d), rc(%d)", msg.Size(), rc));
    return Status::OK();
}
```

> **关键顺序**：
> 1. `t0` = syscall 前取时间
> 2. `zmq_msg_recv` 系统调用
> 3. `t1` = syscall 后取时间（`steady_clock::now()` 不改变 errno）
> 4. `Observe(t1-t0)` — **无分支**（Valid 内部的 branch 由 predictor 消化）
> 5. `int e = errno` — 在 Observe 之后保存仍安全，因为 Observe 内部只做 atomic 操作，不调用任何可能修改 errno 的系统调用
>
> **成功路径新增操作**：仅 2 行（t0 赋值 + Observe），无 if 分支。

**改动后 `SendMsg`**：

```cpp
Status ZmqSocketRef::SendMsg(ZmqMessage &msg, ZmqSendFlags flags)
{
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(sock_ != nullptr, K_INVALID, "Null reference pointer");
    const auto msgSize = msg.Size();
    auto t0 = std::chrono::steady_clock::now();
    int rc = zmq_msg_send(msg.GetHandle(), sock_, static_cast<int>(flags));
    auto t1 = std::chrono::steady_clock::now();
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(
        static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count()));
    if (rc == -1) {
        int e = errno;
        if (e == EAGAIN) {
            metrics::GetCounter(ZMQ_M_SEND_EAGAIN).Inc();
        } else if (e != EINTR) {
            metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc();
            metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(e);
            if (IsNetworkErrno(e)) {
                metrics::GetCounter(ZMQ_M_NET_ERROR).Inc();
            }
            LOG(WARNING) << FormatString("[ZMQ_SEND_FAIL] errno=%d(%s)", e, zmq_strerror(e));
        }
        return ZmqErrnoToStatus(e, "ZMQ send msg unsuccessful", K_RPC_CANCELLED);
    }
    static const auto maxInt = std::numeric_limits<int>::max();
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(rc == maxInt || static_cast<size_t>(rc) == msgSize, K_RUNTIME_ERROR,
                                         FormatString("Expect to send out %d bytes but only got %d", msgSize, rc));
    return Status::OK();
}
```

### 8.3 改动 `zmq_common.h`（序列化/反序列化计时）

**改动后 `SerializeToZmqMessage`**：

```cpp
template <typename T>
inline Status SerializeToZmqMessage(const T &pb, ZmqMessage &dest)
{
    PerfPoint point(PerfKey::ZMQ_COM_SERIAL_TO_ZMQ_MESSAGE);   // 已有，保持不动
    auto sz = pb.ByteSizeLong();
    RETURN_IF_NOT_OK(dest.AllocMem(sz));
    auto *p = dest.Data();
    auto t0 = std::chrono::steady_clock::now();
    bool rc = pb.SerializeToArray(p, sz);
    auto t1 = std::chrono::steady_clock::now();
    metrics::GetHistogram(ZMQ_M_SER).Observe(
        static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count()));
    CHECK_FAIL_RETURN_STATUS(rc, K_RUNTIME_ERROR, "Serialization error");
    point.Record();
    return Status::OK();
}
```

> 只围绕 `SerializeToArray` 打点，不包含 `AllocMem` 和 `ByteSizeLong`，精确度量 protobuf 序列化本身。

**改动后 `ParseFromZmqMessage`**：

```cpp
template <typename T>
inline Status ParseFromZmqMessage(const ZmqMessage &msg, T &pb)
{
    PerfPoint point(PerfKey::ZMQ_COM_PARSE_FROM_ZMQ_MESSAGE);  // 已有，保持不动
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(Validator::IsInNonNegativeInt32(msg.Size()), K_INVALID, "Parse out of range.");
    auto t0 = std::chrono::steady_clock::now();
    bool rc = pb.ParseFromArray(msg.Data(), msg.Size());
    auto t1 = std::chrono::steady_clock::now();
    metrics::GetHistogram(ZMQ_M_DESER).Observe(
        static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0).count()));
    point.Record();
    RETURN_OK_IF_TRUE(rc);
    const google::protobuf::Descriptor *descriptor = pb.GetDescriptor();
    LOG(WARNING) << "Parse from message " << msg << " into protobuf " << descriptor->full_name() << " unsuccessful.";
    RETURN_STATUS(StatusCode::K_INVALID, "ParseFromZmqMessage failed.");
}
```

> 只围绕 `ParseFromArray` 打点，精确度量反序列化本身。

### 8.4 改动 `zmq_socket.cpp`（超时日志标签）

```cpp
if (status.GetCode() == K_TRY_AGAIN && blocking) {
    int64_t waitSec = std::chrono::duration_cast<std::chrono::seconds>(endTick - startTick).count();
    LOG(WARNING) << FormatString("[ZMQ_RECV_TIMEOUT] Blocking recv timed out after %d seconds", waitSec);
    RETURN_STATUS(K_RPC_UNAVAILABLE,
                  FormatString("[ZMQ_RECV_TIMEOUT] Waited %d seconds, no response from server", waitSec));
}
```

### 8.5 改动 `zmq_stub_conn.cpp`（gateway 重建 Counter）

两处 `"New gateway created"` LOG 之后加：
```cpp
metrics::GetCounter(ZMQ_M_GW_RECREATE).Inc();
```

### 8.6 改动 `zmq_monitor.cpp`（连接事件 Counter）

```cpp
void ZmqMonitor::OnEventDisconnected(...) {
    LOG(WARNING) << ...;
    metrics::GetCounter(ZMQ_M_EVT_DISCONN).Inc();
}
void ZmqMonitor::OnEventHandshakeFailedNoDetail(...)  { LOG(...); metrics::GetCounter(ZMQ_M_EVT_HS_FAIL).Inc(); }
void ZmqMonitor::OnEventHandshakeFailedProtocol(...)   { LOG(...); metrics::GetCounter(ZMQ_M_EVT_HS_FAIL).Inc(); }
void ZmqMonitor::OnEventHandshakeFailedAuth(...)       { LOG(...); metrics::GetCounter(ZMQ_M_EVT_HS_FAIL).Inc(); }
```

### 8.7 改动汇总

| 文件 | 改动性质 | 成功路径新增操作 |
|------|---------|---------------|
| 新建 `zmq_metrics_def.h` | ID 枚举 + MetricDesc 数组 | 无（纯声明） |
| `zmq_socket_ref.cpp` | I/O Histogram + 故障 Counter | **2 × `now()` + 1 × `Observe`** |
| `zmq_common.h` | 序列化/反序列化 Histogram | **2 × `now()` + 1 × `Observe`**（per ser/deser） |
| `zmq_socket.cpp` | 超时日志标签 | 无（仅超时路径） |
| `zmq_stub_conn.cpp` | gateway 重建 Counter | 无（低频事件） |
| `zmq_monitor.cpp` | 连接事件 Counter | 无（低频事件） |

---

## 九、日志标签统一

| 标签 | 含义 | 出现位置 |
|------|------|---------|
| `[ZMQ_SEND_FAIL]` | zmq_msg_send 硬失败 | `zmq_socket_ref.cpp` |
| `[ZMQ_RECV_FAIL]` | zmq_msg_recv 硬失败 | `zmq_socket_ref.cpp` |
| `[ZMQ_RECV_TIMEOUT]` | blocking recv 超时 | `zmq_socket.cpp` |

---

## 十、Metrics Summary 输出示例

### 正常运行

```
Metrics Summary, version=v0, cycle=10, interval=10000ms

Total:
zmq_send_failure_total=0
zmq_receive_failure_total=0
zmq_network_error_total=0
zmq_last_error_number=0
zmq_send_io_latency,count=50000,avg=80us,max=350us       ← socket I/O 稳定
zmq_receive_io_latency,count=50000,avg=120us,max=800us
zmq_rpc_serialize_latency,count=50000,avg=10us,max=45us         ← 序列化开销很小
zmq_rpc_deserialize_latency,count=50000,avg=8us,max=40us

Compare with 10000ms before:
zmq_send_failure_total=+0
zmq_receive_failure_total=+0
zmq_send_io_latency,count=+5000,avg=82us,max=200us        ← 本周期 I/O avg 稳定
zmq_rpc_serialize_latency,count=+5000,avg=10us,max=30us          ← 框架开销占比 < 10%
```

**结论**：I/O avg 80-120μs，框架 avg 10-8μs → **RPC 框架占比 ~10%，自证清白**。

### 网卡故障

```
Compare with 10000ms before:
zmq_send_failure_total=+15
zmq_receive_failure_total=+23
zmq_network_error_total=+38
zmq_last_error_number=+0              ← gauge delta (值=113 EHOSTUNREACH)
zmq_send_io_latency,count=+3000,avg=850us,max=50000us     ← I/O 飙升!
zmq_receive_io_latency,count=+2500,avg=3500us,max=65000us    ← I/O 飙升!
zmq_rpc_serialize_latency,count=+3000,avg=11us,max=50us          ← 框架正常
zmq_event_disconnect_total=+5
zmq_gateway_recreate_total=+3
```

**结论**：I/O max 飙升至 50-65ms，net_error +38，框架 avg 不变 → **网卡/网络层故障，RPC 框架清白**。

---

## 十一、验证方案

### 11.1 UT 验证

**测试文件**: `tests/ut/common/rpc/zmq_metrics_test.cpp`

```cpp
#include "datasystem/common/metrics/metrics.h"
#include "datasystem/common/rpc/zmq/zmq_metrics_def.h"
#include "gtest/gtest.h"
#include "ut/common.h"

namespace datasystem {
namespace ut {
namespace {

class ZmqMetricsTest : public CommonTest {
public:
    void SetUp() override {
        CommonTest::SetUp();
        metrics::ResetForTest();
        DS_ASSERT_OK(metrics::Init(ZMQ_METRIC_DESCS, ZMQ_METRIC_DESCS_COUNT));
    }
    void TearDown() override { metrics::ResetForTest(); }
};

// Case 1: 全部 13 个 metric 注册成功
TEST_F(ZmqMetricsTest, all_metrics_registered)
{
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_failure_total=0"),   std::string::npos);
    EXPECT_NE(s.find("zmq_receive_failure_total=0"),   std::string::npos);
    EXPECT_NE(s.find("zmq_network_error_total=0"),   std::string::npos);
    EXPECT_NE(s.find("zmq_last_error_number=0"),  std::string::npos);
    EXPECT_NE(s.find("zmq_send_io_latency,count=0"), std::string::npos);
    EXPECT_NE(s.find("zmq_receive_io_latency,count=0"), std::string::npos);
    EXPECT_NE(s.find("zmq_rpc_serialize_latency,count=0"), std::string::npos);
    EXPECT_NE(s.find("zmq_rpc_deserialize_latency,count=0"), std::string::npos);
}

// Case 2: 故障 Counter
TEST_F(ZmqMetricsTest, send_fail_counter)
{
    metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc();
    metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc();
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_failure_total=2"),  std::string::npos);
    EXPECT_NE(s.find("zmq_send_failure_total=+2"), std::string::npos);
}

// Case 3: recv.fail + net_error + last_errno 联动
TEST_F(ZmqMetricsTest, recv_fail_with_net_error)
{
    metrics::GetCounter(ZMQ_M_RECV_FAIL).Inc();
    metrics::GetCounter(ZMQ_M_NET_ERROR).Inc();
    metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(ECONNRESET);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_receive_failure_total=1"), std::string::npos);
    EXPECT_NE(s.find("zmq_network_error_total=1"), std::string::npos);
    EXPECT_NE(s.find("zmq_last_error_number=" + std::to_string(ECONNRESET)), std::string::npos);
}

// Case 4: Gauge 覆盖
TEST_F(ZmqMetricsTest, last_errno_gauge_override)
{
    metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(ECONNREFUSED);
    metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(EHOSTUNREACH);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_last_error_number=" + std::to_string(EHOSTUNREACH)), std::string::npos);
}

// Case 5: Delta 正确
TEST_F(ZmqMetricsTest, delta_between_dumps)
{
    metrics::GetCounter(ZMQ_M_RECV_FAIL).Inc(5);
    (void)metrics::DumpSummaryForTest();
    metrics::GetCounter(ZMQ_M_RECV_FAIL).Inc(3);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_receive_failure_total=8"),  std::string::npos);
    EXPECT_NE(s.find("zmq_receive_failure_total=+3"), std::string::npos);
}

// Case 6: 零 delta
TEST_F(ZmqMetricsTest, zero_delta_when_idle)
{
    metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc(1);
    (void)metrics::DumpSummaryForTest();
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_failure_total=+0"), std::string::npos);
    EXPECT_NE(s.find("zmq_network_error_total=+0"), std::string::npos);
}

// Case 7: IsNetworkErrno 判定
TEST_F(ZmqMetricsTest, is_network_errno)
{
    EXPECT_TRUE(IsNetworkErrno(ECONNREFUSED));
    EXPECT_TRUE(IsNetworkErrno(ECONNRESET));
    EXPECT_TRUE(IsNetworkErrno(EHOSTUNREACH));
    EXPECT_TRUE(IsNetworkErrno(ENETUNREACH));
    EXPECT_TRUE(IsNetworkErrno(ENETDOWN));
    EXPECT_TRUE(IsNetworkErrno(ETIMEDOUT));
    EXPECT_TRUE(IsNetworkErrno(EPIPE));
    EXPECT_TRUE(IsNetworkErrno(ENOTCONN));
    EXPECT_TRUE(IsNetworkErrno(ECONNABORTED));
    EXPECT_FALSE(IsNetworkErrno(EAGAIN));
    EXPECT_FALSE(IsNetworkErrno(EINTR));
    EXPECT_FALSE(IsNetworkErrno(ENOMEM));
}

// Case 8: Layer 2 连接异常
TEST_F(ZmqMetricsTest, layer2_connection_metrics)
{
    metrics::GetCounter(ZMQ_M_GW_RECREATE).Inc();
    metrics::GetCounter(ZMQ_M_EVT_DISCONN).Inc(3);
    metrics::GetCounter(ZMQ_M_EVT_HS_FAIL).Inc(2);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_gateway_recreate_total=1"), std::string::npos);
    EXPECT_NE(s.find("zmq_event_disconnect_total=3"), std::string::npos);
    EXPECT_NE(s.find("zmq_event_handshake_failure_total=2"), std::string::npos);
}

// Case 9: Histogram I/O 计时
TEST_F(ZmqMetricsTest, io_histogram_observe)
{
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(100);
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(200);
    metrics::GetHistogram(ZMQ_M_IO_RECV).Observe(500);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_io_latency,count=2,avg=150us,max=200us"), std::string::npos);
    EXPECT_NE(s.find("zmq_receive_io_latency,count=1,avg=500us,max=500us"), std::string::npos);
}

// Case 10: Histogram 序列化/反序列化计时
TEST_F(ZmqMetricsTest, ser_deser_histogram)
{
    metrics::GetHistogram(ZMQ_M_SER).Observe(10);
    metrics::GetHistogram(ZMQ_M_SER).Observe(20);
    metrics::GetHistogram(ZMQ_M_DESER).Observe(8);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_rpc_serialize_latency,count=2,avg=15us,max=20us"), std::string::npos);
    EXPECT_NE(s.find("zmq_rpc_deserialize_latency,count=1,avg=8us,max=8us"), std::string::npos);
}

// Case 11: Histogram delta — periodMax 重置
TEST_F(ZmqMetricsTest, histogram_period_max_reset)
{
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(1000);
    (void)metrics::DumpSummaryForTest();
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(200);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_io_latency,count=2,avg=600us,max=1000us"), std::string::npos);
    EXPECT_NE(s.find("zmq_send_io_latency,count=+1,avg=200us,max=200us"), std::string::npos);
}

// Case 12: 自证清白场景 — I/O 占比高
TEST_F(ZmqMetricsTest, scenario_self_prove_innocent)
{
    for (int i = 0; i < 100; ++i) {
        metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(500);
        metrics::GetHistogram(ZMQ_M_IO_RECV).Observe(800);
        metrics::GetHistogram(ZMQ_M_SER).Observe(10);
        metrics::GetHistogram(ZMQ_M_DESER).Observe(8);
    }
    auto s = metrics::DumpSummaryForTest();
    EXPECT_NE(s.find("zmq_send_io_latency,count=100,avg=500us"), std::string::npos);
    EXPECT_NE(s.find("zmq_rpc_serialize_latency,count=100,avg=10us"), std::string::npos);
}

// Case 13: 并发安全
TEST_F(ZmqMetricsTest, concurrent_histogram_and_counter)
{
    const int threads = 32;
    const int loops = 500;
    std::vector<std::thread> workers;
    for (int i = 0; i < threads; ++i) {
        workers.emplace_back([&] {
            for (int j = 0; j < loops; ++j) {
                metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(100);
                metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc();
            }
        });
    }
    for (auto &w : workers) { w.join(); }
    auto s = metrics::DumpSummaryForTest();
    auto expected = std::to_string(threads * loops);
    EXPECT_NE(s.find("zmq_send_io_latency,count=" + expected), std::string::npos);
    EXPECT_NE(s.find("zmq_send_failure_total=" + expected), std::string::npos);
}

// Case 14: 未 Init 时不 crash
TEST_F(ZmqMetricsTest, noop_before_init)
{
    metrics::ResetForTest();
    metrics::GetCounter(ZMQ_M_SEND_FAIL).Inc();
    metrics::GetHistogram(ZMQ_M_IO_SEND).Observe(100);
    metrics::GetGauge(ZMQ_M_LAST_ERRNO).Set(42);
    auto s = metrics::DumpSummaryForTest();
    EXPECT_TRUE(s.empty());
}

}  // namespace
}  // namespace ut
}  // namespace datasystem
```

### 11.2 ST 验证

| ST Case | 前置 | 断言 | 验证目标 |
|---------|------|------|---------|
| **正常 RPC** | N 次正常调用 | `io.send_us`/`recv_us` count > 0, `ser_us`/`deser_us` count > 0, 所有故障 Counter = 0 | 成功路径 Histogram 正常采集 |
| **杀 server** | 正常通信后 kill server | `recv.fail` > 0 或 `recv.eagain` > 0, `gw_recreate` > 0, `io.recv_us max` 飙升 | 故障 + I/O 延迟联动 |
| **正常 I/O vs 框架比例** | 稳定负载 | `io.send_us avg` >> `ser_us avg` | 自证清白比例可观测 |
| **Summary 格式** | 等待 1 个 metrics 周期 | 日志包含 `zmq_send_io_latency,count=`, `[ZMQ_SEND_FAIL]` 可 grep | 运维可用性 |

### 11.3 性能开销验证

```
测试方式：
1. 基线：无 metrics Init，运行 10 万次 RPC，记录吞吐 (msg/s) 和 avg latency
2. 对照：Init 全部 13 个 metrics，相同负载
3. 计算：(对照 latency - 基线 latency) / 基线 latency

预期：
- 额外延迟 < 300ns/RPC
- 吞吐下降 < 0.5%（对比 zmq TCP 典型 100μs+ 延迟）
```

---

## 十二、Build 改动

### CMakeLists.txt / BUILD.bazel

`zmq_metrics_def.h` 为纯 header，`zmq_socket_ref.cpp`、`zmq_stub_conn.cpp`、`zmq_monitor.cpp` 编译目标需链接 `common_metrics`。`zmq_common.h` 新增 `#include` metrics header。

```cmake
target_link_libraries(common_rpc_zmq PRIVATE ... common_metrics)
```

UT 的 `DS_UT_DEPEND_LIBS` 已包含 `common_metrics`，新增 `.cpp` 由 `GLOB_RECURSE` 自动发现。

---

## 十三、风险评估

| 风险点 | 影响 | 缓解措施 |
|--------|------|---------|
| `Init()` 全量替换 | 多模块指标需统一注册 | ID 分段：ZMQ 100-113，业务 0-99，URMA 200-299 |
| Histogram 成功路径开销 | ~280ns/RPC | 对比 zmq I/O 100μs+ 可忽略；可通过不调用 `Init()` 完全关闭 |
| `errno` 被覆盖 | Observe 后 errno 可能改变 | 已处理：`int e = errno` 在 Observe 之后但 Observe 不改 errno |
| 未 Init 时打点 | 降级为 no-op | `Valid()` 检查 `g_inited` |
| `zmq_common.h` 新增 include | 编译依赖传播 | metrics.h 本身无重量级依赖 |
| 跨机器时钟偏差 | 不影响 | 各节点独立度量，不做跨节点时间戳比较 |
| inproc 场景 I/O 极快 (1-5μs) | Histogram 开销占比升至 ~5% | inproc 通常非性能瓶颈，可接受 |

---

## 十四、与 URMA/TCP 计划的关系

| 维度 | URMA/TCP 计划 | ZMQ Metrics 计划（本文） |
|------|-------------|----------------------|
| 核心问题 | URMA 错误码语义 + 故障日志 | ZMQ 故障定界 + 性能自证清白 |
| 改动层 | `urma_manager.cpp`, `rdma_util.h` | `zmq_socket_ref.cpp`, `zmq_common.h`, `zmq_monitor.cpp` |
| 是否改错误码 | 是 | **否** |
| 指标类型 | 主要 Counter | Counter + Gauge + **Histogram** |
| 性能定界 | 不涉及 | **zmq I/O vs 序列化时延对比** |
| 跨机器分析 | 日志标签 | **delta 模式 + cycle 号** |

两个计划互补，合并后覆盖"URMA 数据面 + TCP/RPC 控制面"的完整定界需求。
