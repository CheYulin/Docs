# ZMQ TCP/RPC Metrics 定界计划

本目录集中存放"ZMQ TCP/RPC 层 metrics 定界可观测"的计划文档。

## 目录内容

- `plan-zmq-rpc-metrics-定界可观测.md`  
  三层指标体系设计、metric 清单、定界场景矩阵、分阶段实施计划。
- `ZMQ-metrics-故障注入与日志定界-测试串讲.md`  
  测试串讲：如何构造故障、看哪些日志/metrics、常见误区与验收 Checklist。
- `RESULTS.md`  
  构建与 UT/ST/Bazel 验证记录；含远端复核与故障注入日志验收摘要。

## 与 URMA/TCP 计划的关系

- URMA/TCP 计划（`../urma-tcp-定界修复需求/`）聚焦 URMA 错误码语义修复和故障日志补齐
- 本计划聚焦 ZMQ 通信栈的 metrics 指标建设，利用 PR #584 的轻量级 metrics 框架
- 两者互补：URMA 覆盖数据面，ZMQ metrics 覆盖控制面/传输面

## 依赖

- PR #584（Add lightweight metrics framework）需先合入，Phase 1 的日志标签部分可独立先行
