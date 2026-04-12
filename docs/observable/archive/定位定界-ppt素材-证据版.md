# PPT 素材：定位定界（证据版）

配套详版文档：`docs/reliability/定位定界-故障树-代码证据与告警设计.md`

## 第 1 页：问题定义
- 现状：能看到指标异常和接口报错，但缺少统一告警收敛与证据闭环
- 目标：有理有据定位定界（错误码 + 日志 + Trace + 时序）
- 入口：读/写 `success_rate` 与 `p99`

## 第 2 页：六类故障树
- TCP 链路故障
- UB 链路故障
- 组件本身故障
- 系统资源故障
- 第三方 etcd 故障
- 文件接口故障

## 第 3 页：代码证据链（TCP）
- `ClientReceiveMsg`：`K_TRY_AGAIN -> K_RPC_UNAVAILABLE(1002)`
- `UnixSockFd::ErrnoToStatus`：`ECONNRESET/EPIPE -> 1002`
- `client_worker_common_api`：`shm fd transfer` 失败 -> 1002
- 关键词日志：`has not responded...`、`Connect reset`、`Network unreachable`

## 第 4 页：代码证据链（UB）
- `CheckUrmaConnectionStable` -> `K_URMA_NEED_CONNECT(1006)`
- `TryReconnectRemoteWorker`：1006 后 exchange 成功 -> `K_TRY_AGAIN` 重试
- `GetObjectRemote`：`Read -> CheckConnectionStable -> UrmaWritePayload -> Write -> SendAndTagPayload`

## 第 5 页：代码证据链（组件/etcd/文件）
- 组件：`ListenWorker` 首心跳失败 -> `K_CLIENT_WORKER_DISCONNECT(23)`
- Worker 生命周期：`HealthCheck` 退出态 -> `K_SCALE_DOWN(31)`
- etcd：`EtcdClusterManager` 连接失败 -> `K_MASTER_TIMEOUT(25)`
- 文件接口：`ReadFile/WriteFile` pread/pwrite 失败 -> `K_IO_ERROR`，spill 空间不足 -> `K_NO_SPACE`

## 第 6 页：流程时序（远端读）
- 建议放 PlantUML：URMA 优先 + 1006 重连 + Retry
- 结论：UB 与 RPC 故障要分层看，1002 不能直接当 UB 根因

## 第 7 页：流程时序（部署初始化）
- SDK Connect -> SocketPath -> fd 交换 -> RegisterClient -> Heartbeat
- 失败分流：1002（建链/fd）、23（心跳）、31（worker exiting）

## 第 8 页：告警机制设计
- R1 SLI（必选）：读/写 p99 与 success_rate
- R2~R5：UB/TCP/etcd/资源与文件接口专项
- 分级：P1/P2/P3；抑制：变更窗口；聚合：`cluster+domain+code`

## 第 9 页：巡检与告警复核
- 每日巡检：部署、读写、etcd、文件存储
- 告警复核五步：SLI -> 码/日志 -> 故障树归类 -> Trace 下钻 -> 结论输出

## 第 10 页：FEMA 覆盖说明
- 对应 `00-kv-client-fema-scenarios-failure-modes.md`
- UB/TCP/etcd/资源/组件/文件接口均有证据和告警方案

