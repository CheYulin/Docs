# 可维可测近期PR分析与薄弱点识别

> 日期：2026-04-22
> 范围：近2周（2026-04-07 ~ 2026-04-21）合入PR
> 重点：可维可测 / Metrics / 日志采样相关需求

---

## 一、近期可维可测相关PR汇总

### 1.1 Metrics 与日志格式

| PR | 标题 | 作者 | 合入日 | 类型 | 说明 |
|----|------|------|--------|------|------|
| #669 / #648 | fix(metrics): emit one-line json summary logs | yaohaolin | 04-20/21 | fix | Metrics Summary从多行文本改为单行JSON，避免filebeat按行采集后无法关联同一批metrics。超长日志按`part_index/part_count`自动拆成多条。TraceID复用`${pod_name}-metrics`前缀。 |
| #652 | feat(metrics): SHM leak observability metrics (phase 1-3) | yche-huawei | 04-20 | feat | 新增18个SHM泄漏相关Metrics（KvMetricId 36..53）：Worker端10个（alloc/free/ref_table）、Master端6个（TTL链路）、Client端2个（异步释放）。泄漏判据：`alloc_bytes delta > free_bytes delta` + `ref_table_bytes`持续涨 + `worker_object_count`持平。 |

### 1.2 日志增强

| PR | 标题 | 作者 | 合入日 | 类型 | 说明 |
|----|------|------|--------|------|------|
| #683 | fix: complete urma resource logs | feeiyu | 04-21 | fix | 补齐`urma_resource.cpp`中`ds_urma_*`调用的日志覆盖，避免部分调用缺少调用前或成功日志；将拆分成功/失败日志收敛为单分支。 |
| #677 / #676 | fix: fix error log | weihongyu222 | 04-21 | fix | 去掉不必要的error日志，减少干扰。 |
| #643 / #644 | fix: add reconFlag wait diagnostics | yangxiaogang14 | 04-20 | fix | Worker处理Publish等请求前调用`ValidateWorkerState()`获取`reconFlag_`读锁时线上出现`Waiting for the reconFlag...`，请求耗时增加约10ms。客户的`requestTimeoutMS=8ms`导致RPC unavailable。新增诊断日志揭示该等待场景。 |

### 1.3 资源/内存相关

| PR | 标题 | 作者 | 合入日 | 类型 | 说明 |
|----|------|------|--------|------|------|
| #668 / #660 | fix(shared_memory): advise hugepage for thp mmap | yaohaolin / feeiyu | 04-21 | fix | 当`enable_thp=true`时，为`MemMmap`创建的memfd共享内存在`mmap`成功后追加`madvise(..., MADV_HUGEPAGE)`提示，让THP配置显式作用到共享内存映射。 |
| #641 | fix: reconcile shm refs on current URMA worker | yaohaolin | 04-20 | fix | 修复client开启URMA且跨节点切换后，`ShmRefReconcileThreadFunc()`仍固定向`LOCAL_WORKER`发起`ReconcileShmRef`的问题。导致orphan shm ref无法被清理，worker共享内存持续上涨。修改为优先使用`currentNode_`对应worker执行对账。 |

### 1.4 客户端行为修复

| PR | 标题 | 作者 | 合入日 | 类型 | 说明 |
|----|------|------|--------|------|------|
| #649 / #646 | fix: delay fast transport init until heartbeat is active | yangxiaogang14 | 04-20 | fix | 开启URMA/UB后，client初始化过程中fast transport本地资源初始化阻塞导致client heartbeat线程未启动，worker超过`client_dead_timeout_s`判定client失联并删除。后续fallback到TCP/IP也无法恢复。将fast transport初始化延迟到heartbeat启动之后。 |
| #662 / #656 | fix: handle kv client switch during voluntary scale-down | yaohaolin | 04-21 | fix | 修复KVClient在`enableCrossNodeConnection`打开、worker依次下线且最终无可切换worker时请求线程卡在worker切换流程中的问题。新增`NO_SWITCHABLE_WORKER`状态，请求快速失败避免业务线程长期阻塞。 |
| #664 / #666 | fix: 修复并发调用shutdown可能会coredump的问题 | sunyuchang / OuGongChang | 04-21 | fix | 5000线程并发调用`Shutdown()`时多个线程同时对同一个`std::thread`调用`join()`导致`std::terminate()`。用`metricsMutex_`保护空指针检查和线程移动操作。 |
| #679 / #678 | fix: 修复RETRY_ON_ERROR一直retry的问题 | zhujunliang | 04-21 | fix | remote get retry过程中remain time计算问题：当remain time <= minRetryOnceRpcMs时可能做`remain -= (remain - minRetryOnceRpcMs)`出现0导致大量短时间超时报错。 |
| #645 / #653 | fix: fix oom return rpc unavailable | weihongyu222 / OuGongChang | 04-20 | fix | OOM时client在剩余时间很短的情况下重试，worker返回给client的时间只有几ms，client在50ms内没收到返回导致最终RPC失败。改为在rpc时间剩余很短时不进行重试。 |

