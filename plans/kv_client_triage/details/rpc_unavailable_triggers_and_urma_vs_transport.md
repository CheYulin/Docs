# K_RPC_UNAVAILABLE (1002) 常见触发与「URMA 瞬时失效」怎么区分

面向：Playbook 里 **1002** 与 **1004/1006/1008** 混在一起的排障场景。

---

## 1. 先分清两层：传输 RPC vs URMA 数据面

在 **datasystem 状态码**里（`include/datasystem/utils/status.h`）：

| 码 | 含义（粗分） |
|----|----------------|
| **1002 `K_RPC_UNAVAILABLE`** | **RPC/消息通道不可用或未在时限内就绪**：ZMQ 连接、等待对端、网关转发失败、部分 **socket 错误** 等（见下文 Cases） |
| **1004 `K_URMA_ERROR`** | URMA/UB **数据路径**错误（驱动/资源/语义失败等，依实现而定） |
| **1006 `K_URMA_NEED_CONNECT`** | URMA **会话需重建/重连**（常与切流、建链窗口相关） |
| **1008 `K_URMA_TRY_AGAIN`** | URMA **瞬时/可重试**类失败（实现侧约定） |

**结论**：**「URMA 瞬时失效」在码表上优先看 1008（及 1006/1004），而不是默认当成 1002。**  
若你**只**看到 1002，往往说明失败被 **归类在 ZMQ/TCP 传输层**或 **被映射成 UNAVAILABLE**（见 §3），**不能**从码上直接等价成「UB 坏了」。

---

## 2. 客户端路径上：哪些 Cases 会打出 K_RPC_UNAVAILABLE（有代码依据）

下列为 **仓库内直接 `K_RPC_UNAVAILABLE` / `StatusCode::K_RPC_UNAVAILABLE`** 且与 **Client→Worker 常见链路**相关的典型来源（**非穷举** Master/etcd/stream 等）。

### 2.1 ZMQ：对端长时间无响应，`K_TRY_AGAIN` 被改成 1002

阻塞收包时若底层是 `K_TRY_AGAIN`，`ClientReceiveMsg` 会 **改写**为 `K_RPC_UNAVAILABLE`，并在 `respMsg` 里带 **“has not responded within the allowed time”**：

```881:893:src/datasystem/common/rpc/zmq/zmq_msg_queue.h
    Status ClientReceiveMsg(R &ele, ZmqRecvFlags flags)
    {
        Status rc = ReceiveMsg(ele, flags);
        if (rc.GetCode() == K_TRY_AGAIN) {
            if (flags == ZmqRecvFlags::DONTWAIT) {
                return rc;
            }
            rc = Status(StatusCode::K_RPC_UNAVAILABLE,
                        FormatString("Rpc service for client %s has not responded within the allowed time. Detail: %s",
                                     GetId(), rc.ToString()));
        }
        return rc;
    }
```

**含义**：**1002 可能是「等回复超时」**，根因可能是 Worker 慢、丢包、断连、或后端队列卡住，**单看码无法区分**。

### 2.2 ZMQ：建连等待超时 / 对端在时限内不可用

```1504:1510:src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp
    auto success = wp_.WaitFor(timeout);
    CHECK_FAIL_RETURN_STATUS_PRINT_ERROR(success, K_RPC_UNAVAILABLE, "Timeout waiting for SockConnEntry wait");
    if (!connInProgress_) {
        return connectRc_;
    }
    RETURN_STATUS(K_RPC_UNAVAILABLE, FormatString("Remote service is not available within allowable %d ms", timeout));
```

### 2.3 ZMQ：网关/Frontend 处理失败，统一报「service unavailable」

```220:228:src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp
    Status rc = func(cInfo, meta, frames);
    if (rc.IsError()) {
        // ...
        RETURN_IF_NOT_OK(ZmqBaseStubConn::ReportErrorToClient(
            meta.client_id(), meta, K_RPC_UNAVAILABLE, FormatString("The service is currently unavailable! %s", msg),
            backendMgr_));
```

### 2.4 ZMQ：心跳发送时无 `POLLOUT` → “Network unreachable”

