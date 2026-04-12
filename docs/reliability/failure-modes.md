# 失败模式提纲（跨文档）

本页不是全量细节复写，而是“先分层、再跳转”的提纲页。  
总入口见 [README.md](README.md) 与 [00-kv-client-fema-index.md](00-kv-client-fema-index.md)。

## 1) 控制面故障（配置/选点/元数据）

- **典型现象**：`Init` 失败、选点异常、扩缩容窗口成功率波动。
- **优先证据**：应用日志、etcd 可用性、`HashRingPb` 与 revision 一致性。
- **对应文档**：
  - [00-kv-client-fema-scenarios-failure-modes.md](00-kv-client-fema-scenarios-failure-modes.md)
  - [operations/kv-client-ops-deploy-scaling-failure-triage.md](operations/kv-client-ops-deploy-scaling-failure-triage.md)
  - [deep-dives/timeout-params-restart-vs-scale-down.md](deep-dives/timeout-params-restart-vs-scale-down.md)

## 2) 传输与建链故障（TCP/ZMQ/URMA/fd/共享内存）

- **典型现象**：1002 桶码、URMA 连接抖动、建链失败后重试放大。
- **优先证据**：状态码分层、建链日志、URMA 相关错误码与重连路径。
- **对应文档**：
  - [00-kv-client-visible-status-codes.md](00-kv-client-visible-status-codes.md)
  - [operations/kv-client-rpc-unavailable-triggers.md](operations/kv-client-rpc-unavailable-triggers.md)
  - [deep-dives/故障码树状梳理-URMA与TCP-fd共享内存.md](deep-dives/故障码树状梳理-URMA与TCP-fd共享内存.md)
  - [deep-dives/client-status-codes-evidence-chain.md](deep-dives/client-status-codes-evidence-chain.md)

## 3) 数据面故障（读写超时/重试/一致性语义）

- **典型现象**：短超时下成功率下降、尾延迟拉高、重试导致残余流量。
- **优先证据**：P95/P99、timeout 返回比例、重试次数与对象级状态。
- **对应文档**：
  - [00-kv-client-fema-read-paths-reliability.md](00-kv-client-fema-read-paths-reliability.md)
  - [00-kv-client-fema-timing-and-sli.md](00-kv-client-fema-timing-and-sli.md)
  - [deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md](deep-dives/get-latency-timeout-sensitive-analysis-5ms-20ms.md)

## 4) 运维操作与资源故障（扩缩容/日志采集/退出）

- **典型现象**：31/32 理解偏差导致误判、缩容窗口告警抖动、资源观测缺失。
- **优先证据**：`resource.log`、access log、服务发现与探活状态。
- **对应文档**：
  - [operations/kv-client-scaling-scale-down-client-paths.md](operations/kv-client-scaling-scale-down-client-paths.md)
  - [operations/kv-client-worker-resource-log-triage.md](operations/kv-client-worker-resource-log-triage.md)
  - [archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md](archive/2026-04/00-kv-client-fema-ops-deploy-scaling.md)

## 5) 快速定位顺序（值班默认）

1. 先判“控制面 vs 数据面”；
2. 再用状态码与日志分层到传输/URMA/业务语义；
3. 最后检查是否处在扩缩容或配置变更窗口；
4. 记录到对应 playbook，避免重复排障。
