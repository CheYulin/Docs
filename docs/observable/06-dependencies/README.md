# 06 · 外部依赖与三方件

KV Client 与 Worker 依赖四类外部 / 关键子系统，本目录集中放它们的 **错误语义、接口清单、日志证据与定位方法**。

| 依赖 | 职责 | 文档 |
|------|------|------|
| **URMA / UMDK** | 跨节点零拷贝数据面（UB）；`urma_*` C API | [urma.md](urma.md) |
| **OS syscall** | socket / mmap / fd 传递（SCM_RIGHTS）/ 文件 I/O | [os-syscalls.md](os-syscalls.md) |
| **etcd** | 控制面：租约、成员、hash ring、watch | [etcd.md](etcd.md) |
| **二级存储** | 持久化 / L2 缓存（SFS / OBS） | [secondary-storage.md](secondary-storage.md) |

## 与 reliability 的关系

- 故障如何被**感知**（日志、监控、metrics）→ 本目录
- 故障的**代码证据**（错误码映射、重连路径、状态机）→ [`../../reliability/04-fault-tree.md`](../../reliability/04-fault-tree.md)
- etcd 隔离 / 恢复的**深度分析**（`node_timeout_s` vs `node_dead_timeout_s` / Path 1 vs Path 2）→ [`../../reliability/deep-dives/etcd-isolation-and-recovery.md`](../../reliability/deep-dives/etcd-isolation-and-recovery.md)
