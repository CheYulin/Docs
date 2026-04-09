# Sheet3：TCP / RPC（ZMQ + UDS）侧对照

> 与 Excel **`Sheet3_TCP_RPC`** 一致。说明：客户端到 Worker **控制面**主要为 **ZMQ + Unix socket**；**etcd** 使用 **gRPC**（`grpc_session.h`），**不属于 KV Client 热路径**，故本 Sheet 聚焦 **Object Cache 客户端链路**。

## 1. 层次与典型失败

| 层次 | 语义 | 典型 Status | 典型消息 | errno 说明 |
|------|------|-------------|----------|------------|
| ZMQ RPC | `Get`/`Publish`/`RegisterClient` | `1002`/`1001`/`1000`/`19` | `The service is currently unavailable`; `deadline exceeded`; `Connect reset` | 部分错误经 `UnixSockFd::ErrnoToStatus` 从 **POSIX errno** 映射 |
| UDS | SHM fd 传递 | `1002`/`K_RUNTIME_ERROR` | `Can not create connection to worker for shm fd transfer`; `Receive fd ... failed` | `ECONNRESET`/`EPIPE` 等 |
| TCP payload 回退 | UB 不可用 | 常仍为 OK | `fallback to TCP/IP payload` | 非 errno：性能退化信号 |

## 2. 代码证据（etcd gRPC 与客户端 ZMQ 分离）

**etcd** 同步 RPC 包装（对比理解；KV 客户端不走此路径）：

```250:256:/home/t14s/workspace/git-repos/yuanrong-datasystem/src/datasystem/common/kvstore/etcd/grpc_session.h
            if (!status.ok()) {
                ...
                    RETURN_STATUS(K_RPC_UNAVAILABLE, preMsg + "Send rpc failed: (" + std::to_string(returnCode) + ") "
                                                         + status.error_message());
```

**KV 读路径** 客户端侧重试集合（示例）：

见 `docs/observable/kv-client-读接口-定位定界.md` 中 `ClientWorkerRemoteApi::Get` 的 `RetryOnError` 引用（`1002`/`1001`/`19` 等）。

## 3. 评审注意

- **不要把 gRPC 的 `(error_code)` 与 URMA 的 `urma_status_t` 混为同一列**：二者来源不同。  
- **bonding / 多网口** 对 **TCP** 的影响体现在 **路由、源地址、防火墙、连接重置**；对 **UB** 的影响体现在 **`urma_get_device_list` / 设备名 / EID**（见 Sheet2）。
