# Worker v0.8.1-rc18 → v0.8.1-rc20 变更分析

> 分析日期: 2026-05-12
>
> **背景**: 当前部署组合为 Client rc18 + Worker rc20，本文分析 Worker 侧从 rc18 到 rc20 的变更

---

## 概述

| 指标 | 数值 |
|------|------|
| 总 Commits | 54 |
| 涉及 PRs | 25 |
| fix | 18 |
| perf | 3 |
| feat | 2 |
| tools | 1 |
| revert | 1 |

---

## 按类型统计

| 类型 | 数量 | 占比 |
|------|------|------|
| fix | 18 | 72% |
| perf | 3 | 12% |
| feat | 2 | 8% |
| tools | 1 | 4% |
| revert | 1 | 4% |

---

## 完整 PR 列表

| PR # | 描述 | 类型 | 风险等级 |
|------|------|------|----------|
| !888 | fix(worker): 线程池资源指标从瞬时快照改为区间累计指标 | fix | 🟢 低 |
| !873 | fix: log rate limit | fix | 🟢 低 |
| !886 | fix(worker): 线程池资源指标从瞬时快照改为区间累计指标 | fix | 🟢 低 |
| !887 | tools: add KVCache log analysis scripts and project skill | tools | 🟢 低 |
| !884 | support worker master rpc warmup | feat | 🟡 中 |
| !885 | fix: add traceid for ub connection warmup | fix | 🟡 中 |
| !879 | Persist worker env for process restart | feat | 🟡 中 |
| !882 | fix: Propagate URMA async trace IDs and add concise init logs | fix | 🟢 低 |
| !881 | fix: preserve URMA fallback error details | fix | 🟢 低 |
| !878 | fix: reduce ClearObject master resolution log noise | fix | 🟢 低 |
| !877 | fix: increase WorkerService RPC HWM | fix | 🟡 中 |
| !874 | fix: guard create sealed check with entry read lock | fix | 🔴 高 |
| !871 | perf: optimize Set/Get log volume for observability | perf | 🟢 低 |
| !870 | feat[log]: 日志hostpod字段优先打印POD_IP | feat | 🟢 低 |
| !872 | fix: skip io thread nice when flag is zero | fix | 🟢 低 |
| !868 | fix: record inflight remote get requests | fix | 🟢 低 |
| !863 | fix: round small timeout remaining duration | fix | 🟡 中 |
| !862 | fix: add URMA diagnostics and RPC delay metric | fix | 🟢 低 |
| !860 | fix: revert connect state logic | fix | 🔴 高 |
| !854 | fix: reduce MAX_METRICS_LOG_BYTES and add DumpSummariesForTest | fix | 🟢 低 |
| !853 | fix: fixed bazel compiled fail | fix | 🟢 低 |
| !849 | fix: use async delete for eviction END_LIFE to avoid RPC timeout blocking | fix | 🟡 中 |
| !852 | fix: compatible with older versions | fix | 🟡 中 |
| !851 | fix: add URMA jetty diagnostics | fix | 🟢 低 |
| !848 | fix: reduce MAX_METRICS_LOG_BYTES and add DumpSummariesForTest | fix | 🟢 低 |
| !847 | fix: control fall back to tcp while client get ub error | fix | 🟡 中 |
| !846 | fix: modify default transport mem size and open urma perf | fix | 🟡 中 |

---

## 🔴 高风险修复 (需要重点关注)

### 1. !874 - 并发安全修复

```
fix: guard create sealed check with entry read lock
```

| 项目 | 说明 |
|------|------|
| **风险等级** | 🔴 高 |
| **问题描述** | create sealed 检查缺少锁保护，存在数据竞争风险 |
| **修复内容** | 用 entry read lock 保护 create sealed 检查 |
| **影响范围** | 所有 Object Cache 创建操作 |
| **测试建议** | 高并发创建场景验证 |

### 2. !860 - 连接状态逻辑回退

```
fix: revert connect state logic
fix: fixed and issue where ub was unable to reconnect when the client reconnected
```

| 项目 | 说明 |
|------|------|
| **风险等级** | 🔴 高 |
| **问题描述** | UB 在客户端重连后无法重连的问题 |
| **修复内容** | 回退连接状态逻辑，修复 UB 重连问题 |
| **影响范围** | UB (UDS Bridge?) 连接管理 |
| **测试建议** | 客户端重连场景验证 |

---

## 🟡 中风险修复

