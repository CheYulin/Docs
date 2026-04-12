# 工作簿包（Excel + Sheet 对照 Markdown）

本目录集中存放 **可交付工作簿** 及其 **与各 Sheet 对齐的 Markdown 展开稿**，便于单独打开、评审或打包。

## 正向分析 vs 逆向分析（读表前先对齐脑子）

| 方向 | 是什么 | 在本包里的落点 |
|------|--------|----------------|
| **正向** | **调用树**：从 SDK/Worker **入口**沿 **谁调谁** 一直往下展开到 syscall / `urma_*` / ZMQ 多帧发送等 **叶子**。Sheet1 第二列在树前另有 **`【故障预期】`**、**`【调用链逻辑】`**、`└─` 树。**第 5～8 列**（URMA/OS）由工作簿生成脚本逐行写入 **具体接口 + 日志/grep 原文**；**URMA 错误列与 OS 错误列互斥**（一行只按一类 syscall 层根因排查）。 | **Sheet1**；Markdown **§1 / §2** 与 **步骤 2/3 puml** 对齐。 |
| **逆向** | **流程图逻辑**：现场先拿到 **StatusCode / 返回文案 / 零星日志** → 按规则 **检索 Trace 与关键词** → 与 **Sheet5 定界-case** 或 Sheet1 某行 **对照确认** → 得到责任域与下一步。**不是**把调用树倒着画，而是 **决策/检索路径**。 | **Sheet5**；总图 PlantUML（**先错误码+手册 → 再 Trace**）；[`../../kv-client/kv-client-定位定界手册-基于Excel.md`](../../kv-client/kv-client-定位定界手册-基于Excel.md)、[`../../kv-client/puml/README-总图与分图.md`](../../kv-client/puml/README-总图与分图.md)。 |

Sheet1 表头第二列可悬停 **批注**：再次提示「本列=正向树；逆向用 Sheet5」。

| 文件 | 说明 |
|------|------|
| [kv-client-观测-调用链与URMA-TCP.xlsx](./kv-client-观测-调用链与URMA-TCP.xlsx) | 观测与定界主表：Sheet1 调用链、Sheet2 OS、Sheet3 URMA、Sheet4 性能、Sheet5 定界-case、Sheet6 URMA 错误码解释 |
| [kv-client-Sheet1-调用链-错误与日志.md](./kv-client-Sheet1-调用链-错误与日志.md) | Sheet1 展开：思维导图、按层 Init 表、代码锚点 |
| [kv-client-Sheet2-URMA-C接口映射.md](./kv-client-Sheet2-URMA-C接口映射.md) | 与 xlsx 中 **URMA 接口查表** 对应的展开稿（文件名历史原因仍含 Sheet2） |
| [kv-client-Sheet3-TCP-RPC对照.md](./kv-client-Sheet3-TCP-RPC对照.md) | TCP / ZMQ / RPC 语义对照展开稿 |

**重新生成 xlsx**（写入本目录）：

```bash
./ops docs.kv_observability_xlsx
```

（在 `vibe-coding-files` 仓库根执行。）

上级说明与全文索引：[`../../kv-client/README.md`](../../kv-client/README.md)、[`../../kv-client/文档索引.md`](../../kv-client/文档索引.md)。
