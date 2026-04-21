# 09 · 可观测用例构造与验证指南

> **文档定位**：把 `08-fault-triage-consolidated.md` 的"看日志/metric 做定界"结论**反向转成**：怎么在测试里**故意造出**每一种现象，以及用哪些**可自动化的判据**证明定界所依赖的观测能力真的生效。
>
> **面向读者**：ST/性能测试工程师、PR 发起者、值班现场联调。
>
> **使用姿势**：本文不是"从 0 开始学习 KV Worker"的入门。阅读前应先读：
> - [`04-triage-handbook.md`](04-triage-handbook.md) § 2 Trace 粒度 SOP
> - [`07-pr-metrics-fault-localization.md`](07-pr-metrics-fault-localization.md) § 3 场景 × Metrics × Log 标签对照表
> - [`08-fault-triage-consolidated.md`](08-fault-triage-consolidated.md) § 2~§6 分域速判/分流/落点
>
> **每一条故障场景给出**：故障类（A/B/C/D）→ 注入方式 → 期望日志标签 → 期望 metric delta → 期望 Status 码 → 自动化判据 → 反例排查。

## 对应代码

| 位置 | 作用 |
|------|------|
| `tests/st/common/rpc/zmq/zmq_metrics_fault_test.cpp` | `ZmqMetricsFaultTest` ST，样板 ST（ZMQ 13 条 metric 故障四场景） |
| `tests/st/client/kv_cache/kv_client_mset_test.cpp` | KV 端到端写 ST，用来驱动 KV 业务面 metrics |
| `src/datasystem/common/inject/inject_point.h` | `INJECT_POINT` / `INJECT_POINT_NO_RETURN`（单元/ST 里注入故障的唯一门面） |
| `src/datasystem/common/metrics/metrics.h` | `metrics::DumpSummaryForTest(intervalMs)` —— ST 里拿 Summary 字符串的标准接口 |
| `src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | ZMQ I/O 埋点 + `[ZMQ_*_FAILURE_TOTAL]` / `[ZMQ_RECV_TIMEOUT]` |
| `src/datasystem/common/rdma/urma_manager.cpp` | URMA 事件处理与 `[URMA_*]` 日志源 |
| `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp` / `unix_sock_fd.cpp` | `[TCP_*]` / `[UDS_*]` / `[SOCK_*]` / `[REMOTE_*]` / `[SHM_FD_TRANSFER_FAILED]` |
| `src/datasystem/common/log/access_recorder.cpp` | access log 抓取点（code、handleName、respMsg） |
| `vibe-coding-files/scripts/testing/verify/` | 已落地的端到端/离线自动化校验脚本（`verify_*` / `validate_*` / `run_*`） |

---

## 1. 可观测能力 × 用例证据 总表

把"能排查 → 因为看得见"这件事拆成 4 个维度。用例里**每个维度**都要有证据，缺一算半成品。

| 维度 | 证据形态 | 在测试中如何取 | 自动判定 |
|------|---------|--------------|---------|
| **1. 结构化日志标签** | `[...]` 前缀字符串出现/不出现 | 捕获 stderr/glog 的日志文件；`grep -E '\[...\]'` | `validate_urma_tcp_observability_logs.sh`；自定义 `grep -c` 断言 |
| **2. Metrics Counter delta** | `Compare with Xms before:` 段里 `metric=+N` | 进程内 `metrics::DumpSummaryForTest(ms)`；或日志中的 `Metrics Summary` 块 | `ExtractMetricValue(dump, key)`（见 `zmq_metrics_fault_test.cpp`） |
| **3. Histogram 分布** | `count/avg/max` 三元组 | 同上 | avg/max 阈值断言；两个 histogram 比值 |
| **4. Status 错误码** | `Status::GetCode()` 数值 + `GetMsg()` 片段 | SDK 返回值直接断言；access log 第一列 | `EXPECT_EQ(rc.GetCode(), K_*)`；`EXPECT_THAT(rc.GetMsg(), HasSubstr(...))` |

**陷阱清单（务必写进用例备注）**：

1. **K_NOT_FOUND → K_OK 陷阱**：`KVClient::Get` 在 `kv_client.cpp:187-189` 把 `K_NOT_FOUND` 显式改成 `K_OK` 记进 access log。**断言 Get 不存在对象时应断 `rc.GetCode()==K_NOT_FOUND`，不要用 access log 第一列**。
2. **Client stub 使用 `DONTWAIT + poll` 主路径**：服务端慢导致的超时不会让 `zmq_receive_failure_total` 增长。**期望该 counter=0 + client 侧 `K_RPC_DEADLINE_EXCEEDED` 是正确的"对端慢"断言**（见 `zmq_metrics_fault_test.cpp` 顶部 PURPOSE 注释）。
3. **`zmq_receive_try_again_total` 仅在 blocking 模式计数**（`flags==NONE`，`zmq_socket_ref.cpp:158`）。stub 场景下永远 0，不要把它当超时断言。
4. **Histogram delta 的 `max` 是 `periodMax`**（每次 dump 后 `exchange(0)`），不是累计 max。跨周期比较必须锚定同一个 cycle=N。
5. **`log_monitor_interval_ms` 默认 10000ms**。用例 wall time 必须 **≥ 2× 周期 + ~15s 缓冲**，否则 grep 到空的 Summary 是常见翻车。
6. **`log_monitor_exporter` 必须是 `"harddisk"`**；传 `"backend"` 会让 `ResMetricCollector::Init` 返回 `K_INVALID`（`res_metric_collector.cpp:60-69`）。用例若想把指标写到磁盘，**就是这一个值**。

---

## 2. 用例骨架模板

一个可观测故障 ST 的通用五段结构（以 `ZmqMetricsFaultTest` 为模板抽象）：

```cpp
// ① 清空基线：重置 metrics 并记录起点
(void)metrics::InitKvMetrics();  // 幂等；第一次初始化后可再调用以拿到 DumpSummary 基线
std::string baseline = metrics::DumpSummaryForTest(/*intervalMs=*/0);
uint64_t base_send_fail = ExtractMetricValue(baseline, "zmq_send_failure_total");

