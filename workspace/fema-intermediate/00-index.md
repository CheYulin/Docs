# FMEA 文档索引 v2.0

---

## 文档结构

```
fema-intermediate/
├── code-evidence/
│   ├── 01-urma-fault-detection.md    # URMA层故障检测代码证据
│   ├── 02-component-lifecycle.md     # 组件生命周期代码证据
│   └── 03-os-layer-faults.md        # OS层故障检测代码证据
├── 05-urma-api-faults.md           # URMA API错误传播
├── 06-kvcache-interface-faults.md    # KVCache接口故障
├── 07-core-flow-orthogonal-analysis.md  # 核心流程正交分析
├── 08-fault-triage-guide.md         # 故障定位定界指南（三板斧）
├── 09-fault-test-construction.md   # 故障测试构造指南
├── 10-quick-reference-card.md         # 快速参考卡
├── 11-fault-triage-flowcharts.md     # 故障排查流程图
└── 00-index.md                      # 本文档

workspace/
├── fema-final.csv                   # FMEA最终分析（65条目，4大类）
└── fema-analysis-filled.csv         # FMEA详细分析（48条目）
```

---

## 故障域分类（4大类）

| 故障域 | 错误码 | 典型日志 | 日志来源 |
|--------|--------|---------|---------|
| **A类-用户层** | 2/3/8 | respMsg关键字 | Client日志 |
| **B类-OS层控制面** | 1001/1002/19 | `[TCP_*]` / `[ZMQ_*]` / `[RPC_*]` | Worker日志 |
| **C类-URMA层** | 1004/1006/1008/1010 | `[URMA_*]` / `fallback to TCP` | Worker日志 |
| **D类-组件层** | 23/31/32/5/6/7/13/20/25 | `[HealthCheck]` / etcd/memory指标 | Worker日志 |

---

## 故障处理路线图

```
 ┌─ 用户层(A) ─────────────────────────────────────────┐
 │  K_INVALID(2) / K_NOT_FOUND(3) / K_NOT_READY(8)     │
 │  → 查respMsg关键字 / 检查业务参数                     │
 └─────────────────────────────────────────────────────┘
 │
┌─ 成功率↓/P99↑ ─┼─ OS层-控制面(B) ─────────────────────────┐
│                │  K_RPC_*(1001/1002) / K_TRY_AGAIN(19)     │
│                │  → 查[TCP_*] / [ZMQ_*] / [RPC_*]结构化日志  │
│                └────────────────────────────────────────────┘
│                              │
└──────────────┼─ URMA层(C) ─────────────────────────────────────┐
               │  K_URMA_*(1004/1006/1008/1010)                     │
               │  → 查[URMA_*]标签 + UB/TCP bytes                   │
               └────────────────────────────────────────────────────┘
                              │
 ┌─ 组件层(D) ─────────────────────────────────────────┐
 │  K_CLIENT_WORKER_DISCONNECT(23)                      │
 │  K_SCALE_DOWN(31) / K_SCALING(32)                    │
 │  K_OUT_OF_MEMORY(6) / K_MASTER_TIMEOUT(25)            │
 │  → 查[HealthCheck]标签 / etcd状态 / 内存指标         │
 └─────────────────────────────────────────────────────┘
```

---

## 核心流程 × 故障模式 覆盖

| 核心流程 | 故障数 | 覆盖状态 |
|---------|--------|---------|
| SDK Init | 6 | ✅ |
| MCreate | 8 | ✅ |
| MPublish | 9 | ✅ |
| MGet | 12 | ✅ |
| Exist | 6 | ✅ |
| 远端读取(Worker↔Worker) | 8 | ✅ |
| 组件生命周期 | 7 | ✅ |

---

## FMEA分析差异说明

| 维度 | fema-analysis-filled | fema-final |
|------|---------------------|------------|
| 分析维度 | 单一大类(datasystem) | 四级分类(User/OS/URMA/Component) |
| 条目数 | 48 | 65 |
| 特色 | 详细的故障传播链路 | 按故障域分类，便于定界 |
| 用途 | 开发参考 | 测试验收/运维定界 |

---

## 更新日志

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| v2.0 | 2026-04-21 | 统一故障域为4类，去除Stream/PR编号/自证清白公式 |
| v2.0 | 2026-04-21 | 新增 `11-fault-triage-flowcharts.md` 流程图 |
| v1.0 | 2026-04-20 | 初始版本 |
