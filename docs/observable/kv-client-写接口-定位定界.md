# KV Client 写接口定位定界（基于 `kv_client.h`）

本文聚焦 `kv_client.h` 的写接口，按 **SDK 侧 -> Worker 侧** 串联调用链、错误码、日志与排查树。

配套：
- `docs/observable/sdk-init-定位定界.md`
- `docs/observable/kv-client-读接口-定位定界.md`
- `docs/observable/kv-场景-故障分类与责任边界.md`

---

## 1. 写接口范围

- 单 key：
  - `Set(const std::string&, const StringView&, const SetParam&)`
  - `Set(const StringView&, const SetParam&)`（自动生成 key）
- buffer 写：
  - `Create(...)` + `Set(const std::shared_ptr<Buffer>&)`
  - `MCreate(...)` + `MSet(const std::vector<std::shared_ptr<Buffer>>& )`
- 批量值写：
  - `MSet(keys, vals, failedKeys, MSetParam)`
  - `MSetTx(keys, vals, MSetParam)`

---

## 2. 调用链（SDK -> Worker）

## 2.1 `Set(key,val)` 主链
- `KVClient::Set` -> `ObjectClientImpl::Set(key,val,setParam)` -> `Put(...)`
- `Put` 根据路径选择：
  - SHM/URMA：`ProcessShmPut(...)`
  - payload 直发：`workerApi->Publish(...)`

```2528:2537:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/object_client_impl.cpp
Status ObjectClientImpl::Set(const std::string &key, const StringView &val, const SetParam &setParam)
{
    ...
    return Put(key, reinterpret_cast<const uint8_t *>(val.data()), val.size(), param, {}, setParam.ttlSecond,
               static_cast<int>(setParam.existence));
}
```

## 2.2 `MSet(keys, vals)` 主链
- `KVClient::MSet` -> `ObjectClientImpl::MSet(keys, vals, param, failedKeys)`
- 内部：参数校验 -> Create/MemoryCopy（SHM/UB）-> `workerApi->MultiPublish(...)`

客户端 MultiPublish 重试集合（含 `K_SCALING`）：

```423:437:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
    RETURN_IF_NOT_OK_PRINT_ERROR_MSG(
        RetryOnError(
            requestTimeoutMs_,
            ...
            { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
              StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_OUT_OF_MEMORY, StatusCode::K_SCALING },
            rpcTimeoutMs_),
        "Send multi publish request error");
```

Worker 写入口：
- `WorkerOCServiceImpl::Publish` -> `publishProc_->Publish`
- `WorkerOCServiceImpl::MultiPublish` -> `multiPublishProc_->MultiPublish`

---

## 3. 写接口错误码（SDK 常见）

- `K_INVALID`：keys/vals 不一致、重复 key、空 value、Tx key 数限制
- `K_OC_ALREADY_SEALED`：重复 seal
- `K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED` / `K_TRY_AGAIN`：链路类
- `K_SCALING`：集群迁移窗口（MultiPublish 常见）
- `K_OUT_OF_MEMORY` / `K_NO_SPACE` / `K_IO_ERROR`：资源与持久化

客户端写日志关键词：
- `Start to send rpc to publish object`
- `Send Publish request error`
- `Send multi publish request error`

---

## 4. 写接口关联 Worker 日志（重点）

关键关键词：
- `ValidateWorkerState ...` 失败
- `Authenticate failed.`
- `Publish failed`
- `Fail to create all the objects on master`
- `The cluster is scaling, please try again.`
- `Multiple set fails to save object ... to l2cache.`

`K_SCALING` 证据：

```559:565:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/worker/object_cache/service/worker_oc_service_multi_publish_impl.cpp
        if (rsp.meta_is_moving()) {
            ...
            continue;
        }
        return Status(K_SCALING, "The cluster is scaling, please try again.");
```

---

## 5. 写接口排查树（先 SDK 后 Worker）