// ② 注入故障：INJECT_POINT 或外部故障源（iptables / tc / kill）
InjectPoint::Set("ZmqFrontend.WorkerEntry.FailInit");  // 示意
// or: system("iptables -A OUTPUT -p tcp --dport <port> -j DROP");

// ③ 触发业务流量：执行 SDK 调用，拿 Status
Status rc = client.Get(keys, buffers);

// ④ 取证据：dump metrics + 捕获日志
std::string dump = metrics::DumpSummaryForTest(/*intervalMs=*/1000);
uint64_t after_send_fail = ExtractMetricValue(dump, "zmq_send_failure_total");
std::string log_contents = ReadLogFile(log_path);  // helper

// ⑤ 断言（四维）
EXPECT_EQ(rc.GetCode(), K_RPC_UNAVAILABLE);                    // Status 维
EXPECT_THAT(log_contents, HasSubstr("[ZMQ_SEND_FAILURE_TOTAL]")); // 日志标签维
EXPECT_GT(after_send_fail - base_send_fail, 0U);               // Counter delta 维
EXPECT_GT(ExtractMetricValue(dump, "zmq_send_io_latency.count"), 0U); // Histogram 维
```

**关键原则**：
- **故障注入 → 断言** 之间要走**完整业务路径**（`client.Get/Put` 级），不要只是 unit 层 mock。不然 metric 埋点走不到。
- **业务流量 ≥ `log_monitor_interval_ms` × 2**，否则可能遇到 "周期 Summary 已触发但未 flush" → grep 为空。
- **同一个用例要覆盖正常+故障两段**（先跑基线、再注入故障、再跑），否则无法证明"是**本次故障**造成了 delta"。

---

## 3. A 类（用户层）用例构造

### A-1. `K_INVALID`：参数非法

| 注入 | Status | Log | Metric |
|------|--------|-----|--------|
| 空 key / `dataSize=0` / keys 与 sizes 长度不等 / batch > `OBJECT_KEYS_MAX_SIZE_LIMIT` | `K_INVALID(2)` | Client access log `respMsg` 含 `The objectKey is empty` / `dataSize should be bigger than zero` / `length not match` | `client_put_error_total` +1（或 `client_get_error_total`） |

**ST 示例**：

```cpp
std::vector<std::string> keys = {""};                  // 空 key
std::vector<const void*> bufs = {nullptr};
std::vector<uint64_t> sizes = {0};
Status rc = client.MSet(keys, bufs, sizes);
EXPECT_EQ(rc.GetCode(), K_INVALID);
EXPECT_THAT(rc.GetMsg(), ::testing::HasSubstr("The objectKey is empty"));

