# KVCache 数据系统 FMEA 故障分析表

> 本文档基于 `fault-template.md` 模板生成，结合代码分析和设计文档，涵盖故障检测、定位定界、恢复全链路。

## 目录

1. [填写说明](#1-填写说明)
2. [FMEA 表格](#2-fema-表格)
3. [错误码参考表](#3-错误码参考表)
4. [故障域分类说明](#4-故障域分类说明)

---

## 1. 填写说明

| 列名 | 填写规则 |
|------|---------|
| **一级对象** | datasystem / client / ds-worker / 集群 |
| **二级对象** | client、ds-worker、etcd、UB、TCP 等 |
| **三级对象** | 可选，用于细化故障定位 |
| **故障模式** | 必填，来自 fault-tree-table.md 和代码分析 |
| **可能原因** | 必填，结合 fault-category.md 和代码分析 |
| **故障影响** | 必填，该故障对系统的实际影响 |
| **是否中断业务** | 是/否 |
| **严酷度** | Ⅰ类(严重)/Ⅱ类(较严重)/Ⅲ类(一般)/Ⅳ类(轻微) |
| **故障模式备注** | 关键设计说明、故障域标注 |
| **故障检测方法（版本现状）** | 代码证据：文件+行号+关键日志 |
| **故障处理方法（版本现状）** | 自愈机制/降级路径/人工介入 |
| **故障定位方法（版本现状）** | 关键日志关键字、错误码 |
| **改进建议** | P0/P1/P2 优先级 |

---

## 2. FMEA 表格

### 2.1 Client 与 DS-Worker 网络故障

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | client | - | client与ds-worker网络闪断 | 1.网络拥塞；2.网络不稳定；3.交换机重启 | 数据读写请求失败 | 否 | 一般 | 【故障域】本地client-worker |
| datasystem | client | - | client与ds-worker网络中断/链路吊死 | 1.硬件故障、信令故障；2.操作系统底层通信服务故障 | 数据读写请求失败 | 否 | 一般 | 【故障域】本地client-worker |
| datasystem | client | - | client与ds-worker网络延时高 | 网络拥塞、不稳定、交换机重启、设计缺陷、对端负载过重、病毒攻击 | 数据读写请求失败 | 否 | 一般 | 【故障域】本地client-worker |
| datasystem | client | - | client与ds-worker丢包 | 1.消息包太多；2.处理延迟；3.系统内部消息队列满；4.备份数据量太大 | 数据读写请求失败 | 否 | 一般 | 【故障域】本地client-worker |
| datasystem | client | - | client与ds-worker包乱序 | 1.消息传输路径不一致；2.消息发送过程中传输路径发生切换 | 无影响 | 否 | 一般 | 乱序包被rpc框架重排 |
| datasystem | client | - | client与ds-worker错包/异常包 | 1.被异常改写；2.释放后重用；3.数据帧长度判断错误；4.越界；5.传输错误 | 无影响 | 否 | 一般 | 错包被rpc框架丢弃重传 |
| datasystem | client | - | client与ds-worker建链失败 | 1.网络断链；2.上下游服务异常 | client无法与worker通信，数据读写请求失败 | 否 | 一般 | 【故障域】本地client-worker |
| datasystem | client | - | 进程终止/异常退出 | 1.进程异常；2.进程被误杀 | 业务实例退出 | 是 | 严重 | 【故障域】本地client-worker |
| datasystem | client | - | 进程吊死/饿死 | 1.进程被资源(锁/IO)阻塞；2.死循环；3.进程优先级不够；4.调度器异常 | 业务实例无法正常运行 | 是 | 严重 | 【故障域】本地client-worker |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| 心跳机制保活 | ListenWorker 心跳检测 | 心跳超时检测 | `listen_worker.cpp:114` - `Cannot receive heartbeat from worker` | 自动重连、流量切换 | `object_client_impl.cpp` - `SwitchWorkerNode` | 现象：心跳超时；手段：日志 | `K_CLIENT_WORKER_DISCONNECT` (23) | NA | 检测灵敏度受 `client_dead_timeout_s` 控制，默认120s |
| 心跳机制保活 | ListenWorker 心跳检测 | 心跳超时检测 | `listen_worker.cpp:103` - `The client detects that the worker is disconnected` | 自动重连、流量切换 | `object_client_impl.cpp` - `SwitchWorkerNode` | 现象：心跳超时；手段：日志 | `K_CLIENT_WORKER_DISCONNECT` (23) | NA | 检测灵敏度受 `node_timeout_s` 控制 |
| 心跳机制保活 | ListenWorker 心跳检测 | 心跳超时检测 | `listen_worker.cpp:114` | 自动重试 | `RetryOnError` | 现象：请求响应慢；手段：日志 | `K_TRY_AGAIN` (19) | NA | 检测灵敏度受 `node_timeout_s` 控制 |
| 队列深度监控 | ListenWorker 心跳检测 | 心跳超时检测 | `listen_worker.cpp:114` | 自动重试 | `RetryOnError` | 现象：请求超时；手段：日志 | `K_RPC_TIMEOUT` | NA | 检测灵敏度受 `node_timeout_s` 控制 |
| NA | NA | 无 | NA | rpc框架对包乱序重排 | rpc框架自动处理 | 现象：业务层面无感知；手段：日志 | NA | NA | - |
| NA | NA | 无 | NA | rpc框架丢弃异常包 | rpc框架自动处理 | 现象：业务层面无感知；手段：日志 | NA | NA | - |
| 建链前检查 | RegisterClient 返回值检查 | 建链失败检测 | `client_worker_common_api.cpp` | 自动重试建链 | `RetryOnError` | 现象：连接建立失败；手段：日志 | `K_RPC_UNAVAILABLE` (1001) | NA | - |
| 进程监控 | HealthCheck 心跳机制 | 心跳超时检测 | `listen_worker.cpp:114` - `Cannot receive heartbeat` | 自动清理共享内存引用计数 | `worker_oc_service_impl.cpp:369-372` | 现象：心跳超时；手段：日志 | `K_CLIENT_WORKER_DISCONNECT` (23) | NA | 检测灵敏度受 `client_dead_timeout_s` 控制 |
| 资源监控、busy loop检测 | 心跳超时检测 | 心跳超时检测 | `listen_worker.cpp:114` | 无（依赖外部） | 依赖外部监控 | 现象：进程存在但不响应；手段：日志 | `K_CLIENT_WORKER_DISCONNECT` (23) | P0: Worker挂死检测优化 | 当前无法检查进程吊死，需增加busy loop检测 |

---

### 2.2 DS-Worker 与 DS-Worker 网络故障

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | ds-worker | - | ds-worker与其他ds-worker TCP网络闪断 | 1.网络拥塞；2.网络不稳定；3.交换机重启 | 数据读写功能受损，RPC重试失败后会报错 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker TCP网络中断/链路吊死 | 1.硬件故障、信令故障；2.操作系统底层通信服务故障 | 数据读写功能受损，RPC重试失败后会报错 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker TCP网络延时高 | 网络拥塞、不稳定、交换机重启、设计缺陷、对端负载过重 | 数据读写时延变高，可能出现超时 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker UB链路拥塞 | 存在海量URMA连接且同时工作 | 数据读写时延变高，可能出现超时 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker基于UB链路数据传输失败 | 1.UB单平面故障；2.UB多平面故障 | 数据读写时延受影响，平面切换引入时延开销 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker丢包 | 1.消息包太多；2.处理延迟；3.系统内部消息队列满 | 数据读写功能受损，读写请求超时 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker包乱序 | 1.消息传输路径不一致；2.消息发送过程中传输路径发生切换 | 无影响 | 否 | 一般 | rpc框架底层使用tcp协议自动重排 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker错包/异常包 | 1.被异常改写；2.释放后重用；3.数据帧长度判断错误；4.越界；5.传输错误 | 无影响 | 否 | 一般 | 错包/异常包被rpc框架丢弃重传 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker TCP建链失败 | 1.网络断链；2.上下游服务异常 | 数据读写功能受损，重试失败后会报错 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker与其他ds-worker建UB链路失败 | UB建链失败，Jetty资源数不够，内存不足等 | 数据读写功能受损，重试失败后会报错 | 是 | 一般 | 【故障域】data worker之间 |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| RPC心跳检测 | RPC框架心跳检测 | RPC心跳超时检测 | `worker_oc_service_get_impl.cpp:153` - `RPC timeout` | 记录日志，重建链路 | `RetryOnErrorRepent` | 现象：跨节点请求失败或超时；手段：日志 | `K_RPC_DEADLINE_EXCEEDED` (19) | NA | - |
| RPC心跳检测 | RPC框架心跳检测 | RPC心跳超时检测 | `worker_oc_service_get_impl.cpp:153` | 记录日志，重建链路 | `RetryOnErrorRepent` | 现象：跨节点请求完全不通；手段：日志 | `K_RPC_UNAVAILABLE` (1001) | NA | - |
| RPC心跳检测 | RPC框架心跳检测 | RPC心跳超时检测 | `worker_oc_service_get_impl.cpp:153` | 记录日志，重试 | `RetryOnErrorRepent` | 现象：跨节点请求响应慢；手段：日志 | `K_RPC_TIMEOUT` | NA | - |
| 连接数监控 | URMA侧报错检测 | 超时报错 | `urma_manager.cpp:772` - `[URMA_RECREATE_JFS]` | 记录日志，降级TCP | `fast_transport_manager_wrapper.cpp` | 现象：跨节点请求响应慢或超时；手段：日志 | `K_URMA_ERROR` (1004) | P1: 20ms场景下UB降级优化 | 当前不支持流控，超时时间内返回错误 |
| URMA状态检测 | URMA侧报错检测 | URMA报错检测 | `urma_manager.cpp:772` - `[URMA_RECREATE_JFS]` | 记录日志，重试 | `TryReconnectRemoteWorker` | 现象：跨节点请求响应慢或者超时或失败；手段：日志 | `K_URMA_ERROR` (1004) | NA | 待URMA和元戎数据系统分别具备跨平面切换和切TCP的实现后，存在保证读写可用的能力 |
| RPC心跳检测 | RPC框架心跳检测 | RPC心跳超时检测 | `worker_oc_service_get_impl.cpp:153` | 记录日志，重试 | `RetryOnErrorRepent` | 现象：跨节点请求超时或部分失败；手段：日志 | `K_RPC_TIMEOUT` | NA | 当前是会单次请求访问失败 |
| NA | NA | 无 | NA | rpc框架对包乱序重排 | rpc框架自动处理 | 现象：业务层面无感知；手段：日志 | NA | NA | - |
| NA | NA | 无 | NA | rpc框架识丢弃异常包 | rpc框架自动处理 | 现象：业务层面无感知；手段：日志 | NA | NA | - |
| 建链前检查 | RPC框架建链检测 | 建链失败检测 | `worker_oc_service_get_impl.cpp` | 建链失败后记录日志并重试 | `RetryOnErrorRepent` | 现象：连接建立失败；手段：日志 | `K_RPC_UNAVAILABLE` (1001) | NA | - |
| UB资源检查 | URMA建链检测 | 建链失败检测 | `urma_manager.cpp:1385` - `[URMA_NEED_CONNECT]` | 建链失败后记录日志并重试 | `TryReconnectRemoteWorker` | 现象：连接建立失败；手段：日志 | `K_URMA_NEED_CONNECT` (1006) | NA | 通过重试解决，超过一定时间后，异常进程需要触发缩容流程 |

---

### 2.3 DS-Worker 资源与进程故障

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | ds-worker | - | ds-worker上memory segment交换失败 | 调用memory fabric失败，元数据处理失败，memory segment失败 | data worker启动失败 | 是 | 严重 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker上memory segment分配失败 | 初始化时分配内存段失败，没有大页内存配额、容量不够 | data worker启动失败 | 是 | 严重 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | ds-worker端口/浮动IP绑定失败 | 1.端口/浮动IP被占用；2.网卡设备异常 | 进程启动失败 | 是 | 一般 | 【故障域】data worker之间 |
| datasystem | ds-worker | - | 时间跳变 | 1.掉电重启/异常跳变；2.人工调整时间/时区；3.NTP自动对齐导致跳变 | 时间向前跳变对数据版本号产生影响，造成数据一致性处理异常 | 是 | 一般 | 【故障域】不涉及 |
| datasystem | ds-worker | - | 配置文件丢失/损坏 | 1.配置文件被截断；2.配置内存错乱；3.配置非法 | data worker进程启动失败 | 是 | 一般 | 【故障域】data worker启动 |
| datasystem | ds-worker | - | 程序文件/库文件丢失/损坏 | 1.安装/升级不正确；2.系统环境故障导致文件损坏；3.人工误操作 | data worker进程启动失败 | 是 | 一般 | 【故障域】data worker启动 |
| datasystem | ds-worker | - | 文件权限错误 | 1.安装/升级/程序运行时权限设置错误；2.人工误操作 | data worker进程启动失败 | 是 | 一般 | 【故障域】data worker启动 |
| datasystem | ds-worker | - | 进程终止/异常退出 | 1.进程异常；2.进程被误杀 | 1.client无法接入集群；2.本节点数据若未写入二级缓存则丢失；3.元数据访问失败 | 是 | 严重 | 【故障域】data worker |
| datasystem | ds-worker | - | 进程吊死/饿死 | 1.进程被请求的资源(锁/IO)阻塞；2.死循环；3.进程优先级不够；4.调度器异常 | ds-worker无法提供服务，本地client读写失败，需要重启恢复 | 是 | 严重 | 【故障域】data worker |
| datasystem | ds-worker | - | 线程资源不足 | 1.系统内其他进程缺陷导致资源使用过大；2.业务高峰导致系统内其他进程资源使用过大 | ds-worker业务功能受损，RPC失败导致读写请求失败 | 是 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | fd资源不足 | 1.系统内其他进程缺陷导致资源使用过大；2.业务高峰导致系统内其他进程资源使用过大 | ds-worker业务功能受损，RPC失败导致读写请求失败 | 是 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | 磁盘空间满 | 1.系统内其他进程缺陷导致资源使用过大；2.业务高峰导致系统内其他进程资源使用过大 | 1.spill数据失败；2.rocksdb读写操作失败 | 是 | 严重 | 【故障域】data worker |
| datasystem | ds-worker | - | 磁盘故障 | 磁盘出现坏道等原因 | 1.spill数据失败；2.rocksdb读写操作失败（元数据未持久化） | 是 | 严重 | 【故障域】data worker |
| datasystem | ds-worker | - | rocksdb文件权限错误 | 文件权限被修改 | 对正常运行无影响，对重启场景有影响，启动失败 | 否 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | rocksdb文件丢失 | 文件被误删 | 对正在运行的rocksdb无影响，对重启场景有影响，启动失败 | 否 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | 共享内存空间不足 | 1.用户写入的数据太多且未配置spill、缓存淘汰功能；2.用户配置了spill功能，但磁盘已满或写入速度太快导致来不及spill | 配置数据对象缓存淘汰策略后，会触发缓存淘汰 | 是 | 一般 | 【故障域】data worker |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| BM_JOIN重试 | bm_join接口重试 | 日志检测 | `urma_manager.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错；手段：日志 | `K_URMA_ERROR` (1004) | NA | 对bm_join和init等接口调用失败做重试处理 |
| 大页内存检查 | 大页内存配额检查 | 日志检测 | `allocator.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错；手段：日志 | `K_OUT_OF_MEMORY` (6) | NA | 对内存分配接口报错会重试处理，仍然失败则进程启动失败 |
| 端口可用性检查 | 端口绑定检测 | 日志检测 | `worker_oc_service_impl.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| NTP同步监控 | 时间一致性检查 | 系统日志检测 | `/var/log/message` | 代码中增加处理，规避时间向前跳变带来的版本号问题 | 代码版本号处理 | 现象：系统时间异常；手段：日志 | `K_DATA_INCONSISTENCY` (19) | NA | 故障处理手段当前还不支持 |
| 配置文件校验 | 配置文件解析 | 日志检测 | `worker_oc_service_impl.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错或配置解析失败；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| 文件完整性检查 | 文件存在性检查 | 日志检测 | `worker_oc_service_impl.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| 文件权限检查 | 文件权限检查 | 日志检测 | `worker_oc_service_impl.cpp` | 节点拉起失败后退出，k8s自动重拉 | k8s自动重拉 | 现象：进程启动报错；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| 进程监控 | k8s检测worker进程状态，etcd订阅节点状态 | k8s检测、etcd状态检测、日志 | `worker_oc_service_impl.cpp:369-372` - `[HealthCheck] Worker is exiting now` | 1.节点故障后，k8s会自动重拉；2.可靠性数据需选择Write_through模式；3.节点长时间无法拉起则踢出集群 | k8s自动重拉 + 流量切换 | 现象：进程消失，节点失联；手段：日志、etcd状态 | `K_SCALE_DOWN` (31) | NA | 检测灵敏度受 `node_timeout_s` 参数控制，默认值为60s |
| busy loop检测 | 心跳超时检测 | 心跳超时检测 | `listen_worker.cpp:114` | 无 | 依赖外部监控 | 现象：进程存在但不响应；手段：日志 | `K_CLIENT_WORKER_DISCONNECT` (23) | P0: Worker挂死检测优化 | 当前无法检查进程吊死 |
| 线程池监控 | 线程资源申请检测 | 日志检测 | `worker_oc_service_impl.cpp` | 申请资源失败记录错误日志 | 记录错误日志 | 现象：申请线程资源失败；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| fd监控 | fd申请检测 | 日志检测 | `worker_oc_service_impl.cpp` | 申请资源失败记录错误日志 | 记录错误日志 | 现象：申请文件描述符失败；手段：日志 | `K_FILE_LIMIT_REACHED` (20) | NA | - |
| 磁盘空间监控 | 磁盘空间检测 | 日志检测 | `worker_oc_service_impl.cpp` | 记录错误日志 | 记录错误日志 | 现象：磁盘写入失败；手段：日志 | `K_NO_SPACE` (13) | NA | 当前无处理措施，可考虑当磁盘故障后将此节点隔离，业务迁走 |
| 磁盘健康检查 | 磁盘IO检测 | 日志检测 | `worker_oc_service_impl.cpp` | 记录错误日志 | 记录错误日志 | 现象：磁盘读写错误；手段：日志 | `K_IO_ERROR` (7) | NA | 当前无处理措施，可考虑当磁盘故障后将此节点隔离，业务迁走 |
| 文件权限检查 | 文件权限检查 | 日志检测 | `worker_oc_service_impl.cpp` | 记录错误日志 | 记录错误日志 | 现象：重启时数据库打开失败；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| 文件完整性检查 | 文件存在性检查 | 日志检测 | `worker_oc_service_impl.cpp` | 记录错误日志 | 记录错误日志 | 现象：重启时数据库打开失败；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | - |
| 内存使用率监控 | 共享内存使用率检测 | 日志检测 | `allocator.cpp` | 记录错误日志，触发缓存淘汰 | 缓存淘汰策略 | 现象：共享内存分配失败；手段：日志 | `K_OUT_OF_MEMORY` (6) | NA | - |

---

### 2.4 集群管理故障 (etcd)

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | ds-worker | etcd | 集群管理etcd访问异常 | 1.ETCD进程挂死/退出/过载等；2.网络异常 | 在ds-worker正常运行情况下，集群管理的etcd访问异常无影响；当ds-worker出现故障重启后，可能出现数据不一致 | 否 | 严重 | 【故障域】集群 |
| datasystem | ds-worker | etcd | 集群管理etcd访问慢 | 1.ETCD负荷太高；2.网络存在瓶颈 | 集群管理的etcd异常会导致某些节点续租异常，从而节点状态异常 | 是 | 一般 | 【故障域】集群 |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| etcd高可用部署 | IsKeepAliveTimeout检测 | etcd健康检查 | `replica_manager.cpp:1190` - `etcd is timeout` | 当集群管理etcd故障后，集群的扩缩容、故障处理等功能都不在可用 | 等待恢复 | 现象：etcd连接失败；手段：日志 | `K_MASTER_TIMEOUT` (25) | P0: etcd故障自愈机制 | - |
| etcd负载均衡 | IsKeepAliveTimeout检测 | etcd健康检查 | `etcd_cluster_manager.cpp:897` - `Disconnected from remote node` | 节点会不断重新尝试向etcd发送消息续租，一旦成功则自动恢复 | 续租重试 | 现象：etcd续租响应慢；手段：日志 | `K_MASTER_TIMEOUT` (25) | NA | 可能会出现误判节点故障，会触发扩容操作 |

---

### 2.5 业务层故障

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | ds-worker | - | 异常请求 | 用户传入异常数据 | 无，异常请求会被拒绝 | 是 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | 过多请求 | 1.上游服务异常；2.上游服务业务量激增；3.攻击 | 1.cpu/内存占满导致服务受损；2.消息处理慢 | 是 | 一般 | 【故障域】data worker |
| datasystem | ds-worker | - | 扩容异常 | 扩容过程中网络异常，或扩容节点/其他节点发生了故障 | 扩容失败 | 否 | 一般 | 【故障域】集群 |
| datasystem | ds-worker | - | 缩容异常 | 缩容过程中网络异常，或其他节点发生故障 | 缩容失败 | 否 | 一般 | 【故障域】集群 |
| datasystem | ds-worker | - | 节点频繁加入/退出 | 节点由于bug/资源不足等原因反复重启 | 进程状态故障 | 是 | 一般 | 【故障域】集群 |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| 入参校验 | Validator校验 | K_INVALID检测 | `status_code.def` - `K_INVALID` (2) | 1.对请求进行合法性检查，非法请求报错，记录日志；2.非法请求不影响合法请求处理流程 | 返回错误码 | 现象：收到并拒绝非法请求；手段：日志 | `K_INVALID` (2) | NA | - |
| 流控机制 | 流控检测 | 资源使用率检测 | `worker_oc_service_impl.cpp` | 增加流控机制，控制worker整体支持的请求量以及单个client支持的请求量 | 流控机制（当前不支持） | 现象：资源使用率高，请求处理延迟；手段：日志 | `K_RUNTIME_ERROR` (7) | NA | 当前还不支持流控，依靠前端接入服务实现流控 |
| 扩缩容状态检测 | Worker和etcd保活心跳检测 | 心跳检测 | `etcd_cluster_manager.cpp` | 检测到故障后，自动回滚扩容流程 | 自动回滚 | 现象：扩容流程中断或超时；手段：日志 | `K_SCALING` (32) | NA | - |
| 扩缩容状态检测 | Worker和etcd保活心跳检测 | 心跳检测 | `etcd_cluster_manager.cpp` | 检测到故障后，自动回滚缩容流程 | 自动回滚 | 现象：缩容流程中断或超时；手段：日志 | `K_SCALING` (32) | NA | - |
| 节点稳定性监控 | 日志检测 | 日志检测 | `etcd_cluster_manager.cpp` | 需要人工干预确认资源问题 | 人工介入 | 现象：该实例无法正常响应；手段：日志 | `K_SCALE_DOWN` (31) | NA | 当前在进程故障重启但频繁重启下，无法隔离该进程，需要避免其频繁重启 |

---

### 2.6 URMA/UB 专项故障

| 一级对象 | 二级对象 | 三级对象 | 故障模式 | 可能原因 | 故障影响 | 是否中断业务 | 严酷度 | 故障模式备注 |
|---------|---------|---------|---------|---------|---------|------------|--------|-------------|
| datasystem | ds-worker | UB | UB初始化失败 | ds_urma_init失败、驱动so未加载(/usr/lib64/urma缺失)、dlopen失败 | 整个UB传输不可用，Client无法使用UB通道 | 是 | 严重 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | CQ poll/wait/rearm失败 | poll_jfc失败(CQE为空)、wait_jfc超时(UDMA中断未上报)、rearm失败 | 事件通知机制失效，URMA操作无法完成 | 是 | 较严重 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | JFS重建 | JFS状态异常、cqe status=9(映射到RECREATE_JFS)、SQ不可用 | 写操作失败，需重建JFS | 是 | 较严重 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | UB连接需重建 | 连接不存在、实例不匹配(cachedInstanceId != instanceId)、连接不稳定 | 短时业务中断，需重建连接 | 是 | 一般 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | import jfr失败 | jfr import失败、token不匹配、Fast transport handshake failed | UB远端传输建立失败 | 是 | 较严重 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | UB write/read失败 | urma_write/read调用失败、SQ/RQ错误 | 数据写入/读取失败 | 是 | 较严重 | 【故障域】URMA层 |
| datasystem | ds-worker | UB | UB直发失败降级TCP | Send buffer via UB失败、Jetty不足 | 降级到TCP/IP payload | 部分 | 一般 | 【故障域】URMA层 |

| 故障预防方法（预期） | 故障预防方法（版本现状） | 故障检测方法（预期） | 故障检测方法（版本现状） | 故障处理方法（预期） | 故障处理方法（版本现状） | 故障定位方法（预期） | 故障定位方法（版本现状） | 改进建议 | 故障管理措施备注 |
|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------------------|----------------------|---------|----------------|
| 驱动文件完整性检查、权限校验 | UrmaInit返回值检查 | dlopen返回值检测、/usr/lib64/urma目录存在性检查 | `urma_dlopen_util.cpp` - `dlopen failed` | 降级到TCP传输、告警 | 降级到TCP（UB不可用时自动fallback） | 错误码：K_URMA_ERROR (1004)；日志：`dlopen failed` | 检查驱动文件是否部署正确 | NA | 用户需确保UB驱动正确部署 |
| CQ状态监控、心跳检测 | urma_poll_jfc返回值检查 | poll返回-1时检测、wait超时检测 | `urma_manager.cpp` - `Failed to poll jfc` | 重建CQ、重试 | 重建CQ | 错误码：K_URMA_ERROR (1004)；日志：`Failed to wait jfc` | 代码证据：`code-evidence/01-urma-fault-detection.md` | P2: CQ异常提前检测 | 自愈机制已实现 |
| JFS健康状态检测 | GetUrmaErrorHandlePolicy(statusCode=9) | cqe status检测 | `urma_manager.cpp:772` - `[URMA_RECREATE_JFS] requestId=xxx, cqeStatus=9` | 自动重建JFS | `connection->ReCreateJfs()` | 日志：`[URMA_RECREATE_JFS] requestId=xxx, cqeStatus=9` | 代码证据：`code-evidence/01-urma-fault-detection.md` | NA | 自愈机制已实现 |
| 连接保活检测 | CheckUrmaConnectionStable | urmaConnectionMap_查询、instanceId比对 | `urma_manager.cpp:1385-1413` - `[URMA_NEED_CONNECT] Connection stale` | 自动重连 | `TryReconnectRemoteWorker` → `K_TRY_AGAIN` | 日志：`[URMA_NEED_CONNECT] Connection stale/unstable` | 代码证据：`code-evidence/01-urma-fault-detection.md` | NA | 自愈机制已实现 |
| token校验、握手超时检测 | urma_import_jfr返回值检查 | import失败返回值检测 | `urma_manager.cpp` | 重试、降级到TCP | 降级到TCP | 错误码：K_URMA_ERROR (1004)；日志：`Fast transport handshake failed` | 代码证据：`code-evidence/01-urma-fault-detection.md` | 增加握手超时配置 | 有降级路径 |
| SQ/RQ状态检测 | urma_post_jfs_wr返回值检查 | write/read返回值检测 | `urma_manager.cpp` | 重试、降级 | 重试 | 错误码：K_URMA_ERROR (1004)；日志：`Failed to urma write/read` | 代码证据：`code-evidence/01-urma-fault-detection.md` | NA | - |
| UB端口状态检测 | - | Send失败返回值检测 | `fast_transport_manager_wrapper.cpp` - `fallback to TCP/IP payload` | 自动降级到TCP | 已实现 | 日志：`fallback to TCP/IP payload` | - | 增加降级路径监控 | 无需用户干预 |

---

## 3. 错误码参考表

| 错误码 | 名称 | 故障域 | 定位定界关键字 |
|--------|------|--------|---------------|
| 2 | K_INVALID | 用户错误 | `Invalid parameter` |
| 3 | K_NOT_FOUND | 用户错误 | `Key not found` |
| 6 | K_OUT_OF_MEMORY | OS/组件 | `Failed to allocate memory buffer pool for client` / `Get mmap entry failed` |
| 7 | K_IO_ERROR / K_RUNTIME_ERROR | OS/内部 | `K_IO_ERROR` / `Rpc timeout` |
| 13 | K_NO_SPACE | OS | `No space` |
| 19 | K_TRY_AGAIN / K_DATA_INCONSISTENCY | OS/内部 | `try again` / `data inconsistent` |
| 20 | K_FILE_LIMIT_REACHED | OS | `Limit on the number of open file descriptors reached` |
| 23 | K_CLIENT_WORKER_DISCONNECT | 组件 | `Cannot receive heartbeat from worker` |
| 25 | K_MASTER_TIMEOUT | OS(etcd) | `Disconnected from remote node` / `etcd is unavailable` |
| 31 | K_SCALE_DOWN | 组件 | `Worker is exiting now` |
| 32 | K_SCALING | 组件 | `The cluster is scaling` |
| 1001 | K_RPC_UNAVAILABLE | OS | `RPC unavailable` |
| 1002 | K_URMA_NEED_CONNECT | URMA | `URMA_NEED_CONNECT` |
| 1004 | K_URMA_ERROR | URMA | `URMA_RECREATE_JFS` / `Failed to urma init` |
| 1006 | K_URMA_NEED_CONNECT | URMA | `No existing connection for remoteAddress` |
| 1008 | K_URMA_TRY_AGAIN | URMA | `URMA_RECREATE_JFS` |

---

## 4. 故障域分类说明

| 故障域 | 范围 | 典型故障 | 对应错误码 |
|--------|------|---------|-----------|
| **用户错误** | 入参非法、Key不存在、业务逻辑错误 | 入参校验失败、查询不存在数据 | K_INVALID (2), K_NOT_FOUND (3) |
| **OS层** | socket/TCP/ZMQ/UDS/mmap/文件/syscalls | 网络闪断、mmap失败、etcd超时、磁盘IO错误 | 6, 7, 13, 19, 20, 25, 1001, 1002 |
| **URMA层** | UB数据面、JFC/JFS/JFR/CQ | UB初始化失败、CQ异常、JFS重建、连接重建 | 1004, 1006, 1008 |
| **组件层** | SDK/Worker进程生命周期 | 进程退出/重启/挂死、扩缩容拒绝 | 23, 31, 32 |
| **内部错误** | 数据面内部处理 | UB payload尺寸不一致、数据不一致 | 19 |

---

## 代码证据文件索引

| 文件 | 内容 |
|------|------|
| `code-evidence/01-urma-fault-detection.md` | URMA层检测代码+日志+调用链 |
| `code-evidence/02-component-lifecycle.md` | 组件生命周期检测代码+日志 |
| `code-evidence/03-os-layer-faults.md` | OS层检测代码+日志 |

---

## 改进建议汇总

| 优先级 | 改进项 | 对应故障 |
|-------|-------|---------|
| P0 | etcd故障自愈机制 | 集群管理etcd访问异常/访问慢 |
| P0 | URMA故障自愈 | UB初始化失败 |
| P0 | Worker挂死检测优化 | 进程吊死/饿死 |
| P1 | ZMQ半开连接检测优化 | client与ds-worker网络闪断/中断 |
| P1 | mmap失败降级路径完善 | memory segment分配失败 |
| P1 | 20ms场景下UB降级优化 | ds-worker与其他ds-worker UB链路拥塞 |
| P1 | 扩缩容失败自动回滚 | 扩容异常/缩容异常 |
| P2 | SDK进程健康自愈 | 进程终止/异常退出 |
| P2 | CQ异常提前检测 | CQ poll/wait/rearm失败 |
| P2 | 增加一致性校验 | 时间跳变导致的数据不一致 |

---

**文档版本**: v1.0
**生成时间**: 2026-04-21
**数据来源**: fault-template.md, fault-category.md, fault-tree-table.md, observable-design/design.md, 代码证据分析