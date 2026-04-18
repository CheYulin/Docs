# 官方案例与接口用途（索引 · 待扩展）

本文件为 **后续特性树 / 文档映射**预留：收录 [openYuanrong 入门](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/getting-started/getting_started.html) 中 **说明接口用途** 的嵌入式示例锚点，**不**复制大段代码。

| 主题 | 官方位置（入门页内章节） | 接口/用途摘要 |
|------|--------------------------|----------------|
| 异构对象 | 开发指南 → 异构对象 | `DsClient`、`Blob`、`DeviceBlobList`；NPU 设备侧 mset/mget 等（fork 两进程示例）。 |
| KV | 开发指南 → KV | `DsClient` + `kv().set/get/delete`；DDR 键值示例。 |
| Object | 开发指南 → Object | `object().create/get`、引用计数、`Buffer` 读写与 seal。 |

**权威摘录与部署验证命令**见 [`../reliability/references.md`](../reliability/references.md)。
