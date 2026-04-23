# 故障树（故障模式 × 调用链 × 关键日志）

本文件把原 `fault-tree-table.md` 按层次拆成两张可独立使用的故障树：

- Section 1 — **KVCache 故障树**：KVCache 接口 → 用户 / OS / URMA 问题
- Section 2 — **URMA → UDMA → Kernel 故障树**：底层链路与驱动

约定：

- **KVCache 层只有 `StatusCode`（`include/datasystem/utils/status.h`），没有 `errno`**；
  以枚举名书写，access log 第一列的整数为其数值（K_OK=0、K_NOT_READY=8、K_RPC_DEADLINE_EXCEEDED=1001 等）。
- **URMA / UDMA 用户态** 大多返回「错误返回值 + `errno`」；内核态以 `ERR_PTR(-E*)` 或 UDMA 返回值透传。
- 关键日志来自仓内字面量（`LOG(ERROR/INFO/WARNING)` / `URMA_LOG_ERR` / `ubcore_log_err`），
  用于在 client 日志 / Worker 日志 / access log / dmesg 中 grep 定位。
- Section 1 最后三列给出「用户问题 / OS 问题 / URMA 问题」故障域，
  当判定为 URMA 问题时，按 Section 2 的子树继续下钻。

---

## 1. KVCache 故障树（KVCache 接口 → 用户 / OS / URMA 问题）

<table>
  <thead>
    <tr>
      <th colspan="3">KVCache 接口</th>
      <th colspan="2">SDK 顶层返回</th>
      <th>内部调用链</th>
      <th colspan="3">可能故障域（下钻方向）</th>
    </tr>
    <tr>
      <th>接口（C++ / Python）</th>
      <th>调用场景</th>
      <th>关键日志（client / worker / access log）</th>
      <th>正常返回</th>
      <th>错误 StatusCode（枚举名 + 数值）</th>
      <th>调用链关键错误码（逐层）</th>
      <th>用户问题</th>
      <th>OS 问题</th>
      <th>URMA 问题（→ Section 2）</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Init / KVClient::Init</td>
      <td>SDK 首次与 Worker 建链：做服务发现、证书加载、心跳注册</td>
      <td><b>client</b>：<br>
'Start to init worker client at address: &lt;ip:port&gt;'<br>
'Start to init preferred remote fallback worker client at address: ...'<br>
'Invalid IP address/port. Host %s, port: %d'<br>
'ConnectOptions was not configured with a host and port or serviceDiscovery.'<br>
'[Reconnect] Reconnect local worker failed, error message: ...'<br>
<b>access log</b>：此阶段一般 <u>无</u> <code>DS_KV_CLIENT_*</code> 行</td>
      <td>K_OK</td>
      <td>K_INVALID — 参数/地址非法<br>
K_NOT_READY — 未完成 Init 或已 ShutDown (8)<br>
K_RPC_UNAVAILABLE — 建链失败 (1002)<br>
K_RPC_DEADLINE_EXCEEDED — 建链超时 (1001)<br>
K_CLIENT_WORKER_DISCONNECT — 首心跳失败 (23)<br>
K_MASTER_TIMEOUT — 控制面不可达 (25)</td>
      <td>ObjectClientImpl::Init<br>
&nbsp;├─ ClientStateManager::ProcessInit → K_NOT_READY<br>
&nbsp;├─ ServiceDiscovery::SelectWorker → K_INVALID / K_RPC_UNAVAILABLE<br>
&nbsp;├─ Validator::ValidateHostPortString → K_INVALID<br>
&nbsp;├─ RpcAuthKeyManager::CreateClientCredentials → K_INVALID（证书/AK/SK 非法）<br>
&nbsp;└─ InitClientWorkerConnect → Brpc 连接 + 首心跳<br>
&nbsp;&nbsp;&nbsp;&nbsp;└─ Channel.Init / Heartbeat → K_RPC_UNAVAILABLE / K_CLIENT_WORKER_DISCONNECT</td>
      <td>ConnectOptions 的 ip/port 配错或未配 serviceDiscovery；并发 Init/ShutDown；AK/SK、Token 失效</td>
      <td>安全组/路由不通；DNS 解析失败；证书文件权限或路径错误；本机 fd/线程规格不足</td>
      <td>Init 阶段本身不走 URMA；Init 成功后首次 Create/Publish 才可能触发 URMA 建链</td>
    </tr>
    <tr>
      <td>MCreate / KVClient::MCreate（批量申请 shm buffer）</td>
      <td>批量为 keys 在 Worker 侧申请共享内存，返回可直接填充的 Buffer 列表</td>
      <td><b>client</b>：<br>
'Start to MultiCreate %zu'（size）<br>
VLOG(1) 'Begin to create object, object_key: ...'<br>
'Get mmap entry failed'<br>
'The objectKey is empty' / 'The dataSize value should be bigger than zero.' / 'length of objectKeyList and dataSizeList should be the same.'<br>
<b>access log</b>：<code>DS_KV_CLIENT_MCREATE</code>（dataSize = sizes.size()；respMsg = Status::GetMsg）<br>
<b>worker</b>：<code>DS_POSIX_MCREATE</code>；'MultiCreate failed' / OC 内部日志</td>
      <td>K_OK + buffers 对齐输出</td>
      <td>K_INVALID — keys 空/非法字符、dataSize=0、keys/sizes 长度不等<br>
K_NOT_READY — SDK 未 Init (8)<br>
K_RUNTIME_ERROR — mmap / 'Get mmap entry failed' (5)<br>
K_OUT_OF_MEMORY — shm 池不足 (6)<br>
K_OC_KEY_ALREADY_EXIST — 已存在且 existence=NX (2004)<br>
K_RPC_UNAVAILABLE / K_URMA_* — Worker 通信或 UB 建链异常</td>
      <td>KVClient::MCreate → ObjectClientImpl::MCreate → MultiCreate<br>
