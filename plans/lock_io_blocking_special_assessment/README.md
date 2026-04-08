# Datasystem 锁内阻塞专项评估（总览）

本目录归档“锁内日志/RPC/IO 导致阻塞风险”的专项材料。

## 范围说明（重要）

- **当前客户专项口径**：**仅 Client 侧**（`src/datasystem/client`）及 client **调用图可达** 的本仓代码（etcd/gRPC 封装、ZMQ 相关 common）。  
- **三方分析口径**：**仅** `libdatasystem.so` **依赖且 client 实际调用** 的库；重点找 **lock + IO/阻塞**（`05` §1.1），不做无关 vendor 通读。  
- **不包含** worker、master 进程内逻辑（历史全栈表述已收敛，以 `05` 为准）。  
- **不包含 brpc / bthread 参考测试** 与 `.third_party/brpc_st_compat`（与本专项工作无关）。  
- **三种互补方法**：  
  1. **strace**：client 进程 syscall 面（见 `05` §2）。  
  2. **静态**：`ldd` 收敛依赖 + 沿调用图在 `_deps/*-src` 查持锁 IO（见 `05` §3）。  
  3. **bpftrace**：syscall 与用户态栈对齐，支撑三方归因（见 `05` §6）。

## 报告清单

- `05_client_scope_strace_and_third_party.md`：**范围 + strace + 静态 + bpftrace（先读）**
- `01_full_remediation_assessment.md`：Client 侧整改评估摘要与分级
- `02_hotspot_inventory.md`：Client + client 可达 common 热点清单
- `03_execution_plan_and_workload.md`：Client 专项阶段与人日
- `04_evidence_based_analysis.md`：证据化分析（strace + bpftrace + 代码片段）
- `06_symbolization_execution_log.md`：符号化准备执行记录（含“需 sudo”步骤清单）
- `07_client_third_party_call_sites.md`：**client 源码可确认的三方调用入口**（与 ldd 对齐，用于 lock+IO 裁剪审阅）
- `08_ebpf_bpftrace_operator_runbook.md`：**eBPF/bpftrace 可复制操作指南**（含 sudo/非 sudo 分段 + 脚本执行逻辑）
- `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_140947_report.md`：最新一轮 bpftrace 结果解读（`KVClientExecutorRuntimeE2ETest.*`）

## 证据来源

- 动态：`workspace/observability/strace/trace_*_report.md`（`scripts/perf/trace_kv_lock_io.sh`，默认 `KVClientExecutorRuntimeE2ETest.*`）
- bpftrace：`workspace/observability/bpftrace/trace_*_stacks.txt` 与 `workspace/observability/reports/bpftrace/bpftrace_trace_*_report.md`
- 历史参考：[`docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md`](../../docs/reliability/client-lock-in-rpc-logging-bthread-blocking.md)、`plans/lock_scope_analysis/third_party_lock_io_risk_report.md`（宽扫描，**专项结论以 `05` 的 client 可达性为准**）

## 复现步骤（可直接复制）

仓库根目录执行。

### 1) 准备与编译

```bash
cmake -S . -B build
cmake --build build --target ds_st_kv_cache -j 8
```

### 2) 复现 set/get 性能结论（图表，可选）

```bash
python3 scripts/perf/kv_executor_perf_analysis.py \
  --build-dir build \
  --runs 5 \
  --ops 120 \
  --warmup 20 \
  --output-dir workspace/observability/perf
```

### 3) 复现 strace（方法 A）

```bash
bash scripts/perf/trace_kv_lock_io.sh \
  --build-dir build \
  --out-dir workspace/observability/strace
```

### 4) 对照专项报告

推荐阅读顺序：`05` → `02` → `04` → `01` → `03`。

### 5) 复现 bpftrace（eBPF）调用栈

**完整可复制步骤（含可选符号化、权限表）见：`08_ebpf_bpftrace_operator_runbook.md`。**

最简一条（需 **sudo**）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

推荐（带符号环境，需 **sudo** + 建议先装 `llvm-symbolizer`）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

脚本会尝试把 `workspace/observability/bpftrace` **chown** 回普通用户；若仍属 root：`sudo chown -R "$USER" workspace/observability/bpftrace`。

样例解读：`workspace/observability/reports/bpftrace/bpftrace_trace_20260402_132806_report.md`。

辅助依赖收敛：

```bash
bash scripts/build/list_client_third_party_deps.sh --build-dir build --target lib
```
