# 01 · 可观测架构

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/log/access_recorder.cpp` | 客户端 access log 写入（`ds_client_access_<pid>.log`） |
| `src/datasystem/common/log/access_point.def` | `AccessRecorderKey` 定义（`DS_KV_CLIENT_GET` 等 handle 名） |
| `src/datasystem/common/log/spdlog/` | spdlog 封装（Provider / LoggerContext / ForceFlush） |
| `src/datasystem/common/metrics/kv_metrics.{h,cpp}` | KV / ZMQ 指标 ID 与注册（Counter / Gauge / Histogram） |
| `src/datasystem/common/metrics/metrics.{h,cpp}` | 指标框架（轻量级、本地 steady_clock、周期输出） |
| `src/datasystem/common/metrics/res_metric_collector.cpp` | Worker `resource.log` 定时采集 |
| `src/datasystem/common/metrics/res_metrics.def` | `ResMetricName` 枚举顺序（决定 `resource.log` 输出顺序） |
| `src/datasystem/utils/trace.h` | `TraceGuard` / TraceID |

---

## 1. 可观测层级全景

```text
┌──────────────────────────────────────────────────────────────────────┐
│                     应用视角（Application）                          │
│   KVClient API 返回 Status（code + msg）                             │
├──────────────────────────────────────────────────────────────────────┤
│                     客户端落盘（Client）                             │
│   ds_client_access_<pid>.log  ← AccessRecorder::Record(code, ...)    │
│   应用日志（业务进程 stdout / 统一日志平台）                         │
├──────────────────────────────────────────────────────────────────────┤
│                     服务端日志与指标（Worker）                       │
│   datasystem_worker.*.log       ← spdlog（ERROR/WARN/INFO）           │
│   access.log                    ← 单请求 action + 耗时                │
│   requestout.log                ← 每次调 etcd/OBS 的请求             │
│   resource.log                  ← ResMetricCollector 周期输出         │
│   metrics in-memory             ← datasystem::metrics（Counter/...）  │
├──────────────────────────────────────────────────────────────────────┤
│                     跨进程追踪（Trace）                              │
│   TraceGuard（SDK 侧 TraceID）→ 部分 Worker 日志透传                 │
└──────────────────────────────────────────────────────────────────────┘
```

每条失败定位至少要有 **三类证据**：

1. **Status + access log 第一列 code**（应用侧看到的码）
2. **应用日志 / Worker 日志**（原文与关键词）
3. **metrics / resource.log**（聚合口径，用来判断影响面和性能）

---

## 2. 客户端 access log

**文件名**：`{log_dir}/ds_client_access_{pid}.log`（环境变量可覆盖名）

**写入点**：`src/datasystem/common/log/access_recorder.cpp::AccessRecorder::Record`：
```cpp
Record(StatusCode code, ...) → AccessRecorderManager::LogPerformance
```

**handle 名**来自 `src/datasystem/common/log/access_point.def`：

- `DS_KV_CLIENT_INIT`
- `DS_KV_CLIENT_SET` / `DS_KV_CLIENT_GET`
- `DS_KV_CLIENT_MCREATE` / `DS_KV_CLIENT_MSET` / ...
- `DS_POSIX_GET` 等

**特殊规则**：
- `KVClient::Get` 对 `K_NOT_FOUND` 的处理 —— access log 中记为 `K_OK(0)`：
  ```cpp
  // src/datasystem/client/kv_cache/kv_client.cpp (Get)
  StatusCode code = rc.GetCode() == K_NOT_FOUND ? K_OK : rc.GetCode();
  accessPoint.Record(code, ...);
  ```
  排障时若只看 access log 第一列，`K_NOT_FOUND` 看起来是成功。详见 [`03-fault-mode-library.md § FM-017`](03-fault-mode-library.md)。

---

## 3. Worker 四类日志

| 日志 | 文件 | 侧重点 |
|------|------|--------|
| 运行日志 | `datasystem_worker.*.log` | 具体 ERROR/WARN、栈、组件内部状态；**不替代** 文本日志 |
| 访问日志 | `access.log` | 单次请求成功/失败、耗时、action；与 resource 周期线对齐时间轴 |
| 请求第三方 | `requestout.log` | 每次调 etcd / OBS 等一条；适合算失败率、延迟 |
| 资源日志 | `resource.log` | `ResMetricCollector` 周期输出，字段顺序见 `res_metrics.def` |

详细字段读法见 [`../reliability/06-playbook.md § 4`](../reliability/06-playbook.md) 和本目录 [`06-dependencies/etcd.md`](06-dependencies/etcd.md)、[`05-metrics-and-perf.md`](05-metrics-and-perf.md)。

---

## 4. Metrics 框架（已落地）

**API**（`common/metrics/metrics.h`）：

```cpp
namespace datasystem::metrics {
Status Init(const MetricDesc *descs, size_t count);   // 注册
void Start();                                          // 启动周期输出线程（受 FLAGS_log_monitor 控制）
void Stop();

Counter   GetCounter(uint16_t id);     // .Inc(delta=1)  — fetch_add relaxed
Gauge     GetGauge(uint16_t id);       // .Set / .Inc / .Dec
Histogram GetHistogram(uint16_t id);   // .Observe(val)  — count+sum+max+periodMax

ScopedTimer(uint16_t id);              // 构造时 now()，析构时 Observe(elapsed_us)
std::string DumpSummaryForTest(int intervalMs = 10000);
void ResetForTest();
}
```

**热路径开销**：`Histogram::Observe()` ≈ 2×`steady_clock::now()` + 4×`atomic relaxed` ≈ 70-100 ns。

**当前已落地的 ZMQ metrics**（见 `05-metrics-and-perf.md` 完整清单）：

- `ZMQ_SEND_IO_LATENCY` / `ZMQ_RECEIVE_IO_LATENCY`（Histogram, µs）
- `ZMQ_SEND_FAILURE_TOTAL` / `ZMQ_RECEIVE_FAILURE_TOTAL` / `ZMQ_SEND_TRY_AGAIN_TOTAL` / `ZMQ_RECEIVE_TRY_AGAIN_TOTAL`（Counter）
- `ZMQ_LAST_ERROR_NUMBER`（Gauge，最近一次 errno）
- `ZMQ_NETWORK_ERROR_TOTAL`（Counter）
- `ZMQ_EVENT_DISCONNECT_TOTAL` / `ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL`（Counter）
- `ZMQ_GATEWAY_RECREATE_TOTAL`（Counter）

---

## 5. Trace

**SDK 侧**：`KVClient::Init` / 每次 API 入口调用 `TraceGuard`（见 `include/datasystem/utils/trace.h`），生成/继承 TraceID。

**跨进程透传**：当前取决于部署是否全链路透传。客户端日志通常带 TraceID 前缀；Worker 端对应日志是否带同一 ID，需确认部署配置。

**客户侧实操**：使用 TraceID 过滤日志是定位单次请求最可靠的方式。grep 模板见 [`04-triage-handbook.md § 2`](04-triage-handbook.md)。

---

## 6. PerfPoint（性能埋点，区别于 metrics）

仓库内 `PerfPoint` 走的是专用的计时体系，用于更细粒度的性能分析（非 metrics 框架）。本目录的 metrics 层与 PerfPoint 并列，互不替代：

- **metrics**：轻量 counter/gauge/histogram，支持长期趋势、告警
- **PerfPoint**：具体 API 级耗时切片，用于单次请求性能剖面

详见 [`05-metrics-and-perf.md § 2`](05-metrics-and-perf.md)。

---

## 7. 验证材料

- 运行期导出：`metrics::DumpSummaryForTest(10000)` 输出 10s 窗口摘要
- Worker `resource.log`：由 `FLAGS_log_monitor=true` + `FLAGS_log_monitor_exporter=harddisk` 启用；默认周期 10000 ms
- 故障注入串讲（历史 RFC）：[`../../rfc/2026-04-zmq-rpc-metrics/test-walkthrough.md`](../../rfc/2026-04-zmq-rpc-metrics/test-walkthrough.md)
