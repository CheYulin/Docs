# K_SCALING、K_SCALE_DOWN：客户端是否感知（代码推导）

对应 Playbook：[KV_CLIENT_TRIAGE_PLAYBOOK.md](../KV_CLIENT_TRIAGE_PLAYBOOK.md) 第 4.2 节表中 **31 / 32** 行。

---

## 1. 结论摘要（先看这个）

| 码 | 客户端能否收到 | 典型入口 | 客户端是否按该码自动重试 |
|----|----------------|----------|---------------------------|
| **K_SCALE_DOWN (31)** | **能**（显式 RPC 返回） | `HealthCheck`：Worker 判定本节点正在退出 | **否**（单次 `stub_->HealthCheck`，无 `RetryOnError`） |
| **K_SCALE_DOWN** | **能**（若走迁移 RPC） | `MigrateDataDirect` 等迁移路径上 Worker 返回 | 视调用方是否包 `RetryOnError`；默认 `RETRY_ERROR_CODE` **不含** `K_SCALE_DOWN` |
| **K_SCALING (32)** | **分路径** | Worker **MultiPublish / 元数据 2PC** 相关：`CreateMultiMeta*` 在 `meta_is_moving` 退出循环后返回 | **仅 MultiPublish** 在 `client_worker_remote_api` 里把 `K_SCALING` 列入重试码；**Get/Publish/Create 等默认 `RETRY_ERROR_CODE` 不含 `K_SCALING`** |
| **K_SCALING** | **Get 批量语义下易「怪」** | 若 Worker 把 **32** 放进 **`GetRspPb.last_rc`** 而非 RPC 层失败 | 客户端 `Get` 的 `RetryOnError` **只对** `IsRpcTimeoutOrTryAgain`（含 `K_TRY_AGAIN`）及部分 **OOM** 触发重试；**`K_SCALING` 不在其中**，lambda 对 `last_rc==K_SCALING` 会 **返回 OK** 结束重试，**顶层 `Get()` 仍可能返回 `Status::OK()`**，错误落在 **响应 PB 各 object 状态** —— 与「access log 里看到 32」不一定一致，需看上层是否把 per-object 错误映射成业务失败码 |

因此：**Playbook 把 31/32 当作「客户端最终可见码」在 `HealthCheck`、部分写路径、以及 MultiPublish 重试场景下成立；在 Get 批量路径上 32 可能不体现在顶层 `Status`，运维看 access log 时会觉得「奇怪」。**

---

## 2. 服务端产生位置（证据）

### 2.1 K_SCALE_DOWN

**HealthCheck**（节点退出中）：

```314:333:src/datasystem/worker/object_cache/worker_oc_service_impl.cpp
Status WorkerOCServiceImpl::HealthCheck(const HealthCheckRequestPb &req, HealthCheckReplyPb &resp)
{
    // ...
    if (etcdCM_ != nullptr && etcdCM_->CheckLocalNodeIsExiting()) {
        constexpr int logInterval = 60;
        LOG_EVERY_T(INFO, logInterval) << "[HealthCheck] Worker is exiting now";
        RETURN_STATUS(StatusCode::K_SCALE_DOWN, "Worker is exiting now");
    }
    return Status::OK();
}
```

**迁移缩容**（`MigrateDataDirect` 错误封装示例）：

```185:185:src/datasystem/worker/object_cache/service/worker_oc_service_migrate_impl.cpp
        return PrepareMigrateDataDirectError(req, rsp, StatusCode::K_SCALE_DOWN, "Worker is exiting");
```

### 2.2 K_SCALING

**MultiPublish 元数据 2PC**（Master 侧 `meta_is_moving` 结束后仍非空 info 时返回 32）：

```550:565:src/datasystem/worker/object_cache/service/worker_oc_service_multi_publish_impl.cpp
Status WorkerOcServiceMultiPublishImpl::RetryCreateMultiMetaWhenMoving(...)
{
    while (true) {
        RETURN_IF_NOT_OK(api->CreateMultiMeta(req, rsp, false));
        if (rsp.info().empty()) {
            return Status::OK();
        }
        if (rsp.meta_is_moving()) {
            rsp.Clear();
            std::this_thread::sleep_for(std::chrono::milliseconds(RETRY_INTERNAL_MS_META_MOVING));
            continue;
        }
        return Status(K_SCALING, "The cluster is scaling, please try again.");
    }
```

（`RetryCreateMultiMetaPhaseTwoWhenMoving` 同样返回 `K_SCALING`。）

**说明**：当前在 `worker/object_cache` 下 **grep 不到** `Get` 主路径直接 `return Status(K_SCALING,...)`；32 的**稳定来源**主要是 **MultiPublish 元数据路径**。若线上 Get 相关出现 32，需结合 **是否 per-object `last_rc`** 或 **其它模块/版本** 再查。

---

## 3. 客户端行为（证据）

### 3.1 默认重试集合不含 31/32

```36:38:src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
const std::unordered_set<StatusCode> RETRY_ERROR_CODE{ StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED,
                                                       StatusCode::K_RPC_DEADLINE_EXCEEDED,
                                                       StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_OUT_OF_MEMORY };
```

