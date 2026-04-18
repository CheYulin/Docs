# 05 · Metrics 清单与性能关键路径

## 对应代码

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/metrics/metrics.{h,cpp}` | 指标框架（Counter / Gauge / Histogram + `ScopedTimer`）|
| `src/datasystem/common/metrics/kv_metrics.{h,cpp}` | KV / ZMQ 指标 ID 枚举与注册 |
| `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | ZMQ I/O 延迟与失败计数采集点 |
| `src/datasystem/common/rpc/zmq/zmq_monitor.cpp` | ZMQ 事件 metrics（disconnect / handshake failure）|
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` | `ZMQ_GATEWAY_RECREATE_TOTAL` 等 |
| `src/datasystem/common/rpc/zmq/zmq_network_errno.h` | 网络类 errno 判定 |
| `src/datasystem/common/metrics/res_metric_collector.cpp` | Worker `resource.log` 采集 |

> 落地历史见 [`../../rfc/2026-04-zmq-rpc-metrics/`](../../rfc/2026-04-zmq-rpc-metrics/README.md)。

---

## 1. ZMQ 传输层 metrics（已落地）

从 `common/metrics/kv_metrics.h` 读取 ID 枚举。以下是当前主干已有的 ZMQ 相关 metrics：

### 1.1 I/O 延迟（Histogram，单位 µs）

| Metric | 采集点 | 含义 |
|--------|--------|------|
| `ZMQ_SEND_IO_LATENCY` | `zmq_socket_ref.cpp`（`METRIC_TIMER`）| 发送到 ZMQ socket 的 I/O 时延 |
| `ZMQ_RECEIVE_IO_LATENCY` | 同上 | 从 ZMQ socket 收包的 I/O 时延 |

**自证清白**：当整体 RPC 延迟高时，对比 `ZMQ_*_IO_LATENCY` 与上层 PerfPoint 的业务耗时，可判断瓶颈在 **socket I/O 层** 还是 **框架 / 业务层**。

### 1.2 失败计数（Counter）

| Metric | 采集点 | 含义 |
|--------|--------|------|
| `ZMQ_SEND_FAILURE_TOTAL` | `zmq_socket_ref.cpp`（`rc == -1` 分支）| `zmq_msg_send` 失败 |
| `ZMQ_RECEIVE_FAILURE_TOTAL` | 同上 | `zmq_msg_recv` 失败 |
| `ZMQ_SEND_TRY_AGAIN_TOTAL` | 同上 | `errno == EAGAIN` 发送（非致命）|
| `ZMQ_RECEIVE_TRY_AGAIN_TOTAL` | 同上 | `errno == EAGAIN` 接收（非致命）|
| `ZMQ_NETWORK_ERROR_TOTAL` | 同上 + `zmq_network_errno.h` | 网络类 errno（区分网络 vs 协议 / 资源）|

### 1.3 errno 追踪（Gauge）

| Metric | 采集点 | 含义 |
|--------|--------|------|
| `ZMQ_LAST_ERROR_NUMBER` | `zmq_socket_ref.cpp`（`Set(errno)`）| 最近一次失败的 errno；分析故障时直接读这个 gauge |

> errno 语义由 OS 层给出；结合 `ZMQ_NETWORK_ERROR_TOTAL` 即可判断"是否为网络类"。

### 1.4 事件侧（Counter）

| Metric | 采集点 | 含义 |
|--------|--------|------|
| `ZMQ_EVENT_DISCONNECT_TOTAL` | `zmq_monitor.cpp` | ZMQ Monitor 断连事件 |
| `ZMQ_EVENT_HANDSHAKE_FAILURE_TOTAL` | 同上 | ZMQ Monitor 握手失败事件 |

### 1.5 网关重建（Counter）

| Metric | 采集点 | 含义 |
|--------|--------|------|
| `ZMQ_GATEWAY_RECREATE_TOTAL` | `zmq_stub_conn.cpp:383` | 网关通道重建次数，与长期连接稳定性相关 |

---

## 2. KV 业务 metrics（已落地）

`common/metrics/kv_metrics.h` 中 `KvMetricId` 除 ZMQ 外的关键业务指标（现有代码，节选）：

| 类别 | 示例 metric | 采集点 |
|------|-------------|--------|
| KV Client 请求总数 / 错误 | `CLIENT_PUT_REQUEST_TOTAL`、`CLIENT_PUT_ERROR_TOTAL`、`CLIENT_GET_REQUEST_TOTAL`、`CLIENT_GET_ERROR_TOTAL` | `src/datasystem/client/kv_cache/kv_client.cpp`（`METRIC_INC` / `METRIC_ERROR_IF`）|
| URMA 相关 | 见 `kv_metrics.h` 中 URMA 段 | `urma_manager.cpp` |

> 完整列表请在代码中 grep `KvMetricId::` 获取；本文不逐条列，避免与代码漂移。

---

## 3. Worker `resource.log`（周期聚合）

**开关**：gflag `log_monitor=true`（默认）
**周期**：`log_monitor_interval_ms` 默认 10000 ms
**导出**：`log_monitor_exporter=harddisk` 时写入 `{log_dir}/resource.log`
**字段顺序**：严格以 `src/datasystem/common/metrics/res_metrics.def` 为准

字段读法与 22 个指标解释见 [`../reliability/06-playbook.md § 4`](../reliability/06-playbook.md)。关键条目：

| 顺序 | 指标 | 定位价值 |
|------|------|----------|
| 1 | `SHARED_MEMORY` | 共享内存使用率 |
| 2 | `SPILL_HARD_DISK` | Spill 磁盘用量 |
| 3 | `ACTIVE_CLIENT_COUNT` | 已建连客户端数（连接泄漏线索）|
| 6-9 | `*_SERVICE_THREAD_POOL` | RPC 线程池 `idle/current/max/waiting/rate` |
| 10-11 | `ETCD_QUEUE`、`ETCD_REQUEST_SUCCESS_RATE` | etcd 控制面健康 |
| 22 | `OC_HIT_NUM` | `mem/disk/l2/remote/miss` 五元组 |

---

## 4. 性能关键路径

### 4.1 路径拆解（与调用链对照）

结合 [`02-call-chain-and-syscalls.md`](02-call-chain-and-syscalls.md) 与 `workbook/` Sheet4：

- **读路径**：`client1 → worker1` → `worker1 → worker2` → `worker1 → worker3` → `worker3(URMA)` → `client1 解析`
- **写路径**：`client1 → worker1` 控制面 + `worker1 → worker3` 数据面

### 4.2 核心判定

| 信号 | 结论 | 下一步 |
|------|------|--------|
| P99 上升 + 重试增多 | RPC / 网络 / Worker 排队 | 查 `ZMQ_*_IO_LATENCY`、`*_TRY_AGAIN_TOTAL`；Worker `resource.log` 线程池 waiting |
| `fallback to TCP/IP payload` 日志增多 | URMA 退化导致 CPU 拷贝放大 | 查 UB 池容量、UMDK 驱动；性能告警 PA-003 |
| context switch（cswch）异常升高 + futex 热点 | 锁竞争 / 线程池配置 / 阻塞 syscall | 参考 [`../reliability/deep-dives/client-lock-rpc-logging.md`](../reliability/deep-dives/client-lock-rpc-logging.md) |
| `Failed to wait jfc / poll jfc` 频率上升 | URMA CQ 等待异常 | 检查设备或链路抖动；查 `resource.log` 时间线 |

---

## 5. 采集命令（按优先级）

### 5.1 基础（必做）

```bash
# 线程 / CPU
top -H -p <worker_pid>
pidstat -u -p <worker_pid> 1