// 断言 metric 错误计数 +1
std::string dump = metrics::DumpSummaryForTest(0);
EXPECT_GE(ExtractMetricValue(dump, "client_put_error_total"), base_put_error + 1);
```

### A-2. `K_NOT_FOUND`：对象不存在（陷阱）

```cpp
Status rc = client.Get({"absent_key"}, buffers);
EXPECT_EQ(rc.GetCode(), K_NOT_FOUND);     // ← 必须这样断
// 不要用 access log 第一列做断言，因为会被改成 K_OK（kv_client.cpp:187）
EXPECT_THAT(rc.GetMsg(), ::testing::AnyOf(
    ::testing::HasSubstr("Can't find object"),
    ::testing::HasSubstr("NOT_FOUND")));
```

### A-3. `K_NOT_READY`：未 `Init`

```cpp
KVClient client;  // 没调 Init
Status rc = client.MSet(...);
EXPECT_EQ(rc.GetCode(), K_NOT_READY);
```

---

## 4. B 类（OS 层-控制面）用例构造

### B-1. TCP 建连失败 → `[TCP_CONNECT_FAILED]` / `K_RPC_UNAVAILABLE`

**注入方式**（任选一个）：

```bash
# 方式 1：iptables 拒绝出站（同机/跨机通用）
iptables -A OUTPUT -p tcp --dport <worker_port> -j REJECT

# 方式 2：指向不存在的端口（Worker 未起）
--worker_address=127.0.0.1:0  # 或 :65531 类似关停端口
```

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_RPC_UNAVAILABLE(1002)` |
| SDK `rc.GetMsg()` | 含 `[TCP_CONNECT_FAILED]` 或 `[UDS_CONNECT_FAILED]`（同机 UDS 路径） |
| Worker log / Client log | `grep -E '\[TCP_CONNECT_FAILED\]'` 命中 ≥ 1 |
| Metric | `zmq_last_error_number` gauge 非 0（典型 111=`ECONNREFUSED`） |

### B-2. 对端 crash / 半开连接 → `[TCP_CONNECT_RESET]` / `zmq_gateway_recreate_total++`

**注入**：`kill -9 <worker_pid>`，SDK 再发请求。

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_RPC_UNAVAILABLE` |
| Log | `[TCP_CONNECT_RESET]` 或 `[RPC_SERVICE_UNAVAILABLE]` |
| Metric | `zmq_gateway_recreate_total` delta > 0；`zmq_event_disconnect_total` 可能 +N（异步，可迟到） |
| Metric | `zmq_last_error_number` 可能为 104=`ECONNRESET` |

**参考代码**：`zmq_metrics_fault_test.cpp` 的 `ServerKilled` 场景。

### B-3. ZMQ 发送硬失败 → `[ZMQ_SEND_FAILURE_TOTAL]` / `zmq_send_failure_total++`

**注入**：`iptables -A OUTPUT -p tcp --dport <port> -j DROP`（让 send() 返回非 EAGAIN/EINTR 错）。

| 判据 | 期望值 |
|------|-------|
| Log | `[ZMQ_SEND_FAILURE_TOTAL] errno=<n>(<str>)` |
| Metric | `zmq_send_failure_total` delta > 0；`zmq_network_error_total` delta > 0（若 `IsZmqSocketNetworkErrno` 命中） |
| Metric | `zmq_last_error_number` gauge 落在网络 errno（如 113=`EHOSTUNREACH`） |

### B-4. RPC 应答超时（服务端慢）→ `[RPC_RECV_TIMEOUT]` / **所有 ZMQ fault counter 保持 0**

**注入**：
- 用 `tc qdisc add dev eth0 root netem delay <timeout+100ms>ms`，或
- 用 `INJECT_POINT` 在服务端插入 sleep：

```cpp
// Worker 侧
INJECT_POINT("WorkerOcServiceGetImpl.Get", [](int32_t delayMs) {
    std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));
});
```

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_RPC_DEADLINE_EXCEEDED(1001)` 或 `K_TRY_AGAIN(19)` |
| Log | `[RPC_RECV_TIMEOUT]`（由 `zmq_stub_impl.h:~143` / `zmq_msg_queue.h:~890` 打出） |
| Metric | `zmq_receive_failure_total` delta == **0** |
| Metric | `zmq_send_failure_total` delta == **0** |
| Metric | `zmq_receive_io_latency.avg` 升高 |

