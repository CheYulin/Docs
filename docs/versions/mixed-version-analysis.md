# 跨版本兼容性分析

> Client: v0.8.1-rc18 | Worker: v0.8.1-rc20 | Target: v0.8.1-rc25
>
> 分析日期: 2026-05-12

---

## 概述

当前部署情况：

```
┌─────────────┐         ┌─────────────┐
│   Client    │  ─────►  │   Worker    │
│  v0.8.1-rc18│          │  v0.8.1-rc20│
└─────────────┘          └─────────────┘

升级目标:

┌─────────────┐         ┌─────────────┐
│   Client    │  ─────►  │   Worker    │
│  v0.8.1-rc25│          │  v0.8.1-rc25│
└─────────────┘          └─────────────┘
```

---

## 版本差距

| 组件 | 当前版本 | 目标版本 | 差距 |
|------|----------|----------|------|
| Client | rc18 | rc25 | **rc19 ~ rc25** (7 个 RC) |
| Worker | rc20 | rc25 | **rc21 ~ rc25** (5 个 RC) |

---

## Client rc18 → rc25 差距分析 (需要升级 client)

### 缺失的 PRs (共 31 个)

| PR # | 描述 | 类型 | 风险 | 说明 |
|------|------|------|------|------|
| !933 | fix: 避免跨机器时钟偏差扣减 ZMQ 超时 | fix | 🔴 高 | **重要**: 时钟偏差处理 |
| !859 | fix(client): MCreate NX placeholder 误用 isSeal 导致 MSet 报 already sealed | fix | 🔴 高 | **重要**: 客户端核心 bug |
| !903 | fix(rpc): reduce retry minimum timeout (后被 revert) | fix | 🟡 中 | 超时参数变更 |
| !950 | revert: minOnceRpcTimeoutMs 2ms → 10ms | revert | 🟢 低 | 超时参数回退 |
| !918 | fix: TCP rate limiting should also apply when client-worker lacks UB | fix | 🟡 中 | TCP 限流逻辑 |
| !897 | fix: add redirect for get object locations | fix | 🟡 中 | 对象位置重定向 |
| !898 | fix: persist sdk service discovery host id | fix | 🟡 中 | SDK 服务发现 |
| !899 | feat(rpc): add zmq latency metrics | feat | 🟢 低 | ZMQ 延迟指标 |
| !900 | feat[log]: 观测日志的hostpod字段，优先打印podip | feat | 🟢 低 | 日志字段优化 |
| !902 | fix(worker): support etcd auth for hash ring cli | fix | 🟢 低 | Worker 相关 |
| !904 | Optimize KV Exist local checks | perf | 🟢 低 | KV 检查优化 |
| !907 | Warm up worker master RPC stubs reliably | feat | 🟡 中 | RPC 预热 |
| !909 | fix: bugfix for bazel build | fix | 🟢 低 | Build 修复 |
| !916 | fix: pass timeout to thread pool tasks for batch remote get | fix | 🟡 中 | 超时传递 |
| !917 | fix: make log rate limiter nonblocking | fix | 🟡 中 | 日志限流 |
| !919 | Remove print log | fix | 🟢 低 | 删除调试日志 |
| !922 | fix: 调整 URMA 慢日志阈值 | fix | 🟢 低 | URMA 日志 |
| !930 | fix(log): sample warning/error/fatal in request log rate limiter | fix | 🟢 低 | 日志采样 |
| !934 | Fix: Optimize log print | fix | 🟢 低 | 日志优化 |
| !935 | fix: reduce high-frequency logs | fix | 🟢 低 | 减少日志 |
| !936 | perf: optimize request path log volume for Master/Worker | perf | 🟢 低 | 日志优化 |
| !937 | fix: reduce meta moving retry wait | fix | 🟡 中 | Meta 迁移 |
| !938 | feat(log): add option to skip warning/error log files | feat | 🟢 低 | 日志功能 |
| !939 | perf: reduce object cache request log volume | perf | 🟢 低 | 日志优化 |
| !940 | feat: mark sampled request access logs | feat | 🟢 低 | 日志功能 |
| !941 | perf: reduce thread pool warning log and sdk logs | perf | 🟢 低 | 日志优化 |
| !942 | perf: batch eviction remove-meta requests | perf | 🟢 低 | 批量 eviction |
| !945 | tools: add KVCache log analysis scripts | tools | 🟢 低 | 工具 |
| !954 | fix: skip retry delete unacked meta when timeout exhausted | fix | 🟡 中 | 删除优化 |
| !959 | add rpc slow log | feat | 🟡 中 | RPC 慢日志 |
| !970 | fix: remove PID from dsclient log filename | fix | 🟢 低 | 日志优化 |

