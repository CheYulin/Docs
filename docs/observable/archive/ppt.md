好的，这是为您精心整理的 PPT 素材，围绕 “自证清白” 和 “及时感知” 两大核心，系统梳理了观测指标、定位定界手段与原则、以及恢复方式。内容已按 PPT 页面逻辑进行组织，您可以直接复制使用。
PPT 素材：KVC 数据系统故障定位定界体系
第一部分：总体原则与目标
幻灯片标题：故障定位定界：自证清白与及时感知
核心目标
自证清白: 精准界定故障根因，明确责任边界，快速证明本系统无责，推动依赖模块解决问题。
及时感知: 主动发现性能劣化（尤其是 P99 时延）和故障，实现从被动响应到主动防御的转变。
总体原则
规格先行: 对所有依赖模块（URMA, TCP, etcd 等）提出明确的性能和可靠性规格要求。
分层定界: 基于错误码、超时机制、心跳检测，分层逐级定位故障域。
数据驱动: 依赖详尽的日志和监控指标，实现数据化、可量化的故障分析。
快速恢复: 建立明确的故障恢复路径，确保业务影响最小化。
定位定界总逻辑（手段整合）
一张图（心智模型）: 上下文 → 现象（SLI）→ 分解（状态码 / 日志 / Trace）→ 定界（责任域）→ 告警与升级。
上下文: 租户 / 集群 / 实例 / 请求类型（读、写、批量、远端 Get）、时间窗口、是否变更窗口；用于排除「误报」与「全局 vs 单点」。
状态码（StatusCode）: 客户端/SDK 与 Worker 返回的第一层分类依据；与 `respMsg`、access 日志列一并使用（见 `docs/reliability/00-kv-client-visible-status-codes.md`）。区分 RPC 桶码（如 1002）与 URMA 数据面码（1004/1006/1008），避免混为一谈。
日志: 接口日志（status_code, action, cost, datasize）、资源日志、第三方访问日志、运行错误日志；关键词与时间段对齐状态码突变。
Trace（链路追踪）: 为单次请求或调用链分配 trace_id / span_id（或与平台 TraceId 对齐），使「接口日志 ↔ 资源日志 ↔ Worker 内部打点 ↔ 第三方日志」可关联；用于回答「慢在哪一段」「失败发生在哪一跳」。
告警: 对 SLI 违约与高风险状态码组合设阈值；告警正文应带上下文摘要（集群、实例、指标当前值、最近变更），便于直接进入 Trace/日志。
两类必须告警的 SLI（逻辑要求）
读写时延: 对读路径、写路径分别设 SLO（如 P99 / 均值），按集群或业务维度聚合；持续超过阈值或环比劣化（如连续 N 个周期）触发告警，并联动分段打点（见第四部分）做定界。
成功率: 按接口或操作类型统计成功占比（或错误率）；相对基线下降或绝对值低于阈值触发告警；与状态码分布（如 1002/1001 突增）交叉验证，区分「网络类」与「业务语义类」。
幻灯片标题：五大故障域与定界导航（与第三部分对照）
说明: 下列五条为读写全链路最常见的**责任域划分**；定界时先结合 **读写时延 / 成功率** 告警判断「全局 vs 单点」，再用 **状态码 + 日志 + Trace** 归入其一或多项叠加。
UB 链路故障（数据面）: 跨 Worker 大块数据走 UB/URMA；典型现象为远端读写过慢、失败或长尾；优先看 **1004 / 1006 / 1008**、URMA 侧日志与分段打点中 **URMA Write** 段；责任对齐 **第三部分 · URMA 链路**；恢复见切 TCP / 重连等。
TCP 链路故障（控制面与通用网络）: Client↔Worker RPC、Worker 间元数据 RPC、Socket、fd 交换通道；典型现象为建连失败、等回复超时、断连；优先看 **1001 / 1002**、`K_CLIENT_WORKER_DISCONNECT(23)` 及 `respMsg` 中 **超时 / reset / shm fd transfer** 等关键词；责任对齐 **第三部分 · TCP/OS 链路** 及 fd 场景。
etcd 访问故障（元数据与控制面）: 服务发现、租约、扩缩容与故障隔离依赖 etcd；典型现象为 **etcd 成功率下降**、租约异常、Master/路由问题；优先看 **K_MASTER_TIMEOUT(25)**、**K_NOT_LEADER_MASTER(14)** 及 **第三方访问日志**；数据面读写可能仍可用但**运维能力降级**；责任对齐 **第三部分 · ETCD** 小节。
读写流程中系统资源故障: 共享内存、内存、FD、线程池、队列、磁盘等**在读写路径上触顶或分配失败**；典型现象为分配失败日志、队列堆积、P99 突增伴资源 rate 打满；优先看 **K_OUT_OF_MEMORY(6)**、**K_NO_SPACE(13)**、**K_FILE_LIMIT_REACHED(18)** 与 **资源日志**（mem/threadpool/queueUsage）；责任对齐 **第三部分 · SDK & Data Worker** 中的资源与规格段落。
Worker 故障（进程与节点级）: 进程崩溃、卡死、容器反复重启、心跳失败、缩容窗口；典型现象为**单 Worker / 单 AZ 维度**成功率下降、HealthCheck 失败；优先看 **K_WORKER_ABNORMAL(22)**、断连类码、**K_SCALE_DOWN(31) / K_SCALING(32)** 与时间线对齐；责任对齐 **第三部分 · SDK & Data Worker**（进程、健康检查）及平台侧重启/隔离策略。
五大域与观测手段的交叉（可放在备注页）: 同一事件可能跨域（例如 TCP 抖动 + UB 切换窗口）；**Trace** 用于锁定慢/失败发生在「哪一跳」；**成功率与时延** 双 SLI 用于判断是否需多域联合排查。
部署视图回顾
架构: 64 个 Data Worker 节点，每个节点服务 8 个本地推理实例。
依赖: 5 节点 ETCD 集群（1 主 4 备）、二级存储。
通信链路:
Client-Worker: 共享内存 (OS)、TCP (OS / 容器网络)、UB (URMA / 容器网络)。
Worker-Worker: UB (数据搬移)、TCP (元数据)。
Worker-ETCD: TCP。
Worker - 二级存储：异步持久化 / 加载。
第二部分：全面的观测体系
幻灯片标题：观测体系：多维度监控与日志
监控告警体系
平台: Grafana（集成监控指标）、日志采集平台。
核心监控:
推理实例运维监控: 观测业务侧调用状态。
Data Worker 运维监控: 观测服务侧运行状态。
Grafana 指标:
接口日志: status_code, action, cost, datasize。
资源日志: 内存使用率 (rate), 线程池利用率 (rate), 队列使用率 (queueUsage), 缓存命中率 (memHitNum, diskHitNum) 等。
第三方访问日志: etcd 请求成功率。
日志体系
接口日志: 记录请求的状态、耗时、数据大小，用于追踪单次请求。
资源日志: 周期性输出内存、线程池、队列、缓存等关键资源状态。
第三方访问日志: 记录对 ETCD 等外部服务的调用情况。
运行日志: 记录系统运行时的关键事件和错误信息。
定位定界手段一览（可做成一页表）
手段 | 解决什么问题 | 与 Trace 的关系 | 典型产出
上下文（部署、版本、路由、实例 ID） | 缩小范围、排除误报 | Trace 根 span 上挂载环境标签 | 对比「全局 vs 单 AZ / 单 Worker」
状态码 + `respMsg` | 失败语义与重试策略 | 同一 trace_id 下多跳各自带码 | 区分 RPC 层 vs URMA 层 vs 业务码
接口 / 资源 / 第三方日志 | 时延分解、资源饱和、etcd 健康 | trace_id 串联各组件日志行 | 瓶颈段、队列堆积、etcd 成功率
分段耗时打点（见第四部分） | P99 不满足时的软件/网络/UB 定界 | 可作为 Trace 的子 span 或独立 metric 标签 | 瀑布图、Grafana 多段曲线
指标（Grafana） | SLI 持续监控与告警 | 大盘可下钻到实例，再查该时段 Trace | 时延、成功率、错误码分布
告警规则 | 及时感知 + 升级路径 | 告警中附 trace 采样链接或查询条件 | 缩短 MTTR
代码证据链（错误码 / 日志 / 层层传递）
证据 1：RPC 超时被映射为 1002（Client 感知层）
- 代码位置: `yuanrong-datasystem/src/datasystem/common/rpc/zmq/zmq_msg_queue.h` 中 `ClientReceiveMsg`。
- 逻辑: 当 `ReceiveMsg` 返回 `K_TRY_AGAIN` 且非 DONTWAIT 时，改写为 `K_RPC_UNAVAILABLE(1002)`，并附带日志文案 `has not responded within the allowed time`。
- 结论: 1002 是 RPC 侧“桶码”，不能直接等价为 UB 故障。
证据 2：TCP/UDS + fd 交换失败也会上抛 1002（共享内存建链）
- 代码位置: `yuanrong-datasystem/src/datasystem/client/client_worker_common_api.cpp`。
- 逻辑: `mustUds && !isConnectSuccess` 时直接返回 `K_RPC_UNAVAILABLE`，错误信息 `Can not create connection to worker for shm fd transfer.`；并有握手失败日志 `Client can not connect to server for shm fd transfer ...`。
- 结论: 1002 还覆盖“共享内存 fd 交换通道失败”，属于 TCP/OS/本地链路问题。
证据 3：URMA 数据面成功/失败如何传递到上层
- 代码位置: `yuanrong-datasystem/src/datasystem/worker/object_cache/worker_worker_oc_service_impl.cpp`。
- 逻辑: `GetObjectRemote` 先 `Read(req)`，再 `CheckConnectionStable(req)`，然后 `GetObjectRemoteImpl`。若走 URMA 则调用 `UrmaWritePayload(...)`，成功后 `rsp.data_source=DATA_ALREADY_TRANSFERRED`；最后 `Write(rsp)` + `SendAndTagPayload(...)`。
- 关键日志: `RETURN_IF_NOT_OK_PRINT_ERROR_MSG(..., "GetObjectRemote read/write/send payload error")`、`pull success`。
- 结论: 远端读写的失败可在“读请求 / URMA 写 / 回包发送”三段出现，需按 trace 分段定位。
证据 4：URMA 连接不稳的错误码与重连传递
- 代码位置 A: `yuanrong-datasystem/src/datasystem/common/rdma/urma_manager.cpp`，`CheckUrmaConnectionStable` 返回 `K_URMA_NEED_CONNECT(1006)`（如 `No existing connection requires creation.`）。
- 代码位置 B: `yuanrong-datasystem/src/datasystem/worker/object_cache/service/worker_oc_service_get_impl.cpp`，`TryReconnectRemoteWorker` 捕获 `K_URMA_NEED_CONNECT` 后执行 exchange，成功则返回 `K_TRY_AGAIN` 触发外层重试。
- 结论: 链路是 `1006 -> 重连 -> K_TRY_AGAIN -> Retry`，这是 UB 故障“可恢复窗口”的核心路径。
证据 5：etcd 访问异常上抛控制面超时
- 代码位置: `yuanrong-datasystem/src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp`。
- 逻辑: 远端节点连接失败或超时时返回 `K_MASTER_TIMEOUT(25)`，文案 `Disconnected from remote node ...`。
- 结论: 该类属于元数据/控制面故障，不等价于数据面 UB 传输故障。
证据 6：Worker 退出如何暴露到健康检查
- 代码位置: `yuanrong-datasystem/src/datasystem/worker/object_cache/worker_oc_service_impl.cpp`。
- 逻辑: `HealthCheck` 中当 `CheckLocalNodeIsExiting()` 成立，返回 `K_SCALE_DOWN(31)`，日志 `[HealthCheck] Worker is exiting now`。
- 结论: 成功率下降若集中在单 Worker 且伴随 31，优先归因 Worker 生命周期事件。

