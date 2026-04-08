# brpc+bthread 参考用例说明（兼容工具链）

## 目标

- 在 `tests` 内提供真实 `brpc` client/server RPC 交互。
- 在 server 端 `bthread` 回调中调用 `KVClient::Set/Get`。
- 通过注入适配 `bthread` 的 executor + wait 机制，演示死锁对照（bad timeout / good success）。
- 不修改 `src` 业务实现，仅通过测试与可选 CMake 开关接入。

## 关键文件

- 用例：`tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp`
- brpc proto：`tests/st/client/kv_cache/kv_brpc_bridge.proto`
- CMake 接入：`tests/st/CMakeLists.txt`
- 一键引导脚本：`scripts/build/bootstrap_brpc_st_compat.sh`

## 一键引导（方案 A）

先确保工程已完成一次普通配置（有 `build/CMakeCache.txt`）：

```bash
cmake -S . -B build
```

然后执行兼容工具链引导：

```bash
bash scripts/build/bootstrap_brpc_st_compat.sh --build-dir build --out-dir .third_party/brpc_st_compat
```

脚本会：

1. 从 `build/CMakeCache.txt` 读取工程 protobuf 路径；
2. 构建并安装固定版本 `gflags/leveldb/brpc` 到本地目录；
3. 用同一 protobuf `protoc` 重新生成 `kv_brpc_bridge.pb.cc/.h`，避免 ABI/头文件错配。

## 构建与运行

```bash
cmake -S . -B build \
  -DENABLE_BRPC_ST_REFERENCE=ON \
  -DBRPC_ST_ROOT=.third_party/brpc_st_compat/install

cmake --build build --target ds_st_kv_cache -j

ctest --test-dir build --output-on-failure -R "KVClientBrpcBthreadReferenceTest"
```

也可以直接一键执行：

```bash
bash scripts/verify/validate_brpc_kv_executor.sh
```

若要同时输出该特性对应的覆盖率 HTML：

```bash
bash scripts/verify/validate_brpc_kv_executor.sh \
  --build-dir build_cov \
  --coverage-html
```

覆盖率报告输出到：

- `build_cov/coverage_kvexec/index.html`

默认统计并聚焦以下文件：

- `src/datasystem/client/kv_cache/kv_client.cpp`
- `src/datasystem/client/kv_cache/kv_executor.cpp`
- `tests/st/client/kv_cache/kv_client_brpc_bthread_reference_test.cpp`

## Set/Get 开销实验（Python + matplotlib）

```bash
python3 scripts/perf/kv_executor_perf_analysis.py \
  --build-dir build \
  --runs 5 \
  --ops 120 \
  --warmup 20 \
  --output-dir workspace/observability/perf
```

输出文件：

- `workspace/observability/perf/kv_executor_perf_runs.csv`
- `workspace/observability/perf/kv_executor_overhead_ratio.png`
- `workspace/observability/perf/kv_executor_perf_summary.txt`

关注指标：

- `set_avg_ratio` / `get_avg_ratio`（injected / inline）
- 建议验收口径：平均倍率不超过 `1.20`（即 <=20% 额外开销）

## 预期结果

- `bad` 模式：RPC 超时（验证死锁风险路径可触发）。
- `good` 模式：RPC 返回成功，且 `Set/Get` 状态为 `K_OK`（验证注入机制规避死锁）。

## 当前验证状态（截至 2026-04-01）

- 参考用例、注入逻辑、脚本入口均已落地并打通。
- 已使用 `brpc 1.16.0` + 本地兼容构建脚本成功构建 `ds_st_kv_cache`。
- 用例 `KVClientBrpcBthreadReferenceTest.BrpcRpcBthreadKvDeadlockContrast` 已实测通过。

## 快速排查建议

1. 清理 `brpc` 构建目录重试：
   ```bash
   rm -rf .third_party/brpc_st_compat/src/brpc/build
   bash scripts/build/bootstrap_brpc_st_compat.sh --build-dir build --out-dir .third_party/brpc_st_compat
   ```
2. 若继续失败，优先确认 `BRPC_ST_ROOT` 指向 `.third_party/brpc_st_compat/install`，并重新 configure 一次。