&nbsp;├─ IsClientReady → K_NOT_READY<br>
&nbsp;├─ CheckValidObjectKey / IsBatchSizeUnderLimit → K_INVALID<br>
&nbsp;├─ GetAvailableWorkerApi → K_RPC_UNAVAILABLE / K_CLIENT_WORKER_DISCONNECT<br>
&nbsp;├─ workerApi-&gt;MultiCreate（RPC）<br>
&nbsp;│&nbsp;&nbsp;&nbsp;└─ Worker OC::MultiCreate → K_OUT_OF_MEMORY / K_OC_KEY_ALREADY_EXIST / K_SCALING<br>
&nbsp;└─ mmapManager_-&gt;LookupUnitsAndMmapFd → K_RUNTIME_ERROR（'Get mmap entry failed'）</td>
      <td>空/非法 key；批量超 OBJECT_KEYS_MAX_SIZE_LIMIT；写同名 key+NX；size=0</td>
      <td>本机 shm 池满 / hugepage 不足；client fd 超限导致 mmap 失败；磁盘没空间（spill）</td>
      <td>UB 开启时 Worker 侧 urma_register_seg 失败 → 透传为 K_URMA_ERROR；详见 Section 2（urma_register_seg / ubcore_register_seg 行）</td>
    </tr>
    <tr>
      <td>MPublish / KVClient::MSet(buffers)（与 MCreate 成对）</td>
      <td>把 MCreate 拿到的 shm buffer 发布到数据系统：写元数据、可选二级落盘</td>
      <td><b>client</b>：<br>
'Start putting buffer'<br>
'Client object is already sealed'<br>
'The buffer should not be empty.' / 'The buffer size cannot exceed %d.'<br>
<b>access log</b>：<code>DS_KV_CLIENT_MSET</code>（dataSize = buffers.size()；respMsg = Status::GetMsg）<br>
<b>worker</b>：<code>DS_POSIX_PUBLISH</code>；<br>
'MultiPublish' 相关错误 / Master 'CreateMultiMeta failed'</td>
      <td>K_OK</td>
      <td>K_INVALID — buffer 列表为空/含 nullptr；批量超限<br>
K_OC_ALREADY_SEALED — buffer 已 Publish 过 (2000)<br>
K_RUNTIME_ERROR — DispatchKVSync 异常 (5)<br>
K_RPC_UNAVAILABLE / K_RPC_DEADLINE_EXCEEDED — Worker/Master 不可达<br>
K_MASTER_TIMEOUT — 元数据中心不可达 (25)<br>
K_SCALING — 扩缩容重试到上限 (32)（产品语义对业务透明）<br>
K_URMA_ERROR / K_URMA_NEED_CONNECT — UB 传输异常<br>
K_WRITE_BACK_QUEUE_FULL — 二级回写队列满 (2003)</td>
      <td>KVClient::MSet(buffers) → ObjectClientImpl::MSet<br>
&nbsp;├─ IsClientReady → K_NOT_READY<br>
&nbsp;├─ IsBatchSizeUnderLimit → K_INVALID<br>
&nbsp;├─ Buffer::CheckDeprecated / isSeal → K_OC_ALREADY_SEALED<br>
&nbsp;├─ workerApi-&gt;MultiPublish（RPC，<b>内部对 K_SCALING 自动重试</b>）<br>
&nbsp;│&nbsp;&nbsp;&nbsp;├─ Worker CreateMultiMeta → Master<br>
&nbsp;│&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;└─ K_MASTER_TIMEOUT / K_NOT_LEADER_MASTER / K_SCALING<br>
&nbsp;│&nbsp;&nbsp;&nbsp;└─ WriteMode=WRITE_THROUGH → 二级存储写 → K_IO_ERROR / K_WRITE_BACK_QUEUE_FULL<br>
&nbsp;└─ HandleShmRefCountAfterMultiPublish → 维护引用计数</td>
      <td>对同一个 buffer 重复 Publish；WriteMode 选错导致阻塞写二级；超时配得过紧</td>
      <td>RPC 慢/抖动（CPU 打满、内存压力、网络拥塞）；二级存储盘满 / OBS 不可达</td>
      <td>UB 传输链路异常 → K_URMA_ERROR (1004) / K_URMA_NEED_CONNECT (1006) / K_URMA_TRY_AGAIN (1008)；定位沿 Section 2 下钻</td>
    </tr>
    <tr>
      <td>MGet / KVClient::Get(vector&lt;keys&gt;, ...)（批量读）</td>
      <td>按 key 批量取数；Worker 优先读 L1，未命中则 L2 / 远端 Worker（URMA/TCP 拉取）</td>
      <td><b>client</b>：<br>
'Cannot get value from worker' / 'Get mmap entry failed'<br>
<b>access log</b>：<code>DS_KV_CLIENT_GET</code>（<u>NOT_FOUND → 0</u> 陷阱；microseconds 贴 timeout 判断预算耗尽）<br>
<b>worker</b>：<code>DS_POSIX_GET</code>；'[Remote]Pull object' / 'Remote get failed' / 'Read L2 cache failed'<br>
<b>resource.log</b>：线程池 waiting、SHM rate、OBS 成功率（Playbook 第 7 节）</td>
      <td>K_OK（<b>即使部分 key 不存在，顶层仍为 K_OK</b>；per-key 以 buffer 是否有值为准）</td>
      <td>K_INVALID — keys 为空 / 含空 key / 超 QUERY_SIZE_OBJECT_LIMIT<br>
K_NOT_FOUND — 全部 key 都不存在（<b>access log 中被映射为 0 / K_OK</b>，见 Playbook 第 3 节陷阱）<br>
K_RPC_DEADLINE_EXCEEDED — 超时 (1001)<br>
K_RPC_UNAVAILABLE — RPC 不可达 / 传输 bucket 错误 (1002)<br>
K_URMA_ERROR / K_URMA_TRY_AGAIN / K_URMA_NEED_CONNECT — UB 路径异常<br>
K_RUNTIME_ERROR — mmap / 内部异常<br>
K_CLIENT_WORKER_DISCONNECT — Worker 心跳断</td>
      <td>KVClient::Get → ObjectClientImpl::Get → workerApi-&gt;MultiGet（RPC）<br>
