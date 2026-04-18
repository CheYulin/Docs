# Deep Dives

这里放"高信息密度但非首次必读"的专题分析。按需阅读：

| 文档 | 何时看 |
|------|--------|
| [etcd-isolation-and-recovery.md](etcd-isolation-and-recovery.md) | Worker etcd 续约失败、被动缩容 SIGKILL、闪断误杀、`node_timeout_s` / `node_dead_timeout_s` 参数调优 |
| [timeout-and-latency-budget.md](timeout-and-latency-budget.md) | 集群超时参数语义、5ms / 20ms 短超时下的重试行为与尾延迟 |
| [client-lock-rpc-logging.md](client-lock-rpc-logging.md) | 客户端锁内 RPC / spdlog flush 导致 bthread 阻塞的风险治理 |

返回：[../README.md](../README.md)