1. SDK 返回码分桶
- `K_INVALID`：查参数约束（数量、重复、空值、Tx 限制）
- `K_SCALING`：优先判扩缩容窗口是否预期
- `K_RPC_*`：链路/超时路径
- `K_OUT_OF_MEMORY` / `K_NO_SPACE` / `K_IO_ERROR`：资源与存储路径

2. 对齐 Worker 日志（同时间窗）
- **无写入口日志**：请求未到 Worker，偏网络/前置连接
- **有入口但 master 交互失败**：偏控制面与元数据阶段
- **有 L2 持久化失败**：可靠性降级，业务可能不中断

3. 路径细分
- SHM/UB 路径故障：联动 `sdk-init-定位定界.md` 的 fd/mmap/UB 章节
- MultiPublish `K_SCALING`：结合扩缩容窗口与 etcd 状态

---

## 6. 责任边界与模块落点

- L0（集成方）：写入参数和调用模式问题
- L1（平台与网络）：1002/reset、mmap/fd、磁盘/IO 资源
- L2（三方件）：etcd 控制面、二级存储性能与可用性
- L3（数据系统）：写入状态机、2PC/meta moving、重试和降级策略

L3（数据系统）优先模块：
- `worker_oc_service_publish_impl`
- `worker_oc_service_multi_publish_impl`
- `ClientWorkerRemoteApi::Publish/MultiPublish`

---

## 7. UB 链路故障专项（写）

## 7.1 典型信号
- SDK：
  - `K_RPC_UNAVAILABLE` / `K_RPC_DEADLINE_EXCEEDED`（publish/multi publish 阶段）
  - 与 UB 相关的发送/缓冲失败（可能表现为重试后失败）
- Worker：
  - 多对象写阶段出现 `Fail to create all the objects on master` 后伴随链路错误
  - 迁移/复制相关出现 OOM 或 URMA 读写失败（扩展日志）

## 7.2 关键代码证据
- 客户端写重试集合包含 `K_RPC_UNAVAILABLE`、`K_OUT_OF_MEMORY`、`K_SCALING`：
  - `ClientWorkerRemoteApi::MultiPublish`
- Worker 在 moving 场景会明确返回 `K_SCALING`（不是链路错误）：
  - `worker_oc_service_multi_publish_impl.cpp` `RetryCreateMultiMetaWhenMoving`

## 7.3 链路排查步骤（执行顺序）
1. 先分“控制面失败”与“迁移窗口”：
   - 若 `K_SCALING`，先判扩缩容窗口，不要误判 UB 故障。
2. 若 `K_RPC_*`：
   - 查入口 Worker 是否有 Publish/MultiPublish 入口日志。
   - 有入口则看 master 交互是否失败、是否有 meta moving、是否有 L2 落盘失败。
3. 若怀疑 UB 数据面：
   - 对齐远端 Worker 数据搬移日志与同时间窗网络指标。
4. 判断是否触发了降级（UB -> TCP）以及是否恢复成功。

## 7.4 定界结论规则
- 仅 UB 不稳但写最终成功：性能退化，记录为降级事件。
- UB 与 TCP 都失败且无入口日志：L1（平台与网络）优先。
- 入口正常但 Worker 内部 moving/master 链失败：L3（数据系统）/L2（三方件）优先。

---

## 8. TCP 链路故障专项（写）

## 8.1 典型信号
- SDK：`Send Publish request error` / `Send multi publish request error` + `K_RPC_UNAVAILABLE`/1001
- Worker：可能无对应入口日志，或入口后 master RPC 失败并回传

## 8.2 Worker 日志判据（强相关）
- 有 `Authenticate failed.`：认证链问题（L0（集成方）+L3（数据系统））
- 有 `Fail to create all the objects on master`：控制面/元数据阶段失败
- 有 `ValidateWorkerState ... failed`：worker 状态不满足（非纯网络）
- 无写入口日志：请求未到达，优先链路/连接

## 8.3 链路排查步骤（执行顺序）
1. 从 SDK 错误码入手（1002/1001/19）。
2. 在入口 Worker 查 Publish/MultiPublish 同时间窗日志。
3. 分叉：
   - 无入口：网络、端口、连接复用、容器网络。
   - 有入口：看 Worker 内部是鉴权失败、状态失败、master 交互失败还是 moving。
