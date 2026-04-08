# 热点清单（Client 专项范围）

> **范围**：仅 `src/datasystem/client/**` 与 **client 通过链接/调用必然进入** 的本仓代码（etcd、gRPC 封装、ZMQ 相关 common）。**三方侧只盯 `libdatasystem.so` 依赖且 client 会调到的库**，并查其中的 **lock + IO/阻塞** 形态（见 `05` §1.1）。**client 侧可确认的三方入口文件列表**：`07_client_third_party_call_sites.md`。不包含 worker/master 热点。

## Client（`src/datasystem/client`）

- `mmap_manager.cpp`
  - `LookupUnitsAndMmapFds`：锁内 fd 获取与 mmap（P0）
- `object_cache/device/comm_factory.cpp`
  - `CreateCommInRecv` / `ProcessCommCreationInSend`：锁内 root-info RPC（P0）
- `object_cache/object_client_impl.cpp`
  - `GIncreaseRef` / `GDecreaseRef`：锁内 worker RPC（P1）
  - 节点切换链路锁范围偏大（P1）
- `listen_worker.cpp`
  - 回调容器锁下执行回调/等待（P1）
- `router_client.cpp`
  - 锁内重日志与字符串构造（P2）
- `service_discovery.cpp`
  - 通过 `EtcdStore` 走 etcd/gRPC；与 `common/kvstore/etcd` 热点同属一条调用链（见下节）
- `client_worker_common_api.cpp`
  - `exclusive_conn_mgr`：ZMQ 独占连接与路径配置（P1，阻塞点在 ZMQ/socket）
- `stream_cache/client_worker_api.cpp`
  - `zmq_rpc_generator` 生成路径上的 RPC 发送（P1）

## Common（仅 client 调用图可达）

- `src/datasystem/common/kvstore/etcd/etcd_store.cpp`
  - 多方法共享锁跨 `SendRpc` / `txn.Commit`（P0）
- `src/datasystem/common/kvstore/etcd/grpc_session.cpp` 及 `etcd_watch.cpp`、`etcd_keep_alive.cpp` 等
  - gRPC 异步/流式路径上的锁与 `CompletionQueue` 交互（P1，需对照 gRPC 源码行为）
- `src/datasystem/common/rpc/zmq/`（由 `exclusive_conn_mgr`、`zmq_rpc_generator` 引入）
  - 锁是否跨越 `zmq_*` 或 connect/bind（P1）

## Third-party / 外部库（依赖 + 调用；查 lock + IO）

- **gRPC C++**（`build/_deps/grpc-src`）：仅沿 etcd/`grpc_session` **入口**向下；找 **mutex 内网络/epoll/SSL 读写** 或与 **CQ 等待** 叠锁（P1）。
- **libzmq**（`zeromq-src`）：仅沿 ZMQ 封装 **入口**；找 **socket/engine 锁内 send/recv/poll**（P1）。
- **OpenSSL**：随 TLS 路径进入时；找 **锁内 IO**（握手/读写）（P2，常与 gRPC 同路径）。
- **protobuf**：默认 CPU 序列化；仅当 **持业务锁** 且大拷贝/与日志 IO 绑定时升格（P2）。
- **spdlog / TBB / absl 等**：仅当热点栈或本仓代码证明 **在关键路径持锁进入** 时，按 lock+IO 抽查（P2）。

本专项**不包含** brpc；`libdatasystem.so` 亦不链接 brpc。
