"""Sheet1 与 CHAIN_ROWS 逐行对齐的 URMA/OS 预设。

- primary: URMA | OS | NEITHER（NEITHER=用户参数/纯业务 Status/成功路径等）
- URMA「错误」列与 OS「错误」列经 merge_exclusive 互斥，便于开发按一类 syscall 层根因定位
- 日志字符串尽量贴近 yuanrong-datasystem 源码英文原文，便于 grep

修改 CHAIN_ROWS 时必须同步增删本列表项并保持顺序一致。
"""

def merge_exclusive(primary: str, urma_iface: str, urma_err: str, os_iface: str, os_err: str):
    """互斥规则：URMA 行 OS「错误列」填空；OS 行 URMA「错误列」填空。"""
    u_if, u_er, o_if, o_er = urma_iface, urma_err, os_iface, os_err
    mu = "—（互斥：本行不按 URMA/UMDK 错误定界）"
    mo = "—（互斥：本行不按 OS/zmq/errno 错误定界）"
    if primary == "URMA":
        return u_if, u_er, o_if or "—（本段无独立 OS 接口清单）", mo
    if primary == "OS":
        return u_if or "—（本段无 ds_urma_*）", mu, o_if, o_er
    return u_if, u_er or "—", o_if, o_er or "—"


# (primary, urma_iface, urma_err, os_iface, os_err, 开发定位步骤)
SHEET1_URMA_OS = [
    (
        "NEITHER",
        "可选 UB：ds_urma_register_log_func → ds_urma_init → ds_urma_get_device_by_name → "
        "ds_urma_create_context / create_jfce / jfc / jfs / jfr → ds_urma_import_jfr / advise_jfr",
        "—（成功路径无 URMA 错误；若失败见本表「UB 握手 urma_init」行）",
        "connect / send / recv；libzmq：zmq_socket, zmq_connect, zmq_msg_*, ZmqFrontend::SendAllFrames / GetAllFrames；"
        "recvmsg(SCM_RIGHTS)（RecvPageFd）",
        "—（成功路径无 OS 错误）",
        "无异常时无需 grep。若 Init 失败：先按本表后续行拆分是 Register(OS) 还是 UrmaInit(URMA)。",
    ),
    (
        "NEITHER",
        "—（无：参数校验在客户端逻辑内）",
        "—",
        "—（无 syscall）",
        "—",
        "SDK 日志搜 K_INVALID / Invalid；确认未发起 stub。核对 HostPort、AKSK、batch/offset 等入参。",
    ),
    (
        "OS",
        "—（Register 前尚未走 UB 数据面）",
        "—",
        "socket(2); connect(2); libzmq: zmq_connect, zmq_send/zmq_sendmsg, zmq_recv, zmq_poll（或框架内 Poll）",
        "完整线索：\n"
        "• client: RETURN_IF_NOT_OK_PRINT_ERROR_MSG(..., \"Register client failed\")（client_worker_common_api.cpp / Remote Connect）\n"
        "• Status: K_RPC_UNAVAILABLE(1002) / K_RPC_DEADLINE_EXCEEDED(1001)\n"
        "• worker: LOG(WARNING) << \"Register client failed because worker is exiting and unhealthy now\"\n"
        "grep 示例：\n"
        "  grep -E 'Register client failed|1001|1002|rpc unavailable|deadline exceeded' client.log worker.log",
        "1) client 与 worker 同时段日志 + 同一 Trace。\n"
        "2) 无 worker 侧 Register 日志 → 优先网络/防火墙/端口。\n"
        "3) strace 看 connect ECONNREFUSED/ETIMEDOUT。",
    ),
    (
        "OS",
        "—",
        "—",
        "同上 + 多帧收发路径；EPIPE/ECONNRESET/EAGAIN 常映射 1002/19",
        "完整线索：\n"
        "• LOG/Status: rpc unavailable, try again, send/recv failed, timeout（zmq_stub_conn / stub 路径）\n"
        "• 数据系统码：1001 / 1002 / K_TRY_AGAIN(19)\n"
        "grep：\n"
        "  grep -E '1001|1002|try again|unavailable|send.*recv|zmq_' client.log\n"
        "  对齐 worker.log 同时间点是否仍在处理其它大请求（队列/HWM）。",
        "与上一行同属 OS：本行强调「已连上但传输抖动/半开连接」。抓包 + 对齐两端进程是否重启。",
    ),
    (
        "URMA",
        "ds_urma_init；ds_urma_get_device_by_name；ds_urma_get_eid_list；ds_urma_create_context / jfce / jfc / jfs / jfr（UrmaInit 链）",
        "完整日志（urma_manager.cpp 等）：\n"
        "• RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, \"Failed to initialize URMA dlopen loader\")\n"
        "• RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString(\"Failed to urma init, ret = %d\", ret))\n"
        "• RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString(\"Failed to urma get device by name, errno = %d\", errno))\n"
        "• RETURN_STATUS_LOG_ERROR(K_URMA_ERROR, FormatString(\"Failed to urma get eid list, errno = %d\", errno))\n"
        "grep：\n"
        "  grep -E 'Failed to urma|K_URMA_ERROR|1004' client.log\n"
        "  同时看 /var/log/umdk/urma（若 RegisterUrmaLog 成功）",
        "—（本行错误不归 OS errno）",
        "—",
        "UB 与 OS socket 无关。查 UMDK、设备名 DS_URMA_DEV_NAME、bonding、驱动加载、权限。",
    ),
    (
        "OS",
        "—",
        "—",
        "mmap(2) MAP_ANONYMOUS | MAP_PRIVATE, fd=-1（客户端 UB 匿名池）",
        "完整线索：\n"
        "• RETURN_STATUS(K_OUT_OF_MEMORY, \"Failed to allocate memory buffer pool for client\")\n"
        "• LOG(WARNING) << \"Failed to register memory buffer pool for client, error: \" << rc.ToString()\n"
        "• errno ENOMEM(12) 时可能映射 K_OUT_OF_MEMORY(6)\n"
        "grep：grep -E 'memory buffer pool|ENOMEM|K_OUT_OF_MEMORY|Failed to allocate memory buffer pool' client.log",
        "ulimit -a、/proc/sys/vm/max_map_count、cgroup memory；非 URMA 返回码问题。",
    ),
    (
        "URMA",
        "ds_urma_import_jfr；ds_urma_advise_jfr；ds_urma_import_seg（对端 JFR 对齐）",
        "完整线索：\n"
        "• LOG_IF_ERROR(..., \"Fast transport handshake failed ... fall back\")（常见为 LOG(ERROR) 级文案，具体以代码为准）\n"
        "• Failed to import target jfr / Failed to advise jfr / urma import 失败类 LOG\n"
        "grep：grep -E 'Fast transport handshake|import.*jfr|advise jfr|Failed to import|1004' client.log worker.log",
        "—",
        "—",
        "对端 worker1 UB 是否可达；JFR 是否一致；可先确认 ZMQ 控制面正常再查 URMA。",
    ),
    (
        "OS",
        "—",
        "—",
        "recvmsg(2) MSG_PEEK / SCM_RIGHTS；sendmsg(2)（对端发 fd）；UnixSockFd",
        "完整线索：\n"
        "• LOG: Pass fd meets unexpected error / Unexpected EOF read / invalid fd（fd_pass.cpp / RecvPageFd）\n"
        "• Status: K_UNKNOWN_ERROR / K_RUNTIME_ERROR\n"
        "grep：grep -E 'Pass fd|SCM_RIGHTS|recvmsg|invalid fd|Unexpected EOF' client.log",
        "UDS 路径是否与配置一致；fd 上限 ulimit -n；对端是否先于 client 关闭。",
    ),
    (
        "NEITHER",
        "PrepareUrmaBuffer 路径：GetMemoryBufferHandle → GetMemoryBufferInfo；远端：ds_urma_write/read + poll_jfc（若走 UB）",
        "—（成功）",
        "stub_->Get ZMQ；Directory gRPC；Worker↔Worker stub；client mmap SHM",
        "—（成功）",
        "健康主链：用 Trace 串 client / W1 / W2 / W3。异常见下列各 case 行。",
    ),
    (
        "NEITHER",
        "—",
        "—",
        "—",
        "—",
        "PreGet 失败无下游日志。搜 subTimeoutMs out of range / K_INVALID；对照 OBJECT_KEYS_MAX_SIZE_LIMIT。",
    ),
    (
        "URMA",
        "UrmaManager::GetMemoryBufferHandle / GetMemoryBufferInfo（UMDK 池；无 ds_urma_write）",
        "完整日志（client_worker_base_api.cpp PrepareUrmaBuffer）：\n"
        '• LOG(WARNING) << "UB Get buffer size " << requiredSize << " exceeds max " << maxGetSize << ", fallback to TCP/IP payload."\n'
        '• LOG(WARNING) << "UB Get buffer allocation failed (size " << requiredSize << "): " << ubRc.ToString() << ", fallback to TCP/IP payload."\n'
        "说明：降级后 **不返回 URMA 错误码**，功能可走 TCP。\n"
        "grep：grep -E 'UB Get buffer|fallback to TCP/IP payload' client.log",
        "—",
        "—",
        "确认 UB 池已 Init；对象是否超大；并发是否耗尽池。",
    ),
    (
        "OS",
        "—",
        "—",
        "libzmq + 内核：send/recv/poll/epoll；与 stub_->Get 多帧收发一致",
        "完整线索：\n"
        "• client: VLOG(1) << \"Start to send rpc to get object, rpc timeout: \" << ...\n"
        "• RetryOnError 打 RPC Retry detail（若开启）\n"
        "• Status: 1001 / 1002 / 19\n"
        "• worker: LOG(INFO) << \"Process Get from client:\" …；若无此条而 client 已超时 → 网络丢包/未达 worker\n"
        "grep：\n"
        "  grep -E 'Start to send rpc to get object|Process Get from client|1001|1002|RetryOnError' client.log worker.log",
        "先确认 worker 是否收到 Get；再查 zmq 超时与线程池。",
    ),
    (
        "OS",
        "—",
        "—",
        "同上行，强调 errno 路径：EPIPE ECONNRESET EAGAIN",
        "完整线索：\n"
        "• 框架日志：send/recv failed, rpc unavailable, try again\n"
        "• 与半关闭连接、对端重启相关\n"
        "grep：grep -E 'send|recv|unavailable|try again|1002|19' client.log",
        "与上一行合并排查；本行侧重「已曾成功连上后的读写失败」。",
    ),
    (
        "NEITHER",
        "—",
        "—",
        "—",
        "—",
        "业务 last_rc 触发重试：client 侧 lambda 内判断。搜 last_rc、IsAllGetFailed、K_OUT_OF_MEMORY；对齐 worker ReturnToClient 写入的 last_rc。",
    ),
    (
        "OS",
        "—",
        "—",
        "etcd 客户端：通常为 HTTP/TCP socket + TLS（依实现）；epoll_wait",
        "完整线索：\n"
        "• 日志关键词：etcd is unavailable（以你们分支实际字符串为准）\n"
        "• 常映射 K_RPC_UNAVAILABLE(1002) 经业务封装\n"
        "grep：grep -E 'etcd is unavailable|etcd.*fail|1002' worker.log",
        "查 etcd 集群健康、租约、网络；非 URMA。",
    ),
    (
        "OS",
        "—",
        "—",
        "gRPC/HTTP2 或自定义 RPC：socket, sendmsg, recvmsg, poll；TLS read/write",
        "完整线索（worker_oc_service_get_impl ProcessObjectsNotExistInLocal）：\n"
        '• RETURN_STATUS_LOG_ERROR(K_RUNTIME_ERROR, FormatString("Query from master failed : %s", result.ToString()))\n'
        "• 日志原文仍含 **master** 字样，文档称 Directory。\n"
        "grep：\n"
        "  grep -E 'Query from master failed|QueryMetadataFromMaster|K_RUNTIME_ERROR' worker.log\n"
        "  对端 Directory Worker 同 Trace。",
        "W1 与 W2 同时段；查 gRPC 断开、TLS、非 Leader（Status 码 14/25 等）。",
    ),
    (
        "OS",
        "—",
        "—",
        "Worker↔Worker stub：同 ZMQ 或 gRPC（依实现）；connect/send/recv",
        "完整线索（worker_oc_service_get_impl）：\n"
        '• LOG(ERROR) << FormatString("[ObjectKey %s] Get from remote failed: %s.", objectKey, status.ToString());\n'
        '• LOG(ERROR) << "Failed to get object data from remote. " << successIds.size() << ...\n'
        "• K_WORKER_PULL_OBJECT_NOT_FOUND 等有单独 LOG(INFO)\n"
        "grep：\n"
        "  grep -E 'Get from remote failed|Failed to get object data from remote|ObjectKey' worker.log\n"
        "  对齐 worker3 同 key、同 Trace。",
        "元数据已成功而数据拉取失败：重点看 W3 存活与网络，非 Directory。",
    ),
    (
        "URMA",
        "ds_urma_write；ds_urma_read；ds_urma_post_jfs_wr（数据面，依实现封装）",
        "完整线索（urma_manager / 数据路径）：\n"
        "• LOG(ERROR) / RETURN：Failed to urma write object … / Failed to urma read object …（具体 FormatString 以代码为准）\n"
        "• 映射 K_RUNTIME_ERROR(5) / K_URMA_ERROR(1004)\n"
        "grep：grep -E 'Failed to urma write|Failed to urma read|urma_write|urma_read|1004' worker.log\n"
        "  对齐对端 UB 与 /var/log/umdk/urma",
        "—",
        "—",
        "同 Trace 拉 W3 与 client UB 侧；看 CR.status、链路是否抖动。",
    ),
    (
        "URMA",
        "ds_urma_poll_jfc；ds_urma_wait_jfc；ds_urma_rearm_jfc；ds_urma_ack_jfc（依封装）",
        "完整线索：\n"
        "• FormatString(\"Failed to wait jfc, ret = %d\" …) / Failed to poll jfc / Failed to rearm jfc\n"
        "• 常映射 K_URMA_ERROR(1004)\n"
        "grep：grep -E 'Failed to wait jfc|Failed to poll jfc|Failed to rearm|1004|jfc' worker.log",
        "—",
        "—",
        "CQ 事件是否丢失；对端是否 RNR；设备 reset。",
    ),
    (
        "URMA",
        "Urma 连接状态机：CheckUrmaConnectionStable（逻辑层，非 POSIX connect）",
        "完整线索：\n"
        "• LOG: Urma connect unstable, need to reconnect! / No existing connection requires creation（以 urma_manager.cpp 为准）\n"
        "• Status: K_URMA_NEED_CONNECT(1006)\n"
        "grep：grep -E 'need to reconnect|1006|Urma connect unstable|CheckUrmaConnectionStable' client.log worker.log",
        "—",
        "—",
        "重建 UB 会话；核对两端实例 ID / JFR 是否匹配。",
    ),
    (
        "NEITHER",
        "—（FillUrmaBuffer 为客户端组装 UB 描述符与 payload，非 UMDK 完成队列错误）",
        "—",
        "—（无独立 syscall 列；CopyBuffer 为用户态）",
        "—",
        "完整日志（client_worker_base_api.cpp）：\n"
        '• FormatString("UB payload overflow, object %s, payload size %llu, consumed %llu, buffer size %llu", ...)\n'
        '• FormatString("Invalid UB payload size for object %s: %ld", ...)\n'
        '• "Build UB payload rpc message failed"\n'
        "grep：grep -E 'UB payload overflow|Invalid UB payload|Build UB payload rpc message failed' client.log\n"
        "说明：属 **应答与 UB 尺寸一致性**，不按 URMA 设备、也不按 errno 主因排查。",
    ),
    (
        "OS",
        "—",
        "—",
        "mmap(2)（SHM fd）；open(2) 若经 fd 路径",
        "完整线索：\n"
        "• LOG(ERROR) << \"Failed for \" << objectKey << \" : \" << status.ToString()（ProcessGetResponse 组装失败）\n"
        "• 关键词：Get mmap entry failed / mmap failed（以 object_client_impl 为准）\n"
        "grep：grep -E 'Failed for |mmap|Get mmap entry|EBADF|ENOMEM' client.log",
        "fd 是否有效、是否跨机、MmapManager 表项是否存在。",
    ),
    (
        "NEITHER",
        "—",
        "—",
        "—",
        "—",
        "业务语义：搜 K_NOT_FOUND / Can't find object；非 errno 亦非 urma ret。核对 TTL/是否写入。",
    ),
    (
        "NEITHER",
        "W1 内写路径或含 ds_urma_write（UB）；本行描述成功无错",
        "—",
        "ZMQ MultiPublish；pwrite/sendmsg（若落盘，未开 spill 时仍可能有 fd）",
        "—",
        "成功路径；异常见 Publish/MultiPublish 各行。",
    ),
    (
        "URMA",
        "UrmaWritePayload → ds_urma_write 链（client 直发）",
        "完整线索：\n"
        "• RETURN_IF_NOT_OK_PRINT_ERROR_MSG(..., \"Failed to send buffer via UB\")（SendBufferViaUb）\n"
        "• 伴随 urma 失败 LOG\n"
        "grep：grep -E 'Failed to send buffer via UB|UrmaWritePayload|urma_write' client.log",
        "—",
        "—",
        "对象尺寸与 UB 池；可降级非 UB 路径对比。",
    ),
    (
        "OS",
        "—",
        "—",
        "zmq 多帧 + poll（同 Get）",
        "完整线索：\n"
        "• VLOG: Start to send rpc to publish object\n"
        "• Status: 1001/1002/19\n"
        "grep：grep -E 'publish object|1001|1002|MultiPublish|Publish' client.log",
        "同 Get 控制面：先确认 worker 收到请求。",
    ),
    (
        "OS",
        "—",
        "—",
        "同 Get socket 行",
        "完整线索：同「RPC socket 读写失败」行；附加 MultiPublish 批次大时 HWM 堆积\n"
        "grep：grep -E 'send|recv|unavailable|try again|1002' client.log",
        "调大超时或减 batch；查 worker 线程池队列。",
    ),
    (
        "NEITHER",
        "—",
        "—",
        "—",
        "—",
        "K_SCALING(32) / K_OUT_OF_MEMORY(6)：grep 枚举名与 worker MultiPublish 返回；查集群 scaling 与批次大小。属业务策略非单一 syscall。",
    ),
]
