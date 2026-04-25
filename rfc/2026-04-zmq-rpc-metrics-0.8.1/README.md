# RFC: ZMQ RPC Metrics 修复 - ENABLE_PERF=false 分段时间（0.8.1 分支）

- **Status**: **Draft**
- **Started**: 2026-04-25
- **Target Branch**: `main/0.8.1`
- **Depended on**: PR #706（已修复 master 分支，需要 cherry-pick 到 0.8.1）
- **Goal**: 确保 ZMQ metrics 在 `ENABLE_PERF=false` 时能准确分段时间，用于 TCP 故障定位

---

## 问题背景

### 问题描述
当 `ENABLE_PERF=false` 时，ZMQ RPC metrics 无法记录分段时间，导致：
- 无法自证清白 network 和 RPC framework (send/recv) 的时间
- TCP 故障时无法通过 metrics 定位问题

### 根本原因
原代码中 `GetLapTime()` 和 `GetTotalTime()` 在 `ENABLE_PERF` 关闭时直接返回 0，不记录任何 tick：

```cpp
// 原实现（问题代码）
inline uint64_t GetLapTime(MetaPb &meta, const char *tickName) {
#ifdef ENABLE_PERF
    return RecordTick(meta, tickName);  // 仅在 ENABLE_PERF 时记录
#else
    (void)meta;
    (void)tickName;
    return 0;  // 始终返回 0，tick 被丢弃
#endif
}
```

---

## 修复方案（来源 PR #706）

### 核心改动
1. **新增 `RecordTick()` 函数** - 始终记录 tick，不受 `ENABLE_PERF` 控制
2. **新增 `GetTotalElapsedTime()` 函数** - 始终计算总时间，不受 `ENABLE_PERF` 控制
3. **修改 metrics 记录函数** - 使用新的始终启用的函数

### 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `zmq_common.h` | 新增 `RecordTick()`、`GetTotalElapsedTime()` |
| `zmq_service.cpp` | 拆分 `RecordServerLatencyMetrics`；ns→us 转换 |
| `zmq_stub_conn.cpp` | `GetLapTime` → `RecordTick` |
| `zmq_stub_impl.h` | `GetTotalTime` → `GetTotalElapsedTime` |
| `kv_metrics.h/cpp` | 新增 7 个 RPC Queue Flow Latency metrics |

### 新增 Metrics（用于自证清白）

| Metric | 说明 |
|--------|------|
| `ZMQ_CLIENT_QUEUING_LATENCY` | Client 框架队列等待 |
| `ZMQ_CLIENT_STUB_SEND_LATENCY` | Client Stub 发送 |
| `ZMQ_SERVER_QUEUE_WAIT_LATENCY` | Server 队列等待（自证 network） |
| `ZMQ_SERVER_EXEC_LATENCY` | Server 业务执行（自证业务逻辑） |
| `ZMQ_SERVER_REPLY_LATENCY` | Server 回复入队（自证 RPC framework） |
| `ZMQ_RPC_E2E_LATENCY` | 端到端延迟 |
| `ZMQ_RPC_NETWORK_LATENCY` | 网络延迟 = E2E - ServerExec |

---

## 落地位置（datasystem 0.8.1）

需要 cherry-pick PR #706 的 commit `d3f7dffd` 到 `main/0.8.1` 分支。

---

## 验证方案

### 工作流：rsync 同步 → 远程构建 → smoke_test 验证

```
┌─────────────────┐     rsync      ┌──────────────────────┐
│  本地工作区      │ ─────────────► │  xqyun-32c32g        │
│  yuanrong-datasystem            │  ~/workspace/git-repos/
│  (含 cherry-pick) │               │  yuanrong-datasystem │
└─────────────────┘               └──────────────────────┘
                                          │
                                          ▼
                                  ┌──────────────────────┐
                                  │ 1. rsync 同步代码     │
                                  │ 2. 远程 git cherry-pick│
                                  │ 3. bash build.sh     │
                                  │ 4. run_smoke.py      │
                                  │ 5. 解析 metrics      │
                                  └──────────────────────┘
```

### 执行步骤

#### 步骤 1: 本地 cherry-pick 修复

```bash
cd ~/workspace/git-repos/yuanrong-datasystem
git fetch origin
git checkout -b fix/zmq-metrics-enable-perf origin/main
git cherry-pick d3f7dffd  # feat: Add ZMQ RPC tracing and latency metrics
```

