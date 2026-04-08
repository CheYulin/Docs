# 实施计划与工作量评估（Client 专项）

> **范围**：仅 `client/` 与 client 可达的 `common/kvstore/etcd`、`common/rpc/zmq` 相关改造。不含 worker/master。方法说明见 `05_client_scope_strace_and_third_party.md`。

## 阶段 A（P0，先止血）

范围：

- `client/mmap_manager.cpp`
- `client/object_cache/device/comm_factory.cpp`
- `common/kvstore/etcd/etcd_store.cpp`

目标：消除上述路径上锁内 RPC / mmap / etcd 事务与网络提交的主耦合。

工作量：预计 **8~12 人日**（含 client 相关单测/ST + strace 对比）。

## 阶段 B（P1，主链路收敛）

范围：

- `client/object_cache/object_client_impl.cpp` 引用计数 RPC 路径
- `client/listen_worker.cpp`
- `client/client_worker_common_api.cpp`、`stream_cache/client_worker_api.cpp` 与 ZMQ 下层
- `common/kvstore/etcd/etcd_watch.cpp`、`etcd_keep_alive.cpp`、`grpc_session.cpp` 等与 gRPC 的锁边界

目标：缩短锁持有时长，避免锁内进入 ZMQ/gRPC 阻塞面。

工作量：预计 **10~16 人日**

## 阶段 C（P2，稳定性与可观测）

范围：

- client 锁内日志外移与降采样
- client 侧慢 RPC、锁等待相关指标（按需）
- 每阶段复跑 `trace_kv_lock_io.sh`，对比主进程侧 `futex`/`epoll_wait`/`poll` 趋势

工作量：预计 **4~8 人日**

## 总体工期估算（Client 专项）

- 总计：**22~36 人日**
- 并行：2 人约 **2~4 周** 可完成主闭环（视回归范围而定）

## 验收标准（Client 专项）

1. 功能：client/kv 相关用例与约定的 ST 全绿。
2. 性能：client 侧 set/get 或约定基准 p95/p99 不明显回退。
3. 证据：改造前后各跑一轮 strace 汇总，并保留 `05` 方法 B 中列出的调用链审计记录（etcd/ZMQ/gRPC 边界）。

## 关键改造模板（统一）

1. 锁内：最小快照 + 版本号。
2. 锁外：RPC/IO/回调/等待。
3. 回写：短锁 + 版本校验。

## 风险与回滚

- 风险：解锁后状态竞争。  
- 缓解：版本号/epoch、失败重试、特性开关。  
- 回滚：按模块开关，优先保留 P0 结构性改造可回退路径。