> 这是典型"对端慢 vs 网络坏"分流示例。**=0 是关键断言**，不是"没加上"。

### B-5. 建连等待超时 → `[SOCK_CONN_WAIT_TIMEOUT]` / `[REMOTE_SERVICE_WAIT_TIMEOUT]`

**注入**：
```cpp
InjectPoint::Set("SockConnEntry.WaitForConnected.SetTimeout", /*timeMs=*/1);
// 或
InjectPoint::Set("ZmqBaseStubConn.WaitForConnect");
```

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_RPC_UNAVAILABLE` |
| Log | `[SOCK_CONN_WAIT_TIMEOUT]` **或** `[REMOTE_SERVICE_WAIT_TIMEOUT]`（`zmq_stub_conn.cpp:1503,1509`） |

> ⚠️ 旧内部文档写 `[TCP_CONN_WAIT_TIMEOUT]` 是**错的**，代码里不存在该前缀，用上述两个之一断言。

### B-6. UDS / SHM fd 传递失败 → `[UDS_CONNECT_FAILED]` / `[SHM_FD_TRANSFER_FAILED]`

**注入**：构造无效 socket path；或 `INJECT_POINT("worker.bind_unix_path")` 让 Worker 侧故意 bind 失败。

| 判据 | 期望值 |
|------|-------|
| Log | `[UDS_CONNECT_FAILED]`（`unix_sock_fd.cpp:437`）或 `[SHM_FD_TRANSFER_FAILED]`（`client_worker_common_api.cpp:319`） |
| SDK `rc.GetCode()` | `K_RPC_UNAVAILABLE` |

### B-7. 1002 桶码"至少 3 种前缀"验收（PR #583 验收项）

```bash
# 运行完 ST 之后：
bash vibe-coding-files/scripts/testing/verify/validate_urma_tcp_observability_logs.sh <log-dir>
# 判据：日志里至少 3 种不同的 [...]前缀出现（PR 验收门槛）
```

---

## 5. C 类（URMA 层）用例构造

### C-1. URMA 需要重连 → `[URMA_NEED_CONNECT]` / `K_URMA_NEED_CONNECT(1006)`

**注入**：`kill -9` 远端 Worker 后 SDK 再发 UB 请求；或 `INJECT_POINT` 让 `CheckUrmaConnectionStable` 走"无连接"分支。

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_URMA_NEED_CONNECT(1006)` 或 `K_URMA_TRY_AGAIN(1008)`（SDK 内部重试） |
| Log | `[URMA_NEED_CONNECT]`，含 `remoteAddress=` / `remoteInstanceId=`（`urma_manager.cpp::CheckUrmaConnectionStable` 三个分支） |
| 自动校验 | `validate_urma_tcp_observability_logs.sh`：`URMA_NEED_CONNECT count > 0` + `remoteAddress=` 出现 |

### C-2. JFS 重建 → `[URMA_RECREATE_JFS]` / `cqeStatus=9`

**注入**：构造 cqeStatus=9 事件；或 `INJECT_POINT` 模拟 ACK timeout。

| 判据 | 期望值 |
|------|-------|
| Log | `[URMA_RECREATE_JFS] requestId=... op=READ/WRITE remoteAddress=... cqeStatus=9` |
| Log | 可能伴随 `[URMA_RECREATE_JFS_FAILED]` / `[URMA_RECREATE_JFS_SKIP]` |
| Metric | `worker_urma_write_latency` max 飙升；`client_*_urma_*_bytes` 短暂下跌再回升 |

### C-3. URMA CQ poll 异常 → `[URMA_POLL_ERROR]`