#### 步骤 2: 同步到远程并构建（Bazel + whl）

```bash
cd ~/workspace/git-repos/yuanrong-datasystem-agent-workbench
bash scripts/build/remote_build_run_datasystem.sh \
  --remote xqyun-32c32g \
  --local-ds ~/workspace/git-repos/yuanrong-datasystem \
  --local-vibe ~/workspace/git-repos/yuanrong-datasystem-agent-workbench \
  --skip-ctest \
  --skip-validate
# 使用 Bazel 构建 + 生成 whl 包
```

#### 步骤 3: 运行 smoke_test（脚本内含 etcd + worker 部署）

```bash
ssh xqyun-32c32g \
  'cd ~/workspace/git-repos/yuanrong-datasystem-agent-workbench/scripts/testing/verify/smoke && \
   python3 run_smoke.py'
```

#### 步骤 4: 检查 metrics 输出

```bash
cat ~/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_*/metrics_summary.txt
```

#### 步骤 4a（推荐，先于 summary）：核对 tick 链

代码在 worker 出队后、`ServiceToClient` 追加 `SERVER_SEND` 后、以及 stub/unary 计算 7 指标前会打一行 **`[ZmqTickOrder]`**（`chain=` 为 meta 中 ticks **顺序** 的 `name@ts`；`SERVER_EXEC_NS@…[exec_dur_ns]` 表示该 tick 的 `ts` 是 **handler 耗时** 而非墙钟）。

在 smoke 或单测跑完后从 worker/日志目录检索：

```bash
rg '\[ZmqTickOrder\]' -n /path/to/workers/worker-*/ 2>/dev/null | head -40
# 或 rg '\[ZmqTickOrder\]' -n /path/to/results/smoke_test_*/*.log
```

**期望（逻辑顺序，不要求每个 RPC 都出现在同一文件）**：

- `unary_rsp_before_metrics` 或 `stub_rsp_before_metrics` 的 `chain` 在末尾应能看到 `CLIENT_RECV`，且含服务端 ticks（`SERVER_DEQUEUE` … `SERVER_EXEC_END` → `SERVER_EXEC_NS[exec_dur_ns]` → `SERVER_SEND` 等，中间可有 PERF 名）。
- `worker_after_server_exec_and_metrics`：应在 `SERVER_EXEC_END` 后紧跟 `SERVER_EXEC_NS`（duration）。
- `service_to_client_after_server_send`：应在链尾含墙钟的 `SERVER_SEND`。

若链顺序与 [sequence_diagram.puml](sequence_diagram.puml) 明显不符，再对照 C++ 打点与本次日志。

#### 步骤 4b: 解析 metrics 汇总

在确认 tick 链合理后，再对照 `metrics_summary.txt` 中 7 个 `zmq_*` 指标与 [验收标准](#验收标准)。

### 验收标准

1. ✅ `ENABLE_PERF=false` 时 ZMQ metrics 正常打印
2. ✅ `zmq_client_queuing_latency` 有值 → 自证 Client 框架队列等待
3. ✅ `zmq_client_stub_send_latency` 有值 → 自证 Client Stub 发送
4. ✅ `zmq_server_queue_wait_latency` 有值 → 自证 network 等待时间
5. ✅ `zmq_server_exec_latency` 有值 → 自证业务逻辑执行时间
6. ✅ `zmq_server_reply_latency` 有值 → 自证 RPC framework 回复时间
7. ✅ `zmq_rpc_e2e_latency` 有值 → 端到端延迟
8. ✅ `zmq_rpc_network_latency` 有值 → 网络延迟 = E2E - ServerExec

---

## 本目录文件

| 文件 | 说明 |
|------|------|
| [design.md](design.md) | 详细设计方案 |
| [test-walkthrough.md](test-walkthrough.md) | 测试串讲 |
| [results.md](results.md) | 验证记录 |
| [pr-description.md](pr-description.md) | PR 描述模板 |

---

## 相关文档

- [PR #706](https://gitcode.com/openeuler/yuanrong-datasystem/pull/706)
- [run_smoke.py](../../scripts/testing/verify/smoke/run_smoke.py)
- [remote_build_run_datasystem.sh](../../scripts/build/remote_build_run_datasystem.sh)
