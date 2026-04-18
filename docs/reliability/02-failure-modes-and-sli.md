# 02 · 业务流程、故障模式与 SLI

## 对应代码

本篇是清单型文档（FEMA 表 + SLI 粗算），没有单点代码锚点。关键时间参数定义在：

| 代码位置 | 作用 |
|---------|------|
| `src/datasystem/common/util/gflag/common_gflag_define.cpp` | `node_timeout_s`、`node_dead_timeout_s`、`heartbeat_interval_ms`、`passive_scale_down_ring_recheck_delay_ms` 等 |
| `src/datasystem/common/rpc/rpc_constants.h` | `RPC_MINIMUM_TIMEOUT` 等 RPC 侧常量 |
| `src/datasystem/worker/cluster_manager/etcd_cluster_manager.cpp` | `DemoteTimedOutNode` 等状态机 |

超时参数详细语义见 [deep-dives/timeout-and-latency-budget.md](deep-dives/timeout-and-latency-budget.md)。

---

## 1. 业务流程（11 类）

| 编号 | 场景 |
|---|---|
| 1 | 业务实例部署，本地有 KVCache worker |
| 2 | 业务实例部署，本地无 KVCache worker |
| 3 | KVCache worker 实例部署 |
| 4 | 业务实例本节点 KVCache 命中 |
| 5 | 业务实例本节点未命中，跨节点 worker 读数据 |
| 6 | 业务实例节点无 worker，跨节点读 KVCache |
| 7 | 业务实例扩容 |
| 8 | 业务实例缩容 |
| 9 | KVCache worker 实例扩容 |
| 10 | KVCache worker 实例缩容 |
| 11 | KVCache worker 故障，数据自动恢复 |

---

## 2. 故障模式（53 条）

| 编号 | 类别 | 故障模式 |
|---|---|---|
| 1 | 主机/OS | OS 重启 |
| 2 | 主机/OS | OS Panic |
| 3 | 主机/OS | BMC 强制上下电 |
| 4 | 主机资源 | 主机资源不足（Jetty） |
| 5 | 主机资源 | 主机资源不足（UB 带宽） |
| 6 | 主机资源 | 主机资源不足（CPU） |
| 7 | 主机资源 | 主机资源不足（存储空间） |
| 8 | 主机资源 | 主机资源不足（硬盘 IO 慢） |
| 9 | 主机资源 | 主机内存故障 |
| 10 | 时间 | 时间往前跳变 |
| 11 | 时间 | 时间往后跳变 |
| 12 | 容器 | Client 容器异常退出 |
| 13 | 容器 | Worker 容器异常退出 |
| 14 | 容器 | 容器资源不足（内存 / FD） |
| 15 | 容器 | 容器资源不足（CPU） |
| 16 | 容器 | 容器资源不足（存储空间） |
| 17 | 进程 | UBSE 进程故障 |
| 18 | 进程 | UBM 进程故障 |
| 19 | 进程 | Client 进程异常退出 |
| 20 | 进程 | Worker 进程异常退出 |
| 21 | 进程 | Client 进程反复重启 |
| 22 | 进程 | Worker 进程反复重启 |
| 23 | 进程 | Client 进程挂死 |
| 24 | 进程 | Worker 进程挂死 |
| 25 | UB 端口 | UB 端口 down |
| 26 | UB 端口 | UB 端口闪断 |
| 27 | UB 端口 | UB 端口丢包 |
| 28 | UB 端口 | UB 端口降 lane |
| 29 | UB 芯片 | UB 芯片 CE 故障 |
| 30 | UB 芯片 | UB 芯片 NFE 故障 |
| 31 | UB 芯片 | UB 芯片 FE 故障 |
| 32 | TCP 网卡 | TCP 网卡全部 down |
| 33 | TCP 网卡 | TCP 单网卡 down |
| 34 | TCP 网卡 | TCP 网卡时延 |
| 35 | TCP 网卡 | TCP 网卡丢包 |
| 36 | TCP 网卡 | TCP 网卡抖动 |
| 37 | TCP 网卡 | TCP 网卡闪断 |
| 38 | TCP 网卡 | TCP 网卡带宽不足 |
| 39 | UB 交换机 | UB 交换机端口故障 |
| 40 | UB 交换机 | UB 交换机端口闪断 |
| 41 | UB 交换机 | UB 交换机端口降 lane |
| 42 | UB 交换机 | UB 交换机故障 |
| 43 | etcd | etcd 集群不可用 |
| 44 | etcd | ETCD 故障 |
| 45 | etcd | ETCD 备节点故障 |
| 46 | etcd | ETCD 主节点故障 |
| 47 | etcd | ETCD 脑裂 |
| 48 | etcd | ETCD 网络中断 |
| 49 | 分布式网盘 | 读写慢 |
| 50 | 分布式网盘 | 网络中断 |
| 51 | 分布式网盘 | 网络时延 |
| 52 | 分布式网盘 | 网络抖动 |
| 53 | 分布式网盘 | 网络丢包 |

