# 符号化准备执行记录（午休代跑）

> 目标：在**不使用 sudo** 的前提下，先完成可执行的准备动作；把必须 sudo 的步骤明确列出，方便恢复后直接继续。

## 1) 已执行（无需 sudo）

### 1.1 工具检查

执行：

```bash
command -v llvm-symbolizer || true
command -v perf || true
command -v bpftrace || true
```

结果：

- `bpftrace` 已存在（`/usr/bin/bpftrace`）。
- 当前 shell 未返回 `llvm-symbolizer` 路径（后续符号化建议安装/确认）。
- 当前 shell 未返回 `perf` 路径（若后续走 perf 备用链路，需要先安装）。

### 1.2 client 三方依赖收敛（ldd/readelf）

执行：

```bash
bash scripts/build/list_client_third_party_deps.sh --build-dir build --target lib
```

结果（摘要）：

- `libdatasystem.so` 的关键依赖包含：`grpc++/grpc/gpr`、`protobuf`、`libzmq`、`openssl`、`abseil`、`zlib`、`spdlog`、`tbb`、`securec`。
- 输出中提示了对应源码根目录：`build/_deps/{grpc,protobuf,zeromq,openssl,...}-src`。

### 1.3 启动“符号友好”重编（进行中）

已执行：

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fno-omit-frame-pointer -g" \
  -DCMAKE_C_FLAGS="-fno-omit-frame-pointer -g" && \
cmake --build build --target ds_st_kv_cache -j"$(nproc)"
```

状态（记录时）：

- 进程仍在运行，构建进度约在中段（已见到 `common_etcd_client`、`common_rpc_zmq*` 等目标编译/链接日志）。

你回来后可用以下命令确认是否完成：

```bash
pgrep -af "cmake --build build --target ds_st_kv_cache" || echo "build command finished"
```

若完成，建议立即验证目标是否存在：

```bash
test -x build/tests/st/ds_st_kv_cache && echo "ds_st_kv_cache ready"
```

## 2) 已准备但未执行（无需 sudo）

新增脚本：

- `scripts/perf/bpftrace/env_for_symbols.sh`：设置 `LLVM_SYMBOLIZER_PATH`、`BPFTRACE_MAX_STRLEN`。
- `scripts/perf/bpftrace/symbolize_bpftrace_stacks.py`：`maps + 地址 -> 符号` 后处理。
- `scripts/perf/perf_record_kv_lock_io.sh`：`perf record --call-graph dwarf` 备用链路。
- `scripts/perf/bpftrace/RUN_SYMBOLS.txt`：完整步骤说明。

## 3) 需要 sudo 的步骤（已明确）

### 3.1 安装工具（若缺）

```bash
sudo apt-get install -y llvm llvm-symbolizer linux-tools-common linux-tools-generic
```

> 发行版不同时包名会变；至少保证 `llvm-symbolizer`、`perf` 可用。

### 3.2 运行 bpftrace（保留符号环境）

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh --out-dir workspace/observability/bpftrace
```

### 3.3（可选）修复 bpftrace 输出目录权限

脚本已自动尝试 `chown`，但若历史目录仍是 root：

```bash
sudo chown -R "$USER" workspace/observability/bpftrace
```

### 3.4（可选）perf 权限

若 `perf record` 报权限：

```bash
sudo sysctl kernel.perf_event_paranoid=-1
```

## 4) 你回来后最短继续路径

1. 先确认第 1.3 的编译是否完成。  
2. 跑 `BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh ...`。  
3. 另开终端抓 maps，再跑 `symbolize_bpftrace_stacks.py` 生成 `*.sym.txt`。  
4. 再基于 `*.sym.txt` 回填 `04/05` 的三方 lock+IO 归因结论。  

## 5) 2026-04-02 14:48:30 这轮执行补充（非 root 已完成）

输入：

- `workspace/observability/bpftrace/trace_20260402_144830_stacks.txt`
- `workspace/observability/bpftrace/trace_20260402_144830_maps.txt`

执行：

```bash
python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \
  --maps workspace/observability/bpftrace/trace_20260402_144830_maps.txt \
  workspace/observability/bpftrace/trace_20260402_144830_stacks.txt \
  -o workspace/observability/bpftrace/trace_20260402_144830_stacks.sym.txt
```

产物：

- `workspace/observability/bpftrace/trace_20260402_144830_stacks.sym.txt`
- `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_144830_report.md`

观察结论（摘要）：

- 已看到 `ds_spdlog` 符号与 `libzmq` 动态库帧，不再是“纯地址不可读”。
- 本轮仍未看到 `grpc` 可读符号，需在后续用更聚焦 grpc 的测试路径补采样验证。

脚本修正（本轮为保证可落地执行）：

1. 修复 maps 解析 bug（路径字段拼接）。  
2. 增加地址解析缓存（同一地址只符号化一次）。  
3. 下调单次外部符号器超时，避免长时间卡住。  

## 6) 2026-04-02 15:00:17（grpc/etcd 定向 filter）补充

输入：

- `workspace/observability/bpftrace/trace_20260402_150017_stacks.txt`
- `workspace/observability/bpftrace/trace_20260402_150017_maps.txt`

执行（非 root）：

```bash
python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \
  --maps workspace/observability/bpftrace/trace_20260402_150017_maps.txt \
  workspace/observability/bpftrace/trace_20260402_150017_stacks.txt \
  -o workspace/observability/bpftrace/trace_20260402_150017_stacks.sym.txt
```

产物：

- `workspace/observability/bpftrace/trace_20260402_150017_stacks.sym.txt`
- `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_150017_report.md`

结论摘要：

- 正文日志里大量出现 `grpc_session.h` / `RPC unavailable`（grpc 路径已触发）。
- 但在 `--- futex` 之后聚合栈段里，`grpc/gpr/protobuf` 仍未形成可读栈帧。
- `ds_spdlog` 与 `libzmq` 仍可见；系统调用分布继续表现为 `futex + rw` 主导。

## 7) 2026-04-02 15:18:24（KV set/get 重点）补充

输入：

- `workspace/observability/bpftrace/trace_20260402_151824_stacks.txt`
- `workspace/observability/bpftrace/trace_20260402_151824_maps.txt`

执行（非 root）：

```bash
python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \
  --maps workspace/observability/bpftrace/trace_20260402_151824_maps.txt \
  workspace/observability/bpftrace/trace_20260402_151824_stacks.txt \
  -o workspace/observability/bpftrace/trace_20260402_151824_stacks.sym.txt
```

产物：

- `workspace/observability/bpftrace/trace_20260402_151824_stacks.sym.txt`
- `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_151824_report.md`

结论摘要：

- 本轮 `futex/rw` 均明显升高（`futex top≈10000`，`rw top≈1625`）。
- 聚合栈里继续命中 `ds_spdlog`，`libzmq` 仅少量命中。
- 聚合栈段仍未出现可读 `grpc/gpr/protobuf`；同时出现 `failed to look up stack id -17`，提示局部栈完整性受限。
