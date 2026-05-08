# Issue: Network Residual 网络残留延迟分析 (40664us - 83252us)

## 问题分类

| 分类 | 值 |
|------|-----|
| **问题类型** | 性能异常 (Performance Anomaly) |
| **影响组件** | URMA/RDMA Network |
| **影响节点** | 多worker节点 |
| **严重程度** | High |
| **Trace ID** | metrics_network_residual_us_min_40664_max_83252 |

---

## 一、现象描述

Network Residual 延迟范围 **40.6ms - 83.2ms**，占 E2E 延迟的 **99.4% - 99.8%**。

**关键现象**：
1. network_residual 范围: 40.6ms - 83.2ms
2. 占 E2E 延迟 99%+ - **系统是网络 bound**
3. URMA 连接建立开销约 8ms
4. NUMA 亲和性使用正确 (useNumaAffinity:1)

---

## 二、日志证据

### Trace: 0c3d819d (network: 82509us)

**URMA 连接建立**:
```
14:28:30.137018 - WorkerWorkerExchangeUrmaConnectInfo start
14:28:30.139174 - Import target jetty elapsed = 1.86ms
14:28:30.140276 - WorkerWorkerExchangeUrmaConnectInfo finish, elapsed = 3.26ms
```

**URMA Write**:
```
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1029
Remote get success, elapsed 92.531 ms
```

**内存区域信息**:
```
Local:  eid 4645:4944:2500:0000:2f00:0000:3000:0000, va 281367602528256
Remote: eid 4545:4944:2000:0000:2100:0000:2200:0000, va 281362233819136
len: 12884901888 (12GB)
attr: 449, token_id: 0
```

### Segment Import 详情

```
Import seg [6]: 0000:0000:0001:c060:0010:0000:dfdf:0906 <- 0000:0000:0000:0060:0010:0000:dfdf:07c6
Import seg [7]: 0000:0000:0001:c060:0010:0000:dfdf:0907 <- 0000:0000:0000:0060:0010:0000:dfdf:07c7
Import seg [15]: 0000:0000:0001:c060:0010:0000:dfdf:0926 <- 0000:0000:0000:0060:0010:0000:dfdf:07e6
Import seg [16]: 0000:0000:0001:c060:0010:0000:dfdf:0927 <- 0000:0000:0000:0060:0010:0000:dfdf:07e7
```

### Trace: 69608f19 (network: 46524us)

```
Worker 192.168.235.151 -> Worker 192.168.215.24
URMA write: useNumaAffinity:1, src:1, dst:1, jetty id:1095
Remote get success, elapsed 58.436 ms
```

---

## 三、时序分析

### Trace 0c3d819d 完整时序

| 时间 (worker1 时钟) | 事件 | 耗时 |
|---------------------|------|------|
| T+0us | client_req_framework | 49us |
| T+49us | worker1 发送请求 | - |
| T+~3000us | URMA_NEED_CONNECT 触发 | 新连接 |
| T+~8000us | URMA 连接建立完成 | ~5000us |
| T+~83000us | Remote get success | ~75000us (传输) |
| T+82701us | 总计 e2e | 82.7ms |

**关键发现**：
1. URMA 连接建立: ~8ms (占 10%)
2. 数据传输: ~75ms (占 90%)

---

## 四、根因分析

### 4.1 网络传输是主导因素

```
network_residual / e2e = 82509 / 82701 = 99.8%
```

99.8% 的时间花在网络传输上。

### 4.2 URMA 连接开销

| 阶段 | 耗时 | 占比 |
|------|------|------|
| Jetty 创建 | ~1ms | 12.5% |
| Segment Import | ~2ms | 25% |
| 连接握手 | ~5ms | 62.5% |
| **总计** | **~8ms** | **100%** |

### 4.3 可能的原因

1. **网络路径问题**: 跨交换机/路由
2. **RDMA QP 饱和**: 同时传输太多
3. **内存注册开销**: 每次传输需要注册内存
4. **对象大小**: 8MB 可能不是 RDMA 最优大小

---

## 五、结论

| 问题 | 答案 |
|------|------|
| network_residual 延迟？ | **40.6ms - 83.2ms** |
| 占比？ | **99.4% - 99.8%** |
| URMA 连接开销？ | **~8ms/新连接** |
| 根因？ | 网络传输主导，与 URMA/RDMA 配置相关 |

**根因**：系统网络 bound，URMA/RDMA 传输是主要瓶颈。连接建立和数据传输都有优化空间。

---

## 六、建议

1. **URMA 连接池** (P0)
   - 缓存 URMA 连接避免重建 (~8ms 节省)
   - 监控连接命中率

2. **RDMA 调优** (P0)
   ```
   - 检查 CQ (Completion Queue) 大小
   - 检查 QP (Queue Pair) 深度
   - 验证 MTU (应 > 2048)
   ```

3. **网络拓扑检查** (P1)
   - 确认是否为直连或跨交换机
   - 检查是否有路由绕行

4. **批量优化** (P1)
   - 考虑更大传输批次
   - 8MB 可能偏小

5. **监控告警** (P2)
   - network_residual > 50ms 触发告警
   - URMA 连接 > 10ms 触发告警

---

## 七、其他受影响 Trace

| Trace ID | network_residual_us | e2e_us | 占比 | URMA 连接类型 |
|----------|-------------------|--------|------|--------------|
| 0c3d819d | 82509 | 82701 | 99.8% | 新连接 |
| 2e978f3e | 66550 | 66768 | 99.7% | 新连接 |
| 69608f19 | 46524 | 46800 | 99.4% | 新连接 |
| 776cfbc9 | 83252 | 83567 | 99.6% | 新连接 |