### 1.5 近期其他PR（未归类可维可测，但有参考价值）

| PR | 标题 | 作者 | 合入日 | 说明 |
|----|------|------|--------|------|
| #640 | feat(obs): 实现双签名系统支持MinIO/S3兼容 | OuGongChang | 04-20 | OBS客户端双签名：OBS V2 + AWS V4自动检测 |
| #651 | fix: Mcreate nx in distributed_master | linkuan123 | 04-20 | 放开distributed_master下NTX+NX组合；MSet(buffers)增强空buffer容错 |
| #639 | Fix bazel error | yaohaolin | 04-19 | 修复bazel编译wheel包时没有带上datasystem_worker二进制文件的问题 |

---

## 二、当前维测文档现状

### 2.1 已有的维测文档体系

```
workspace/
├── fema-intermediate/
│   ├── 00-index.md              # 文档索引，4故障域分类
│   ├── 08-fault-triage-guide.md    # 故障定位定界指南（三板斧）
│   ├── 09-fault-test-construction.md  # 故障测试构造指南
│   ├── 10-quick-reference-card.md    # 快速参考卡（grep命令）
│   ├── 11-fault-triage-flowcharts.md  # ASCII流程图
│   └── code-evidence/           # 代码证据文件
│       ├── 01-urma-fault-detection.md
│       ├── 02-component-lifecycle.md
│       └── 03-os-layer-faults.md

docs/observable/
├── 08-fault-triage-consolidated.md   # 华为值班内部手册（通断×时延）
├── 10-customer-fault-scenarios.md   # 客户侧场景化手册
├── 08-fault-triage-consolidated.docx  # Word版
└── 10-customer-fault-scenarios.docx   # Word版

workspace/observable-design/
└── design.md                  # 可观测性设计（指标/日志/告警/Trace）
```

### 2.2 文档覆盖的能力维度

| 维度 | 文档依据 | 覆盖状态 |
|------|---------|---------|
| 错误码体系 | 08-guide / 08-consolidated | ✅ 完整 |
| 结构化日志标签（TCP/ZMQ/RPC/URMA/HealthCheck） | 10-quick-ref / 08-consolidated | ✅ 完整 |
| Metrics体系（54条KV + 18条SHM泄漏新增） | 08-consolidated 附录D | ✅ 完整但待更新 |
| 定界流程（User→DS→etcd→URMA→OS） | 08-guide / 08-consolidated | ✅ 完整 |
| 场景化故障排查（7个场景） | 10-customer-scenarios | ✅ 完整 |
| 日志采样策略 | design.md §9 | ⚠️ 有设计但未细化 |
| Trace串联 | design.md §4.3 | ⚠️ 有设计但未落地到代码证据 |
| 告警阈值 | design.md §6 | ⚠️ 有设计但未与代码关联 |

---

## 三、识别到的薄弱点

### 薄弱点 1：Metrics JSON单行输出后日志解析方式变化未同步

**问题描述**：PR #669/#648 将Metrics Summary从多行文本输出改为单行JSON格式：
- 不再是原来的多行`Metrics Summary, version=v0, cycle=N...`格式
- 超长日志按`part_index/part_count`自动拆成多条
- TraceID复用`${pod_name}-metrics`前缀，不再在JSON payload中重复输出

**当前文档状态**：
- `08-fault-triage-consolidated.md` 附录A.1 中的`grep 'Compare with' ...` 命令和附录D的Metrics Summary格式说明**未反映此变化**
- `10-quick-reference-card.md` 的Metrics delta段说明也是旧的
- 用户实际看到的日志格式与文档描述不一致

**影响**：值班人员或调试人员按文档命令grep可能匹配不到预期内容，或解析逻辑需要更新。

**建议**：
1. 更新`10-quick-reference-card.md`的Metrics节，描述新的JSON格式
2. 在`08-fault-triage-consolidated.md`附录A中增加JSON格式解析示例
3. 在附录D的Metrics Summary格式说明中注明单行JSON输出的格式

---

### 薄弱点 2：SHM泄漏Metrics（新增18条）未进入故障排查文档

