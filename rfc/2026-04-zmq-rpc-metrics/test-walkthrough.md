# ZMQ Metrics 故障注入与日志定界 — 测试串讲说明

**版本**：与 `plan-zmq-rpc-metrics-定界可观测.md`、`RESULTS.md` 配套  
**适用角色**：功能测试、现场联调、CI 看护  
**目标**：在**可控故障**下，确认日志与 metrics 输出能支撑「ZMQ I/O vs RPC 框架 vs 业务/服务端」的定界；掌握**如何构造故障**与**如何判定日志有效**。

---

## 1. 为什么要做故障注入验证

仅跑「全绿 UT」只能证明代码路径存在，不能证明**故障时观测信号是否出现**。本串讲围绕仓库内 **`ZmqMetricsFaultTest`**（`ds_st`）与脚本 **`verify_zmq_fault_injection_logs.sh`**，验证：

- 故障注入分支是否打出**带标签的结构化日志**（如 `[FAULT INJECT]`、`[ISOLATION]`、`[METRICS DUMP]`）；
- **metrics 文本块**（`zmq.*=` 与 histogram 行）是否与定界结论一致；
- 可选路径上的 **`[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECV_TIMEOUT]`** 在什么故障下才会出现（避免误判「没打日志 = 没生效」）。

---

## 2. 环境与一键命令

| 项 | 说明 |
|----|------|
| 二进制 | `build/tests/st/ds_st` |
| 用例过滤 | `--gtest_filter='ZmqMetricsFaultTest.*'` |
| 日志级别 | 必须带 `--alsologtostderr`，否则 INFO 级埋点不可见 |
| 远端示例 | `ssh root@<host> 'cd .../build && ./tests/st/ds_st --gtest_filter=ZmqMetricsFaultTest.* --alsologtostderr' \| tee zmq_fault.log` |

**日志校验脚本**（仓库外脚本，便于测试统一使用）：

```bash
# 本地：对已保存的完整日志做关键字验收
bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh ./zmq_fault.log

# 远端直连跑 ds_st + 校验（需本机已配置 ssh）
bash vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh --remote
```

脚本检查项与下面 §4 四个场景一一对应；**全部 ✓ 且 exit 0** 即表示「关键日志链」完整。

---

## 3. 日志与指标：看什么、定什么界

### 3.1 三层信号（建议按顺序看）

1. **gtest 结果**：`[  PASSED  ]` / 是否有 `[  FAILED  ]` —— 行为是否符合预期。  
2. **测试注入标签**（人工串讲时先讲这一层，听众最容易跟上）：  
   - `[FAULT INJECT] ...`：说明**当前场景在模拟什么**；  
   - `[METRICS DUMP - ...]`：紧跟其后的 **Total / Compare** 块是**证据快照**；  
   - `[ISOLATION] ...`：用自然语言总结**本场景应得出的定界结论**。  
3. **ZMQ 底层告警**（不一定每个场景都有，见 §6）：  
   - `[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]`：`zmq_msg_recv/send` 返回 **-1 且 errno 非 EAGAIN/EINTR**；  
   - `[ZMQ_RECV_TIMEOUT]`：**阻塞 recv + 套接字 RCVTIMEO** 路径上的超时（与 client stub 的 **poll + DONTWAIT** 路径不同）。

### 3.2 metrics 行与故障类型对照（速查）

| 现象（日志/metrics） | 优先解读 |
|---------------------|----------|
| `zmq_gateway_recreate_total=+N`（delta 在 Compare 段） | 对端不可达或连接重建，**连接层**问题（场景：杀 server） |
| `zmq_receive_failure_total` / `zmq_send_failure_total` > 0 | **ZMQ 硬错误**，看 `zmq_last_error_number` |
| `zmq_network_error_total` > 0 | errno 属网络类，**网卡/路由/对端 reset** 方向 |
| RPC 失败但 **所有 zmq.* fault 计数仍为 0** | **ZMQ 层健康**；慢处理或 **RPC 层 poll 超时**（场景：慢 server） |
| `zmq.io.*_us` avg ≫ `zmq_rpc_serialize_latency` / `deser_us` avg | 时间主要在 **I/O 等待**，框架非主瓶颈（场景：高压自证） |

---

## 4. 四个内置场景（与 `ZmqMetricsFaultTest` 对应）

以下场景在**同一进程**内起 ZMQ Demo server + client，无需额外进程脚本；适合回归与培训。

### 4.1 正常 RPC（基线）

| 项目 | 内容 |
|------|------|
| **构造** | 连续发送 `msg="Hello"` 的 `SimpleGreeting`，短超时 |
| **必现日志** | `[METRICS DUMP - Normal RPCs]`；`zmq_send_io_latency,count=` / `zmq_receive_io_latency,count=`；`[SELF-PROOF] framework_ratio=` |
| **定界结论** | fault 类 counter 为 0；histogram 有计数 → **传输面有观测、无故障** |

