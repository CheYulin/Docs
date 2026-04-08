# 手动验收：性能 · 覆盖率 · 用例正确性（需求前 / 需求后对照）

本文用于 **client 锁范围治理及相关改动** 的合并前验收。对照维度：**同一机器、同一集群拓扑、同一构建类型（Debug/Release）**，否则数值只能作趋势参考。

**路径与执行目录**：下文所有 shell 命令均在 **Datasystem 仓库根目录**（含 `CMakeLists.txt`、`scripts/`、`src/` 的那一层）作为当前工作目录执行；文中路径均为 **从该根目录起的相对路径**（不以 `/` 开头）。

---

## 0. 记录「需求前 / 需求后」两套证据

| 项目 | 需求前（基线） | 需求后（当前） |
|------|----------------|----------------|
| Git | `git rev-parse --short HEAD` 写入 `plans/client_lock_baseline/runs/<时间>_<githash>/RUN_META.txt` 或 MR | 同上 |
| 构建目录 | 默认 `build/`（与 `cmake -B build` 一致） | 同上路径，避免混用不同 CMake 缓存 |
| 集群 | 记录 worker 数、是否本机 ST | 必须与基线一致或 MR 说明差异 |

建议基线目录统一落在 `plans/client_lock_baseline/runs/<时间>_<githash>/`（由 `scripts/perf/collect_client_lock_baseline.sh` 生成）。

---

## 1. 用例正确性（必须通过）

### 1.1 全量 KV ST（`ds_st_kv_cache`）

**步骤**

1. `cmake --build build --target ds_st_kv_cache -j$(nproc)`
2. 在 ST 集群与流水线一致的 `LD_LIBRARY_PATH` 等环境下，直接执行：  
   `build/tests/st/ds_st_kv_cache`（跑满该二进制内全部 gtest；**勿**用 `ctest --test-dir build -L object -L st` 代替，以免混入 `ds_st_object_cache`）。

**预期结果**

- 退出码 `0`，无失败用例。
- 若 CI 仅跑子集：MR 中写明原因，并附上上述全量命令与 **失败数 0** 的日志摘要。

### 1.2 与本需求强相关的单测（示例）

**步骤**（按你实际改动勾选）

- mmap / ref：`ctest --test-dir build -R MmapManager`（或你们命名；UT 可执行文件路径见 `build/tests/ut/` 下对应目标）
- 其它：对 `object_client_impl` / ZMQ 等有定向 UT 则一并列出并执行。

**预期结果**

- 相关 UT 全绿；若有跳过，说明原因。

### 1.3 BrPC / executor 参考 ST（可选环境）

仅在开启 `ENABLE_BRPC_ST_REFERENCE` 且依赖齐全时：

**步骤**

- `bash scripts/verify/validate_brpc_kv_executor.sh --build-dir build`  
  或 `ctest --test-dir build -R KVClientBrpcBthreadReferenceTest`

**预期结果**

- `gate_exit.code` 为 `0`（若用 `scripts/perf/collect_client_lock_baseline.sh`，见 `plans/client_lock_baseline/runs/<本次run>/gate_exit.code`）。

### 1.4 语义与风险自证（文档级）

**预期**：MR 或设计笔记中说明 **无** refcount / shutdown / 重连 / `SelectWorker` 等已知回退；若有行为变化，写明测试或运维注意点。

---

## 2. 性能（需求前 / 需求后要有可比对数字）

### 2.1 门禁脚本 + 绝对时延摘要（与 `collect_client_lock_baseline.sh` 对齐）

**步骤**

```bash
# 需求前（基线）
bash scripts/perf/collect_client_lock_baseline.sh --build-dir build

# 需求后（同一集群、同一参数）
bash scripts/perf/collect_client_lock_baseline.sh --build-dir build

# 对比（将下列两段路径换成实际子目录名，仍相对于仓库根）
bash scripts/perf/compare_client_lock_baseline.sh \
  plans/client_lock_baseline/runs/<基线目录名> \
  plans/client_lock_baseline/runs/<当前目录名>
```

**预期结果**

- 两次 `plans/client_lock_baseline/runs/<各run>/gate_exit.code` 均为 `0`（在无集群等情况下按团队约定说明）。
- 若 `plans/client_lock_baseline/runs/<各run>/perf_exit.code == 0`：在 `plans/client_lock_baseline/runs/<各run>/perf/kv_executor_perf_summary.txt` 中对比 **`inline_set_avg_us_mean`、`inline_get_avg_us_mean`**（及你们约定的其它字段）；**需求后至少一项绝对 µs 优于基线**（同机同拓扑）。
- `perf_exit.code == 77`：表示未跑 perf，须在 MR 中补充 **其它绝对时延证据**（见 2.2），否则性能项按你们清单可判「待补」。