故障模式 → 错误码的启发式映射见 [03-status-codes.md § 4](03-status-codes.md)。故障模式 → 根因定位见 [04-fault-tree.md](04-fault-tree.md)。

---

## 3. 关键时间量级

| 时间量级 | 来源 / 含义 | 对客户侧的典型影响 |
|----------|-------------|-------------------|
| **~2 s** | etcd lease TTL（`node_timeout_s`，默认 60s）、SDK 心跳超时，用于 Worker 故障检测与 SDK 切流触发 | 秒级窗口内读写可能失败或切流；过后随新路由恢复 |
| **~3 s** | 故障检测 + 隔离整体窗口（与 2s 检测 + 秒级隔离对齐） | 按 2~3s 典型值做 SLI 粗算 |
| **~100 ms** | TCP 单口切换 | 切换窗口内该路径读写报错；成功率、P99 短时劣化 |
| **20 ms** | 用户侧 RPC / Get 超时配置示例 | 与 UB 128ms 硬件感知不同量级；短超时下 UB 未检测完即失败 |
| **~128 / 133 ms** | UB 硬件侧感知、检测 + 平面切换（128 + 5ms） | 与 20ms 客户超时叠加时，现象与定界需分 TCP / UB |

**影响归纳**：

- **毫秒级**（100ms、20ms）→ 成功率瞬时下降、P99 毛刺、超时错误码（1001）
- **秒级**（2~3s）→ 整批实例成功率下降、切流建链、隔离窗口内的 2/N 效应（见下节）

---

## 4. 单点故障：2/N 与监控窗口粗算

**假设**：某单点（如某个 Worker 节点）故障时，该点同时参与全局元数据访问与数据访问路径的一份份额；在节点被剔除 / 隔离完成前（秒级，典型 2~3s），会有约 **2/N** 比例的数据访问处于失败或不可服务状态，**N** 为集群 Worker 节点总数。

在固定监控统计周期 \(T_{\mathrm{monitor}}\)（例如 5s）内，若故障持续可见时间为 \(T_{\mathrm{剔除}}\)（取隔离/不可服务窗口，例如 3s），可用下式把"单点窗口"映射到"该周期内的失败占比"：

\[
\text{粗算失败占比} \approx \frac{2}{N} \times \frac{T_{\mathrm{剔除}}}{T_{\mathrm{monitor}}}
\]

| 符号 | 含义 |
|------|------|
| **N** | 集群中 Worker 节点数（例：64） |
| **2/N** | 单点故障下，对全局元数据与数据访问的影响面工程近似 |
| **T_剔除** | 单点从故障到被隔离、流量迁出前，客户侧持续感知的秒级窗口（例：3s） |
| **T_monitor** | 监控或报表的聚合周期（例：5s） |

**数值示例**：\(N=64\)，\(T_{\mathrm{剔除}}=3\,\mathrm{s}\)，\(T_{\mathrm{monitor}}=5\,\mathrm{s}\)：

\[
\frac{2}{64} \times \frac{3}{5} = \frac{3}{160} \approx 1.875\%
\]

**解读**：在 5s 监控桶内，若单点不可用 3s，按 2/64 的全局影响面近似，则该桶内"与此次单点相关的"失败约占 **~1.875%** 量级。

**注意**：该式不替代线上真实成功率；用于故障演练、容量沟通、告警阈值时的数量级对齐。短超时（5ms/20ms）下的重试与超时细节见 [deep-dives/timeout-and-latency-budget.md](deep-dives/timeout-and-latency-budget.md)。