### 4.2 对端进程被杀（模拟 crash）

| 项目 | 内容 |
|------|------|
| **构造** | 先若干成功 RPC，再 `rpc->Shutdown()`，之后继续发 RPC |
| **必现日志** | `[FAULT INJECT] Shutting down server`；`[METRICS DUMP - Server Killed]`；`[ISOLATION] gw_recreate total= ... delta= ...` |
| **定界结论** | **`gw_recreate` delta > 0** 表示 stub 侧检测到断连并重建网关；**不以** `recv.fail` 为唯一判据（stub 多为 DONTWAIT + poll） |

### 4.3 服务端故意变慢（RPC 超时）

| 项目 | 内容 |
|------|------|
| **构造** | `DemoServiceImpl` 对 `msg=="World"` **sleep 1s**；客户端 `RpcOptions` **500ms** 超时 |
| **必现日志** | `[FAULT INJECT] Sending 'World'`；`[METRICS DUMP - Slow Server]`；`[ISOLATION] ... recv.fail=0 ... → ZMQ layer clean` |
| **定界结论** | **RPC 超时 + ZMQ fault 计数全 0** → 瓶颈在**服务端处理或 RPC 调度**，不是「网卡坏了」；**不要期待** `zmq_receive_try_again_total` 在此路径必涨（见 plan 中架构说明） |

### 4.4 高压自证（框架占比）

| 项目 | 内容 |
|------|------|
| **构造** | 200 次正常 `Hello` RPC |
| **必现日志** | `[METRICS DUMP - High Load]`；`[SELF-PROOF REPORT]`；`CONCLUSION:` 行 |
| **定界结论** | 对比 **I/O ratio vs Framework ratio**；环回环境下可能出现 WARNING 文案，重点看 **histogram 是否均有采样** 与 **fault 仍为 0** |

---

## 5. 扩展故障（联调 / 现场）— 如何构造、日志上期待什么

在 ST 用例之外，测试可按下表扩展；**每次只改变一个变量**，便于定界。

| 故障类型 | 建议构造方式 | 优先看的日志/metrics |
|----------|----------------|---------------------|
| 对端不可达 | 停服务 / 改错端口 / `iptables DROP` 对端 IP | `zmq_send_failure_total` / `zmq_receive_failure_total`、`zmq_network_error_total`、`zmq_last_error_number` |
| 对端半开连接 | `kill -9` server 或拔网线 | `zmq_event_disconnect_total`（异步）、`zmq_gateway_recreate_total` |
| 纯延迟 | `tc qdisc` 增加 RTT | `zmq_receive_io_latency` max/avg 上升；fault 可能仍为 0 |
| HWM 背压 | 极快发送、收端不读 | `zmq_send_try_again_total` |
| 阻塞 recv 超时 | 使用 **阻塞 ZMQ recv + RCVTIMEO** 的业务路径（若有） | `[ZMQ_RECV_TIMEOUT]` |

---

## 6. 常见误区（串讲时重点强调）

1. **「没看到 `[ZMQ_RECEIVE_FAILURE_TOTAL]` 说明埋点没生效」**  
   **错。** 当前 client stub 以 **DONTWAIT + poll** 为主，很多「超时 / 对端死」不会走到 `zmq_msg_recv` 的硬失败；应结合 **`gw_recreate`**、RPC 返回码与 **metrics fault 是否为 0** 综合判断。

2. **「慢调用一定会涨 `zmq_receive_try_again_total`」**  
   **错。** `recv.eagain` 在实现里对 **阻塞 recv + EAGAIN** 计数；慢 server + Rpc 超时往往走 poll，**计数仍为 0 是符合设计的**。

3. **「只看 Total 不看 Compare」**  
   **不推荐。** 网关**首次创建**也会计入 `gw_recreate` total；看 **Compare 段的 `+delta`** 才能判断「本次故障窗口内是否发生重建」。

---

## 7. 验收 Checklist（测试签字用）

- [ ] `ds_st --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr` 全通过  
- [ ] `verify_zmq_fault_injection_logs.sh <log>` exit 0，**Mandatory 区无 ✗**  
- [ ] 能口头说明四个场景中 **至少 2 条** `[ISOLATION]` 与 metrics 的对应关系  
- [ ] 能说明为何本 run **可以没有** `[ZMQ_RECEIVE_FAILURE_TOTAL]`（§6）

---

## 8. 运行证据归档（示例）

将以下内容粘贴到 `RESULTS.md` 或测试报告即可：

