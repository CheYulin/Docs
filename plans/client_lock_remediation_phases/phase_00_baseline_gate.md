# 阶段 0：基线与门禁（无 sudo）

## 目标

- 建立可对比的 **功能 + 绝对时延** 基线，后续各阶段 MR 必须能对照。
- **不依赖 root**：不用 bpftrace / 特权 perf record 作为硬门槛。

## 工作事项

1. **环境**：确认 `build/` 已 configure；若需 brpc 参考测试，按 `brpc_bthread_reference_test_guide.md` 完成 `bootstrap` 与 `-DENABLE_BRPC_ST_REFERENCE=ON`。
2. **跑通门禁**：
   - `bash scripts/verify/validate_brpc_kv_executor.sh`
   - 记录退出码；失败则先修环境或登记「当前基线不可用」。
3. **采集基线目录**：
   - `bash scripts/perf/collect_client_lock_baseline.sh --build-dir build`
   - 若有集群与 `ds_st_kv_cache`，**不要**加 `--skip-perf`，以便写入 `perf/kv_executor_perf_summary.txt` 中的 **绝对 µs**。
4. **归档**：将本次 `plans/client_lock_baseline/runs/<id>/` 路径写入团队 wiki 或 MR 模板「基线 run id」。

## 依赖

- 脚本：`scripts/verify/validate_brpc_kv_executor.sh`、`scripts/perf/collect_client_lock_baseline.sh`、`scripts/perf/compare_client_lock_baseline.sh`。
- 总说明：`plans/kvexec/executor_injection_prs/brpc_bthread_reference_test_guide.md`。

## 风险

- 无外部集群时 perf 子步骤会跳过（`perf_exit.code=77`），此时阶段 0 仍可通过 **功能门禁**，但阶段 1+ 合入前须补绝对时延或明确约定「下一环境补数」。

## 本阶段验收

| 类型 | 标准 |
|------|------|
| 正确性 | `validate_brpc_kv_executor.sh` 退出码 `0`；`gate_exit.code==0`。 |
| 性能 | 若成功生成 `perf/kv_executor_perf_summary.txt`，其中含 `inline_*_avg_us_mean` 等字段，作为后续对比基准。 |
| KV | 门禁脚本中包含的 `KVClientBrpcBthreadReferenceTest` 相关 ctest **通过**。 |

完成本阶段后，再开始阶段 1 代码改造。