**注入**：让 `PollJfcWait` 返回非 `K_TRY_AGAIN` 的错误码（`INJECT_POINT` 替换返回值）。

| 判据 | 期望值 |
|------|-------|
| Log | `[URMA_POLL_ERROR] PollJfcWait failed: <status>, success=<N>, failed=<M>`（`urma_manager.cpp:625`） |

### C-4. URMA 等待超时 → `[URMA_WAIT_TIMEOUT]` / `K_URMA_WAIT_TIMEOUT(1010)`

**注入**：`INJECT_POINT` 在 `WaitToFinish` 中模拟 `timeoutMs<0`；或使远端真正不响应 UB 事件。

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_URMA_WAIT_TIMEOUT(1010)` |
| Log | `[URMA_WAIT_TIMEOUT] timedout waiting for request: <requestId>` |
| 行为 | 进入 `RetryOnRPCErrorByTime`（`rpc_util.h`） |

### C-5. UB 降级 TCP → `fallback to TCP/IP payload`

**注入**：
- `ifconfig ub0 down` / 拔 UB 插线；
- 或在 client 侧让 `PrepareUrmaBuffer` 返回失败（构造 UB 池超限 / 分配失败）。

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | **仍为 `K_OK`**（降级成功，业务不挂） |
| Log | `..., fallback to TCP/IP payload.`（`client_worker_base_api.cpp:117,131`） |
| Metric | `client_*_urma_*_bytes` delta **= 0** |
| Metric | `client_*_tcp_*_bytes` delta **> 0** |
| 派生 | `worker_tcp_write_latency` 开始有分布 |

> 这是功能正确、性能退化的典型。**PA-003 告警条件**：`fallback to TCP/IP payload / 总 Get 请求 > 基线 3σ`。

---

## 6. D 类（组件层）用例构造

### D-1. Worker 退出 → `[HealthCheck] Worker is exiting now` / `K_SCALE_DOWN`

**注入**：优雅关闭 Worker（`worker_oc_service_impl.cpp::SetExiting`）。

| 判据 | 期望值 |
|------|-------|
| Worker Log | `[HealthCheck] Worker is exiting now` |
| SDK `rc.GetCode()` | `K_SCALE_DOWN(31)`；在 KV Get 批量路径 `last_rc==K_SCALING` 时 Get 返回 OK 但 per-object 缺失（见 `04-triage-handbook § 10.3`） |
| Metric | `worker_object_count` gauge 下降 |

### D-2. 心跳超时 → `Cannot receive heartbeat from worker.` / `K_CLIENT_WORKER_DISCONNECT(23)`

**注入**：`kill -STOP <worker_pid>` 让 Worker 不响应心跳。

| 判据 | 期望值 |
|------|-------|
| SDK `rc.GetCode()` | `K_CLIENT_WORKER_DISCONNECT(23)` |
| Client Log | `Cannot receive heartbeat from worker.`（`listen_worker.cpp:114`） |
| 恢复 | `kill -CONT <worker_pid>` 心跳自动恢复 |

### D-3. etcd 超时 / 不可用

**注入**：`systemctl stop etcd`。

| 判据 | 期望值 |
|------|-------|
| Worker Log | `etcd is timeout`（Master 视角，`replica_manager.cpp:1190`）**或** `etcd is unavailable`（Worker 视角，`worker_oc_service_get_impl.cpp:1631`）。**两种都要 grep** |
| SDK `rc.GetCode()` | `K_MASTER_TIMEOUT(25)` 或 `K_RPC_UNAVAILABLE(1002)`（取决于是 Master 还是 Worker 抛出） |
| resource.log | `ETCD_REQUEST_SUCCESS_RATE` 明显下降 |

### D-4. SHM 钉住泄漏 → `worker_shm_ref_table_bytes` 涨 + `worker_object_count` 持平

**注入**：构造 client 侧 不释放 ref 的场景（忘记 `DecRef`）/或 `INJECT_POINT` 跳过 `RemoveClientRefs`。

| 判据 | 期望值 |
|------|-------|
| Metric gauge | `worker_shm_ref_table_bytes` 持续上涨 |
| Metric counter 比对 | `worker_allocator_alloc_bytes_total` delta > `worker_allocator_free_bytes_total` delta |
| Metric counter 比对 | `worker_shm_unit_created_total` > `worker_shm_unit_destroyed_total` |
| Metric gauge | `worker_object_count` 持平或下降 |
| resource.log | `SHARED_MEMORY` 占用率上升 |

> **警告**：原 `fema-intermediate/10` 文档列的 `worker_shm_alloc_total` / `worker_shm_free_total` / `worker_shm_alloc_bytes` / `worker_shm_free_bytes` / `worker_shm_unit_ref_count` **在当前代码中不存在**，用例里不要 grep 这些名字。正确名见本文上表和 [`08-fault-triage-consolidated.md § 4.4`](08-fault-triage-consolidated.md)。

**参考脚本**：`run_shm_leak_metrics_remote.sh`。

### D-5. `K_FILE_LIMIT_REACHED(18)`：fd 耗尽

**注入**：`ulimit -n 64`，然后并发开大量客户端。

| 判据 | `rc.GetCode() == 18`（注意：**不是 20**） |

### D-6. mmap 失败

**注入**：`ulimit -l 0`。

| 判据 | Log `Get mmap entry failed`；`rc.GetCode() == K_RUNTIME_ERROR(5)` |

---

## 7. 注入手段速查

| 注入方式 | 适用面 | 优点 | 注意事项 |
|---------|-------|------|---------|
| **`INJECT_POINT` / `INJECT_POINT_NO_RETURN`** | 单进程代码级故障注入 | 精确、可关闭；支持 lambda | 只在 `USE_INJECTION` 编译条件下生效；release 构建会被 `#ifdef` 掉 |
| **iptables** | 所有 TCP 场景 | 主机级 drop/reject | `-A` 之后必须 `-D`；跨机别忘两端 |
| **tc qdisc netem** | 延迟 / 丢包 / 乱序 | 模拟真实网络抖动 | `tc qdisc del dev eth0 root` 清理；Docker/K8s 中需 `NET_ADMIN` |
| **kill -9** | Worker / 对端 crash | 最真实 | 需要 k8s/调度器拉起；验收时要测自动恢复 |
| **kill -STOP / -CONT** | 挂死 Worker / 心跳场景 | 不杀进程、完整恢复 | 注意 Lease 超时窗口 |
| **`ifconfig ub0 down`** | UB 降级场景 | 直接触发 C-5 | 需要 root；验收后 `ifconfig ub0 up` |
| **`ulimit -n/-l`** | fd / mmap 场景 | 同一进程内生效 | 父子 shell 之间有继承关系，建议 `exec` 内部 ulimit |
| **`systemctl stop etcd`** | etcd 场景 | 真实 | 注意 cluster 里多节点，可能要一并 stop |