```text
./tests/st/ds_st --gtest_filter='ZmqMetricsFaultTest.*' --alsologtostderr
[  PASSED  ] 4 tests.

bash .../verify_zmq_fault_injection_logs.sh zmq_fault.log
Mandatory RESULT: 15 matched | 0 missing
```

---

## 9. 关键错误日志样例（可直接给测试复用）

下面样例来自最近一次远端执行 `ZmqMetricsFaultTest.*` 的真实日志，测试可直接对照。

### 9.1 对端被杀（连接层重建）

```text
[FAULT INJECT] Shutting down server to simulate peer crash
[FAULT INJECT] 5/5 RPCs failed after server kill
[METRICS DUMP - Server Killed]
[ISOLATION] gw_recreate total=4 delta=3 evt.disconn=0 recv.fail=0
[ISOLATION] evt.disconn=0 (monitor event not yet delivered; gw_recreate alone is sufficient for isolation)
```

**如何判定有效：**
- 必须同时看到 `[FAULT INJECT]` + `[METRICS DUMP - Server Killed]` + `[ISOLATION] gw_recreate ... delta=...`。
- `gw_recreate delta > 0` 即可判定：连接层感知到了断连并重建，具备定界价值。

### 9.2 服务端慢（RPC 超时但 ZMQ 层健康）

```text
[FAULT INJECT] Sending 'World' msg (server sleeps 1s, timeout=500ms)
[FAULT INJECT] 3/3 RPCs timed out
[METRICS DUMP - Slow Server]
[ISOLATION] recv.fail=0 recv.eagain=0 send.fail=0 net_error=0  → ZMQ layer clean; fault is server-side latency
```

**如何判定有效：**
- 看到超时日志，同时 `recv.fail/send.fail/net_error` 都是 0，说明不是网卡/链路硬故障。
- 结论应落在“server-side latency / RPC timeout path”，不是“ZMQ socket hard fail path”。

### 9.3 高负载自证（框架占比结论）

```text
[SELF-PROOF REPORT]
  zmq_send_io_latency avg   = 2 us
  zmq_receive_io_latency avg   = 0 us
  zmq_rpc_serialize_latency avg   = 0 us
  zmq_rpc_deserialize_latency avg = 1 us
  I/O ratio            = 66.6667%
  Framework ratio      = 33.3333%
  CONCLUSION: WARNING: Framework overhead may be significant
```

**如何判定有效：**
- 必须有 `[SELF-PROOF REPORT]` 与 `CONCLUSION:`。
- 不要只看 WARNING 文案，需结合 `io.*` 与 `rpc.*` 的 avg 值做占比判断。

### 9.4 为什么这轮没有 `[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]` / `[ZMQ_RECV_TIMEOUT]`

这轮故障注入走的是 `stub poll + DONTWAIT` 主路径，且没有触发底层硬 errno：
- 所以可能没有 `[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]`；
- 也可能没有 `[ZMQ_RECV_TIMEOUT]`（该标签更偏阻塞 recv + RCVTIMEO 路径）。

这不是失败，属于**与故障模型匹配的预期行为**。测试侧应优先看 `[ISOLATION]` 行和 metrics dump 的 fault counters。

### 9.5 建议给测试的 grep 命令

```bash
# 先看四类主标签（定界主证据）
grep -E "\\[FAULT INJECT\\]|\\[METRICS DUMP -|\\[ISOLATION\\]|\\[SELF-PROOF REPORT\\]|CONCLUSION:" zmq_fault.log

# 再看底层 ZMQ 错误标签（可选证据）
grep -E "\\[ZMQ_RECEIVE_FAILURE_TOTAL\\]|\\[ZMQ_SEND_FAILURE_TOTAL\\]|\\[ZMQ_RECV_TIMEOUT\\]" zmq_fault.log

# 看关键 metrics 行（fault + io + ser/deser）
grep -E "zmq\\.(send|recv|net|gw|evt|io|rpc)" zmq_fault.log
```

---

## 10. 相关文件索引

| 路径 | 说明 |
|------|------|
| `yuanrong-datasystem/tests/st/common/rpc/zmq/zmq_metrics_fault_test.cpp` | 四场景故障注入与 `[FAULT INJECT]` / `[ISOLATION]` 日志 |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_socket_ref.cpp` | `[ZMQ_RECEIVE_FAILURE_TOTAL]` / `[ZMQ_SEND_FAILURE_TOTAL]` |
| `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_socket.cpp` | `[ZMQ_RECV_TIMEOUT]` |
| `vibe-coding-files/scripts/testing/verify/verify_zmq_fault_injection_logs.sh` | 日志关键字自动化验收 |

---

*文档随代码迭代更新；与 `RESULTS.md` §八 的 CMake/UT 回归互补：§八偏「框架+ZMQ UT」，本文偏「故障注入 + 日志定界」。*
