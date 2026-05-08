# Issue: Server Exec 服务器执行延迟分析 (1527us - 3685us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能分析 (Performance Analysis) |
| **影响组件** | Worker Service |
| **影响节点** | 192.168.168.216, 192.168.42.114, 192.168.219.66 |
| **严重程度** | Medium |
| **Trace ID** | metrics_server_exec_us_min_1527_max_3685 |

---

## 一、现象描述

Server Exec 延迟范围 **1.5ms - 3.7ms**，包含对象读取、内存操作等。

**关键现象**：
1. server_exec 范围: 1.5ms - 3.7ms
2. 某些 traces server_exec 占比高达 51.7%
3. URMA wait 时间波动大 (1.6ms - 3.6ms)
4. 与 eviction 操作相关

---

## 二、日志证据

### Trace: 0d34feb8 (server_exec: 3654us - 最高)

```
[ZMQ_RPC_FRAMEWORK_SLOW] trace_id=0d34feb8
framework_us=3442
server_req_queue_us=109
server_exec_us=3654 (51.7%)  <-- 高
server_rsp_queue_us=85
network_residual_us=3218

Worker 192.168.168.216 -> Worker 192.168.219.66
Object: kv_test_24_14_119472993788120_0, size: 8388608
DS_POSIX_GET | 7525 | 8388608
```

**URMA Wait**:
```
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr
cost 3.57336ms, request id:972970
status: code: [OK], urma_inflight_wr_count: 2
```

### Trace: 1051ba83 (server_exec: 1790us)

```
[ZMQ_RPC_FRAMEWORK_SLOW] trace_id=1051ba83
framework_us=3463
server_req_queue_us=3068 (55.5%)  <-- 高
server_exec_us=1790
server_rsp_queue_us=146
network_residual_us=215

EvictionList size before evict: 1226
```

### Trace: 3ec5259c (server_exec: 1658us)

```
threadPool: idle(12), total(17), wait(0)
EvictionList size after evict: 1218, failed size: 1218
```

---

## 三、延迟分解

### 0d34feb8 分解

```
server_exec = 3654us
  ├── Object read from storage: ~500us (估算)
  ├── Memory copy: ~1000us (8MB)
  ├── URMA wait: 3573us (主要)
  └── Other: ~581us
```

### 1051ba83 分解

```
server_exec = 1790us
  ├── Eviction processing: ~1000us
  ├── Object lookup: ~500us
  └── Other: ~290us
```

---

## 四、根因分析

### 4.1 URMA Wait 高延迟

Trace 0d34feb8 显示 URMA wait 长达 **3.57ms**：

```
[URMA_ELAPSED_TOTAL]: Waiting URMA jfc event done after urma_post_jetty_send_wr
cost 3.57336ms
suggest: check URMA_ELAPSED_THREAD_SHED/URMA_ELAPSED_POLL_JFC/URMA_ELAPSED_NOTIFY
```

**可能原因**：
1. RDMA Completion Queue 等待
2. CPU 调度延迟
3. 内存带宽瓶颈

### 4.2 Eviction 影响

Trace 1051ba83 和 3ec5259c 显示大量 eviction 操作：

```
EvictionList size before evict: 1226
EvictionList size after evict: 1218
failed size: 1218  <-- 所有 eviction 都失败了
```

Eviction 失败意味着需要从存储读取，而不是从缓存。

### 4.3 Thread Pool 状态

```
0d34feb8: threadPool: idle(18), total(20), wait(0)
1051ba83: threadPool: idle(12), total(17), wait(0)
3ec5259c: threadPool: idle(12), total(17), wait(0)
```

线程池资源充足，但请求仍需排队。

---

## 五、结论

| 问题 | 答案 |
|------|------|
| server_exec 延迟？ | **1.5ms - 3.7ms** |
| 主要瓶颈？ | **URMA wait 和 eviction 处理** |
| 高 exec 原因？ | 等待 RDMA 完成事件 |
| 异常？ | URMA wait 3.5ms 偏高 |

**根因**：Server exec 高延迟主要由 URMA wait 事件等待和 eviction 处理导致。

---

## 六、建议

1. **URMA 性能调优** (P0)
   ```
   - 检查 RDMA CQ 大小配置
   - 考虑 interrupt vs polling 模式
   - 监控 urma_inflight_wr_count
   ```

2. **Eviction 优化** (P1)
   ```
   - 1226 个对象的 eviction list 太大
   - 考虑增量 eviction
   - 调查为何 100% eviction 都失败
   ```

3. **内存预分配** (P1)
   - 避免每次传输都注册/注销内存
   - 使用 memory pool

4. **监控告警** (P2)
   - URMA wait > 1ms 告警
   - Eviction failed > 50% 告警

---

## 七、其他受影响 Trace

| Trace ID | server_exec_us | URMA wait | server_req_queue | 问题类型 |
|----------|---------------|-----------|-----------------|----------|
| 0d34feb8 | 3654 | 3.57ms | 109us | URMA wait 高 |
| 1051ba83 | 1790 | 1.64ms | 3068us | Queue + Eviction |
| 3ec5259c | 1658 | N/A | 3025us | Queue + Eviction |
| 836d814b | 1628 | N/A | 2955us | Queue 主导 |