### 2.2 高并发批量路径（MCreate / MSet / MGet / Exist）

详见 `plans/kvexec/kv_concurrent_lock_perf.md`。

**步骤**

```bash
cmake --build build --target ds_st_kv_cache -j8
bash scripts/perf/run_kv_concurrent_lock_perf.sh build
# 或
ctest --test-dir build --output-on-failure -R PerfConcurrentMCreateMSetMGetExistUnderContention
```

**预期结果**

- 用例通过；stdout 出现一行 **`PERF_CONCURRENT_BATCH ...`**。
- **需求前 / 需求后** 各保存一行，优先对比 **`mcreate_p99_us`、`mset_p99_us`、`mget_p99_us`、`exist_p99_us`**（环境变量保持一致：`DS_KV_CONC_PERF_THREADS` 等）。

### 2.3 性能验收的「变化」应长什么样

| 维度 | 需求前 | 需求后（预期方向） |
|------|--------|---------------------|
| 绝对时延 | `*_avg_us_mean`、`*_p99_us` 基线值 | 同字段 **降低** 或持平且 CPU/负载说明合理 |
| 仅 ratio | 不足以单独作为合入依据 | 须有绝对 µs/ms 对照（与 `plans/client_lock_remediation_phases/ACCEPTANCE_CHECKLIST.md` 一致） |

---

## 3. 覆盖率（需求前 / 需求后可对照 HTML 或 lcov 摘要）

### 3.1 与 executor / KVClient 路径相关的聚焦覆盖（推荐）

依赖：`BUILD_COVERAGE=ON` 的构建目录、`lcov`/`genhtml` 可用；BrPC ST 参考环境按需开启。

**步骤**

```bash
# 示例：独立 coverage 构建目录（与团队 build.sh 一致即可）
bash scripts/verify/validate_brpc_kv_executor.sh \
  --build-dir build_cov \
  --coverage-html \
  --coverage-out-dir build_cov/coverage_kvexec
```

默认 `--feature-filter` 包含 `KVClientExecutorRuntimeE2ETest.*` 等（见脚本 `--help`）。

**预期结果**

- 测试阶段无失败；生成 `build_cov/coverage_kvexec/index.html`（与上文 `--coverage-out-dir build_cov/coverage_kvexec` 一致）。
- **需求前 / 需求后** 各保留一份 HTML 或导出关键文件的 **行覆盖率 / 分支覆盖率** 截图或数字；关注你改动的文件（如 `src/datasystem/client/mmap_manager.cpp`、`src/datasystem/client/object_cache/object_client_impl.cpp`、`src/datasystem/common/rpc/zmq/` 下相关源文件等）。

### 3.2 更广的 KV ST + 覆盖（可选，成本高）

若要对 **全量 KV ST**（`ds_st_kv_cache`）做覆盖：需在 **`build_cov/`**（或你们约定的目录）用 `BUILD_COVERAGE=ON` 配置并编译后，完整跑 `build_cov/tests/st/ds_st_kv_cache` 或等价 ctest 子集，再用 `lcov` 采集；预期为 **改动文件命中新增分支**，且 **无覆盖率异常下降**（大段未执行的新代码需在 MR 说明）。

---

## 4. 一页核对表（签字用）

| 序号 | 项 | 需求前证据 | 需求后证据 | 通过？ |
|------|----|------------|------------|--------|
| 1 | `ds_st_kv_cache` 全绿 | 日志 / CI | 同左 | ☐ |
| 2 | `scripts/perf/collect_client_lock_baseline.sh` 两次 + `scripts/perf/compare_client_lock_baseline.sh` | `plans/client_lock_baseline/runs/<基线>/` 与 `.../<当前>/` | 终端 diff 输出 | ☐ |
| 3 | `PERF_CONCURRENT_BATCH` 两行对比 | 保存 stdout | 同左 | ☐ |
| 4 | 覆盖率 HTML 或关键文件 % | 例如 `build_cov/coverage_kvexec/index.html` | 同左 | ☐ |
| 5 | MR 语义与风险说明 | N/A | 链接或段落 | ☐ |

---

## 5. 相关文件索引

- 验收清单：`plans/client_lock_remediation_phases/ACCEPTANCE_CHECKLIST.md`
- 并发批量 perf：`plans/kvexec/kv_concurrent_lock_perf.md`
- 基线采集 / 对比：`scripts/perf/collect_client_lock_baseline.sh`、`scripts/perf/compare_client_lock_baseline.sh`
- BrPC 校验与覆盖：`scripts/verify/validate_brpc_kv_executor.sh`