### Client 缺失的关键功能

| 功能 | 相关 PR | 影响 |
|------|---------|------|
| **MCreate NX placeholder bug 修复** | !859 | 可能导致 MSet 报错 "already sealed" |
| **时钟偏差处理** | !933 | 跨机房部署时 ZMQ 超时计算错误 |
| **RPC 预热机制** | !907 | 冷启动性能可能较差 |
| **TCP 限流完善** | !918 | 高并发场景可能有限流问题 |
| **ZMQ 延迟指标** | !899 | 缺少延迟监控能力 |

---

## Worker rc20 → rc25 差距分析

### 新增 PRs (共 11 个)

| PR # | 描述 | 类型 | 风险 | 说明 |
|------|------|------|------|------|
| !945 | tools: add KVCache log analysis scripts | tools | 🟢 低 | 日志分析工具 |
| !950 | revert: minOnceRpcTimeoutMs 2ms → 10ms | revert | 🟢 低 | **回退超时调整** |
| !951 | perf: increase min thread pool size for OC Get operations | perf | 🟢 低 | 线程池扩展 |
| !952 | perf: increase thread pool size for RPC | perf | 🟢 低 | RPC 线程池扩容 |
| !954 | fix: skip retry delete unacked meta when timeout exhausted | fix | 🟡 中 | 删除重试优化 |
| !955 | Add PLOG slow get diagnostics | feat | 🟡 中 | PLOG 慢诊断 |
| !956 | perf: add intermediate RPC latency checks | perf | 🟢 低 | RPC 延迟检查 |
| !957 | perf: add zmq_client_io_thread flag | perf | 🟢 低 | ZMQ 线程可配置 |
| !958 | perf: increase async_release_buffer thread pool from 1 to 4 | perf | 🟢 低 | 线程池扩展 4x |
| !959 | add rpc slow log | feat | 🟡 中 | RPC 慢日志 |
| !970 | fix: remove PID from dsclient log filename | fix | 🟢 低 | 日志文件名优化 |

### Worker rc25 新增的关键功能

| 功能 | 相关 PR | 影响 |
|------|---------|------|
| **线程池资源扩展** | !951, !952, !958 | 内存使用可能上升 |
| **RPC 慢日志诊断** | !959 | 可观测性增强 |
| **删除重试优化** | !954 | 删除操作更可靠 |
| **超时参数回退** | !950 | 2ms → 10ms 更稳定 |

---

## 🔴 跨版本兼容性问题 (Client rc18 + Worker rc20)

### 1. 协议兼容性

**Client rc18 与 Worker rc20 之间的 RPC 协议是兼容的**，因为主要的协议变更都在 rc20 之前完成了。

但需要注意以下潜在问题：

| 场景 | 风险 | 说明 |
|------|------|------|
| MCreate NX + MSet | 🔴 高 | Client rc18 的 MCreate 有 bug，可能导致 MSet 报 "already sealed" |
| 跨机房部署 | 🔴 高 | 时钟偏差处理缺失，可能导致超时问题 |
| RPC 预热 | 🟡 中 | Client 没有 RPC 预热，可能导致冷启动延迟 |

### 2. 功能兼容性矩阵

