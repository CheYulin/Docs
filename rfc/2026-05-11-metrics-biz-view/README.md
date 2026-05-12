# RFC: Metrics 可观测 — 业务视角仪表盘

## Status

**Draft**（RFC 撰写阶段，代码待实现）

## 背景

`metrics_summary` 日志（`DumpSummaryJson` / `LOG(INFO)` 输出）是 DataSystem 运行时可观测性的核心数据源。当前仅有原始 JSON 行，缺乏统一的可视化入口：

- 原始日志体积大（1MB+），无法直观理解
- 多 `part_index` 分片场景下数据需手动合并
- 无时间窗口过滤能力
- 无 P99/Avg/Max 分组聚合视图

## 目标

在 `yuanrong-datasystem-agent-workbench` 中新增 **Metrics 可观测**特性，提供：

1. **Python 可视化脚本**（`scripts/metrics/metrics_biz_view.py`）：将 `metrics_summary` 日志转换为 ECharts HTML 仪表盘
2. **设计文档**（`docs/metrics-biz-view/design.md`）：完整记录架构、数据流、指标分组
3. **RFC 文档**（本目录）：特性开发任务跟踪

## 代码落点

| 区域 | 文件 | 说明 |
|------|------|------|
| 脚本 | `agent-workbench/scripts/metrics/metrics_biz_view.py` | 主生成脚本 (~52KB, 900+ 行) |
| 文档 | `agent-workbench/docs/metrics-biz-view/design.md` | 设计文档（从 `c:\00-工具\` 迁移） |
| 验证数据 | `rfc/2026-05-11-metrics-biz-view/data/metrics_summary_cut.log` | 2026-05-11 下载的验证样本 |
| RFC | `rfc/2026-05-11-metrics-biz-view/` | 本 RFC 目录 |

## 功能要点

- **45 个指标分组**：Write Flow、Read Meta、Read Data、ZMQ RPC、URMA、Memory、Allocator、ShmRef、Eviction & TTL、MetaTable
- **时间窗口过滤**：`--since HH:MM` 或 `--since YYMMDD_HHMM`
- **同 cycle 多 part_index 合并**：自动合并不同分片数据
- **ECharts 渲染**：CDN 加载 (~300KB)，生成 ~100KB HTML（减少 90%+ 体积）
- **校验报告**：运行时打印未识别指标、无分组指标、全零数据指标

## 验证方法

```bash
# 基本验证
python3 scripts/metrics/metrics_biz_view.py \
  -i data/metrics_summary_cut.log \
  -o /tmp/worker_biz.html

# 时间过滤验证
python3 scripts/metrics/metrics_biz_view.py \
  -i data/metrics_summary_cut.log \
  -o /tmp/worker_biz.html \
  --since "10:05" -v
```

## 后续扩展方向

- 多节点聚合视图
- 时间范围选择器（支持 zoom）
- 对比模式（两个时间窗口叠加）
- 自动异常检测（时延突增标红）
- 导出 PDF 功能

## 关联

- [2026-05-03 metrics-p99-histogram](../2026-05-03-metrics-p99-histogram/README.md)：P99 直方图
- [2026-04-30 zmq-rpc-queue-latency](../2026-04-30-zmq-rpc-queue-latency/README.md)：ZMQ RPC 延迟
- [2026-04-27 worker-get-metrics-breakdown](../2026-04-27-worker-get-metrics-breakdown/README.md)：Get 路径指标分解
