# Test Walkthrough: ZMQ RPC Metrics 验证

## 1. 验证目标

确认 `ENABLE_PERF=false` 时，ZMQ metrics 能正常分段时间。

## 2. 验证环境

- 远程主机：`xqyun-32c32g`
- 构建：Bazel + whl 包
- 测试：`run_smoke.py`（内含 etcd + worker 部署）

## 3. 验证步骤

### 步骤 1: 构建（Bazel + whl）

```bash
cd ~/workspace/git-repos/yuanrong-datasystem-agent-workbench
bash scripts/build/remote_build_run_datasystem.sh \
  --remote xqyun-32c32g \
  --skip-ctest --skip-validate
# 使用 Bazel 构建 + 生成 whl 包
```

### 步骤 2: 运行 smoke_test（脚本内含 etcd + worker）

```bash
ssh xqyun-32c32g \
  'cd ~/workspace/git-repos/yuanrong-datasystem-agent-workbench/scripts/testing/verify/smoke && \
   python3 run_smoke.py'
```

### 步骤 3: 检查 metrics

```bash
cat ~/workspace/git-repos/yuanrong-datasystem-agent-workbench/results/smoke_test_*/metrics_summary.txt
```

## 4. 预期结果

### 4.1 新增 Metrics 有值

```
zmq_server_queue_wait_latency: <value>  # 自证 network 等待
zmq_server_exec_latency: <value>       # 自证业务逻辑
zmq_server_reply_latency: <value>      # 自证 RPC framework
zmq_rpc_e2e_latency: <value>           # 端到端
zmq_rpc_network_latency: <value>       # 网络延迟
```

### 4.2 现有 Metrics 正常

```
zmq_send_io_latency: <value>
zmq_receive_io_latency: <value>
zmq_rpc_serialize_latency: <value>
zmq_rpc_deserialize_latency: <value>
```

## 5. 故障注入验证（可选）

如需验证 TCP 故障时的 metrics 行为，可参考：
- `scripts/testing/verify/verify_zmq_metrics_fault.sh`
- `scripts/testing/verify/verify_zmq_fault_injection_logs.sh`

## 6. 验收 Checklist

- [ ] `ENABLE_PERF=false` 构建成功
- [ ] smoke_test 运行成功
- [ ] `zmq_client_queuing_latency` 有非零值
- [ ] `zmq_client_stub_send_latency` 有非零值
- [ ] `zmq_server_queue_wait_latency` 有非零值
- [ ] `zmq_server_exec_latency` 有非零值
- [ ] `zmq_server_reply_latency` 有非零值
- [ ] `zmq_rpc_e2e_latency` 有非零值
- [ ] `zmq_rpc_network_latency` 有非零值