&nbsp;├─ Worker 命中 L1：直接返回 shm / urma 描述<br>
&nbsp;│&nbsp;&nbsp;&nbsp;└─ client mmap 新 fd → K_RUNTIME_ERROR（'Get mmap entry failed'）<br>
&nbsp;├─ Worker 未命中 L1：<br>
&nbsp;│&nbsp;&nbsp;&nbsp;├─ 远端 Worker 拉取（UB 优先，TCP 降级）<br>
&nbsp;│&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;└─ K_URMA_* / K_RPC_UNAVAILABLE / K_RPC_DEADLINE_EXCEEDED<br>
&nbsp;│&nbsp;&nbsp;&nbsp;└─ L2 存储读 → K_IO_ERROR / K_NOT_FOUND<br>
&nbsp;└─ per-key 结果放 buffers[i]；<b>per-object last_rc 可能为失败而顶层 K_OK</b></td>
      <td>key 格式非法；批量 &gt; QUERY_SIZE_OBJECT_LIMIT；timeout 过紧；业务把 NOT_FOUND 当错误</td>
      <td>网络拥塞 / 丢包；本机 CPU 饱和；shm fd 超限 / mmap 失败；磁盘或 OBS 延迟高</td>
      <td>跨节点拉数走 UB：UB 降 lane / Jetty / 平面切换 → K_URMA_ERROR / K_URMA_TRY_AGAIN；沿 Section 2 定位</td>
    </tr>
    <tr>
      <td>Exist / KVClient::Exist</td>
      <td>批量查询 key 是否存在：查 Worker 元数据 + 可选 etcd</td>
      <td><b>client</b>：<br>
'Exist resp error, msg:...'<br>
'Exist response size X is not equal to key size Y'<br>
'The objectKeys size exceed %d.'<br>
<b>access log</b>：Exist <u>当前未挂</u> <code>DS_KV_*</code> access 点（Playbook 第 2 节），依赖应用日志定位<br>
<b>worker</b>：Exist 相关 RPC 错误 / etcd 读失败</td>
      <td>K_OK + exists[] 与 keys[] 一一对应</td>
      <td>K_INVALID — keys 空 / 含空 key / size &gt; QUERY_SIZE_OBJECT_LIMIT（10000）<br>
K_NOT_READY — SDK 未 Init (8)<br>
K_RPC_UNAVAILABLE / K_RPC_DEADLINE_EXCEEDED — Worker 不可达 / 超时<br>
K_MASTER_TIMEOUT — 查 etcd 时 Master 不可达 (25)<br>
K_RUNTIME_ERROR — 响应大小与请求不一致</td>
      <td>KVClient::Exist → ObjectClientImpl::Exist<br>
&nbsp;├─ IsClientReady → K_NOT_READY<br>
&nbsp;├─ CheckValidObjectKeyVector → K_INVALID<br>
&nbsp;├─ size &lt;= QUERY_SIZE_OBJECT_LIMIT → K_INVALID<br>
&nbsp;└─ workerApi-&gt;Exist（RPC）<br>
&nbsp;&nbsp;&nbsp;&nbsp;├─ Worker 查本地元数据 / etcd（queryEtcd=true 时）<br>
&nbsp;&nbsp;&nbsp;&nbsp;│&nbsp;&nbsp;&nbsp;└─ K_MASTER_TIMEOUT / K_KVSTORE_ERROR<br>
&nbsp;&nbsp;&nbsp;&nbsp;└─ 返回 exists.size() 必须等于 keys.size()，否则 K_RUNTIME_ERROR</td>
      <td>批量过大；传入空字符串 key；把『不存在』当错误处理</td>
      <td>client ↔ worker 网络不通；etcd 访问异常或高延迟（对应 Section 2 下部 MAMI / etcd 侧）</td>
      <td>纯元数据路径，不走 URMA</td>
    </tr>
    <tr>
      <td>其它常用（Del / Expire / QuerySize / Create+Set）</td>
      <td>Del=删除；Expire=设置 TTL；QuerySize=查对象大小；Create+Set=单 key 版的 MCreate+MPublish</td>
      <td><code>DS_KV_CLIENT_DELETE</code> / <code>DS_KV_CLIENT_EXPIRE</code> / <code>DS_KV_CLIENT_CREATE</code> / <code>DS_KV_CLIENT_SET</code>；<br>
'Set expire ttl failed' / 'The objectKeys size exceed'</td>
      <td>K_OK</td>
      <td>K_INVALID — key 空 / 批量超 QUERY_SIZE_OBJECT_LIMIT<br>
K_NOT_FOUND — key 不存在（Expire / QuerySize）<br>
K_NOT_READY — SDK 未 Init<br>
K_RPC_UNAVAILABLE / K_RPC_DEADLINE_EXCEEDED — 链路类<br>
K_RUNTIME_ERROR — 内部异常</td>
      <td>与前述通用路径一致：IsClientReady → 校验 → GetAvailableWorkerApi → workerApi-&gt;RPC → Worker 元数据 / 数据路径</td>
      <td>参数校验类；业务超时配置；并发生命周期管理</td>
      <td>同 MCreate / MGet</td>
      <td>仅 Create+Set 走 URMA（同 MPublish 行）</td>
    </tr>
  </tbody>
</table>

