文本用例描述要求：

目标：
- 平均吞吐在范围内，达成2ms目标
- 可靠性：吞吐和并发度大幅超过负荷，不崩溃，回落后可以继续达成功能可用

数据大小：
- 0.5MB
- 精排最大：8MB
- 召排最大：12MB

包含：
- 变量：
    - QPS的尖峰倍数 = 尖峰 / Avg QPS
- 环境Setup：
    - 容器数：kv worker （固定：1个节点1个），kv client (Predicator主图、子图)
    - 读写模式（kv worker视角）：
        - [共享内存访问] kv worker触发的Get请求QPS (35 * K QPS) --- 共享内存
        - [入口带宽占用] kv worker触发的远端数据拉取的Get请求QPS (35 * K QPS) --- 入口带宽
        - [基于共享内存Copy] kv worker本地接收的的Put请求QPS（35 * K QPS) --- 跨NUMA HCCS带宽
        - [出口带宽占用] 其他kv worker触发跨级拉取，本kv worker提供数据的处理QPS --- 出口带宽
        ...
    - kv client容器数，规格 （比如8C 32G)
    - kv worker规格：召排8C192G, 精排8C16G
- 核心生命周期管理功能
 - 召回：缓存淘汰 (整体数据容量按照10%，50%，100%)
 - 精排：TTL （5s) + 缓存淘汰

 观测：
 成功率（100%）和P99时延 （< 2ms）