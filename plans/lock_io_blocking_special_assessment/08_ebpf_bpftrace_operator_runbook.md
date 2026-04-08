# eBPF / bpftrace 操作指南（可复制）

> 用途：对 **`ds_st_kv_cache`** 采集 **futex / epoll / poll / 网络读写** 等 syscall 上的 **用户态栈**，用于 client 专项的 **lock + IO** 归因。  
> 仓库根目录默认：`/home/t14s/workspace/git-repos/yuanrong-datasystem`（请按你本机路径替换 `cd`）。

---

## 0.1 脚本执行逻辑（复现链路）

按下面顺序执行即可（每一步的输入/输出都固定）：

1. `scripts/build/list_client_third_party_deps.sh`
   - **输入**：`build/src/datasystem/client/libdatasystem.so`
   - **作用**：用 `readelf/ldd` 收敛 client 实际依赖，确定三方审计范围
   - **输出**：终端打印 `NEEDED` + `_deps/*-src` 对照

2. `scripts/perf/trace_kv_lock_io_bpftrace.sh`
   - **输入**：
     - `build/tests/st/ds_st_kv_cache`
     - `build/tests/st/ds_st_kv_cache_tests.cmake`（脚本里自动抽取 `LD_LIBRARY_PATH`）
     - `scripts/perf/bpftrace/kv_lock_io_stacks.bt`
   - **作用**：`bpftrace -c` 跑测试并采 `futex/epoll/poll/net/rw` 用户态栈
   - **输出**：`workspace/observability/bpftrace/trace_*_stacks.txt`

3. （可选）`scripts/perf/bpftrace/symbolize_bpftrace_stacks.py`
   - **输入**：
     - 第 2 步 `trace_*_stacks.txt`
     - `/tmp/ds_maps.txt`（你运行中抓的 `/proc/<pid>/maps` 快照）
   - **作用**：把栈中的 `0x...` 地址尽量转为符号/文件行号
   - **输出**：`workspace/observability/bpftrace/trace_*_stacks.sym.txt`

4. （可选替代）`scripts/perf/perf_record_kv_lock_io.sh`
   - **作用**：当 bpftrace 栈符号仍不足时，用 `perf --call-graph dwarf` 补充
   - **输出**：`workspace/observability/perf/kv_lock_io.perf.data`

5. 文档回填
   - 把第 2/3/4 步结果回填到：
     - `workspace/observability/reports/bpftrace/bpftrace_trace_*_report.md`
     - `plans/lock_io_blocking_special_assessment/04_evidence_based_analysis.md`

---

## 0. 权限说明

| 操作 | 是否需要 `sudo` |
|------|------------------|
| 运行 `bpftrace`（本指南主命令） | **需要** |
| `apt-get` 安装 `llvm` / `llvm-symbolizer` | **需要** |
| 抓 `/proc/.../maps`、Python 后处理符号 | **不需要** |

---

## 1. 前置检查（无需 sudo）

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

test -x build/tests/st/ds_st_kv_cache && echo "OK: ds_st_kv_cache exists" || echo "FAIL: build tests first"

command -v bpftrace && bpftrace --version
```

若测试二进制不存在，先编译：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
cmake -S . -B build
cmake --build build --target ds_st_kv_cache -j "$(nproc)"
```

（可选）符号友好编译，便于栈上出函数名：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_CXX_FLAGS="-fno-omit-frame-pointer -g" \
  -DCMAKE_C_FLAGS="-fno-omit-frame-pointer -g"
cmake --build build --target ds_st_kv_cache -j "$(nproc)"
```

---

## 2.（可选）安装 llvm-symbolizer — 需要 sudo

bpftrace 解析 C++ 符号时常依赖 `llvm-symbolizer`：

```bash
sudo apt-get update
sudo apt-get install -y llvm
command -v llvm-symbolizer || command -v llvm-symbolizer-18 || true
```

---

## 3. 主流程：跑 bpftrace（需要 sudo）

### 3.0 三步最简（推荐，便于复制）

第 1 步和第 3 步都不需要 sudo；第 2 步你手动输入 sudo 密码执行。

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

# Step 1: 正确性检查 + 打印 sudo 采集命令
bash scripts/perf/run_kv_lock_ebpf_workflow.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

# Step 2: 手动 sudo 采集（你输入 sudo 密码）
sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace \
  --filter 'KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention'

# Step 2.1: 立即确认并修正输出目录权限（避免后续无法读写）
OUT_DIR="/home/t14s/workspace/git-repos/yuanrong-datasystem/workspace/observability/bpftrace"
sudo chown -R "$USER":"$(id -gn)" "$OUT_DIR"
chmod -R u+rwX "$OUT_DIR"
```

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

# Step 3: 分析（把文件名替换成你的实际产物）
python3 scripts/perf/analyze_kv_lock_bpftrace.py \
  --baseline workspace/observability/bpftrace/trace_BASELINE_stacks.txt \
  --current workspace/observability/bpftrace/trace_CURRENT_stacks.txt
