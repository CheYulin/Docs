# Reliability Deep Dives

本目录收纳“高信息密度但非首次必读”的专项分析，适合在以下场景按需阅读：

- 需要追溯状态码到源码证据链；
- 需要解释超时参数、重试行为与尾延迟；
- 需要评估锁内 RPC/日志阻塞对稳定性的影响；
- 需要深入 URMA/TCP/fd/共享内存链路细节。

当前专题：

- [client-status-codes-evidence-chain.md](client-status-codes-evidence-chain.md)
- [故障码树状梳理-URMA与TCP-fd共享内存.md](故障码树状梳理-URMA与TCP-fd共享内存.md)
- [get-latency-timeout-sensitive-analysis-5ms-20ms.md](get-latency-timeout-sensitive-analysis-5ms-20ms.md)
- [timeout-params-restart-vs-scale-down.md](timeout-params-restart-vs-scale-down.md)
- [client-lock-in-rpc-logging-bthread-blocking.md](client-lock-in-rpc-logging-bthread-blocking.md)

返回总索引：[`../README.md`](../README.md)。
