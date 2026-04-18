# References · 外部入口与 DryRun 模板

---

## 1. openYuanrong datasystem 官方文档

| 资源 | URL |
|------|-----|
| **入门（安装、部署、开发指南入口）** | [openYuanrong datasystem getting started](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/getting-started/getting_started.html) |
| **附录 · 日志**（与 `resource.log` 对照） | [日志附录](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/appendix/log_guide.html) |
| **附录**（含 Bazel 集成等） | [appendix](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/appendix/) |

### 1.1 安装与验证

摘自官方入门页（**版本以官方页面为准**）：

- **Python**：3.9 / 3.10 / 3.11
- **OS / 架构**：Linux（建议 glibc 2.34+）、x86-64
- **PyPI 完整发行版**（含 Python SDK、C++ SDK、命令行工具）：
  ```bash
  pip install openyuanrong-datasystem
  ```
- **验证**：
  ```bash
  python -c "import yr.datasystem; print('openYuanrong datasystem installed successfully')"
  dscli --version
  ```

### 1.2 进程部署（etcd + dscli）

```bash
# 1) 先起 etcd（单节点示例）
etcd --listen-client-urls http://0.0.0.0:2379 --advertise-client-urls http://localhost:2379 &

# 2) 一键起 Worker
dscli start -w --worker_address "127.0.0.1:31501" --etcd_address "127.0.0.1:2379"

# 3) 停止
dscli stop --worker_address "127.0.0.1:31501"
```

### 1.3 Kubernetes 部署

```bash
dscli generate_helm_chart -o ./
# 编辑 ./datasystem/values.yaml（镜像、etcdAddress 等）
helm install openyuanrong_datasystem ./datasystem
# helm uninstall openyuanrong_datasystem
```

### 1.4 开发接口层级（示意）

| 能力 | 官方定位 |
|------|----------|
| **异构对象** | HBM 抽象、D2D / H2D / D2H、训推与 KVCache 等场景 |
| **KV** | 共享内存免拷贝 KV、DRAM / SSD / 二级缓存置换、Checkpoint 等 |
| **Object** | 共享内存 Object 语义、引用计数、Buffer 映射 |

Python 侧入口类为 `DsClient`（`init` 后 `kv()` / `object()` / `hetero()` 等）；C++ / Java API 树见同站"编程接口 → API"。

---

## 2. DryRun 模板（故障演练与 Case 记录）

### 2.1 模板字段

| 字段 | 填写说明 |
|------|----------|
| Case ID | 内部编号或需求单号 |
| 场景名称 | 如"本端 Client 读远端 Worker 失败" |
| 业务线 | 精排 / 召排（影响 E2E 还是 TP99 口径） |
| 数据路径 | 对照 [01-architecture-and-paths.md § 2](01-architecture-and-paths.md)（正常 / 切流 6 步） |
| 观测现象 | 负载均衡器 / 监控平台 / 日志分别看到什么 |
| 定界结论 | 网络 / Worker / 主机 / 时间 等大类 |
| 定位步骤 | Step1…StepN（尽量可脚本化，避免全集群无差别 grep） |
| 根因类型 | 与 [02-failure-modes-and-sli.md § 2](02-failure-modes-and-sli.md) 故障模式编号对照 |
| 加固项 | 如：`GetRsp` 回传异常节点 `IP:Port`；指标分阶段 |

### 2.2 已填样例：某节点 UB 端口 down（远端读失败）

**场景**：本端 Client 读远端 Worker，读取失败（UB 链路相关，已 DryRun）。

| 维度 | 内容 |
|------|------|
| 业务线 | 召排为主示例：Prefill 路径依赖 KV；精排若同链路则 E2E 失败更明显 |
| 路径简述 | Client → 所连 Worker（常为 worker1）→ 跨机元数据 / 拉取 → 对端 URMA Write / Get resp；失败点常出现在 UB 端口 / Jetty 一侧 |
| 观测到的现象 | 监控平台：KV Get 读取成功率下降。负载均衡器：召回时延增大；可进一步看到某批业务请求处理实例异常。业务请求处理实例：Prefill 时延升至 xx ms（不符合预期）。接口 / 运行日志中可出现 URMA Error 09（示例码，以实际环境为准） |
| 定界（大类） | 优先怀疑 UB 端口 / UB 链路（与 TCP 网卡、`K_RPC_*` 区分见下节） |
| 定位步骤（推荐顺序） | **Step1**：看负载均衡器侧监控：召回时延、成功率，缩小到异常实例批次。**Step2**：从负载均衡器关联到业务请求处理实例列表，确认 Prefill 时延是否符合 SLA。**Step3**：在云平台 / 业务请求处理实例访问日志中查 URMA Error 或 SDK 错误串（避免先全集群 grep）。**Step4**：用 SDK 已知的当前 KVC Worker `IP:Port` 定位到对应 Worker 日志；若有 TraceID 则只在已锁定的 Worker 上 grep。**加固方向**：URMA Write / 关键路径失败时，在 `GetRsp` 或 `Status` 中带回异常节点 `IP:Port`，减少盲 grep |
| 问题类型（本样例已对齐） | 某个节点 UB 端口 down（本 DryRun 主因）。同类可扩展：UB 端口闪断 / 丢包（多与成功率、重试相关）；UB 端口降 lane、UB 芯片 CE/NFE/FE（多见时延劣化，未必同等幅度掉成功率） |
| 与精排 / 召排差异 | **召排**：现象常体现为 TP99 / Prefill 时延变差；**精排**：更易出现 E2E 失败率上升。同一 UB 故障建议在两条业务线各记一条现象 |

### 2.3 举一反三：问题类型 → 观测 / 码速查

| 问题类型 | 典型观测或辅助定界 | 备注 |
|----------|---------------------|------|
| OS 重启、OS Panic、BMC 强制上下电 | 成功率陡降、多实例同时异常 | 与单机维护窗口对齐 |
| 主机资源不足（UB 带宽 / CPU）、时间跳变 | 成功率或 TP99 异常 | 结合主机监控 |
| KVC Worker：容器 / 进程异常、反复重启、挂死 | 心跳与隔离窗口内失败 | SDK 切流日志 |
| UB 端口 down / 闪断 / 丢包 | 成功率下降 + URMA 类日志 | **本样例已覆盖 down** |
| UB 端口降 lane、UB 芯片 CE/NFE/FE | 多表现为时延（TP99） | 成功率未必同幅下降 |
| `K_RPC_DEADLINE_EXCEEDED` (1001)、`K_RPC_UNAVAILABLE` (1002) | TCP 路径超时 / 不可用 | 与 UB 区分需网卡 / 交换机侧指标，见 [06-playbook § 2](06-playbook.md) |

---

## 3. 日志与排障的外部 × 内部关系

- **官方附录 · 日志**：说明运行日志、资源日志等分类与字段语义（与 [06-playbook § 4](06-playbook.md) 配合阅读）。
- **客户端 access 日志、错误码分层**：以本目录 [03-status-codes.md](03-status-codes.md)、[04-fault-tree.md](04-fault-tree.md)、[06-playbook.md](06-playbook.md) 为准。

---

## 4. 修订

- 官方链接随上游站点更新；若导航变更，以入门首页侧栏为准。
- DryRun 新 Case 按 § 2.1 模板记录，根因类型引用 [02 § 2](02-failure-modes-and-sli.md) 编号。