<!--
说明：
- 关键日志节选自 src/datasystem/client/kv_cache/kv_client.cpp、
  src/datasystem/client/object_cache/object_client_impl.cpp、
  src/datasystem/client/object_cache/client_worker_api/*.cpp、
  src/datasystem/common/log/access_point.def。
- DS_KV_CLIENT_GET 的 K_NOT_FOUND → 0 映射陷阱见 plans/kv_client_triage/KV_CLIENT_TRIAGE_PLAYBOOK.md 第 3 节。
- K_SCALING / K_SCALE_DOWN 的产品语义（对业务透明）见同一 Playbook 第 4.3 节。
- K_URMA_ERROR=1004、K_URMA_NEED_CONNECT=1006、K_URMA_TRY_AGAIN=1008 等 URMA 码都来自下游 UB 路径，
  根因请沿 Section 2 的 URMA / UDMA / 内核接口下钻。
-->

---

## 2. URMA → UDMA → Kernel 故障树（底层链路与驱动）

> 原 TSV 的「KVCache / 出错返回值 / errno」三列在旧文件中全部为空（属于 KVCache 层，
> 已移入 Section 1）。本节保留 URMA 用户态 → UDMA 用户态 → URMA 内核态（ubcore）→ UDMA 内核态 →
> MAMI，以及右侧「检查工具 / 恢复手段」两列。


<table>
  <thead>
    <tr>
      <th colspan="4">URMA 用户态</th>
      <th colspan="4">UDMA 用户态</th>
      <th colspan="3">URMA 内核态（ubcore）</th>
      <th colspan="2">UDMA 内核态</th>
      <th>MAMI</th>
      <th>检查工具</th>
      <th>恢复手段</th>
    </tr>
    <tr>
      <th>接口</th><th>出错返回值</th><th>errno</th><th>errno 原因 / 关键日志</th>
      <th>接口</th><th>出错返回值</th><th>errno</th><th>故障点 / 关键日志</th>
      <th>接口</th><th>返回值</th><th>故障原因 / 关键日志</th>
      <th>接口</th><th>故障原因</th>
      <th>故障原因</th>
      <th>检查工具</th>
      <th>恢复手段</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td colspan="16"><b>KVC场景下RM CTP+bonding设备多端口</b></td>
    </tr>
    <tr>
      <td colspan="16"><b>1. URMA接口</b></td>
    </tr>
    <tr>
      <td>urma_ack_jfc</td>
      <td>NA</td>
      <td>NA</td>
      <td>NA</td>
      <td>udma_u_ack_jfc</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_advise_jfr(UB场景不支持此API)</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_create_context</td>
      <td>NULL</td>
      <td>EINVAL<br>EIO<br>N/A</td>
      <td>EINVAL-参数校验错误，空指针，或驱动不支持create_contest ops<br>URMA_LOG_ERR("Invalid parameter with err dev or ops.\n");<br>EIO-sysfs设备信息读取失败<br>URMA_LOG_ERR("Failed to query eid.\n");<br>打开字符设备失败<br>URMA_LOG_ERR("Failed to open urma cdev with path %s, dev_fd: %d\n",<br>                dev-&gt;path, dev_fd);<br>N/A-udma接口调用失败<br>URMA_LOG_ERR("[DRV_ERR]Failed to create urma context.\n");</td>
      <td>udma_u_create_context</td>
      <td>NULL</td>
      <td></td>
      <td>urma_cmd_create_context接口调用失败，返回urma错误码<br>mmap申请db_addr失败，返回值22</td>
      <td>ubcore_alloc_ucontext</td>
      <td>ERR_PTR(-EINVAL)<br>ERR_PTR(-EPERM)<br>UDMA返回值</td>
      <td>"参数检查错误，非法空指针等<br>ubcore_log_err(""Invalid argument.\n"");"<br>设备access权限访问错误<br>调用UDMA 接口返回失败</td>
      <td>udma_alloc_ucontext</td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前不会触发</td>
    </tr>
    <tr>
      <td>urma_create_jfc</td>
      <td>NULL</td>
      <td>EINVAL<br>N/A</td>
      <td>EINVAL-参数校验错误，空指针入参<br>URMA_LOG_ERR("Invalid parameter.");<br>参数错误，用户传入的jfc深度为0，或者超过FE支持的最大jfc深度<br>URMA_LOG_ERR("jfc cfg depth of range, depth: %u, max_depth: %u.\n", jfc_cfg-&gt;depth,<br>                     attr-&gt;dev_cap.max_jfc_depth);<br>N/A-udma接口调用失败<br>URMA_LOG_ERR("[DRV_ERR]Failed to create jfc, dev_name: %s, eid_idx: %u.\n",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);</td>
      <td>udma_u_create_jfc</td>
      <td>NULL</td>
      <td></td>
      <td>参数校验错误（depth/ceqn）,返回值22<br>用户态分配 CQ buf 失败，返回值14<br>用户态 sw db（doorbell）分配失败，返回值NULL<br>urma_cmd_create_jfc接口调用失败，返回值urma错误码</td>
      <td>ubcore_create_jfc</td>
      <td>UDMA返回值，如果udma返回为空，则为ERR_PTR(-UBCORE_DRV_ERRNO)</td>
      <td>调用UDMA接口返回异常指针<br>ubcore_log_err("failed to create jfc, dev_name: %s.\n", dev-&gt;dev_name);</td>
      <td>udma_create_jfc</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_create_jfce</td>
      <td>NULL</td>
      <td>EINVAL<br>N/A</td>
      <td>EINVAL-参数校验错误，空指针入参<br>URMA_LOG_ERR("Invalid parameter.\n");<br>N/A-udma接口调用失败<br>URMA_LOG_ERR("[DRV_ERR]Failed to create jfce, dev_name: %s, eid_idx: %u.\n",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前预期不会出现，如果fd超规格可能导致失败，此时需要修改系统fd规格数，或者减小应用创建jfce的数量</td>
    </tr>
    <tr>
      <td>urma_create_jfr</td>
      <td>NULL</td>
      <td>EINVAL<br>N/A</td>
      <td>EINVAL-参数校验错误，空指针异常<br>URMA_LOG_ERR("Invalid parameter.\n");<br>trans_mode异常：<br>URMA_LOG_ERR("Invalid parameter, trans_mode: %d.\n", (int)jfr_cfg-&gt;trans_mode);<br>jfr深度非法或超过FE上限：<br>URMA_LOG_ERR("jfr cfg out of range, depth:%u, max_depth:%u, sge:%u, max_sge:%u.\n", jfr_cfg-&gt;depth,<br>                     attr-&gt;dev_cap.max_jfr_depth, jfr_cfg-&gt;max_sge, attr-&gt;dev_cap.max_jfr_sge);<br>N/A-udma接口调用失败<br>URMA_LOG_ERR("[DRV_ERR]Failed to create jfr, dev_name: %s, eid_idex: %u.\n",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);</td>
      <td>udma_u_create_jfr</td>
      <td>NULL</td>
      <td></td>
      <td>参数校验错误（depth/sge/token_policy），返回EINVAL（22）<br>分配 index queue buf 失败（bitmap申请失败/ index_buf mmap/madvise失败），返回ENOMEM（12）<br>分配 RQ buf 失败（用户态 mmap/madvise 失败），返回EINVAL（22）<br>申请hugepage 失败且申请普通内存也失败，返回NULL<br>分配 sw_db 失败，返回NULL<br>urma_cmd_create_jfr接口调用失败，返回urma错误码</td>
      <td>ubcore_create_jfr</td>
      <td>UDMA返回值</td>
      <td>调用UDMA接口返回异常指针<br>ubcore_log_err("[DRV]failed to create jfr,device: %s.\n", dev-&gt;dev_name);</td>
      <td>udma_create_jfr</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_create_jfs</td>
      <td>NULL</td>
      <td>EINVAL<br>N/A</td>
      <td>EINVAL-参数校验错误，空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>参数校验错误，传输模式非法<br>URMA_LOG_ERR("Invalid parameter, trans_mode: %d.\n", (int)jfs_cfg-&gt;trans_mode);<br>参数校验错误，保序类型错误等<br>URMA_LOG_ERR("Invalid parameter, trans_mode: %d, order_type: %u.\n", (int)jfs_cfg-&gt;flag.bs.order_type,<br>                     order_type);<br>jfs深度层参数错误<br>URMA_LOG_ERR("jfs cfg out of range, depth:%u, max_depth:%u, inline_data:%u, max_inline_len:%u, "<br>                     "sge:%hhu, max_sge:%u, rsge:%hhu, max_rsge:%u.\n",<br>                     jfs_cfg-&gt;depth, attr-&gt;dev_cap.max_jfs_depth, jfs_cfg-&gt;max_inline_data,<br>                     attr-&gt;dev_cap.max_jfs_inline_len, jfs_cfg-&gt;max_sge, attr-&gt;dev_cap.max_jfs_sge, jfs_cfg-&gt;max_rsge,<br>                     attr-&gt;dev_cap.max_jfs_rsge);<br>N/A-调用UDMA接口失败<br>URMA_LOG_ERR("[DRV_ERR]Failed to create jfs, dev_name: %s, eid_idx: %u.\n",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);</td>
      <td>udma_u_create_jfs</td>
      <td>NULL</td>
      <td></td>
      <td>参数校验错误<br>用户态分配 SQ buf 失败<br>urma_cmd_create_jfs接口调用失败<br>mmap申请SQ db_addr失败</td>
      <td>ubcore_create_jfs</td>
      <td>ERR_PTR(-EINVAL)<br>UDMA返回值<br>ERR_PTR(-EEXIST)</td>
      <td>ERR_PTR(-EINVAL)：非法参数<br>ubcore_log_err("jfs cfg is not qualified.\n");<br>UDMA返回值：<br>ubcore_log_err("[Drv]failed to create jfs, device: %s.\n", dev-&gt;dev_name);<br>ERR_PTR(-EEXIST)：重复添加，当前不存在此错误</td>
      <td>udma_create_jfs</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_delete_context</td>
      <td>URMA_EINVAL<br>URMA_EAGAIN</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误<br>URMA_LOG_ERR("Invalid parameter.\n");<br>URMA_EAGAIN-依赖的资源尚未清理<br>URMA_LOG_WARN("already in use, atomic_cnt: %lu, dev_name: %s, eid_idx: %u.\n",<br>            atomic_cnt, dev_name, eid_index);<br>NA-调用UDMA接口失败<br>URMA_LOG_WARN("[DRV_ERR]Delete ctx error, fd: %d, ret: %d, dev_name: %s, eid_idx: %u.\n",<br>            dev_fd, ret, dev_name, eid_index);</td>
      <td>udma_u_delete_context</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_delete_context接口调用失败，返回URMA_FAIL</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前不会触发</td>
    </tr>
    <tr>
      <td>urma_delete_jfc</td>
      <td>URMA_EINVAL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查失败，空指针等错误<br>URMA_LOG_ERR("Invalid parameter.\n");<br>jfc状态异常，与用户用法有关，通算场景不涉及<br>URMA_LOG_ERR("jfc is deactived, can not delete.\n");<br>UDMA错误返回值-调用UDMA接口错误<br>URMA_LOG_ERR(<br>            "[DRV_ERR]Failed to delete jfc, dev_name: %s, eid_idx: %u, id: %u, ret: %d.\n",<br>            urma_ctx-&gt;dev-&gt;name, urma_ctx-&gt;eid_index, jfc_id, ret);</td>
      <td>udma_u_delete_jfc</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_delete_jfc接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_delete_jfc</td>
      <td>UDMA返回值</td>
      <td>ubcore_log_err(<br>   "[DRV] failed to destroy jfc, dev_name: %s, jfc_id: %u, ret: %d\n",<br>   dev-&gt;dev_name, jfc_id, ret);</td>
      <td>udma_destroy_jfc</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_delete_jfce</td>
      <td>URMA_EINVAL<br>URMA_FAIL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>URMA_FAIL-jfce销毁之前，关联的jfc仍然存在<br>URMA_LOG_ERR("Jfce is still used by at least one jfc, refcnt:%u.\n",<br>            (uint32_t)atomic_load(&amp;jfce-&gt;ref.atomic_cnt));<br>UDMA错误返回值<br>URMA_LOG_ERR("[DRV_ERR]Failed to delete jfce, ret: %d\n", (int)ret);</td>
      <td>udma_u_delete_jfce</td>
      <td>URMA_EINVAL（22）</td>
      <td></td>
      <td>参数校验错误（fd），返回错误码URMA_EINVAL</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前不会触发</td>
    </tr>
    <tr>
      <td>urma_delete_jfr</td>
      <td>URMA_EINVAL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针<br>URMA_LOG_ERR("Invalid parameter.\n");<br>URMA_EINVAL-jfr状态异常，与用户用法有关，通算场景不涉及<br>URMA_LOG_ERR("jfr is deactived, can not delete.\n");<br>UDMA错误返回值<br>"[DRV_ERR]Failed to delete jfr, dev_name: %s, eid_idx: %u, id: %u, status: %d.\n",<br>            urma_ctx-&gt;dev-&gt;name, urma_ctx-&gt;eid_index, jfr_id, status);</td>
      <td>udma_u_delete_jfr</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_delete_jfr接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_delete_jfr</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err(<br>   "[DRV] failed to destroy jfr, dev_name: %s, eid_idx: %u, jfr_id: %u, ret:%u\n",<br>   dev-&gt;dev_name, jfr-&gt;jfr_cfg.eid_index, jfr_id, ret);</td>
      <td>udma_destroy_jfr</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_delete_jfs</td>
      <td>URMA_EINVAL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针<br>URMA_LOG_ERR("Invalid parameter.\n");<br>URMA_EINVAL-jfs状态异常，与用户用法有关，通算场景不涉及<br>URMA_LOG_ERR("jfs is deactived, can not delete.\n");<br>UDMA错误返回值<br>"[DRV_ERR]Failed to delete jfs, dev_name: %s, eid_idx: %u, id: %u, ret: %d.\n",<br>            urma_ctx-&gt;dev-&gt;name, urma_ctx-&gt;eid_index, jfs_id, ret);</td>
      <td>udma_u_delete_jfs</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_delete_jfs接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_delete_jfs</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV] Failed to destroy jfs, dev_name: %s, eid_idx: %u, jfs_id: %u.\n",<br>   dev-&gt;dev_name, jfs-&gt;jfs_cfg.eid_index, jfs_id);</td>
      <td>udma_destroy_jfs</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_free_eid_list</td>
      <td>NA</td>
      <td>NA</td>
      <td></td>
      <td>NA</td>
      <td>NA</td>
      <td></td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>NA</td>
    </tr>
    <tr>
      <td>urma_get_device_by_name</td>
      <td>NULL</td>
      <td>EINVAL<br>ENODEV</td>
      <td>EINVAL-参数检查错误，异常空指针或入参<br>URMA_LOG_ERR("Invalid dev_name.\n");<br>NA-查询设备列表不存在-UDMA未注册设备，或udma内核不存在<br>URMA_LOG_ERR("urma get device list failed, device_num: %d.\n", device_num);<br>ENODEV-不存在与入参名称相同的UB设备<br>URMA_LOG_ERR("device list name:%s does not match dev_name: %s.\n", device_list[i]-&gt;name, dev_name);</td>
      <td>N/A</td>
      <td>N/A</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>lsmod | grep udma<br>urma_admin show -a查看UB设备是否存在，部署完成后重试</td>
    </tr>
    <tr>
      <td>urma_get_device_list</td>
      <td>nullptr</td>
      <td>EINVAL<br>ENODEV<br>ENOMEM<br>ENOEXEC</td>
      <td>EINVAL-"参数校验错误，出入参为空指针<br>URMA_LOG_ERR(""Invalid parameter.\n"");"<br>ENODEV-查询出的设备数量为0<br>ENOMEM-申请内存失败（此场景不记录日志）<br>ENOEXEC-获取设备字符数量前后查询不一致（此场景预期不会出现）</td>
      <td>N/A</td>
      <td>N/A</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>lsmod | grep udma<br>urma_admin show -a查看UB设备是否存在，部署完成后重试</td>
    </tr>
    <tr>
      <td>urma_get_eid_list</td>
      <td>null</td>
      <td>EINVAL<br>ENOMEM<br>EIO</td>
      <td>EINVAL-参数校验错误，空指针等非法参数<br>URMA_LOG_WARN(""invalid parameter with null_ptr.\n"");<br>udma注册的FE中，eid规格异常为0<br>URMA_LOG_ERR(""max eid cnt %u is err"", max_eid_cnt);<br>ioctl返回失败，内核FE中无EID列表<br>URMA_LOG_ERR(""ioctl failed, ret:%d, errno:%d, cmd:%u, kdrv_err: %d.\n"",<br>            ret, errno, hdr.command, (int)(errno == URMA_KERNEL_DRV_ERRNO));"<br>ENOMEM-OS内存分配出错（此场景不记录日志）<br>EIO-出参cnt为0，内核FE找不到EID信息<br>URMA_LOG_INFO(""There is no eid in dev: %s, max_eid_cnt: %u."",<br>            dev-&gt;name, max_eid_cnt);</td>
      <td>N/A</td>
      <td>N/A</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>lsmod | grep udma<br>urma_admin show -a查看UB设备是否存在，部署完成后重试</td>
    </tr>
    <tr>
      <td>urma_import_jfr</td>
      <td>NULL</td>
      <td>EINVAL<br>UDMA返回错误码</td>
      <td>EINVAL-参数检查错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>EINVAL-token_policy等参数非法<br>URMA_LOG_ERR("Token value must be set when token policy is not URMA_TOKEN_NONE.\n");<br>其他错误码-调用UDMA import_jfr失败</td>
      <td>udma_u_get_tp_list</td>
      <td></td>
      <td></td>
      <td>urma_cmd_get_tp_list</td>
      <td>ubcore_get_tp_list</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV_ERROR]Failed to get to list, ret: %d.\n", ret);</td>
      <td>udma_get_tp_list</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>udma_u_import_jfr_ex</td>
      <td>NULL</td>
      <td></td>
      <td>urma_cmd_import_jfr_ex接口调用失败，返回NULL</td>
      <td>ubcore_import_jfr_ex</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV] failed to import jfr ex, dev_name: %s, jfr_id:%u.\n",<br>   dev-&gt;dev_name, cfg-&gt;id.id);</td>
      <td>udma_import_jfr_ex</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>ubcore_active_tp</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err(<br>   "Failed to active tp, ret: %d, local tpid: %u.\n", ret,<br>   (uint32_t)active_cfg-&gt;tp_handle.bs.tpid);</td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>UDMA错误定界；<br>建链交换信息失败，可重试</td>
    </tr>
    <tr>
      <td>urma_import_seg</td>
      <td>nullptr</td>
      <td>EINVAL<br>UDMA返回错误码</td>
      <td>EINVAL-"参数校验错误，空指针等<br>URMA_LOG_ERR(""Invalid parameter.\n"");<br>token权限配置错误<br>URMA_LOG_ERR(""Token value must be set when token policy is not URMA_TOKEN_NONE.\n"");"<br>UDMA返回错误码-"udma接口调用失败<br>URMA_LOG_ERR(""[DRV_ERR]Failed to import seg, dev_name: %s, eid_idx: %u.\n"",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);"</td>
      <td>udma_u_import_seg</td>
      <td>NULL</td>
      <td></td>
      <td>参数校验错误（token_policy），返回NULL指针<br>calloc申请target seg失败，返回NULL指针</td>
      <td>ubcore_import_seg</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV] failed to import segment with va\n");</td>
      <td>udma_import_seg</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_init</td>
      <td>URMA_EEXIST<br>URMA_FAIL</td>
      <td>NA</td>
      <td>URMA_EEXIST-"多次初始化<br>URMA_LOG_ERR(""urma_init has been called before.\n"");"<br>URMA_FAIL-"驱动so文件dlopen失败<br>URMA_LOG_ERR(""None of the providers registered.\n"");"</td>
      <td>udma_u_init</td>
      <td>N/A</td>
      <td></td>
      <td>N/A</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>查看/usr/lib64/urma目录下，是否存在liburma_udma.so等驱动文件，或查看文件是否具备x权限，完成正确部署后重试</td>
    </tr>
    <tr>
      <td>urma_modify_jfs</td>
      <td>URMA_EINVAL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA错误返回值-当前暂未记录日志</td>
      <td>udma_u_modify_jfs</td>
      <td>URMA_EINVAL</td>
      <td></td>
      <td>参数校验错误（jfs_attr mask）,返回URMA_FAIL<br>urma_cmd_modify_jfs接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_modify_jfs</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV_ERROR]Failed to modify jfs, jfs_id:%u, ret: %d.\n",<br>       jfs_id, ret);</td>
      <td>udma_modify_jfs</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_poll_jfc</td>
      <td>-1<br>UDMA返回值</td>
      <td>N/A</td>
      <td>-1："参数校验错误，空指针或cr_cnt非法等异常<br>URMA_LOG_ERR(""Invalid parameter.\n"");"<br>udma接口调用失败（性能考虑不记录日志）</td>
      <td>udma_u_poll_jfc</td>
      <td>UDMA_INTER_ERR（1）</td>
      <td></td>
      <td>cqe为NULL，poll失败，返回错误码JFC_EMPTY（1）<br>cqe解析失败，返回错误码JFC_POLL_ERR（2）</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_post_jfs_wr</td>
      <td>URMA_EINVAL<br>UDMA返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL：参数校验错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA返回值：当前URMA不会记录日志</td>
      <td>udma_u_post_jfs_wr</td>
      <td>URMA_EINVAL</td>
      <td></td>
      <td>JFS post sq wr失败，返回URMA_EINVAL</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_query_device</td>
      <td>URMA_EINVAL<br>URMA_FAIL</td>
      <td>EINVAL<br>N/A</td>
      <td>URMA_EINVAL："参数校验错误<br>URMA_LOG_ERR(""Invalid parameter.\n"");"<br>URMA_FAIL："udma接口调用失败<br>URMA_LOG_ERR(""Failed to query device attr, ret: %d.\n"", ret);"</td>
      <td>udma_u_query_device</td>
      <td>NA</td>
      <td></td>
      <td>直接返回URMA_SUCCESS</td>
      <td>ubcore_query_device_attr</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("failed to query device attr, ret: %d.\n", ret);</td>
      <td>udma_query_device_attr</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_read</td>
      <td>URMA_EINVAL<br>UDMA返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL：参数检查错误，空指针等异常<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA异常返回值：当前URMA未记录日志</td>
      <td>N/A</td>
      <td>NA</td>
      <td></td>
      <td>N/A</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_rearm_jfc</td>
      <td>URMA_EINVAL<br>UDMA异常返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL：参数检查错误，空指针等异常<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA异常返回值：当前URMA未记录日志</td>
      <td>udma_u_rearm_jfc</td>
      <td>NA</td>
      <td></td>
      <td>直接返回URMA_SUCCESS</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_register_log_func</td>
      <td>URMA_EINVAL</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前不会触发失败</td>
    </tr>
    <tr>
      <td>urma_register_seg</td>
      <td>null</td>
      <td>EINVAL<br>UDMA返回错误码</td>
      <td>EINVAL-"参数检查错误，空指针或者seg access等错误<br>URMA_LOG_ERR(""Invalid parameter.\n"");<br>URMA_LOG_ERR(""token_id must set when token_id_valid is true, or must NULL when token_id_valid is false.\n"");<br>URMA_LOG_ERR(""Local only access is not allowed to config with other accesses.\n"");<br>URMA_LOG_ERR(""Write access should be config with read access.\n"");<br>URMA_LOG_ERR(""Atomic access should be config with read and write access.\n"");"<br>UDMA返回错误码："udma接口调用失败<br>URMA_LOG_ERR(""[DRV_ERR]Failed to register seg, dev_name: %s, eid_idx: %u.\n"",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);"<br>UDMA返回错误码："udma接口调用失败<br>URMA_LOG_ERR(""[DRV_ERR]register seg failed, dev_name: %s, eid_idx: %u.\n"",<br>            ctx-&gt;dev-&gt;name, ctx-&gt;eid_index);"</td>
      <td>udma_u_register_seg</td>
      <td>NULL</td>
      <td></td>
      <td>参数校验错误（access/token_id/token_policy），返回NULL指针<br>ummu_grant接口调用错误，返回NULL指针<br>urma_cmd_register_seg接口调用失败，返回URMA错误码</td>
      <td>ubcore_register_seg</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV]failed to register segment,dev name is %s.\n",<br>          dev-&gt;dev_name);</td>
      <td>udma_register_seg</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>ubcore_unimport_jfr</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV] Failed to unimport jfr, dev_name: %s, eid_idx: %u, tjfr_id: %u.\n",<br>   dev-&gt;dev_name, tjfr-&gt;cfg.eid_index, tjfr_id);</td>
      <td>udma_unimport_jfr</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_unimport_jfr</td>
      <td>URMA_EINVAL<br>UDMA错误返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA错误返回值：URMA当前未记录日志</td>
      <td>udma_u_unimport_jfr</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_unimport_jfr接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_deactive_tp</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV_ERROR]Failed to deactivate tp, ret: %d.\n", ret);</td>
      <td>udma_deactive_tp</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_unimport_seg</td>
      <td>URMA_EINVAL<br>UDMA错位返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA错误返回值：URMA当前未记录日志</td>
      <td>udma_u_unimport_seg</td>
      <td>NA</td>
      <td></td>
      <td>直接返回URMA_SUCCESS</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_uninit</td>
      <td>URMA_FAIL</td>
      <td>NA</td>
      <td>调用UDMAuninit失败<br>URMA_LOG_WARN("Provider uninit failed %s\n", driver-&gt;ops-&gt;name);</td>
      <td>udma_u_uninit</td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_unregister_log_func</td>
      <td>恒返回URMA_SUCCESS</td>
      <td>NA</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td>当前不会触发失败</td>
    </tr>
    <tr>
      <td>urma_unregister_seg</td>
      <td>URMA_EINVAL<br>UDMA异常返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL-参数检查错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA异常返回值-调用UDMA返回失败<br>URMA_LOG_ERR(<br>            "[DRV_ERR]Unregister seg fail, dev_name: %s, eid_idx: %u, tid: %u, ret: %d.\n",<br>            urma_ctx-&gt;dev-&gt;name, urma_ctx-&gt;eid_index, token_id-&gt;token_id, ret);</td>
      <td>udma_u_unregister_seg</td>
      <td>URMA_FAIL</td>
      <td></td>
      <td>urma_cmd_unregister_seg接口调用失败，返回URMA_FAIL</td>
      <td>ubcore_unregister_seg</td>
      <td>UDMA错误返回值</td>
      <td>ubcore_log_err("[DRV]failed to unregister segment,dev name is %s, ret is %d.\n",<br>   dev-&gt;dev_name, ret);</td>
      <td>udma_unregister_seg</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_wait_jfc</td>
      <td>-1<br>UDMA返回值</td>
      <td>NA</td>
      <td>-1："参数检查错误，非法空指针等<br>URMA_LOG_ERR(""Invalid parameter.\n"");"<br>处于性能考虑，异常不记录错误日志</td>
      <td>udma_u_wait_jfc</td>
      <td></td>
      <td></td>
      <td>urma_cmd_wait_jfc接口调用失败，返回URMA错误码</td>
      <td>uburma_jfce_wait</td>
      <td>ERR_PTR(512)</td>
      <td>UDMA中断未上报<br>中断打断wait（errno 512）<br>uburma_log_err("Failed to wait jfce event, ret: %d.\n", ret);</td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
    <tr>
      <td>urma_write</td>
      <td>URMA_EINVAL<br>UDMA异常返回值</td>
      <td>NA</td>
      <td>URMA_EINVAL：参数检查错误，异常空指针等<br>URMA_LOG_ERR("Invalid parameter.\n");<br>UDMA异常返回值-调用UDMA返回失败<br>出于性能考虑，当前URMA未记录此日志</td>
      <td>udma_u_post_jfs_wr</td>
      <td></td>
      <td></td>
      <td></td>
      <td>NA</td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
      <td></td>
    </tr>
  </tbody>
</table>

<!--
说明：
- 本表由原 fault-tree-table.md（TSV）转 HTML，并去掉全部为空的 KVCache 三列；
  原单行以及 '1. URMA接口' 等目录行渲染为整行标题（<td colspan=16>）。
- 多行单元格用 <br> 保留换行；URMA_LOG_ERR / ubcore_log_err 等日志字面量保留不改，便于 grep 定位。
- 右两列（检查工具 / 恢复手段）汇总了 URMA 侧的排查动作（lsmod | grep udma、urma_admin show -a 等），
  是从 Section 1 'URMA 问题' 列下钻的入口。
-->

---

## 3. 使用指引（从 KVCache 症状 → URMA / 内核根因）

1. **先看 Section 1**：从 SDK 顶层的 `StatusCode` 反查接口行，确认是哪一类故障域：
   - **用户问题**（参数 / 编排 / 超时）→ 按『用户问题』列修正应用侧；
   - **OS 问题**（fd / shm / 网络 / 磁盘）→ 走主机侧运维；
   - **URMA 问题**（`K_URMA_*` 或 `K_RPC_UNAVAILABLE` 且 Worker 日志命中 UB 关键字）→ 进入 Section 2。
2. **在 Section 2 下钻**：根据 Worker / client / dmesg 日志定位到具体的 URMA 用户态接口
   （如 `urma_create_jfs`、`urma_import_seg`），再顺着同一行看 UDMA 用户态 → URMA 内核态（ubcore）
   → UDMA 内核 → MAMI，直到找到真正失败的层。
3. **排查 / 恢复**：右两列给出 `lsmod | grep udma`、`urma_admin show -a`、有界重试等动作，
   结合 Worker `resource.log` 与 access log 交叉验证。

## 4. 相关文档

- `vibe-coding-files/plans/kv_client_triage/KV_CLIENT_TRIAGE_PLAYBOOK.md`：Access log 字段、`K_NOT_FOUND → 0` 陷阱、错误码表
- `vibe-coding-files/plans/kv_client_triage/KV_CLIENT_FAULT_TRIAGE_TREE.md`：TP99 × 成功率两维度 triage 树
- `vibe-coding-files/workspace/fema-analysis-legacy.md`：FEMA 故障清单（已规范化为 19 列模板）
- `include/datasystem/utils/status.h`：`StatusCode` 枚举定义
- `src/datasystem/common/log/access_point.def`：`DS_KV_CLIENT_*` handle 名