4. 若是 master 交互失败，再查 etcd/master 可用性与时延。
5. 结合写路径分段时延，判断慢在入口 RPC 还是控制面元数据提交。

## 8.4 定界结论规则
- SDK 1002 + Worker无入口：L1（平台与网络）优先。
- SDK 1002 + Worker有入口且内部 master/moving 异常：L3（数据系统）/L2（三方件）优先。

---

## 9. 数据系统内部问题专项（写）

## 9.1 常见内部问题信号
- `The cluster is scaling, please try again.`（`K_SCALING`）
- `Fail to create all the objects on master`（元数据提交链）
- `Multiple set fails to save object ... to l2cache.`（落盘路径问题）
- `Publish failed`（写主流程失败）

## 9.2 快速定位到模块
- 单写：`worker_oc_service_publish_impl.cpp`
- 批写：`worker_oc_service_multi_publish_impl.cpp`
- SDK 侧重试：`ClientWorkerRemoteApi::Publish/MultiPublish`

## 9.3 建议输出的自证信息
- keys 数量、失败 keys、重试次数、是否 `meta_is_moving`
- 入口 Worker 与 master 地址、超时与错误码
- L2（本地二级存储）落盘是否失败、是否降级运行

---

## 10. 写接口定界表格（错误码 + 定界话术）

| 场景信号 | 首选证据（SDK + Worker） | 初判责任域 | 数据系统内优先模块 |
|------|------------------|------------|---------------------|
| SDK `K_INVALID` | keys/vals 输入、重复 key、Tx 约束 | L0（集成方） | `ObjectClientImpl::MSet` 参数校验 |
| SDK `K_SCALING` | Worker `The cluster is scaling, please try again.` | L3（数据系统）/L2（三方件）（迁移控制面） | `worker_oc_service_multi_publish_impl` |
| SDK `K_RPC_UNAVAILABLE(1002)` 且 Worker 无写入口 | SDK 错误 + Worker 无 Publish/MultiPublish 日志 | L1（平台与网络） | `ClientWorkerRemoteApi::Publish/MultiPublish` |
| SDK `K_RPC_UNAVAILABLE(1002)` 且 Worker 有入口 | Worker `Fail to create all the objects on master` / 状态失败 | L3（数据系统）/L2（三方件）（写处理链+控制面） | `worker_oc_service_multi_publish_impl` |
| 写成功但出现 UB 降级或重试放大 | SDK 重试日志 + 分段时延上升 | 性能退化，非功能故障 | SDK 重试策略 + Worker 写路径 |
| `K_IO_ERROR` / `K_NO_SPACE` + L2 落盘失败日志 | `Multiple set fails to save object ... to l2cache.` | L1（平台与网络）（存储资源）+ L3（数据系统）（落盘链） | `publish_impl` / `eviction` |

## 10.1 写接口定界话术模板（可直接复用）

- **网络/连接侧（L1（平台与网络））**  
  “本次写请求 SDK 返回 `K_RPC_UNAVAILABLE(1002)`，同时间窗入口 Worker 无 Publish/MultiPublish 入口日志，优先定界为网络/连接前置问题，数据系统侧提供请求时间窗与空入口证据。”

- **迁移窗口（L3（数据系统）/L2（三方件））**  
  “写请求返回 `K_SCALING`，Worker 侧有 `The cluster is scaling, please try again.` 明确日志，属于扩缩容迁移窗口语义，不按普通链路故障定性。”

- **数据系统写链问题（L3（数据系统））**  
  “请求已进入 Worker，且出现 `Fail to create all the objects on master` / `Publish failed`，故优先定界在数据系统写处理链，再细分到 master 交互或对象状态机阶段。”

- **存储可靠性降级（L1（平台与网络）+L3（数据系统））**  
  “写路径出现 `K_IO_ERROR/K_NO_SPACE` 并伴随 `...save object ... to l2cache` 失败日志，功能可能降级但业务不中断，需按存储资源与落盘链联合处理。”