关键能力：及时感知
日志驱动告警: 关键错误码、超时事件通过日志收集，由监控平台触发告警。
SLI 双轨告警（逻辑必备）: （1）**读/写时延**：按路径与百分位设阈值，劣化即告警，并提示打开分段打点与 Trace。（2）**成功率（或错误率）**：相对基线或绝对阈值告警，与状态码分布、etcd 成功率联动，避免只看单一指标。
性能劣化感知: 对 URMA、TCP 等关键链路进行分段打点，统计 P99 时延。当连续多次波动超过阈值时，自动打印异常信息并触发告警。
Trace 关联: 日志与指标侧统一 trace_id（或与业务 RequestId 映射），保证「告警 → 单次请求还原 → 定界」可闭环。
当前现状与告警机制设计（建议新增一页）
现状判断: 当前代码路径中已有完整错误码与日志，但缺少统一、自动化的告警收敛与分发机制（更多依赖人工查日志/看图）。
设计目标: 把「状态码 + 日志 + 指标 + trace」统一成可触发、可抑制、可升级的告警事件。
事件模型（Alert Event）
- 维度: `cluster/az/worker/client/action/path(read|write|remote_get)/status_code`。
- 证据字段: 最近 N 分钟错误码分布、P99/成功率、关键日志样本、trace 查询条件。
- 域标签: `UB/TCP/ETCD/RESOURCE/WORKER`（对应五大故障域）。
规则设计（第一版）
1) SLI 规则（必选）
   - 读时延告警: `read_p99` 连续 N 个窗口 > 阈值。
   - 写时延告警: `write_p99` 连续 N 个窗口 > 阈值。
   - 成功率告警: `success_rate` 连续 N 个窗口 < 阈值（或错误率 > 阈值）。