`Get`、`Create`、`Publish`（除下面特例外）等大量使用 `RETRY_ERROR_CODE`。

### 3.2 Get：仅 `K_TRY_AGAIN` + RPC 超时类 + 特定 OOM 会触发重试

```316:321:src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
            Status recvStatus = Status(static_cast<StatusCode>(rsp.last_rc().error_code()), rsp.last_rc().error_msg());
            if (IsRpcTimeoutOrTryAgain(recvStatus)
                || (recvStatus.GetCode() == StatusCode::K_OUT_OF_MEMORY && IsAllGetFailed(rsp))) {
                return recvStatus;
            }
            return Status::OK();
```

`IsRpcTimeoutOrTryAgain` **仅** `K_TRY_AGAIN` 与 RPC 超时/不可用类：

```46:49:src/datasystem/common/util/rpc_util.h
inline bool IsRpcTimeoutOrTryAgain(const Status &status)
{
    return status.GetCode() == StatusCode::K_TRY_AGAIN || IsRpcTimeout(status);
}
```

故 **`last_rc == K_SCALING` 时**：不进入重试分支，lambda 返回 **OK**，`RetryOnError` 结束，随后 `Get()` 末尾 **`return Status::OK()`**（在 `stub_->Get` 本身成功的前提下）。**顶层 Status 不一定为 32**。

### 3.3 MultiPublish：显式把 K_SCALING 加入重试

```424:436:src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
        RetryOnError(
            requestTimeoutMs_,
            [this, &req, &rsp, &payloads](int32_t realRpcTimeout) {
                // ...
                return stub_->MultiPublish(opts, req, rsp, payloads);
            },
            []() { return Status::OK(); },
            { StatusCode::K_TRY_AGAIN, StatusCode::K_RPC_CANCELLED, StatusCode::K_RPC_DEADLINE_EXCEEDED,
              StatusCode::K_RPC_UNAVAILABLE, StatusCode::K_OUT_OF_MEMORY, StatusCode::K_SCALING },
            rpcTimeoutMs_),
```

### 3.4 HealthCheck：无 RetryOnError，K_SCALE_DOWN 原样返回

```226:241:src/datasystem/client/object_cache/client_worker_api/client_worker_remote_api.cpp
Status ClientWorkerRemoteApi::HealthCheck(ServerState &state)
{
    // ...
    return stub_->HealthCheck(opts, req, rsp);
}
```

`KVClient::HealthCheck` → `ObjectClientImpl::HealthCheck` → 上述路径，故 **集成方调用 `HealthCheck()` 可直接拿到 31**。

集成测试示例：

```1253:1253:tests/st/client/kv_cache/kv_client_voluntary_scale_down_test.cpp
        ASSERT_EQ(client0_->HealthCheck().GetCode(), StatusCode::K_SCALE_DOWN);
```

---

## 4. 与 Access Log / Playbook 的对应关系

- Access log 的 `code` 来自 **`Status::GetCode()`** 在 KV 路径 `Record` 时的值（见 Playbook §1.3）。
- **`HealthCheck`** 若单独埋点或业务自行打日志，可稳定看到 **31**。
- **`KVClient::Get`** 若在 `object_client_impl` 层把 **整次调用** 标成成功，而 **per-object** 含 32，则 **DS_KV_CLIENT_GET 行可能仍是 0**，与 Playbook **「32｜扩缩容」** 的直观预期可能不一致 —— **需要看 object 级错误是否被汇总成顶层失败**（建议在排障文档中注明）。

---

## 5. 时序图

见同目录 [scaling_scale_down_sequences.puml](./scaling_scale_down_sequences.puml)。图中 **ClientWorkerRemoteApi → Worker** 经 **自研 Worker RPC Stub**（非 brpc）；与 `stub_->HealthCheck` / `MultiPublish` 等代码一致。

---

## 6. 产品语义与集成方建议（扩缩容与用户无关）

**逻辑语义**：扩缩容依赖 **元数据重定向**，对业务侧的目标是 **不中断**；**31 / 32 不是「用户要执行某种操作」的 API 契约**，而是实现与窗口期下仍可能冒头的 **Status / 日志信号**。

| 角色 | 建议 |
|------|------|
| **业务 / 终端用户** | **无需**为 31/32 设计专门业务流程或提示文案；读写应依赖 **幂等、超时、多副本路由**，与常规定义一致。 |
| **集成 / 运维** | **31**：`HealthCheck` 探活命中时，让 **LB / 服务发现** 不再把新请求打到正在退出的节点。**32**：写路径上 SDK 已对 `MultiPublish` **内置重试**；业务侧重在 **超时与幂等**，勿把 32 当容量告警。**Get** 路径上 32 可能只在 **PB `last_rc`**，以 **per-object 状态** 为准。 |
| **文档 / Playbook** | 与 **用户操作建议** 的完整对照表见 [KV_CLIENT_TRIAGE_PLAYBOOK.md](../KV_CLIENT_TRIAGE_PLAYBOOK.md) **§4.3**。 |

**实现侧（可选）**：若希望运维在 access log **稳定**看到 32，需在 **KV 汇总层** 对 `last_rc` 含 `K_SCALING` 时 **提升为顶层 Status** 或 **单独打点**（属产品决策，非当前代码事实）。
