# 故障测试构造与验收指南 v2.0

---

## 一、故障构造方法分类

### 1.1 故障注入方法矩阵

| 故障大类 | 构造方法 | 注入层面 | 预期StatusCode | 验证指标 | 验证日志 |
|---------|---------|---------|---------------|---------|---------|
| **网络闪断** | iptables drop / tc qdisc | OS网络层 | 1001/1002 | `zmq_send_failure_total`↑ | `[ZMQ_SEND_FAILURE_TOTAL]` |
| **网络中断** | kill Worker进程 | OS网络层 | 1002/23 | `zmq_gateway_recreate_total`↑ | `[RPC_SERVICE_UNAVAILABLE]` |
| **RPC超时** | tc delay + timeout配置 | OS网络层 | 1001 | `client_rpc_get_latency` max↑ | `[RPC_RECV_TIMEOUT]` |
| **ZMQ建连失败** | 端口不可达 | OS网络层 | 1002 | `zmq_event_handshake_failure_total`↑ | `[TCP_CONNECT_FAILED]` |
| **URMA连接断** | kill远端Worker | URMA层 | 1006 | `zmq_gateway_recreate_total`↑ | `[URMA_NEED_CONNECT]` |
| **UB降级TCP** | ifconfig ub0 down | URMA层 | 无上抛 | `tcp_read_total_bytes`↑ | `fallback to TCP/IP payload` |
| **JFS重建** | 触发cqeStatus=9 | URMA层 | 1004 | `worker_urma_write_latency` max↑ | `[URMA_RECREATE_JFS]` |
| **etcd超时** | systemctl stop etcd | OS层 | 25/1001 | `ETCD_REQUEST_SUCCESS_RATE`↓ | `etcd is timeout` |
| **mmap失败** | ulimit -l 0 | OS层 | 5/7 | `client_get_error_total`↑ | `Get mmap entry failed` |
| **Worker退出** | kill -9 Worker | 组件层 | 31/23 | `worker_object_count`↓ | `[HealthCheck] exiting` |
| **Worker挂死** | kill -STOP Worker | 组件层 | 23 | `Cannot receive heartbeat` | 心跳超时 |
| **SHM内存泄漏** | 模拟ref_table钉住 | 组件层 | 无 | `worker_shm_ref_table_bytes`涨 | - |
| **参数非法** | 传空key | 用户层 | 2 | 无 | `The objectKey is empty` |

---

## 二、具体故障构造步骤

### 2.1 网络故障

#### 【故障1】ZMQ发送失败
```
构造方法：
  iptables -I OUTPUT -p tcp --dport <worker_port> -j DROP
  持续10秒

验证步骤：
  1. zmq_send_failure_total delta > 0
  2. grep '[ZMQ_SEND_FAILURE_TOTAL]' worker.log 有输出
  3. access log: code=1002

恢复：
  iptables -D OUTPUT -p tcp --dport <worker_port> -j DROP
```

#### 【故障2】RPC超时
```
构造方法：
  tc qdisc add dev eth0 root netem delay 3000ms 100ms

验证步骤：
  1. access log microseconds 接近 timeout 配置
  2. [RPC_RECV_TIMEOUT] 出现
  3. zmq_receive_io_latency avg > 2000ms

恢复：
  tc qdisc del dev eth0 root netem
```

#### 【故障3】TCP建连失败
```
构造方法：
  iptables -A INPUT -p tcp --dport <worker_port> -j REJECT

验证步骤：
  1. [TCP_CONNECT_FAILED] 出现
  2. client返回 K_RPC_UNAVAILABLE (1002)

恢复：
  iptables -D INPUT -p tcp --dport <worker_port> -j REJECT
```

---

### 2.2 URMA层故障

#### 【故障4】URMA连接需重建
```
构造方法：
  kill -9 <远端Worker进程PID>

验证步骤：
  1. [URMA_NEED_CONNECT] 出现，remoteAddress指向被kill的Worker
  2. [URMA_NEED_CONNECT] TryReconnectRemoteWorker triggered
  3. 最终 K_TRY_AGAIN (19) 或重试成功

预期结果：SDK自动重连，业务自动恢复
```

#### 【故障5】UB降级TCP
```
构造方法：
  ifconfig ub0 down

验证步骤：
  1. client_get_tcp_read_total_bytes delta > 0
  2. client_get_urma_read_total_bytes delta = 0
  3. grep 'fallback to TCP/IP payload' worker.log 有输出
  4. P99可能上升（TCP比UB慢）

恢复：
  ifconfig ub0 up
```