2) 错误码规则（辅助定界）
   - UB 类: `1004/1006/1008` 占比或速率突增。
   - TCP/RPC 类: `1001/1002/23` 突增；若附带 `shm fd transfer` 关键词，优先标注 fd/建链问题。
   - ETCD 类: `25/14` 突增 + etcd 第三方访问成功率下降。
   - Worker 生命周期: `31/32/22` 突增。
   - 资源类: `6/13/18` 突增 + 资源日志（mem/threadpool/queueUsage）打满。
3) 组合规则（降噪）
   - 仅当「SLI 违约 + 对应错误码异常」同时满足，升级为 P1/P2；仅单信号触发为 P3 观察告警。
分级与升级（建议）
- P1: 全局成功率明显下降或读写 P99 严重超阈，且持续 > T；自动拉群并通知值班。
- P2: 单 AZ/单 Worker 显著异常，存在用户影响。
- P3: 早期抖动或单一信号异常，进入观察与自愈窗口。
抑制与自愈
- 变更窗口抑制: 发布/扩缩容期间提高阈值或延迟升级。
- 去重聚合: 同一 `cluster+domain+status_code` 在冷却时间内合并。
- 自愈联动: 对 `1006` 允许重连窗口；窗口结束仍失败再升级。
告警输出模板（建议）
- 标题: `[域][级别] 集群X 读写异常`
- 内容: 影响范围、SLI 当前值、Top 状态码、关键日志 1~3 条、trace 查询链接、推荐下一步排查项。

