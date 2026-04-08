# Client 侧会实际触达的三方库：入口文件与调用链（lock+IO 审计用）

> 范围：`src/datasystem/client/**` 中 **能确认** 引入或经一层本仓封装即进入三方实现的入口。  
> 用途：与 `ldd libdatasystem.so`（`scripts/build/list_client_third_party_deps.sh`）对齐，避免扫无关 vendor；审阅时只看 **依赖 ∩ 这些入口可达** 的三方代码路径中的 **lock + IO**（见 `05` §1.1）。

---

## 1. gRPC / etcd API（`libgrpc++` / `libgrpc` / `libgpr`）

**Client 直接入口（仅通过 `EtcdStore`，无 `grpc::` 直写在 client `.cpp` 中）：**

| 文件 | 行为 |
|------|------|
| `client/service_discovery.cpp` | `#include etcd_store.h`，`make_shared<EtcdStore>(...)`，后续经 `EtcdStore` 调 etcd |
| `client/router_client.cpp` | 同上 |

**本仓向下进入三方：**  
`common/kvstore/etcd/etcd_store.cpp`、`grpc_session.cpp`、`etcd_watch.cpp`、`etcd_keep_alive.cpp`、`etcd_health.cpp`、`etcd_elector.cpp` — 内部使用 `grpc::` / `grpcpp`。  
**OpenSSL**：若 etcd 为 TLS，通常随 **gRPC 安全通道** 进入 `libssl`/`libcrypto`，client 源码中 **无** 直接 `SSL_*` 引用。

---

## 2. ZeroMQ（`libzmq`）

**Client 侧入口：**

| 文件 | 行为 |
|------|------|
| `client/client_worker_common_api.cpp` | `#include common/rpc/zmq/exclusive_conn_mgr.h`；`RpcChannel`；`exclusive_conn_sockpath` 等独占连接与注册 RPC |
| `client/object_cache/client_worker_api/client_worker_remote_api.cpp` | `std::make_shared<RpcChannel>(...)`，远端 worker 通道 |
| `client/stream_cache/client_worker_api.cpp` | `#include zmq_rpc_generator.h`；`RpcChannel` |
| `client/perf_client/perf_client_worker_api.cpp` | `RpcChannel`（perf 用例） |

**说明：**  
`RpcChannel`（`common/rpc/rpc_channel.{h,cpp}`）主要持有 **ZMQ endpoint 字符串** 与路由配置；**实际 `zmq_*` 发送/接收、epoll 等**在 `common/rpc/zmq/*`（如 `zmq_socket`、`zmq_stub`、`zmq_epoll`）及 **生成桩**（`*stub.rpc.pb.*`）中。client 通过 **worker/stream 的 API + 生成代码** 进入上述路径。

---

## 3. Protobuf（`libprotobuf`）

**Client 大量通过生成的 `*.pb.h` / `*.stub.rpc.pb.h` / `*.service.rpc.pb.h` 使用运行时：**

典型文件（不完整列举，覆盖主链路）：

- `client/client_worker_common_api.{h,cpp}` — `share_memory.stub.rpc.pb` 等
- `client/object_cache/object_client_impl.{h,cpp}` — `object_posix`、`meta_transport`、`utils` 等
- `client/object_cache/client_worker_api/*` — `object_posix`、`master_object`、`p2p_subscribe` 等
- `client/stream_cache/*` — `worker_stream`、`stream_posix`、`rpc_option` 等
- `client/service_discovery.cpp` / `router_client.cpp` — `hash_ring.pb.h`
- `client/perf_client/*` — `perf_posix.stub.rpc.pb.h`

**lock+IO 关注点：** 序列化多为 CPU；若在 **持业务锁** 下做 **大 message 序列化/拷贝** 或与 **日志写盘** 叠在一起，再标 P2。

---

## 4. oneTBB（`libtbb`）

**Client 直接使用 `tbb::concurrent_hash_map` 等：**

- `client/object_cache/object_client_impl.h` — `TbbGlobalRefTable`、`P2PPeerTable`
- `client/object_cache/client_memory_ref_table.h`
- `client/object_cache/device/client_device_object_manager.{h,cpp}`、`comm_factory.h`、`p2p_subscribe.h`、`hccl_comm_magr.h`
- `client/client_worker_common_api.cpp` — 一处 `concurrent_hash_map` 相关逻辑

**lock+IO 关注点：** TBB 并发容器自身有同步；需看 **在 accessor 持有期间** 是否调用 **RPC / ZMQ / 可能阻塞** 的路径（与 `GIncreaseRef` 等热点叠加）。

---

## 5. spdlog（`libds-spdlog`）

