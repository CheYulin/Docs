# v0.8.1 版本变更分析

> 分析日期: 2026-05-12
>
> **注意**: 当前仓库最新 tag 为 `v0.8.1.rc25`

---

## 目录

- [v0.8.1-rc20 → v0.8.1-rc25 完整变更](#v081-rc20--v081-rc25-完整变更)
- [v0.8.1-rc23 → v0.8.1-rc25 新增变更](#v081-rc23--v081-rc25-新增变更)
- [风险评估](#风险评估)
- [升级建议](#升级建议)

---

## v0.8.1-rc20 → v0.8.1-rc25 完整变更

### 概述

| 指标 | 数值 |
|------|------|
| 总 Commits | 74 |
| 涉及 PRs | 35 |
| 新增 feat | 4 |
| 修复 fix | 21 |
| 性能优化 perf | 8 |
| revert | 1 |
| tools | 1 |

### PR 列表 (35 个)

| PR # | 描述 | 类型 | 风险等级 |
|------|------|------|----------|
| !970 | fix: remove PID from dsclient log filename | fix | 🟢 低 |
| !959 | add rpc slow log | feat | 🟡 中 |
| !958 | perf: increase async_release_buffer thread pool from 1 to 4 | perf | 🟢 低 |
| !957 | perf: add zmq_client_io_thread flag for client ZMQ IO thread configuration | perf | 🟢 低 |
| !956 | perf: add intermediate RPC latency checks to prevent metric loss on dropped requests | perf | 🟢 低 |
| !955 | Add PLOG slow get diagnostics | feat | 🟡 中 |
| !954 | fix: skip retry delete unacked meta when timeout exhausted | fix | 🟡 中 |
| !952 | perf: increase thread pool size for RPC | perf | 🟢 低 |
| !951 | perf: increase min thread pool size for OC Get operations | perf | 🟢 低 |
| !950 | revert(rpc): restore minOnceRpcTimeoutMs from 2ms back to 10ms | revert | 🟢 低 |
| !945 | tools: add KVCache log analysis scripts and project skill | tools | 🟢 低 |
| !942 | perf: batch eviction remove-meta requests | perf | 🟢 低 |
| !941 | perf: reduce thread pool warning log and sdk logs | perf | 🟢 低 |
| !940 | feat: mark sampled request access logs | feat | 🟢 低 |
| !939 | perf: reduce object cache request log volume | perf | 🟢 低 |
| !938 | feat(log): add option to skip warning/error log files | feat | 🟢 低 |
| !937 | fix: reduce meta moving retry wait | fix | 🟡 中 |
| !936 | perf: optimize request path log volume for Master/Worker | perf | 🟢 低 |
| !935 | fix: reduce high-frequency logs | fix | 🟢 低 |
| !934 | Fix: Optimize log print | fix | 🟢 低 |
| !933 | fix: 避免跨机器时钟偏差扣减 ZMQ 超时 | fix | 🔴 高 |
| !930 | fix(log): sample warning/error/fatal in request log rate limiter | fix | 🟢 低 |
| !922 | fix: 调整 URMA 慢日志阈值 | fix | 🟢 低 |
| !919 | Remove print log | fix | 🟢 低 |
| !918 | fix: TCP rate limiting should also apply when client-worker lacks UB | fix | 🟡 中 |
| !917 | fix: make log rate limiter nonblocking | fix | 🟡 中 |
| !916 | fix: pass timeout to thread pool tasks for batch remote get | fix | 🟡 中 |
| !909 | fix: bugfix for bazel build | fix | 🟢 低 |
| !907 | Warm up worker master RPC stubs reliably | feat | 🟡 中 |
| !904 | Optimize KV Exist local checks | perf | 🟢 低 |
| !903 | fix(rpc): reduce retry minimum timeout (后被 revert) | fix | 🟡 中 |
| !902 | fix(worker): support etcd auth for hash ring cli | fix | 🟢 低 |
| !900 | feat[log]: 观测日志的hostpod字段，优先打印podip | feat | 🟢 低 |
| !899 | feat(rpc): add zmq latency metrics | feat | 🟢 低 |
| !898 | fix: persist sdk service discovery host id | fix | 🟡 中 |
| !897 | fix: add redirect for get object locations | fix | 🟡 中 |
| !859 | fix(client): MCreate NX placeholder 误用 isSeal 导致 MSet 报 already sealed | fix | 🔴 高 |

### 按类型统计

| 类型 | 数量 | 占比 |
|------|------|------|
| perf | 8 | 22.9% |
| fix | 21 | 60.0% |
| feat | 4 | 11.4% |
| revert | 1 | 2.9% |
| tools | 1 | 2.9% |

---

## v0.8.1-rc23 → v0.8.1-rc25 新增变更

这是 **rc25 相比 rc23 的增量**，共 **22 个 commits**，**11 个 PRs**。

### 新增 PR 列表

| PR # | 描述 | 类型 | 风险等级 | 说明 |
|------|------|------|----------|------|
| !970 | fix: remove PID from dsclient log filename | fix | 🟢 低 | 日志文件名简化 |
| !959 | add rpc slow log | feat | 🟡 中 | **新增**: RPC 慢日志诊断 |
| !958 | perf: increase async_release_buffer thread pool from 1 to 4 | perf | 🟢 低 | 线程池扩展 4x |
| !957 | perf: add zmq_client_io_thread flag for client ZMQ IO thread configuration | perf | 🟢 低 | ZMQ IO 线程可配置 |
| !956 | perf: add intermediate RPC latency checks to prevent metric loss | perf | 🟢 低 | RPC 中间延迟检查 |
| !955 | Add PLOG slow get diagnostics | feat | 🟡 中 | **新增**: PLOG 慢请求诊断 |
| !954 | fix: skip retry delete unacked meta when timeout exhausted | fix | 🟡 中 | 删除操作优化 |
| !952 | perf: increase thread pool size for RPC | perf | 🟢 低 | RPC 线程池扩展 |
| !951 | perf: increase min thread pool size for OC Get operations | perf | 🟢 低 | OC Get 线程池扩展 |
| !950 | revert(rpc): restore minOnceRpcTimeoutMs from 2ms back to 10ms | revert | 🟢 低 | **重要 revert**: 回退超时调整 |
| !945 | tools: add KVCache log analysis scripts and project skill | tools | 🟢 低 | KVCache 日志分析工具 |

### rc25 主题分析

#### 1. 线程池资源扩展 (重点)
rc25 是一个 **"资源扩展"** 版本，大量线程池参数被上调：

| PR | 变更 |
|----|------|
| !958 | async_release_buffer 线程池: 1 → 4 |
| !952 | RPC 线程池扩容 |
| !951 | OC Get 线程池最小值扩容 |
| !957 | ZMQ IO 线程可配置 |

⚠️ **注意**: 这些变更可能导致内存使用量上升

#### 2. 诊断能力增强
- `!959` **RPC 慢日志** - 新增
- `!955` **PLOG 慢请求诊断** - 新增
- `!956` RPC 中间延迟检查

#### 3. 关键 Revert
- `!950` 回退了 `!903` 的超时调整（2ms → 10ms），表明 2ms 超时过短导致问题

---

## 风险评估

### 🔴 高风险项

| PR # | 描述 | 风险说明 | 建议 |
|------|------|----------|------|
| !933 | 避免跨机器时钟偏差扣减 ZMQ 超时 | 时钟偏差处理逻辑变更，可能影响 ZMQ 超时计算 | ⚠️ 需在跨机房部署环境充分测试 |
| !859 | MCreate NX placeholder 误用 isSeal 导致 MSet 报 already sealed | 客户端核心逻辑修复，可能影响现有 MSet 行为 | ⚠️ 需验证现有 MSet 调用链 |

### 🟡 中风险项

| PR # | 描述 | 风险说明 | 建议 |
|------|------|----------|------|
| !970 | remove PID from dsclient log filename | 日志文件名变更可能导致日志收集规则失效 | 检查日志路径配置 |
| !959 | add rpc slow log | 新增日志可能增加日志量 | 确认慢日志阈值配置 |
| !955 | Add PLOG slow get diagnostics | 新增诊断可能增加日志量 | 确认诊断开关 |
| !954 | fix: skip retry delete unacked meta | 删除重试逻辑变更 | 验证删除可靠性 |
| !903→!950 | minOnceRpcTimeoutMs 2ms → 10ms → 2ms → 10ms | 超时参数来回调整，需确认稳定值 | 验证 10ms 超时是否合理 |
| !907 | Warm up worker master RPC stubs reliably | RPC 预热机制变更，可能影响冷启动行为 | 验证预热逻辑正确性 |

### 🟢 低风险项

- perf 优化 (8 个): 线程池扩展、日志降量
- 日志相关 (5 个): 采样优化、格式优化
- Build 修复 (1 个)
- 工具类 (1 个)

---

## 升级建议

### 升级路径
```
v0.8.1-rc20 → v0.8.1-rc25 (建议灰度发布)
```

### rc25 相比 rc20 的关键变化

#### 1. ✅ 新增功能
- RPC stubs 预热机制 (!907)
- ZMQ 延迟指标 (!899)
- 可配置日志文件跳过 (!938)
- **RPC 慢日志诊断** (!959) - rc25 新增
- **PLOG 慢请求诊断** (!955) - rc25 新增

#### 2. ✅ Bug 修复
- MCreate NX placeholder 严重 bug (!859)
- 时钟偏差导致 ZMQ 超时问题 (!933)
- TCP 限流逻辑完善 (!918)
- **删除操作优化** (!954) - rc25 新增

#### 3. ⚠️ 需注意
- **线程池资源扩展** (可能导致内存使用上升)
  - async_release_buffer: 1 → 4
  - RPC 线程池扩容
  - OC Get 线程池扩容
- **超时参数最终回退到 10ms** (!950)
- **日志采样策略变更**
- **非阻塞日志限流器**

### 测试建议

| 场景 | 重点验证 |
|------|----------|
| 跨机房部署 | 时钟偏差场景下 ZMQ 超时是否正常 |
| MSet 操作 | 确认 NX placeholder 场景不再报错 |
| 冷启动 | RPC 预热是否按预期工作 |
| 高并发 | TCP 限流新逻辑是否有效 |
| 日志量 | 新日志策略是否达到降量目标 |
| **资源使用** | 线程池扩展后内存使用是否正常 |
| **超时场景** | 10ms 超时是否满足业务需求 |

---

## 更新历史

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-05-12 | v2.0 | 更新分析 v0.8.1-rc20 ~ v0.8.1-rc25，新增 rc23-rc25 增量 |
| 2026-05-12 | v1.0 | 初始版本，分析 v0.8.1-rc18 ~ v0.8.1-rc23 |