```

---

在仓库根目录执行（**推荐**：把符号相关环境传入 root）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

若提示 `BPFTRACE_MAX_STRLEN ... exceeds ... 200 bytes`，用兼容值重跑：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
BPFTRACE_MAX_STRLEN=200 BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

新版脚本会额外输出：

- `trace_* .pid`：被追踪测试进程 pid
- `trace_*_maps.txt`：自动后台抓取的 `/proc/<pid>/maps` 快照（用于后处理符号化）
- `trace_*_maps_bg.pid`：后台抓取进程 pid（脚本结束时会回收）

说明：

- 默认 gtest filter：**`KVClientExecutorRuntimeE2ETest.*`**（与 `scripts/perf/trace_kv_lock_io.sh` 一致）。  
- 若要改 filter：  
  `FILTER='YourSuite.*' BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh ...`
- 若要**补 grpc/etcd 路径**（推荐下一轮）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
BPFTRACE_SYMBOL_ENV=1 sudo -E bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace \
  --filter 'KVClientEtcdDfxTest.LEVEL1_TestEtcdRestart:KVClientEtcdDfxTest.TestEtcdCommitFailed:KVClientEtcdDfxKeepAliveTest.LEVEL1_TestEtcdKeepAlive:KVClientEtcdDfxTestAdjustNodeTimeout.TestSetHealthProbe:KVClientEtcdDfxTestAdjustNodeTimeout.TestRestartDuringEtcdCrash'
```
- 结束时会打印一行：  
  `[DONE] bpftrace stack report: .../workspace/observability/bpftrace/trace_YYYYMMDD_HHMMSS_stacks.txt`  
  **该路径即本次证据文件。**
- 建议紧接着执行一次权限兜底（即使脚本已自动 `chown`，这一步可避免环境差异）：

```bash
OUT_DIR="/home/t14s/workspace/git-repos/yuanrong-datasystem/workspace/observability/bpftrace"
sudo chown -R "$USER":"$(id -gn)" "$OUT_DIR"
chmod -R u+rwX "$OUT_DIR"
```
- 测试常需 **1～2 分钟以上**，终端先有 `[INFO]`，属正常。

若**不用**符号环境（最简）：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem
sudo bash scripts/perf/trace_kv_lock_io_bpftrace.sh \
  --build-dir build \
  --out-dir workspace/observability/bpftrace
```

---

## 4.（可选）抓 maps + 生成符号化副本 — 无需 sudo

### 4.1 在测试进程存活时抓 maps

**另开一个终端**，在 `ds_st_kv_cache` 仍在跑时执行：

```bash
pgrep -nx ds_st_kv_cache | xargs -I{} cat /proc/{}/maps > /tmp/ds_maps.txt
```

### 4.2 bpftrace 结束后做地址 → 符号

把 `trace_YYYYMMDD_HHMMSS_stacks.txt` 换成你上一步 `[DONE]` 里的文件名：

```bash
cd /home/t14s/workspace/git-repos/yuanrong-datasystem

python3 scripts/perf/bpftrace/symbolize_bpftrace_stacks.py \
  --maps workspace/observability/bpftrace/trace_YYYYMMDD_HHMMSS_maps.txt \
  workspace/observability/bpftrace/trace_YYYYMMDD_HHMMSS_stacks.txt \
  -o workspace/observability/bpftrace/trace_YYYYMMDD_HHMMSS_stacks.sym.txt
```

---

## 5. 输出在哪里、交给谁分析

- 原始栈：`workspace/observability/bpftrace/trace_*_stacks.txt`  
- 符号化后：`workspace/observability/bpftrace/trace_*_stacks.sym.txt`（若执行了第 4 节）

把 **`trace_*_stacks.txt` 或 `.sym.txt` 的路径**发给分析；或复制文件中从 **`--- futex (top`** 开始到文件末尾。

---

## 6. 故障排查

**`bpftrace` 报需要 root**  
→ 必须用 `sudo` 执行第 3 节。

**长时间无输出**  
→ gtest 在跑；等 `[DONE]`。已用 `tee`，终端与文件同步。

**`workspace/observability/bpftrace` 属主为 root 无法写**  
→ 脚本会尝试 `chown` 回 `SUDO_UID`；仍不行时：

```bash
sudo chown -R "$USER" /home/t14s/workspace/git-repos/yuanrong-datasystem/workspace/observability/bpftrace
```

**WSL2 上 eBPF 异常**  
→ 优先在原生 Linux 复现；详见 `05` §6。

**用例失败后有残留进程（推荐先清理再重跑）**

```bash
pkill -f 'ds_st_kv_cache|datasystem_worker|/usr/local/bin/etcd|trace_kv_lock_io_bpftrace.sh' || true
pkill -f '/usr/bin/addr2line -C -f -p -e .*/build/tests/st/ds_st_kv_cache' || true
sleep 1
pgrep -af 'ds_st_kv_cache|datasystem_worker|/usr/local/bin/etcd|trace_kv_lock_io_bpftrace.sh|/usr/bin/addr2line -C -f -p -e .*/build/tests/st/ds_st_kv_cache' || echo '[OK] no leftovers'
```

---

## 7. 相关脚本与长说明

- `scripts/perf/bpftrace/RUN_SYMBOLS.txt`：符号化细节  
- `scripts/perf/bpftrace/env_for_symbols.sh`：`source` 后手动跑 bpftrace 时用  
- `scripts/build/list_client_third_party_deps.sh`：client 依赖收敛（先做，避免看无关三方）  
- `05_client_scope_strace_and_third_party.md` §6 / §6.1：方法与专项口径