**问题描述**：PR #652 新增了18个SHM泄漏相关Metrics（KvMetricId 36..53），覆盖：
- Worker端：alloc/free/ref_table/对象计数（10个）
- Master端：TTL链路（6个）
- Client端：异步DecRef（2个）

泄漏判据：`worker_shm_alloc_bytes_total delta > worker_shm_free_bytes_total delta` + `worker_shm_ref_table_bytes` Gauge持续涨 + `worker_object_count`持平

**当前文档状态**：
- `08-fault-triage-consolidated.md` 附录D（KV Metrics全量）中**只有54条中到53**的说明，新增的36..53未列入
- `10-quick-reference-card.md` 的SHM Leak判断公式只说了3个指标名称，未列出新增指标
- `10-customer-fault-scenarios.md` §4.5 SHM容量/内存不足/泄漏场景中只提到了`worker_shm_ref_table_bytes`，未覆盖新增的alloc/free差值指标

**影响**：现场用文档的指标名grep可能找不到，或判断公式不完整。

**建议**：
1. 在`08-fault-triage-consolidated.md`附录D末尾补充D.8节"SHM泄漏检测Metrics"，列出36..53全部指标
2. 更新`10-quick-reference-card.md`的SHM Leak判断公式，增加alloc/free差值比较
3. 更新`10-customer-fault-scenarios.md` §4.5步骤3的grep命令和判据描述

---

### 薄弱点 3：reconFlag等待诊断日志是新增能力，文档未覆盖

**问题描述**：PR #643/#644 新增了`Waiting for the reconFlag...`诊断日志，当Worker处理Publish等请求前调用`ValidateWorkerState()`获取`reconFlag_`读锁时会出现。该等待可能导致请求耗时增加约10ms，在`requestTimeoutMS=8ms`配置下会触发RPC unavailable。

**当前文档状态**：
- 没有任何文档提及`reconFlag`关键字
- `08-fault-triage-consolidated.md` 附录B.3（组件/生命周期/etcd关键字）中无此标签
- 结构化日志标签表中也没有`reconFlag`

**影响**：现场看到该日志不知道是什么、是否正常、是否需要处理。

**建议**：
1. 在`08-fault-triage-consolidated.md`附录B.3中新增`reconFlag`相关标签说明
2. 在`10-customer-fault-scenarios.md` §4.1或新增一个"DS进程内通延"场景中覆盖此诊断日志
3. 在`10-quick-reference-card.md` 的grep命令中增加reconFlag查询

---

### 薄弱点 4：URMA资源日志补齐（#683）后未同步文档

**问题描述**：PR #683 补齐了`urma_resource.cpp`中`ds_urma_*`调用的日志覆盖，将拆分的成功/失败日志收敛为单分支。

**当前文档状态**：
- `08-fault-triage-consolidated.md` 附录B.2 URMA标签表中列出了`[URMA_NEED_CONNECT]`、`[URMA_RECREATE_JFS]`等，但`urma_resource.cpp`中的调用前日志/成功日志未有对应描述
- `10-quick-reference-card.md` 的URMA关键字只有6条，不完整

**影响**：URMA问题排查时看到的日志可能比文档描述的更丰富，现场无法关联到具体代码位置。

**建议**：
1. 更新`10-quick-reference-card.md` URMA层关键字，增加`urma_resource.cpp`相关标签
2. 在`08-fault-triage-consolidated.md` 附录B.2中补充`ds_urma_*`调用的日志语义说明

---

### 薄弱点 5：Client侧Worker切换状态机故障场景文档缺失

**问题描述**：PR #662/#656 修复了`enableCrossNodeConnection`场景下worker切换流程卡死问题，新增了`NO_SWITCHABLE_WORKER`状态和快速失败机制。

**当前文档状态**：
- `10-customer-fault-scenarios.md` §4.6 扩缩容/Worker升级/重启期间业务中断提到了K_SCALING/K_SCALE_DOWN/K_CLIENT_WORKER_DISCONNECT，但**没有覆盖**跨节点切换卡死的场景
- `08-fault-triage-consolidated.md` §3.5.2(d) 心跳/生命周期/扩缩容也没有覆盖此场景
- 文档中没有`NO_SWITCHABLE_WORKER`状态说明

**影响**：现场遇到请求卡在切换流程中时，文档无法指导定位。

**建议**：
1. 在`10-customer-fault-scenarios.md` §4.6或新增§4.8中覆盖KVClient跨节点切换场景
2. 在`08-fault-triage-consolidated.md` §3.5.2(d)中补充跨节点切换fail-fast机制说明

---

