# kv_client_triage / details

本目录放 **从 Playbook 条目到源码的推导长文** 与 **专用时序图**，避免把主 README / Playbook 撑得过长。

**镜像副本（便于与 `docs/reliability` 同层检索）**：[`docs/reliability/operations/`](../../../docs/reliability/operations/)（文件名以 `kv-client-*.md` 开头）。**以本目录或 `docs` 之一为准修订即可**；若双份并存，请同步更新。

| 文档                                                                                                       | 说明                                                                               |
| -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| [scaling_scale_down_client_paths.md](./scaling_scale_down_client_paths.md)                               | `K_SCALING` / `K_SCALE_DOWN` **客户端是否可见**、从 Worker 哪条路径抛出、`RetryOnError` 是否重试     |
| [scaling_scale_down_sequences.puml](./scaling_scale_down_sequences.puml)                                 | 上述两条码的 **PlantUML 时序图**（**副本**见 [`docs/flows/sequences/kv-client/`](../../../docs/flows/sequences/kv-client/)） |
| [rpc_unavailable_triggers_and_urma_vs_transport.md](./rpc_unavailable_triggers_and_urma_vs_transport.md) | **1002** 常见触发 Case（ZMQ/UDS/建连）、与 **1004/1006/1008** 分层；**URMA 瞬时**为何不能单靠 1002 判断 |
| [ops_deploy_scaling_failure_triage.md](./ops_deploy_scaling_failure_triage.md) | **运维部署 / 扩缩容失败**：文首 **排查前置**（L0–L5 观测清单）；**0. 部署冷启动**；**2. 运行中变更**（监控+log，弱化 CAS） |
| [worker_resource_log_triage.md](./worker_resource_log_triage.md) | Worker **`resource.log`**：与 [官方日志附录](https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/appendix/log_guide.html) 对照；**`res_metrics.def` 字段顺序**；SHM / Client 数 / OC 对象数 / 线程池 / etcd / OBS / 命中拆分的 **定界用法** 与源码锚点 |

