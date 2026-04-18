# 可观测定位定界配图（PlantUML）

与 [`../04-triage-handbook.md`](../04-triage-handbook.md) 配合阅读。

## 总图 + 5 张分图

总图做"错误码 → 手册 → Trace → 指向分图"的入口，分图展开具体责任域：

| 文件 | 说明 |
|------|------|
| [triage-overview.puml](triage-overview.puml) | 总图（精简）：错误码 → 手册 → Trace → 指向分图 |
| [triage-urma.puml](triage-urma.puml) | URMA / UB / 1004·1006·1008（含新增 1009/1010） |
| [triage-rpc-network.puml](triage-rpc-network.puml) | RPC、超时、断连（1001/1002 桶码分流）|
| [triage-os-resources.puml](triage-os-resources.puml) | mmap / fd / shm / 资源 |
| [triage-params-semantics.puml](triage-params-semantics.puml) | INVALID / NOT_FOUND / etcd / 缩容 / seal / NX |

## 步骤图（调用链时序）

| 文件 | 说明 |
|------|------|
| [step-init.puml](step-init.puml) | Init 调用链 + 错误分支 + 责任团队 |
| [step-read-get-mget.puml](step-read-get-mget.puml) | Get / MGet 调用链 + 错误分支 + 责任团队 |
| [step-write-put-mset.puml](step-write-put-mset.puml) | MCreate / MSet(buffer) / Put / MSet(kv) 调用链 + 错误分支 + 责任团队 |

## 与其它 PlantUML 的关系

- 读写主路径时序：`../../flows/sequences/kv-client/`
- 可靠性方案的故障处理图：`../../reliability/diagrams/`
