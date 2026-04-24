# Deprecated Scripts

这些脚本已被归档，功能由新拆分结构替代。

## 归档原因

| 文件 | 归档原因 | 替代品 |
|------|---------|--------|
| `run_zmq_metrics_bazel.sh` | 功能完全被 `ut/run_ut_bazel.sh` 覆盖；无 rsync 会导致远端代码漂移 | `testing/verify/ut/run_ut_bazel.sh` |
| `run_zmq_metrics_fault_e2e_remote.sh` | 被 `e2e/run_zmq_fault_e2e.sh` 覆盖 | `testing/verify/e2e/run_zmq_fault_e2e.sh` |
| `run_kv_rw_metrics_remote_capture.sh` | 无任何脚本调用 | 拆分入新层级 |
| `run_shm_leak_metrics_remote.sh` | 功能拆分入 `e2e/run_shm_leak_metrics.sh` | `testing/verify/e2e/run_shm_leak_metrics.sh` |
| `run_zmq_metrics_ut_regression_remote.sh` | 功能拆分入 `ut/run_ut_remote.sh` | `testing/verify/ut/run_ut_remote.sh` |
| `run_zmq_rpc_metrics_remote.sh` | 功能拆分入 `st/run_st_zmq_metrics.sh` | `testing/verify/st/run_st_zmq_metrics.sh` |

归档时间：2026-04-25