---

## 8. 自动化校验脚本对接

仓库内现有脚本（位置：`vibe-coding-files/scripts/testing/verify/`）：

| 脚本 | 目标 | 返回码判据 |
|------|------|-----------|
| `summarize_observability_log.sh <log>` | 把最新 metrics delta + 全部 `[...]` 标签命中数打成速查表 | 0 = 成功产出；观测用 |
| `verify_zmq_fault_injection_logs.sh [--run\|--remote]` | ZMQ 故障四场景（Normal / ServerKilled / ServerSlow / HeavyLoad）关键日志必须出现 | `Mandatory RESULT: X matched \| 0 missing` → 0；否则 1 |
| `validate_urma_tcp_observability_logs.sh <log-dir>` | URMA 三组日志 + 1002 桶码 ≥ 3 种前缀 | 不满足 → 非 0 |
| `run_kv_rw_metrics_remote_capture.sh` | 远端跑 `kv_client_mset_test` → 拉取 worker*/log、client 目录、跑 summarize | 产物在 `results/kv_rw_metrics_<UTC>/` |
| `run_zmq_rpc_metrics_remote.sh` | `ZmqMetricsFaultTest.*` 端到端 | 同上格式 |
| `run_shm_leak_metrics_remote.sh` | SHM 钉住场景端到端 | 同上格式 |

**新用例接入方式（两条路）**：

