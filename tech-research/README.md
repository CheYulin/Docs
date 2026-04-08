# Tech research（技术调研）

与 **yuanrong-datasystem 产品源码无直接绑定** 的第三方库、运行时、观测手段的**独立分析**放在此目录，区别于 `plans/` 中随 datasystem 迁移或特性绑定的材料。

| 子目录 | 说明 |
|--------|------|
| [`brpc-analysis/`](brpc-analysis/) | brpc / bthread 等栈与 syscall 路径分析 |
| [`bpftrace/`](bpftrace/) | eBPF/bpftrace **方法论**（问题发现与识别）；**单次采集解读报告**在 [`../workspace/observability/reports/bpftrace/`](../workspace/observability/reports/bpftrace/) |

与 executor、锁、perf 相关的**设计文稿**仍可能在 [`../plans/kvexec/`](../plans/kvexec/)（与 PR/RFC 同目录）。