| 功能 | Client rc18 | Worker rc20 | 兼容状态 |
|------|-------------|-------------|----------|
| 基础 Object Cache | ✅ | ✅ | ✅ 兼容 |
| MCreate/MSet | ⚠️ 有 bug | ✅ | ⚠️ 可能报错 |
| RPC 预热 | ❌ 不支持 | ✅ 支持 | ⚠️ 降级运行 |
| ZMQ 延迟指标 | ❌ | ✅ | ⚠️ 指标缺失 |
| TCP 限流 | ⚠️ 不完善 | ✅ 完善 | ⚠️ 限流可能不均 |
| URMA 连接 | ✅ | ✅ | ✅ 兼容 |

---

## 📋 升级路径建议

### 推荐方案：Client 和 Worker 一起升级到 rc25

```
Phase 1: Client rc18 + Worker rc20 (当前)
    ↓
Phase 2: Client rc25 + Worker rc25 (推荐一起升级)
```

### 升级步骤

1. **先在测试环境验证**
   - Client rc25 + Worker rc25 完整测试
   - 重点验证 MCreate/MSet 场景

2. **灰度发布**
   - 先升级 Worker 到 rc25
   - 观察 RPC 预热日志
   - 确认线程池资源使用正常

3. **Client 升级**
   - Worker rc25 稳定后，升级 Client 到 rc25
   - 观察 MSet 操作是否正常

### 不推荐的方案

| 方案 | 风险 | 说明 |
|------|------|------|
| 只升级 Worker (Client 保持 rc18) | 🔴 高 | MCreate bug 仍会影响 MSet |
| 只升级 Client (Worker 保持 rc20) | 🟡 中 | 可能缺少 Worker 的一些兼容性修复 |

---

## ⚠️ 升级风险评估

### 立即升级到 rc25 的风险

| 风险项 | 等级 | 说明 | 缓解措施 |
|--------|------|------|----------|
| MCreate bug | 🔴 高 | !859 修复了 NX placeholder 误用问题 | 升级后需测试 MSet 场景 |
| 时钟偏差 | 🔴 高 | !933 处理跨机房时钟偏差 | 跨机房部署需验证 |
| 线程池扩展 | 🟡 中 | 内存使用可能上升 | 监控内存使用 |
| 日志变更 | 🟢 低 | PID 从日志文件名移除 | 检查日志收集规则 |

### 当前版本继续运行的风险

| 风险项 | 等级 | 说明 |
|--------|------|------|
| MCreate bug | 🔴 高 | 生产环境可能遇到 MSet 报错 |
| 时钟偏差 | 🔴 高 | 跨机房部署可能超时计算错误 |
| 缺少监控 | 🟡 中 | 无法获取 ZMQ 延迟指标 |

---

## 🧪 升级前检查清单

### 功能验证

- [ ] MSet 操作是否正常 (MCreate NX 场景)
- [ ] 跨机房网络延迟场景是否正常
- [ ] RPC 冷启动延迟是否可接受
- [ ] TCP 限流是否有效

### 资源验证

- [ ] 线程池扩展后内存使用情况
- [ ] ZMQ IO 线程配置是否合理
- [ ] RPC 线程池负载情况

### 日志验证

- [ ] 日志文件名变更是否影响日志收集
- [ ] 新增的 RPC 慢日志是否正常输出
- [ ] 日志量是否在预期范围内

---

## 📊 总结

### 当前版本组合

| 组件 | 版本 | 已知问题 |
|------|------|----------|
| Client | rc18 | ⚠️ MCreate bug, 时钟偏差未处理 |
| Worker | rc20 | ⚠️ 部分功能缺失 |

### 升级收益 (到 rc25)

| 类别 | 收益 |
|------|------|
| **Bug 修复** | MCreate NX placeholder bug、时钟偏差问题 |
| **性能优化** | 线程池扩展、批量 eviction 优化 |
| **可观测性** | RPC 慢日志、ZMQ 延迟指标 |
| **可靠性** | 删除重试优化、RPC 预热 |

### 最终建议

> **强烈建议 Client 和 Worker 一起升级到 rc25**
>
> 当前 rc18 + rc20 的组合存在已知的 MCreate bug 和时钟偏差风险，建议尽快升级。