1. **新增独立 `validate_<topic>_logs.sh`**：参考 `validate_urma_tcp_observability_logs.sh` 的判据格式（"每一个 `[PREFIX]` 的 `grep -c` 必须 ≥ 1，否则 exit 非 0"），可被 CI 直接串接。
2. **在 ST 内部直接断言**：如 `zmq_metrics_fault_test.cpp`，用 `metrics::DumpSummaryForTest()` + `ExtractMetricValue()` 把断言写进 gtest，`bazel run` 即可。

---

## 9. 验收 Checklist（测试签字必过）

### 9.1 基础观测（任何版本发布前必须通过）

- [ ] Worker 与 Client 日志都出现 `Metrics Summary, version=v0, cycle=...`（至少 2 次，证明周期触发）
- [ ] `Total:` 段含 **≥ 54 行 metric**（当前 `KvMetricId::KV_METRIC_END=54`）；若少于 54，构建未启用 `InitKvMetrics`
- [ ] `client_put_request_total` / `client_get_request_total` `+delta > 0`（端到端有业务流量）
- [ ] `client_put_error_total` / `client_get_error_total` `+delta = 0`（正常场景下零错误）
- [ ] `access.log` 与 `ds_client_access_<pid>.log` 双边都有记录
- [ ] `resource.log` 存在且至少 22 个字段均有数据（含 `SHARED_MEMORY/ETCD_QUEUE/OC_HIT_NUM`）

### 9.2 故障注入（按故障域各至少通过一条）

| 域 | 最少通过项 | 自动化判据 |
|----|-----------|-----------|
| A 类 | 参数非法 → `K_INVALID` + `client_put_error_total +1` | gtest 断言 |
| B 类 | ZMQ 四场景任一 | `verify_zmq_fault_injection_logs.sh` Mandatory 全 matched |
| B 类 | 1002 桶码 ≥ 3 种前缀 | `validate_urma_tcp_observability_logs.sh` 满足第 4 条 |
| C 类 | URMA 三组日志都出现 | `validate_urma_tcp_observability_logs.sh` 前 3 条满足 |
| C 类 | UB 降级 → TCP bytes↑ 且 URMA bytes=0 | metrics diff 断言 |
| D 类 | Worker 退出 → `[HealthCheck]` + `K_SCALE_DOWN` | gtest + `grep` |
| D 类 | SHM 钉住 → `worker_shm_ref_table_bytes` 涨 | `run_shm_leak_metrics_remote.sh` |

### 9.3 自证清白（性能场景）

- [ ] 四个 histogram（`zmq_send_io_latency` / `zmq_receive_io_latency` / `zmq_rpc_serialize_latency` / `zmq_rpc_deserialize_latency`）全部 `count > 0`
- [ ] 按公式算出的 "RPC 框架占比" < 5%（稳态）；如 ≥ 5%，需要在用例报告里给出解释
- [ ] Trace ID 能对齐跨进程日志（`cycle=N` 或 TraceID 粘合）

---

## 10. 端到端示例：构造 ZMQ 发送失败用例

以下是一个**完整可运行**的故障用例骨架，结合 iptables + gtest + dump summary 三件套。真实形态见 `tests/st/common/rpc/zmq/zmq_metrics_fault_test.cpp`。

