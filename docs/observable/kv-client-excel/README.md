# KV Client 观测：Excel 与 Markdown（调用链 / URMA / TCP）

本目录提供 **Excel 工作簿**（便于评审、筛选）及 **Markdown 证据版**（便于版本管理与 PR 评论），内容与 `docs/flows/sequences/kv-client/` 时序图、`docs/observable/` 既有定位定界材料一致，并 **锚定 `yuanrong-datasystem` 源码**。

## 文件

| 文件 | 说明 |
|------|------|
| [kv-client-观测-调用链与URMA-TCP.xlsx](./kv-client-观测-调用链与URMA-TCP.xlsx) | **Sheet1** 调用链路（含**责任归属**、**接口信息**、**定位建议**）；**Sheet2** OS syscall（每行一 case）；**Sheet3** URMA C 接口（每行一 case）；**Sheet4** 性能关键路径；**Sheet5** **定界-case查表**（Status/日志 → URMA/OS/逻辑/RPC/用户） |
| [kv-client-Sheet1-调用链-错误与日志.md](./kv-client-Sheet1-调用链-错误与日志.md) | Sheet1 展开 + 代码引用 |
| [kv-client-Sheet2-URMA-C接口映射.md](./kv-client-Sheet2-URMA-C接口映射.md) | Sheet2 展开 + `urma_manager.cpp` 证据 |
| [kv-client-Sheet3-TCP-RPC对照.md](./kv-client-Sheet3-TCP-RPC对照.md) | Sheet3 展开 |
| [kv-client-上下游语义要求-URMA与TCP.md](./kv-client-上下游语义要求-URMA与TCP.md) | 上游调用与下游 UB/TCP 的语义约束与建议 |
| [kv-client-调用链行模板-示例-MGet最长路径.md](./kv-client-调用链行模板-示例-MGet最长路径.md) | **Excel 第二列写法**：MGet 最长路径 1～5 段（client→W1→…→URMA）+ 配套列建议 |
| [kv-client-URMA-OS-读写初始化-跨模块错误与重试.md](./kv-client-URMA-OS-读写初始化-跨模块错误与重试.md) | **Init/读/写**：URMA 与 OS、跨模块传播、`Status`/`last_rc`/仅日志、**RetryOnError** 与触发码 |
| [kv-client-URMA-错误枚举与日志-代码证据.md](./kv-client-URMA-错误枚举与日志-代码证据.md) | URMA 专项：UMDK 枚举值（`urma_status_t`）+ 数据系统实际 error 日志与处理路径（代码证据） |
| [kv-client-定位定界手册-基于Excel.md](./kv-client-定位定界手册-基于Excel.md) | 精简手册：如何结合 3 个 Sheet 快速定界，并给出日志自动化分析建议 |
| [kv-client-定位定界-总图.puml](./puml/kv-client-定位定界-总图.puml) | 测试/开发/Agent 共用定位流程图：按状态码/日志分支到 URMA、OS、RPC、系统逻辑、用户参数，并给出下钻 Sheet 建议 |
| [kv-client-定位定界-步骤1-Init.puml](./puml/kv-client-定位定界-步骤1-Init.puml) | 分步骤图（Init）：调用链 + 错误分支 + 责任团队 |
| [kv-client-定位定界-步骤2-读路径Get_MGet.puml](./puml/kv-client-定位定界-步骤2-读路径Get_MGet.puml) | 分步骤图（读）：Get/MGet 调用链 + 错误分支 + 责任团队 |
| [kv-client-定位定界-步骤3-写路径Put_MSet.puml](./puml/kv-client-定位定界-步骤3-写路径Put_MSet.puml) | 分步骤图（写）：Put/MSet 调用链 + 错误分支 + 责任团队 |
| [kv-client-性能关键路径与采集手册.md](./kv-client-性能关键路径与采集手册.md) | 性能专题：线程切换、RPC等待、URMA降级影响、采集命令与 ST 验证建议 |
| [../kv-client-Get路径-树状错误矩阵.md](../kv-client-Get路径-树状错误矩阵.md) | **Get/MGet 专用**：路径为列、阶段为行的树状错误矩阵（内部 / OS / URMA / RPC） |
| [../kv-client-SDK与Worker-读路径-快速定位定界.md](../kv-client-SDK与Worker-读路径-快速定位定界.md) | **读路径工单级**：快速区分 OS/URMA/系统，定段①～⑥、模块、入口/远端 Worker |
| [scripts/generate_kv_client_observability_xlsx.py](./scripts/generate_kv_client_observability_xlsx.py) | 重新生成 xlsx（依赖 `openpyxl`） |

## 重新生成 Excel

```bash
python3 docs/observable/kv-client-excel/scripts/generate_kv_client_observability_xlsx.py
```

（在 `vibe-coding-files` 仓库根目录执行时，请使用脚本绝对路径或 `cd` 到仓库后调整路径。）

## 外部资料说明（URMA）

- 数据系统通过 **`#include <ub/umdk/urma/urma_api.h>`** 使用 URMA；**`urma_status_t` / `URMA_SUCCESS` 的完整枚举**以 **构建环境安装的 UMDK 头文件** 为准。
- 公开仓库线索（用于对照目录结构，**不等价于你们现场编译选项**）：
  - [openeuler-mirror/umdk](https://github.com/openeuler-mirror/umdk)（含 `urma.spec`、头文件树）
  - [Gitee openEuler umdk PR 讨论片段](https://gitee.com/openeuler/umdk/pulls/1.diff?skip_mobile=true)（对 URMA 子系统有文字描述）
- 本材料 **不臆造** 各 `urma_*` 的逐条 errno；代码未记录处标注 **查 UMDK 头文件与厂商手册**。
- **bonding 多端口**：代码在 UB 模式下若配置设备名不在列表中，会尝试匹配 **`bonding`** 前缀设备（见 Sheet2 / 对应 Markdown 中的代码引用）。

## 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-09 | 初版：xlsx + 4 份 Markdown |
| 2026-04-09 | 增加 Get 路径树状错误矩阵（上级目录 Markdown）链接 |
| 2026-04-09 | 增加 SDK/Worker 读路径快速定位定界文档链接 |
| 2026-04-09 | 增加 MGet 调用链行模板（与 Excel 分段列对齐） |
| 2026-04-09 | 增加 URMA/OS/重试跨模块总表（Init+读+写） |
| 2026-04-09 | Excel 升级为 3 张定位专用 Sheet，并增加自动化定位手册 |
| 2026-04-09 | 新增性能关键路径 Sheet 与性能采集手册 |
| 2026-04-09 | Sheet1 增加责任归属/接口/定位建议列；Sheet2/3 拆行+定位建议；新增 Sheet5 定界-case 总表 |
| 2026-04-09 | 新增 PlantUML 定位定界总图（测试/开发/Agent 共用） |
| 2026-04-09 | 新增分步骤 PlantUML（Init / Get-MGet / Put-MSet），体现调用链、错误分支与责任团队 |
