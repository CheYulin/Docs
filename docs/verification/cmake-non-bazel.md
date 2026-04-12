# CMake：构建、测试、perf、覆盖率、examples（yuanrong-datasystem）

**约定**：`yuanrong-datasystem` 根目录执行 `build.sh`；`vibe-coding-files` 侧优先使用统一入口 `./ops` 执行验证/分析/文档脚本（见 [`scripts/README.md`](../../scripts/README.md)）。下文用 **`$DS`** 表示 datasystem 根目录，`$VIBE` 表示 `vibe-coding-files` 根目录（请按本机路径替换）。

**第三方缓存、安装产物（Client/Worker/whl·dscli）、tests/example 与 CMake 生成物路径**：见 [**构建产物目录与可复现工作流.md**](构建产物目录与可复现工作流.md)。

多根工作区：[`datasystem-dev.code-workspace`](../../datasystem-dev.code-workspace)。

```bash
bash "$DS/build.sh" -h
```

环境变量：`CTEST_OUTPUT_ON_FAILURE=1` 便于失败时查看用例输出。

---

## 0. 前提与常见坑

- **ST 用例**依赖 CMake 生成的 `LD_LIBRARY_PATH`。请使用 **`ctest --test-dir <build>`** 或 **`$VIBE/ops test.kv_executor`**；不要直接运行 `build/tests/st/ds_st_kv_cache`，否则易出现 `libeSDKOBS.so` 等缺失。
- **`cmake --build ... --target ds_st_kv_cache`** 可能触发大范围第三方逻辑。已编过时使用 **`$VIBE/ops test.kv_executor --skip-build <build>`**。
- **锁 / perf** 类用例可能耗时较长；超时见 `build.sh` 的 **`-m`**。

---

## 1. 构建（build）

在 **`$DS`**：

```bash
cd "$DS"
bash build.sh
bash build.sh -B ./build
```

增量 / Ninja：`build.sh -h`（`-i`、`-n`）。

---

## 2. Perf

在 **`$DS`** 打开 perf 埋点后重编：

```bash
cd "$DS"
bash build.sh -p on
```

KV **executor 注入 vs 内联**（需已构建 `ds_st_kv_cache`）：

```bash
bash "$VIBE/ops" analysis.kv_executor_perf \
  --build-dir "$DS/build" \
  --output-dir "$VIBE/workspace/observability/perf"
```

**锁竞争 batch**（关注输出中的 `PERF_CONCURRENT_BATCH`）：

```bash
bash "$VIBE/ops" runtime.lock_perf build
```

（第二个参数为**相对 datasystem 根**的构建目录名；也支持绝对路径。任意当前目录均可执行。）

---

## 3. 统计覆盖率（coverage）

在 **`$DS`**：

```bash
cd "$DS"
bash build.sh -c on -t build
bash build.sh -c html -t run_cpp -l 'st*'
```

**brpc ST + executor 聚焦覆盖率**（可选）：

```bash
bash "$VIBE/ops" test.brpc_kv_executor --build-dir "$DS/build" --coverage-html
```

**分支覆盖率含义与报告阅读方式**：优先看 CI 产出的 coverage HTML（`build.sh` 已使用 `lcov_branch_coverage=1`）；历史流程稿见 [`docs/observable/archive/分支覆盖率与定位定界-流程指南.md`](../observable/archive/分支覆盖率与定位定界-流程指南.md)。

---

## 4. 运行用例 — executor 注入

源文件：`$DS/tests/st/client/kv_cache/kv_client_executor_runtime_e2e_test.cpp`，夹具：`KVClientExecutorRuntimeE2ETest`。

```bash
bash "$VIBE/ops" test.kv_executor --skip-build "$DS/build"
```

首次需要编译 ST 目标时去掉 `--skip-build`。

**与注入相关的用例名**（节选）：`SubmitAndWaitWithInjectedExecutor`、`ReentrantCallInExecutorThreadShouldNotNestedSubmit`、`PerfSetGetInlineVsInjectedExecutor` 等。

```bash
export CTEST_OUTPUT_ON_FAILURE=1
ctest --test-dir "$DS/build" --output-on-failure -R "KVClientExecutorRuntimeE2ETest"
```

---

## 5. 运行用例 — 锁相关

```bash
ctest --test-dir "$DS/build" --output-on-failure -R "PerfConcurrentMCreateMSetMGetExistUnderContention"
bash "$VIBE/ops" runtime.lock_perf build
```

bpftrace / strace 工作流：`$VIBE/ops analysis.lock_ebpf_workflow`（底层仍调用 perf 子脚本，常需 root）。

---

## 6. 运行 Examples

在 **`$DS`**（见 `build.sh -h` 中 `-t run_example`）：

```bash
cd "$DS"
bash build.sh -t build    # 或你已完成的等价构建
bash build.sh -t run_example
```

示例构建目录一般为 `example/cpp/build`，由 `build.sh` 内逻辑管理。

---

## 7. IDE：URMA/UB 索引（仅索引，非编译）

```bash
bash "$VIBE/ops" analysis.refresh_urma_index
```

默认更新 **`$DS/.cursor/compile_commands.json`**（相对 `DATASYSTEM_ROOT` 解析）。详见 [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](../../plans/agent开发载体_vibe与yuanrong分工.plan.md) 第 4 节。

---

## 8. 建议的逐步验证顺序

1. `bash "$DS/build.sh"`  
2. `bash "$DS/build.sh" -t build`  
3. `bash "$VIBE/ops" test.kv_executor --skip-build "$DS/build"`  
4. `bash "$VIBE/ops" runtime.lock_perf build`  
5. `bash "$DS/build.sh" -p on` 后按需跑 `kv_executor_perf_analysis.py`  
6. `bash "$DS/build.sh" -c html -t run_cpp ...` 或 `validate_brpc_kv_executor.sh --coverage-html`  
7. `bash "$DS/build.sh" -t run_example`  

---

## 9. 全量测试入口（datasystem）

仍在 **`$DS`** 使用 `build.sh`：

```bash
bash build.sh -t run_cpp -l 'st*'
bash build.sh -t run_cases -l 'level1'
```

并行度 **`-u`**；Sanitizer **`-S`**。

**说明**：省略 **`-l`** 时，`run_cpp` 默认匹配 **`level*`**，用例数量可达**两千级以上**，且 **`-u` 过大**时多进程同时起服务易触发 **端口占用（如 `errno 98` EADDRINUSE）**，出现大批量失败未必是代码回归。可尝试 **`-u 2`**～**`4`** 或按 label 分段重跑；日常门禁仍以 **`ops test.kv_executor`** 与文档 [手动验证确认指南](手动验证确认指南.md) 为准。全量跑日志可落到 **`$VIBE/results/<时间戳>_run_cpp_*/`**（见 [`results/README.md`](../../results/README.md)）。