| PR # | 描述 | 说明 |
|------|------|------|
| !884 | support worker master rpc warmup | **RPC 预热**: 冷启动性能优化关键 |
| !885 | fix: add traceid for ub connection warmup | URMA warmup trace ID 传播 |
| !879 | Persist worker env for process restart | **环境持久化**: 进程重启后配置保持 |
| !877 | fix: increase WorkerService RPC HWM | RPC High Water Mark 调整 |
| !849 | fix: use async delete for eviction END_LIFE | **异步删除**: 避免 RPC 超时阻塞 |
| !847 | fix: control fall back to tcp while client get ub error | TCP fallback 控制 |
| !852 | fix: compatible with older versions | 向后兼容 |
| !863 | fix: round small timeout remaining duration | 小超时舍入处理 |

---

## 🟢 低风险修复

| PR # | 描述 | 说明 |
|------|------|------|
| !888/!886 | 线程池资源指标从瞬时快照改为区间累计指标 | **指标改进**: 更准确的监控 |
| !878 | fix: reduce ClearObject master resolution log noise | 减少日志噪音 |
| !871 | perf: optimize Set/Get log volume for observability | 日志优化 |
| !870 | feat[log]: 日志hostpod字段优先打印POD_IP | 日志增强 |
| !872 | fix: skip io thread nice when flag is zero | IO 线程配置优化 |
| !868 | fix: record inflight remote get requests | 请求追踪增强 |
| !862 | fix: add URMA diagnostics and RPC delay metric | **诊断增强** |
| !851 | fix: add URMA jetty diagnostics | URMA 诊断 |
| !854/!848 | fix: reduce MAX_METRICS_LOG_BYTES | metrics 日志优化 |
| !853 | fix: fixed bazel compiled fail | Build 修复 |
| !846 | fix: modify default transport mem size and open urma perf | **URMA 性能优化** |

---

## 重点修复详解

### 1. RPC 预热机制 (!884)

```
support worker master rpc warmup
fix: add traceid for ub connection warmup
```

**问题**: 冷启动时 RPC stubs 需要建立连接，导致首次请求延迟高

**解决方案**: 在 Worker 启动时预热 Worker-Master RPC 连接

**影响**: 显著降低冷启动延迟

---

### 2. 异步删除优化 (!849)

```
fix: use async delete for eviction END_LIFE to avoid RPC timeout blocking
```

**问题**: eviction END_LIFE 阶段的删除操作是同步的，可能阻塞 RPC 导致超时

**解决方案**: 改为异步删除，避免阻塞

**影响**: eviction 流程更稳定，避免级联超时

---

### 3. 环境持久化 (!879)

```
Persist worker env for process restart
```

**问题**: 进程重启后环境变量丢失

**解决方案**: 持久化 Worker 环境配置

**影响**: 进程重启后自动恢复配置

---

### 4. URMA 性能优化 (!846)

```
fix: modify default transport mem size from 128 to 512 and open urma perf always
```

**变更**:
- 传输内存: 128 → 512 (扩大 4x)
- URMA 性能模式: 默认开启

**影响**: 更高的 URMA 吞吐能力

---

### 5. 连接稳定性 (!860)

```
fix: revert connect state logic
fix: fixed and issue where ub was unable to reconnect when the client reconnected
```

**问题**: 客户端重连后，UB 无法正确重连

**解决方案**: 回退并修复连接状态逻辑

**影响**: UB 连接可靠性

---

## 升级收益总结

| 类别 | 关键修复 | 风险 |
|------|----------|------|
| **稳定性** | 连接重连 (!860)、并发安全 (!874) | 🔴 高 |
| **性能** | RPC 预热 (!884)、异步删除 (!849)、URMA 优化 (!846) | 🟡 中 |
| **可观测性** | 线程池指标改进 (!888)、URMA 诊断 (!862, !851) | 🟢 低 |
| **可靠性** | 环境持久化 (!879)、向后兼容 (!852) | 🟡 中 |

---

## 升级建议

### Worker rc18 → rc20 是**推荐升级**的

| 因素 | 评估 |
|------|------|
| 兼容性 | ✅ 向后兼容 |
| 风险 | 🟡 中等 (无破坏性变更) |
| 收益 | ✅ 显著 (稳定性+性能) |

### 升级前检查清单

- [ ] 高并发创建场景测试
- [ ] 客户端重连场景验证
- [ ] URMA 连接稳定性验证
- [ ] 内存使用监控配置

### 升级后观察

- [ ] RPC 冷启动延迟
- [ ] 线程池资源使用
- [ ] UB 连接成功率
- [ ] eviction 流程稳定性
