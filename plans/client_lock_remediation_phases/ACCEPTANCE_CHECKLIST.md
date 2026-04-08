# 明日验收清单（正确性 + 性能 + KV）

按顺序勾选。未勾选项请在 MR / 备注中说明原因（例如无集群仅跑门禁、perf 跳过等）。

**执行目录**：以下命令默认在 **Datasystem 仓库根目录**（含顶层 `CMakeLists.txt`）下执行；路径均为 **相对该根目录的完整相对路径**。

---

## A. 正确性（必须通过）

- [ ] **构建成功**：`cmake --build build` 无错误（或你们流水线等价通过；构建目录默认为 `build/`）。
- [ ] **全部 KV ST 用例通过**（`ds_st_kv_cache` 可执行文件内的全部 gtest；与 `ds_st`、`ds_st_object_cache` 不同目标）：
  - [ ] 在已配置集群与 ST 所需环境变量（与 CMake `TEST_ENVIRONMENT` / 流水线一致，含 `LD_LIBRARY_PATH` 等）的前提下，直接执行：  
    `build/tests/st/ds_st_kv_cache`，**退出码 0**（跑全量 gtest，等价于该 target 下 CTest 注册的全部用例）。  
    注意：**不要**仅用 `ctest --test-dir build -L object -L st` 当作「仅 KV ST」——`ds_st_object_cache` 同类标签会一并命中。
  - [ ] 合并前至少跑一次完整 KV ST；若 CI 只跑子集，MR 中说明并附上全量命令与结果摘要。
- [ ] **KV / brpc 参考用例通过**（在已启用 `ENABLE_BRPC_ST_REFERENCE` 的环境下）：
  - [ ] `bash scripts/verify/validate_brpc_kv_executor.sh --build-dir build` 退出码为 `0`，或
  - [ ] `ctest --test-dir build -R KVClientBrpcBthreadReferenceTest` 全绿。
- [ ] **与本改动相关的其它 st / 单测**：若 MR 改了 Object/mmap/ZMQ/日志，已补充或复跑对应测试（在 CI 或本地声明范围）。
- [ ] **无已知语义回退**：例如 refcount、shutdown 顺序、重连与 `SelectWorker` 行为，MR 描述中有说明或指向设计笔记。

---

## B. 性能（必须通过 — 须有绝对时延证据）

- [ ] 已保存 **阶段 0 基线** 一次：`plans/client_lock_baseline/runs/<时间>_<githash>/`（`collect_client_lock_baseline.sh`）。
- [ ] 已保存 **当前改动后** 一次同脚本输出目录。
- [ ] 若跑了 perf（未 `--skip-perf` 且 `plans/client_lock_baseline/runs/<本次run>/perf_exit.code==0`）：
  - [ ] 打开 **`plans/client_lock_baseline/runs/<本次run>/perf/kv_executor_perf_summary.txt`**，对比基线与当前的 **`inline_set_avg_us_mean`、`inline_get_avg_us_mean`**（或你们约定的其它绝对字段）。
  - [ ] **至少一项绝对 µs 数值较基线下降**（同机器、同 `ops/warmup`、同集群拓扑）。
  - [ ] **不能仅凭 ratio**（`set_ratio_mean` 等）作为唯一收益说明。
- [ ] 若 **未跑 perf**（无集群 / `perf_exit.code!=0`）：
  - [ ] MR 或附录中说明原因，并给出 **其它可重复绝对时延证据**（例如 gtest 打印的 p95/p99、或微基准脚本输出），否则本阶段性能验收 **不通过**（需补数据后再合）。

---

## C. 基线目录与对比命令（无 sudo）

```bash
# 基线（改代码前）
bash scripts/perf/collect_client_lock_baseline.sh --build-dir build

# 改代码后
bash scripts/perf/collect_client_lock_baseline.sh --build-dir build

# 对比（把下面两个路径换成实际 runs 子目录）
bash scripts/perf/compare_client_lock_baseline.sh \
  plans/client_lock_baseline/runs/<基线> \
  plans/client_lock_baseline/runs/<当前>
```

检查：

- `plans/client_lock_baseline/runs/<各run>/gate_exit.code` 均为 `0`。
- `plans/client_lock_baseline/runs/<各run>/SUMMARY.txt` 或对比输出中 **绝对时延行** 有改善说明。

---

## D. 快速否决项（任一即不合格）

- KV brpc 参考测试失败或 `gate_exit.code != 0`（在无合理解释的情况下）。
- 仅声称「倍率变好」但 **无任何绝对 µs/ms 对比**。
- 引入行为变化但 **无测试或说明** 覆盖 shutdown / ref / mmap 等敏感路径。

---

## E. 锁风险事项（来自 `kv_lock_in_syscall_cases_report.md`）

- [ ] **Case A（ZMQ）**：`SetPollOut/epoll_ctl` 不在 `outMux_` 临界区内执行，锁内仅做入队与状态位更新。
- [ ] **Case B（日志）**：`Provider::FlushLogs` 路径为“锁内快照、锁外 flush”，避免锁内潜在 `write/fsync`。
- [ ] **Case C（mmap）**：`LookupUnitsAndMmapFds` 保持三段式（锁内分类 → 锁外 RPC/mmap → 锁内回填）。
- [ ] **Case D（shutdown）**：`ShutDown` 不在 `shutdownMux_` 长锁内执行 worker `Disconnect`。
- [ ] **Case F（rediscover）**：`SelectWorker` 在 `switchNodeMutex_` 锁外执行，锁内仅快照与二次校验。
- [ ] **Case H/H-2（MemoryCopy）**：禁止在全局业务锁内执行大块 `MemoryCopy`；确认 `WLatch/UnWLatch` 契约与线程池背压观测。
- [ ] **Case E（GInc/GDec）**：当前轮次按计划放附录（暂不纳入主治理）；若后续开启，需按“锁内计数、锁外 RPC、锁内回滚”验收。

---

## F. 验收签字区（可选）

| 项目 | 结果 | 备注 |
|------|------|------|
| KV 用例 | ☐ 通过 ☐ 未跑/跳过 | |
| 绝对时延 | ☐ 有下降 ☐ 待补 | 基线 run：______ 当前 run：______ |
| 评审人 | | 日期： |
