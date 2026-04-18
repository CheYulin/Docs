# 工作簿（Excel + Sheet 对照 Markdown）

本目录集中存放 **可交付工作簿** 及其 **与各 Sheet 对齐的 Markdown 展开稿**，便于单独打开、评审或打包。

## 正向分析 vs 逆向分析

| 方向 | 是什么 | 落点 |
|------|--------|------|
| **正向** | **调用树**：从 SDK/Worker 入口沿"谁调谁"展开到 syscall / `urma_*` / ZMQ 多帧发送等叶子。Sheet1 第二列有 `【故障预期】` + `【调用链逻辑】` + `└─` 树；**第 5~8 列**（URMA/OS）由脚本写入具体接口 + 日志 grep 原文；**URMA 错误列与 OS 错误列互斥**（一行只按一类 syscall 层根因排查）| **Sheet1**；Markdown [sheet1-call-chain.md](sheet1-call-chain.md)；步骤图 `../diagrams/step-*.puml` |
| **逆向** | **流程图逻辑**：现场先拿到 StatusCode / 返回文案 / 零星日志 → 按规则检索 Trace 与关键词 → 与 **Sheet5 定界-case** 或 Sheet1 某行对照确认 → 得到责任域与下一步。**不是**把调用树倒着画，是**决策 / 检索路径** | **Sheet5**；总图 `../diagrams/triage-overview.puml`；[`../04-triage-handbook.md`](../04-triage-handbook.md) |

Sheet1 表头第二列可悬停批注："本列 = 正向树；逆向用 Sheet5"。

## 文件

| 文件 | 说明 |
|------|------|
| [kv-client-观测-调用链与URMA-TCP.xlsx](kv-client-观测-调用链与URMA-TCP.xlsx) | 观测与定界主表：Sheet1 调用链、Sheet2 OS、Sheet3 URMA、Sheet4 性能、Sheet5 定界-case、Sheet6 URMA 错误码解释 |
| [sheet1-call-chain.md](sheet1-call-chain.md) | Sheet1 展开：思维导图、按层 Init 表、代码锚点 |
| [sheet2-urma-capi.md](sheet2-urma-capi.md) | URMA 接口查表展开稿（文件名历史原因仍含 "Sheet2"，实际与 xlsx 中 URMA 接口 Sheet 对应）|
| [sheet3-tcp-rpc.md](sheet3-tcp-rpc.md) | TCP / ZMQ / RPC 语义对照展开稿 |

## 重新生成 xlsx

```bash
./ops docs.kv_observability_xlsx
```

（在 `vibe-coding-files` 仓库根执行，产物写入本目录。）

## 相关文档

- 定位定界手册：[`../04-triage-handbook.md`](../04-triage-handbook.md)
- 故障模式库：[`../03-fault-mode-library.md`](../03-fault-mode-library.md)
- 总图与分图：[`../diagrams/README.md`](../diagrams/README.md)

## `.gitignore`

本目录 `.gitignore` 只忽略扫描脚本生成的临时产物；正式提交的 xlsx 按上面命令重生成。