健康检查与故障隔离: 上层业务通过 Health Check 感知异常，多次失败后结合重启失败次数，自动隔离故障节点。
第三部分：核心能力：分模块自证清白与定位定界
幻灯片标题：定位定界能力：URMA 链路 (UMDK 团队)
定界原则
错误码: 严格依据 URMA 返回的错误码判断其内部错误。
超时机制: 基于 URMA 规格（如 128ms）设定超时，而非剩余时间预算。超时则判定 URMA 违规。
心跳机制: 考虑引入心跳，判断链路是否存活，应对请求无法送达的场景。
观测与定位手段
数据系统日志: 详细记录 URMA 操作的端点、类型和结果，实现 “自证清白”。
管理面工具: 结合URMA ping（LCNE 层 -> UBS Engine -> Mami）结果进行交叉验证。
关键事件监控:
URMA 建链失败但返回成功。
URMA Write 报错或 Poll Completion 事件获取到错误。
Poll 状态完成但数据错误。
异步 Write 超时。
恢复方式
切 TCP: URMA 链路故障，自动切换至 TCP 传输。
自杀: TCP 链路也故障时，进程主动退出，由上层调度重启。
警惕反复重拉: 需避免因配置问题导致的无限重启循环。
幻灯片标题：定位定界能力：TCP/OS 链路 (OS / 容器网络团队)
定界原则
错误码: 依据 Socket 接口返回的错误码判断 OS 网络问题。
超时机制: 基于 TCP Socket 读写规格设定超时，超时则判定 OS 违规。
心跳时延: 在心跳中记录时延，监控网络健康度。
观测与定位手段
数据系统日志: 记录 TCP 操作的端点和结果。
OS 工具链:
用户态工具 (devtools): 定位时使用，查看网络全栈耗时、重传数。
驱动日志: 筛选link down等硬件错误。
ftrace/perf: 分析软件栈、线程调度、上下文切换问题。
特定场景检测:
fd 交换 /mmap 失败: 记录错误码。
SIGBUS 信号: 信号处理时 dump 内存地址，用于事后推演。
恢复方式
重试: 对 TCP 慢或抖动进行重试。
自杀: 关键 TCP 链路（如 ETCD）长时间中断时，进程主动退出。
幻灯片标题：定位定界能力：SDK & Data Worker
定界原则
资源规格: 基于评审通过的资源规格（CPU, Mem, FD），当分配失败时明确记录并报错。
健康检查: 引入周期性验证逻辑，检测关键线程是否卡死。
观测与定位手段
资源监控: 异步记录 SDK/Worker 的资源占用情况，确保未超规格。
线程状态: 通过perf/ftrace分析线程是否得到调度，上下文切换是否频繁。
自证清白:
SDK: 明确记录资源分配失败的日志。
Data Worker: 记录 Socket 接口超时，并提供故障时间段，供运维查监控。
恢复方式
SDK: 资源分配失败时，报错退出并告警，由运维保障资源后重启。
Data Worker: 触发告警，通知人工排查，解决问题后重启。
幻灯片标题：定位定界能力：ETCD & 二级存储 (客户中台团队)
ETCD
定界原则:
错误码: 检测 ETCD 明确返回的错误（如 “没有主”）。
交叉验证: 当自身访问超时，通过与其他 Worker 通信确认 ETCD 集群整体状态。
观测手段:
第三方访问日志: 监控 ETCD 访问成功率，连续失败触发告警。
租约状态: 监控租约是否超期。
恢复方式:
告警通知: 通知客户运维恢复 ETCD 集群。
降级运行: 在 ETCD 故障期间，数据读写不受影响，但无法进行扩缩容和故障隔离。
二级存储
定界原则:
错误码: 记录 OS 文件接口调用失败。
超时记录: 记录连续的pread/pwrite超时，并监控写入队列长度。
观测手段:
监控写入队列大小，确保能容纳缓存总对象数。
恢复方式:
告警通知: 通知客户恢复磁盘 / 存储服务。
业务不中断: 数据可靠性等级下降，但业务读写不受影响。未持久化数据在重启后丢失。
第四部分：P99 时延深度分析
幻灯片标题：P99 时延分析：从分段打点到精准定界
核心逻辑：绘制单次请求的时间线
目标: 将端到端时延分解到各个关键环节，精准定位性能瓶颈。
分段打点: 对以下关键路径进行精确计时：
Client -> Worker1 (TCP RPC)
Worker1 -> Worker2 (TCP RPC)
Worker1 -> Worker3 (TCP RPC)
Worker3 -> Worker1 (URMA Write)
... 其他关键内部调用
定界与定位
与五大故障域的对应（便于汇报）: TCP RPC 各段 → **TCP 链路**；URMA Write 段 → **UB 链路**；排队/本地计算过长且资源日志异常 → **系统资源**；元数据/Master 段异常且 etcd 指标差 → **etcd**；仅某 Worker 相关段劣化 → **Worker**。
数据呈现: 在 Grafana 上将各分段耗时绘制成时序图或瀑布图。
瓶颈定位:
软件侧开销: 如果某个内部函数或逻辑耗时过长，定位为软件问题。
URMA 瓶颈: 如果 URMA Write 端到端耗时超过规格，定位为 URMA / 硬件问题。
TCP 瓶颈: 如果 TCP RPC 耗时过长，定位为 OS / 网络 / 驱动问题。
恢复与优化
软件问题: 识别代码瓶颈，进行优化。
URMA 问题: 推动 UMDK / 硬件团队解决。
TCP 问题: 推动 OS / 网络团队解决。
第五部分：总结
幻灯片标题：总结：构建主动、透明、高效的故障响应体系
我们的能力
全面的可观测性: 覆盖日志、指标、链路追踪，为定位提供数据基础。
清晰的定界原则: 基于规格、错误码、超时，实现责任边界清晰化；**按 UB / TCP / etcd / 资源 / Worker 五域**导航到对应团队与手段（见「五大故障域」页）。
主动的故障感知: 从被动响应转向主动发现性能劣化和故障；**入口上坚持「读写时延 SLI + 成功率 SLI」双告警**，再下钻状态码、日志与 Trace。
高效的恢复路径: 明确的降级和恢复策略，保障业务连续性。
仓库内延伸阅读（非 PPT 正文）: `docs/reliability/00-kv-client-visible-status-codes.md`（状态码）；`docs/reliability/deep-dives/故障码树状梳理-URMA与TCP-fd共享内存.md`（URMA 与 fd/SHM）；`docs/reliability/00-kv-client-fema-timing-and-sli.md`（时延与 SLI 口径）。
为客户带来的价值
缩短 MTTR: 快速定位问题，减少故障排查时间。
提升系统稳定性: 主动发现并处理潜在风险，避免问题扩大化。
保障业务收入: 确保在故障场景下，业务影响最小化，维持高可用性。
建立信任: 通过透明、数据驱动的方式，与客户和各依赖团队建立高效协作关系。