```268:270:src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp
    unsigned int events = static_cast<unsigned int>(frontend_->Get(sockopt::ZmqEvents, 0));
    CHECK_FAIL_RETURN_STATUS(events & ZMQ_POLLOUT, K_RPC_UNAVAILABLE, "Network unreachable");
```

### 2.5 UDS/TCP 辅助：`UnixSockFd` 连接被 reset 等

```61:61:src/datasystem/common/rpc/unix_sock_fd.cpp
        RETURN_STATUS(StatusCode::K_RPC_UNAVAILABLE, FormatString("Connect reset. fd %d. err %s", fd, StrErr(err)));
```

### 2.6 Client↔Worker：必须走 SHM/UDS 传 fd 却建失败

```301:303:src/datasystem/client/client_worker_common_api.cpp
    if (mustUds && !isConnectSuccess) {
        return { StatusCode::K_RPC_UNAVAILABLE, "Can not create connection to worker for shm fd transfer." };
    }
```

### 2.7 重试策略里的 1002

`RegisterClient` / `GetSocketPath` / `Get` 等使用的 `RetryOnError` **把 1002 列入可重试码**（与 1001、1000 等并列），说明 **1002 被当作「可恢复的通道类问题」**，仍**不**说明根因是 URMA 还是 TCP。

---

## 3. 为何「URMA 瞬时」不好判断？

1. **码不同层**：UB/URMA 问题若仍在 **Worker 业务层**处理，可能返回 **1004/1006/1008**；若失败发生在 **ZMQ 收发包、建连、等待响应**，客户端更容易看到 **1002** 或 **1001**。  
2. **1002 吞掉 TRY_AGAIN 语义**：见 §2.1，**同一类「没等到包」**在阻塞模式下直接显示为 UNAVAILABLE，`respMsg` 里的 **Detail** 才带原始信息。  
3. **access log 只有 code + 短 msg**：没有「子类型」字段，**必须**结合 `respMsg` 全文、Worker 侧日志、时间线、是否 UB 路径、基础设施指标。

---

## 4. 实操上怎么区分（建议顺序）

1. **看码**：若存在 **1008 / 1006 / 1004**，优先按 **URMA 专题**（Playbook 1004/1006/1008 行 + Worker URMA 日志）处理，**不要**先当普通断网。  
2. **看 `respMsg` 关键词**（`Status::GetMsg()` / access log 最后一列）：  
   - `has not responded within the allowed time` → §2.1 类 **等回复超时**  
   - `Remote service is not available within allowable` / `Timeout waiting for SockConnEntry` → §2.2 **建连/就绪**  
   - `Network unreachable`（ZMQ POLLOUT）→ §2.4 **本机 socket 不可写**  
   - `Can not create connection to worker for shm fd transfer` → §2.6 **SHM/UDS 强制路径失败**  
   - `The service is currently unavailable` → §2.3 **网关/后端处理失败**（需对 Worker/网关日志）  
3. **看路径**：当前请求是否 **走 UB 读**（`Get` + URMA buffer）还是纯 ZMQ payload；UB 路径失败更常先体现为 **1004/1008**（仍取决于实现分支）。  
4. **看 Worker 同时间点**：`DS_POSIX_GET` / UB 相关日志、是否 **TCP 降级**、是否 **K_URMA_NEED_CONNECT** 重试成功。  
5. **仍糊**：用你们已有的 **bpftrace / strace / 网卡与 UB 端口指标** 做时间关联（见 `workspace/observability`、`tech-research/bpftrace` 与 lock-io 专题）；**单靠 1002 无法定界到「URMA 瞬时」**。

---

## 5. 与 Playbook 的对应

- Playbook **1002** 行写「连接不可用、断连、对端拒绝」——与 **§2** 一致，但应理解 **1002 内部是多 Case 桶**。  
- **URMA 瞬时**优先用 **1008**（及上下文 **1006**）在 Playbook 中单独跟进；**不要把 1002 默认当成 UB 抖动**。

---

## 6. 修订记录

- 初版：基于 `zmq_msg_queue.h`、`zmq_stub_conn.cpp`、`unix_sock_fd.cpp`、`client_worker_common_api.cpp` 中与 1002 直接相关的返回点整理；Master/etcd/stream 侧另有多处 1002，集成方若直连需单独扩展表。
