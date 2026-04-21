# KV Client 可观测文档

本目录面向 **研发、测试、值班** 的可观测与定位定界。骨架：**调用链 → 埋点 → 现象 → 证据 → 归因**，所有内容锚定 `yuanrong-datasystem` 源码。

## 与 `docs/reliability/` 的分工

| 维度 | `docs/reliability/` | `docs/observable/`（本目录） |
|------|---------------------|------------------------------|
| 关注点 | **故障处理方案、SLI、错误码分层、运维排障剧本** | **如何看到故障**：调用链、埋点、日志、Trace、metrics；**客户/研发定位手册** |
| 核心骨架 | 错误码 → 根因（代码证据） | 调用链 → 现象 → 证据 → 归因 |
| 示例 | "1002 桶码有哪些子类、各自代码证据" | "看 `access log` 第一列 + `respMsg` 关键词，从现象回溯到哪段代码" |

交叉引用（不复述）：
- 本目录提到错误码语义 → 跳 `../reliability/03-status-codes.md` / `04-fault-tree.md`
- 本目录涉及外部依赖状态机 → 跳 `../reliability/deep-dives/`（如 etcd 隔离与恢复）
- `reliability/` 提到客户端 access log / resource.log → 跳本目录对应章节

---

## 阅读顺序

| 序号 | 文档 | 主题 | 对应代码 |
|-----|------|------|---------|
| 01 | [01-architecture.md](01-architecture.md) | 可观测架构：应用日志 / access log / resource.log / metrics / Trace / PerfPoint 全景 | `common/log/` / `common/metrics/` |
| 02 | [02-call-chain-and-syscalls.md](02-call-chain-and-syscalls.md) | Init / MCreate / MSet / MGet 完整调用链 + OS/URMA 接口全量清单 | `kv_client.cpp` / `object_client_impl.cpp` / `urma_manager.cpp` |
| 03 | [03-fault-mode-library.md](03-fault-mode-library.md) | FM-001..023 故障模式库 + 日志关键字 + URMA/OS 互斥定界 + Get 路径错误矩阵 | `sheet1_system_presets.py`（脚本） |
| 04 | [04-triage-handbook.md](04-triage-handbook.md) | 定位定界手册：Trace 粒度 SOP、`grep` 模板、读/写/Init 分支表、责任域判别 | `access_recorder.cpp` / `access_point.def` |
| 05 | [05-metrics-and-perf.md](05-metrics-and-perf.md) | 已落地的 ZMQ/KV metrics 清单（可运行时读取）+ 性能关键路径 + 采集命令 | `common/metrics/kv_metrics.{h,cpp}` / `zmq_socket_ref.cpp` |
| 06 | [06-dependencies/](06-dependencies/README.md) | 外部/三方件依赖：URMA、OS syscall、etcd、二级存储 | — |
| 07 | [07-pr-metrics-fault-localization.md](07-pr-metrics-fault-localization.md) | PR 串讲 (#583/#584/#586/#588) × 36 条 metric × 17 个日志标签 × 故障定界决策树，给测试/研发值班用 | `common/metrics/kv_metrics.cpp` / `zmq_socket_ref.cpp` / `urma_manager.cpp` |
| 08 | [08-fault-triage-consolidated.md](08-fault-triage-consolidated.md) | **值班速查 + 附录参考**：从 access 日志看成功率/P99 → 30 秒分类 → 1–3 分钟定界；五边界（用户/DS 进程内/三方 etcd/URMA/OS）；附录 A–F 速查卡 / 54 条 metrics / 结构化日志标签 / resource.log 字段 / 注入矩阵 / gflag | `kv_metrics` / `status.h` / `zmq` / `urma`（细节见 05/07） |
| 09 | [09-observable-test-construction.md](09-observable-test-construction.md) | **可观测用例构造与验证指南**：把 08 的"看证据做定界"反向成"故障注入 → 期望证据 → 自动化判据"；给每个故障域提供 ST 骨架、`INJECT_POINT` / iptables / tc 注入手段、四维断言模板 | `tests/st/common/rpc/zmq/zmq_metrics_fault_test.cpp` / `common/inject/inject_point.h` / `scripts/testing/verify/*` |

## 工具与产物

| 文件 | 说明 |
|------|------|
| [diagrams/README.md](diagrams/README.md) | PlantUML 总图 + 分图（triage + 步骤图） |
| [workbook/README.md](workbook/README.md) | Excel 工作簿 + Sheet1/2/3 Markdown 对照稿（命令 `./ops docs.kv_observability_xlsx`） |

## 维护约定

1. **对齐代码**：每篇顶部列出对应 `yuanrong-datasystem` 源码文件；代码变更后同步更新。
2. **不重复**：每个主题只在一处展开，其它文档引用即可。
3. **RFC 分离**：特性开发任务（设计、验证、PR 文案）放 `../../rfc/`，本目录仅留稳定文档。
4. **与 reliability 自洽**：交叉引用而非复述；两边的 StatusCode 表必须一致。