```cpp
TEST_F(ZmqMetricsFaultTest, SendFailure_IptablesDrop)
{
    // 1. 基线
    (void)metrics::InitKvMetrics();
    std::string baseline = metrics::DumpSummaryForTest(0);
    uint64_t base_sendfail = ExtractMetricValue(baseline, "zmq_send_failure_total");
    uint64_t base_neterr  = ExtractMetricValue(baseline, "zmq_network_error_total");

    // 2. 启动 client/server 正常连通一次（确保建连路径走过）
    ASSERT_TRUE(rpcClient_->CallUnary(...).IsOk());

    // 3. 注入：drop 掉后续发送
    const std::string kIptRule = "iptables -I OUTPUT -p tcp --dport " + std::to_string(port_) + " -j DROP";
    const std::string kIptUndo = "iptables -D OUTPUT -p tcp --dport " + std::to_string(port_) + " -j DROP";
    ASSERT_EQ(std::system(kIptRule.c_str()), 0);

    // 4. 触发业务
    Status rc;
    for (int i = 0; i < 100; ++i) {
        rc = rpcClient_->CallUnary(...);
        if (rc.IsError()) break;
    }
    std::system(kIptUndo.c_str());  // 清理

    // 5. 等待 tick 周期
    std::this_thread::sleep_for(std::chrono::seconds(2));
    std::string dump = metrics::DumpSummaryForTest(1000);

    // 6. 四维断言
    EXPECT_FALSE(rc.IsOk());
    EXPECT_EQ(rc.GetCode(), K_RPC_UNAVAILABLE);
    EXPECT_THAT(rc.GetMsg(), ::testing::HasSubstr("[ZMQ_SEND_FAILURE_TOTAL]"));

    uint64_t cur_sendfail = ExtractMetricValue(dump, "zmq_send_failure_total");
    uint64_t cur_neterr  = ExtractMetricValue(dump, "zmq_network_error_total");
    EXPECT_GT(cur_sendfail - base_sendfail, 0U) << "zmq_send_failure_total should increase";
    EXPECT_GT(cur_neterr  - base_neterr,  0U) << "network errno should be classified";

    // last_error_number 是 Gauge，断言它落在网络 errno 域
    uint64_t last_errno = ExtractMetricValue(dump, "zmq_last_error_number");
    EXPECT_TRUE(last_errno == 113 || last_errno == 101 || last_errno == 111)
        << "EHOSTUNREACH/ENETUNREACH/ECONNREFUSED expected, got " << last_errno;
}
```

**反例排查（跑不过时）**：

1. **`zmq_send_failure_total` 没涨** → 检查 iptables 是否在正确的方向/端口；检查是否 client stub 直接走了 reconnect → 看 `zmq_gateway_recreate_total` 是否反而在涨。
2. **`zmq_network_error_total` 为 0 但 `zmq_send_failure_total` 涨了** → 检查 `errno` 是否在 `zmq_network_errno.h::IsZmqSocketNetworkErrno` 白名单内。如果不是网络类 errno（比如 `EINVAL`），该 metric 不涨是正确的。
3. **`DumpSummaryForTest` 返回空** → 确认用例进程真的带了 `InitKvMetrics`；确认 `FLAGS_log_monitor=true`；确认 wall 时间 ≥ `log_monitor_interval_ms`（默认 10s）。

---

## 11. 远端执行（xqyun-32c32g）

按 `.cursor/rules/remote-dev-host.mdc`，所有**运行验证**走远端。常见命令：

```bash
# B 类：ZMQ 故障四场景（自带 bazel 路径）
bash vibe-coding-files/scripts/testing/verify/run_zmq_rpc_metrics_remote.sh

# B+C 类：KV 端到端 + 远端拉 Summary + 子进程日志 tar
bash vibe-coding-files/scripts/testing/verify/run_kv_rw_metrics_remote_capture.sh

# 离线校验（1002 桶码 + URMA）：
bash vibe-coding-files/scripts/testing/verify/validate_urma_tcp_observability_logs.sh results/kv_rw_metrics_<UTC>/cluster_logs

# D 类：SHM 钉住
bash vibe-coding-files/scripts/testing/verify/run_shm_leak_metrics_remote.sh
```

产物约定：`results/<topic>_<UTC>/` 下包含 `ds_st_full.log`、`grep_metrics_summary.txt`、`cluster_logs/`、`summary.txt`。

---

## 12. 维护约定

1. 新增一个"故障域场景"时，必须同时补齐 § 3~§ 6 对应小节的四维证据（日志、counter、histogram、Status），否则 PR 不收。
2. `INJECT_POINT` 名字与 `common/inject/inject_point.h` 的 key 保持一致；新注入点在 PR 里同步 § 7 表。
3. `[PREFIX]` 标签新增时，同步更新 [`08-fault-triage-consolidated.md § 4`](08-fault-triage-consolidated.md) 和 `validate_urma_tcp_observability_logs.sh` 白名单。
4. Metrics 增删以 `kv_metrics.cpp::KV_METRIC_DESCS` 为单一事实来源；本文 § 9.1 的"≥ 54 行"门槛随之更新。
5. 所有 ST 必须**同时包含**一个"基线正常"分支与一个"故障注入"分支，只跑一段的 PR 不收。