**Client 侧：** 普遍通过 `LOG(INFO/WARNING/...)`（见 `client_worker_common_api.h`、`client_state_manager.h` 等），底层为工程封装的 **ds-spdlog**。  
**lock+IO 关注点：** 异步/同步策略与 **持锁打日志**（见专项 P2）。

---

## 6. Huawei Secure C（`libsecurec`）

**Client 直接调用：**

- `client/object_cache/device/comm_factory.cpp` — `memcpy_s`
- `client/object_cache/client_worker_api/client_worker_base_api.cpp` — `memcpy_s`
- `client/stream_cache/producer_impl.cpp` — `#include <securec.h>`

**lock+IO 关注点：** 一般为内存拷贝，**非 IO**；除非与 **大块拷贝 + 持锁 + 相邻 RPC** 同一临界区。

---

## 7. 依赖在 ldd 中但 client 源码未见直接 API 的项

以下多为 **传递依赖** 或 **经 gRPC/其它库间接使用**，client 目录内 **无** 直接 `#include` / 符号调用；审阅 **lock+IO** 时从 **§1 gRPC / §2 ZMQ** 向下跟即可覆盖主风险：

- **Abseil**（`libabseil_dll`）：gRPC/protobuf 内部使用为主。  
- **zlib**（`libz`）：多为 HTTP/压缩等传递路径。  
- **etcdapi_proto / rpc_option_protos 等**：本仓生成库，非第三方；protobuf 运行时仍落 §3。

---

## 8. 与专项文档的索引

- 方法论、ldd 收敛：`05_client_scope_strace_and_third_party.md` §1.1、§3。  
- 热点清单：`02_hotspot_inventory.md`。  
- 本文件：**按源码确认的「client → 三方」入口清单**，用于精读 `build/_deps/*-src` 时裁剪范围。

---

## 9. thread_local / TLS 风险标识（client 路径）

下列是当前在 client 侧可见、且可能影响 lock+IO 结论稳定性的 TLS 使用点：

### 9.1 全局 thread_local 变量（`common/util/thread_local.*`）— **中风险**

定义（进程级、按线程隔离）：

- `reqTimeoutDuration` / `timeoutDuration` / `scTimeoutDuration`
- `g_ContextTenantId`
- `g_SerializedMessage`
- `g_ReqAk` / `g_ReqSignature` / `g_ReqTimestamp`

client 路径高频读写：

- `client/context/context.cpp`：`Context::SetTenantId()` 写 `g_ContextTenantId`
- `client/client_worker_common_api.h`：`SetTenantId()` 直接读 `g_ContextTenantId`
- `client/object_cache/object_client_impl.cpp`、`stream_client_impl.cpp`、`embedded_mmap_table_entry.cpp`：读 `g_ContextTenantId`
- `client/*worker_api*.cpp`：大量 `reqTimeoutDuration.Init(...)`

风险说明：

- 在线程池/复用线程模型下，TLS 状态可能“跨请求残留”；若未显式 reset，可能出现 **租户上下文串用** 或 timeout 语义漂移（尤其是共享 worker thread 时）。
- `reqTimeoutDuration` 依赖“每次调用前显式 Init”；遗漏初始化会导致剩余时间计算受上次调用污染。

建议：

- 为 `Context` 增加明确的 `ClearTenantId()/ScopedTenantContext`（RAII）并在请求边界强制恢复。
- 对关键 RPC 路径在入口处统一 `Init` timeout，避免分散在深层函数“靠约定”初始化。

### 9.2 ZMQ 独占连接管理器 TLS（`gExclusiveConnMgr`）— **中高风险**

定义：

- `common/rpc/zmq/exclusive_conn_mgr.cpp`：`thread_local ExclusiveConnMgr gExclusiveConnMgr`

client 调用：

- `client/client_worker_common_api.cpp`：关闭独占连接时访问 `gExclusiveConnMgr`

风险说明：

- 连接池/decoder/encoder 是 **按线程持有**；若业务线程与回收线程不一致，可能出现“在线程 A 创建、在线程 B 清理不到位”的生命周期偏差，带来 fd/连接残留或行为不一致风险。

建议：

- 为独占连接增加“按 clientId 全局可观测的清理入口”与诊断计数（创建数/关闭数/线程维度）。
- 在 client shutdown / reconnect 关键路径增加线程一致性与兜底清理。

### 9.3 代码内已出现 TLS 依赖提示（证据）

- `client/stream_cache/producer_consumer_worker_api.cpp` 有注释：  
  “we still need to set this thread_local variable.”

说明：该路径已显式承认业务语义受 TLS 变量约束，属于需要规范化治理的信号。