#### 【故障6】JFS重建
```
构造方法：
  触发cqeStatus=9场景（URMA内部错误）

验证步骤：
  1. [URMA_RECREATE_JFS] requestId=xxx, cqeStatus=9 出现
  2. [URMA_RECREATE_JFS_SKIP] 可能出现
  3. worker_urma_write_latency max可能飙升

预期结果：自动重建JFS，恢复后继续正常
```

---

### 2.3 etcd/OS层故障

#### 【故障7】etcd超时
```
构造方法：
  systemctl stop etcd

验证步骤：
  1. worker.log 'etcd is timeout'
  2. 'Disconnected from remote node' 出现
  3. client K_MASTER_TIMEOUT (25)
  4. CreateMeta / MultiPublish 失败

恢复：
  systemctl start etcd
```

#### 【故障8】mmap失败
```
构造方法：
  ulimit -l 0

验证步骤：
  1. client.log 'Get mmap entry failed'
  2. K_RUNTIME_ERROR (7)
  3. 可能降级到TCP

恢复：
  ulimit -l unlimited
```

---

### 2.4 组件层故障

#### 【故障9】Worker进程退出
```
构造方法：
  kill -9 <worker_pid>

验证步骤：
  1. [HealthCheck] Worker is exiting now 出现
  2. client K_SCALE_DOWN (31) 或 K_CLIENT_WORKER_DISCONNECT (23)
  3. SDK自动切换到其他Worker
  4. k8s自动拉起新Worker

预期结果：SDK自动切流，业务自动恢复
```

#### 【故障10】Worker进程挂死
```
构造方法：
  kill -STOP <worker_pid>

验证步骤：
  1. client心跳超时
  2. Cannot receive heartbeat from worker 出现
  3. 最终 K_CLIENT_WORKER_DISCONNECT (23)

恢复：
  kill -CONT <worker_pid>
```

---

### 2.5 SHM内存泄漏

#### 【故障11】SHM内存泄漏
```
构造方法：
  模拟元数据已删但物理shm仍被memoryRefTable_钉住的场景
  - 正常写入大量数据
  - 触发元数据删除但不触发物理释放

验证步骤：
  1. shm.memUsage 从 3.58GB → 37.5GB (100s内)
  2. OBJECT_COUNT 从 438 → 37 (反向于OBJECT_SIZE)
  3. worker_shm_alloc_total - worker_shm_free_total 差值持续涨
  4. worker_shm_ref_table_bytes 持续涨
  5. resource.log SHARED_MEMORY 使用率突增

Metrics验证：
  - worker_shm_alloc_total > worker_shm_free_total
  - worker_shm_ref_table_bytes > 0 并持续增长
```

---

## 三、验收指标Checklist

### 3.1 必验项（每类故障都要验证）

| 故障类型 | 观测指标 | 预期结果 | 验收 |
|---------|---------|---------|------|
| 网络闪断 | `zmq_send_failure_total` delta | > 0 | ☐ |
| 网络闪断 | `[ZMQ_SEND_FAILURE_TOTAL]` | 有日志 | ☐ |
| RPC超时 | `client_rpc_get_latency` max | > timeout | ☐ |
| RPC超时 | `[RPC_RECV_TIMEOUT]` | 有日志 | ☐ |
| TCP建连失败 | `[TCP_CONNECT_FAILED]` | 有日志 | ☐ |
| URMA重连 | `[URMA_NEED_CONNECT]` | 有日志 | ☐ |
| UB降级 | `tcp_read_total_bytes` delta | > 0 | ☐ |
| UB降级 | `urma_read_total_bytes` delta | = 0 | ☐ |
| JFS重建 | `[URMA_RECREATE_JFS]` | 有日志 | ☐ |
| etcd超时 | `etcd is timeout` | 有日志 | ☐ |
| Worker退出 | `[HealthCheck] Worker is exiting` | 有日志 | ☐ |
| mmap失败 | `Get mmap entry failed` | 有日志 | ☐ |
| SHM泄漏 | `worker_shm_ref_table_bytes` | 持续涨 | ☐ |
| SHM泄漏 | OBJECT_COUNT vs OBJECT_SIZE | 反向变化 | ☐ |

### 3.2 Metrics完整性验证