# 上下文切换
pidstat -w -p <worker_pid> 1

# 日志关键词
grep -E "RPC timeout|Retry|fallback to TCP/IP payload|poll jfc|wait jfc" worker.log sdk.log
```

### 5.2 syscall 与阻塞

```bash
strace -f -tt -T -p <worker_pid> -e trace=network,ipc,memory
# 重点看：recvmsg / sendmsg / futex / epoll_wait / mmap
```

### 5.3 若有 perf

```bash
perf stat -p <pid> -e context-switches,cpu-migrations,cache-misses,cycles,instructions -- sleep 30
perf top -p <pid>
perf record -g -p <pid> -- sleep 30 && perf report
```

### 5.4 运行期 metrics 导出

```cpp
// 代码调用
std::string dump = datasystem::metrics::DumpSummaryForTest(10000);
```

---

## 6. ST 验证建议

- **读**：`tests/st/client/object_cache/client_get_test.cpp`
- **写**：`tests/st/client/kv_cache/kv_client_mset_test.cpp`

建议流程：

1. 启动 worker + SDK 测试
2. 同时采集 `pidstat / top / strace`
3. 对齐日志时间窗，映射到 `workbook/sheet1-call-chain.md` + Sheet4（性能关键路径）
4. 输出结论：瓶颈段位 + 责任域（RPC / OS / URMA / 系统逻辑）

---

## 7. 自动化判定思路

将日志与系统指标统一成一条记录：

```text
time, interface, stage, location, status_code, keyword, cswch, nvcswch, cpu, syscall_hotspot
```

判定规则示例：

- 命中 `fallback to TCP/IP payload` 且 `cpu%`、`memcpy` 上升 → **URMA 降级导致性能退化**
- `1001 / 1002` 增多且 worker 入口日志减少 → **client1 → worker1 控制面瓶颈**
- `cswch / nvcswch` 异常升高 + futex 热点 → **线程 / 锁竞争瓶颈**

---

## 8. metrics 热路径开销

`Histogram::Observe()` 的实际操作（`metrics.h`）：

```cpp
void Histogram::Observe(uint64_t value) const {
    if (Valid(id_, MetricType::HISTOGRAM)) {   // 1 次分支（branch predictor 命中率 ~100%）
        slot.u64Value.fetch_add(1, relaxed);   // 1 次 atomic add (~5 ns)
        slot.sum.fetch_add(value, relaxed);    // 1 次 atomic add (~5 ns)
        UpdateMax(slot.max, value);            // 1 次 atomic load + 条件 CAS (~5-10 ns)
        UpdateMax(slot.periodMax, value);      // 1 次 atomic load + 条件 CAS (~5-10 ns)
    }
}
```

每次 `Observe` ≈ **70-100 ns**（2×`steady_clock::now()` + 4×`atomic relaxed`），对热路径影响可忽略。