### 薄弱点 6：日志采样策略设计未落地

**问题描述**：`design.md` §9 描述了按业务等级配置采样（稳态1%~5%，异常窗口20%~100%），支持动态生效。但：
- 代码中采样开关和配置方式未找到文档说明
- `09-fault-test-construction.md` 没有采样相关测试构造指南
- `10-quick-reference-card.md` 的grep命令没有采样率相关的说明

**影响**：现场需要调整采样率时没有操作指引。

**建议**：
1. 在`09-fault-test-construction.md`中增加采样配置测试用例指南
2. 在`10-quick-reference-card.md`增加采样相关的gflag/配置项说明

---

### 薄弱点 7：fast transport初始化时机问题文档缺失

**问题描述**：PR #649/#646 修复了URMA初始化在异常链路过长时超过worker的`client_dead_timeout_s`导致client被删除的问题。

**当前文档状态**：
- 没有任何文档描述URMA初始化时序依赖heartbeat启动的问题
- `08-fault-triage-consolidated.md` 的URMA层故障中没有提到初始化时序相关的定界方法

**影响**：现场遇到URMA初始化慢导致client注册失败的问题时无法定位。

**建议**：
1. 在`08-fault-triage-consolidated.md` §3.5.3 URMA故障中增加初始化时序说明
2. 在`10-customer-fault-scenarios.md` §4.4（Client Init/连接Worker失败）中增加URMA初始化依赖heartbeat的场景

---

## 四、优先级建议

| 优先级 | 薄弱点 | 涉及文档 | 建议动作 |
|-------|--------|---------|---------|
| **P0** | #1 Metrics JSON格式变化 | 10-quick-ref, 08-consolidated | 更新grep命令和格式说明 |
| **P0** | #2 SHM泄漏Metrics缺失 | 08-consolidated 附录D, 10-quick-ref | 补充36..53指标清单 |
| **P1** | #3 reconFlag诊断日志 | B.3标签表, 10-quick-ref | 增补标签说明和grep |
| **P1** | #4 URMA资源日志补齐 | 附录B.2, 10-quick-ref | 完善URMA标签表 |
| **P2** | #5 Worker切换状态机场景 | §3.5.2(d), §4.6/新增 | 补充跨节点切换fail-fast |
| **P2** | #6 日志采样策略未落地 | 09-test-guide, 10-quick-ref | 补充配置和测试指南 |
| **P3** | #7 fast transport初始化时序 | §3.5.3, §4.4 | 增加初始化依赖说明 |

---

## 五、附录：近2周PR时间线（可维可测相关）

```
04-21  #683 urma resource logs补齐 (feeiyu)
04-21  #681 [WIP] fix request timeout not contain client (weihongyu222)
04-21  #680 docs: Behavioral guidelines (OuGongChang)
04-21  #679/678 RETRY_ON_ERROR一直retry (zhujunliang)
04-21  #677/676 fix error log (weihongyu222)
04-21  #674 deploy: datasystem chart适配k8s 1.34 (ChamberlainJI)
04-21  #673 MCreate NX + MSet ntx_1 (OuGongChang)
04-21  #670 dsbench validate kv thread bounds (OuGongChang)
04-21  #669 metrics: one-line json summary logs (yaohaolin)
04-21  #668 shared_memory: advise hugepage for thp (yaohaolin)
04-21  #667 dsbench validate kv thread bounds (feeiyu)
04-21  #666 shutdown并发coredump修复 (OuGongChang)
04-21  #664 shutdown并发coredump修复 (sunyuchang)
04-21  #662 kv client switch during scale-down (yaohaolin)
04-21  #660 shared_memory: advise hugepage for thp (feeiyu)
04-21  #659 dsbench skip local data (feeiyu)
04-21  #656 kv client switch during scale-down (yaohaolin)
04-21  #654 Code check and add doc (OuGongChang)
04-20  #652 SHM leak observability metrics (yche-huawei)
04-20  #651 Mcreate nx in distributed_master (linkuan123)
04-20  #650 Code check and add doc (zhujunliang)
04-20  #649/646 delay fast transport init (yangxiaogang14)
04-20  #648 metrics: one-line json summary logs (yaohaolin)
04-20  #645/653 fix oom return rpc unavailable (weihongyu222/OuGongChang)
04-20  #644/643 add reconFlag wait diagnostics (yangxiaogang14)
04-20  #641 reconcile shm refs on current URMA worker (yaohaolin)
04-20  #640 obs: 双签名系统支持MinIO/S3 (OuGongChang)
04-19  #639 Fix bazel error (yaohaolin)
```