| 验证项 | 命令/方法 | 通过标准 |
|-------|---------|---------|
| Metrics Summary | `grep "Metrics Summary, version=v0" log` | ≥2个周期 |
| ZMQ Metrics | `grep "zmq_send_failure_total" log` | 有输出 |
| URMA Metrics | `grep "urma_write_total_bytes" log` | 有输出 |
| SHM Metrics | `grep "worker_shm_ref_table" log` | 有输出 |
| Histogram有效 | `grep "latency.*count=" log` | count > 0 |

---

## 四、故障注入脚本模板

### 4.1 网络故障注入
```bash
#!/bin/bash
# 网络闪断注入
PORT=${1:-8080}
DROP_DURATION=${2:-10}

echo "[FAULT INJECT] 开始网络闪断故障注入"
echo "[FAULT INJECT] 目标端口: $PORT, 持续: ${DROP_DURATION}s"

# 注入故障
iptables -I OUTPUT -p tcp --dport $PORT -j DROP
echo "[FAULT INJECT] iptables规则已添加"

# 等待持续时间
sleep $DROP_DURATION

# 恢复
iptables -D OUTPUT -p tcp --dport $PORT -j DROP
echo "[FAULT INJECT] 网络已恢复"
```

### 4.2 Worker进程故障注入
```bash
#!/bin/bash
# Worker进程故障注入
WORKER_PID=${1:-$(pgrep datasystem_worker | head -1)}

echo "[FAULT INJECT] Worker PID: $WORKER_PID"
kill -9 $WORKER_PID
echo "[FAULT INJECT] Worker已kill"
sleep 5
NEW_PID=$(pgrep datasystem_worker | head -1)
echo "[FAULT INJECT] 新Worker PID: $NEW_PID"
```

---

## 五、维测效果验证矩阵

### 5.1 按故障类别验证

| 故障类别 | 验证日志 | 验证Metrics | 验证Access Log | 验证手段 |
|---------|---------|-----------|--------------|---------|
| **A类-用户层** | respMsg关键字 | 无特殊 | code=2 | 业务参数校验 |
| **B类-控制面** | TCP/ZMQ/RPC标签 | ZMQ counters | code=1001/1002 | 网络故障注入 |
| **C类-URMA** | URMA标签 | UB/TCP bytes | code=1004/1006 | UB故障注入 |
| **D类-组件** | HealthCheck/etcd | worker metrics | code=23/31 | 进程故障注入 |
| **D类-SHM泄漏** | SHM使用率 | SHM metrics | OBJECT_COUNT变化 | 内存泄漏场景 |

### 5.2 验证执行顺序
```
1. 故障前：记录baseline metrics
   grep "Compare with" baseline.log | head -5

2. 故障注入：执行故障构造步骤

3. 故障中：观察日志输出
   grep -E "\[FAULT INJECT\]|\[URMA_|\[ZMQ_|\[TCP_" worker.log

4. 故障后：验证指标变化
   grep "Compare with" fault.log | head -5
   与baseline对比

5. 恢复验证：确认自动恢复
   - 业务请求成功率恢复
   - Metrics恢复到baseline水平
```

---

## 六、常用验收命令

```bash
#!/bin/bash
# verify_fault_injection.sh

LOG=${1:-worker.log}

echo "=== 故障注入验证 ==="
echo ""

echo "1. Metrics Summary 检查"
grep "Metrics Summary, version=v0" $LOG | wc -l
echo "期望: ≥2 (至少2个周期)"
echo ""

echo "2. ZMQ Metrics 检查"
grep -E "zmq_(send|receive)_(failure|try_again)_total" $LOG | tail -5
echo ""

echo "3. URMA 标签检查"
grep -oE "\\[URMA_[A-Z_]+\\]" $LOG | sort | uniq -c | sort -nr
echo "期望: 至少1种URMA标签"
echo ""

echo "4. RPC 标签检查"
grep -oE "\\[(TCP|RPC|SOCK|ZMQ)_[A-Z_]+\\]" $LOG | sort | uniq -c | sort -nr
echo "期望: 至少1种TCP/RPC标签"
echo ""

echo "5. fallback 检查"
grep -c "fallback to TCP" $LOG
echo "期望: ≥1 (如果有UB降级)"
echo ""

echo "6. SHM Metrics 检查"
grep -E "worker_shm_(alloc|free|ref_table)" $LOG | tail -5
echo "期望: 有SHM分配/释放/钉住指标"
echo ""

echo "7. resource.log 检查"
grep -E "SHARED_MEMORY|OBJECT_COUNT|ETCD_QUEUE" /logs/resource.log | tail -5
echo "期望: 有资源指标输出"
echo ""

echo "=== 验证完成 ==="
```
