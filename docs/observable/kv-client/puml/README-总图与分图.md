# KV Client 定位定界 — PlantUML 总图与分图（阅读顺序）

**PUML 用语 ↔ 本仓文档路径**（核对、对外打包）：[`关联文档对照表.md`](./关联文档对照表.md)

## 设计说明

- **总图**（[`kv-client-定位定界-总图.puml`](kv-client-定位定界-总图.puml)）按 **客户真实路径**：先看到 **错误码 + 手册**，再取 **Trace** 做日志分诊；不再把「参数是否合法」放在第一步（参数问题通常已体现为 **K_INVALID**，在查码后进入 **分图 05**）。
- **分图** 将原总图中较长的 URMA / RPC / OS / 业务 四块拆开，便于单独打印、评审或嵌入 Wiki。

## 文件一览

| 文件 | 内容 |
|------|------|
| **kv-client-定位定界-总图.puml** | 入口：错误码 → 手册 → Trace → 指向哪张分图 |
| **kv-client-定位定界-总图-02-URMA.puml** | URMA / UB / 1004·1006·1008 / 降级 |
| **kv-client-定位定界-总图-03-RPC与网络.puml** | RPC、超时、断连、建连 |
| **kv-client-定位定界-总图-04-OS与资源.puml** | mmap、fd、shm、OOM、磁盘 |
| **kv-client-定位定界-总图-05-参数与业务语义.puml** | INVALID、NOT_FOUND、etcd/**Directory**（日志可有 master 原文）、缩容、seal/NX |
| kv-client-定位定界-步骤1-Init.puml | Init 时序级 |
| kv-client-定位定界-步骤2-读路径Get_MGet.puml | 读路径时序级：**Client/W1/W2/W3 与 OS syscall、URMA 显式关联**（RPC→recv、etcd→socket、W3→pread/mmap+URMA、Client→mmap） |
| kv-client-定位定界-步骤3-写路径Put_MSet.puml | 写路径时序级：**MCreate 经 OS 分配与 fd 传递、Publish 经 RPC、W3 落盘 syscall + URMA**，与 Client 侧 UB 直发 **U** 对照 |

## 建议用法

1. 给客户/值班：**只发总图 + 分图 02～05 中与其错误码相关的一张**。  
2. 研发深潜：总图 → 对应分图 → **步骤 1/2/3** 时序图。  
3. 与 Markdown 对照：[kv-client-定位定界-客户操作手册-分支全量与Trace粒度.md](../kv-client-定位定界-客户操作手册-分支全量与Trace粒度.md)。
