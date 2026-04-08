# bpftrace 问题发现与识别（符号证据汇总）

## 1. 文档目标

基于以下证据，统一输出“已发现问题、风险等级、识别依据、改进优先级”：

- 符号化栈：`workspace/observability/bpftrace/trace_*_stacks.sym.txt`
- 采集报告：
  - `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_144830_report.md`
  - `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_150017_report.md`
  - `workspace/observability/reports/bpftrace/bpftrace_trace_20260402_151824_report.md`

## 1.1 本文采用的“证据链”口径（锁机制 + 系统调用）

为了判断“可能导致死锁/假死/长尾放大”的风险路径，本文件要求证据同时覆盖两类信号（同一 KV 场景下出现即可）：

1. **锁等待/锁竞争机制证据**：通常表现为 `futex(2)`。在 Linux 上，pthread mutex/condvar/rwlock 等在竞争或等待时常会落到 futex 等待/唤醒机制。
2. **阻塞系统调用证据（IO/等待类）**：如 `read/write`、`recvfrom/sendto`、`epoll_wait/poll` 等。

说明：

- bpftrace 当前采集的是“系统调用入口 + 用户态栈”，不会直接标注“当前线程持有哪些业务锁”。因此本文用 **“futex 热 + IO 系统调用热”** 作为强风险证据，再结合入口用例与代码审计完成“是否存在持锁跨 IO”的最终判定。

## 2. 识别结论（按风险优先级）

### P0：KV 热路径“等待 + IO”并存，尾延迟放大风险高

识别依据：

- 20260402_151824（KV set/get）：
  - `futex max≈10000, sum≈14306`
  - `rw max≈1625, sum≈3021`
- 20260402_144830、20260402_150017 也持续呈现 `futex + rw` 主导。

结论：

- 运行时主瓶颈不是网络收发，而是等待类与本地 IO/日志类叠加。
- 在高并发 set/get 下更明显，属于首要治理项。

### P0：日志链路（spdlog）在 rw 热簇反复命中

识别依据（来自 `.sym.txt` 聚合栈段）：

- `ds_spdlog::level::from_str(...)`
- `ds_spdlog::details::E_formatter<...>::format(...)`
- 在 `--- read/write (top 15) ---` 附近重复出现。

结论：

- 日志路径已进入高频阻塞调用栈，可能放大锁持有时长和尾延迟。
- 若业务锁/临界区与日志输出耦合，风险进一步上升。

### P1：grpc 路径“被触发但未完成聚合栈函数级归因”

识别依据：

- 20260402_150017 的正文日志命中大量 grpc 失败信息（`grpc_session.h`、`RPC unavailable`、`Failed to connect`）。
- 但在 `--- futex` 之后聚合栈段，`grpc/gpr/protobuf` 可读符号仍为 0。

结论：

- 不能判定 grpc 不参与；只能判定“当前 bpftrace 聚合 ustack 对 grpc 可见性不足”。
- grpc 需通过补充证据链（如 perf dwarf）完成函数级归因。

### P1：libzmq 有命中但占比低，当前不是主导瓶颈

识别依据：

- 多轮 `.sym.txt` 命中 `libzmq.so...+offset`，但频次远低于 `futex/rw/spdlog` 主簇。

结论：

- zmq 在路径上存在，但现阶段优先级低于日志链路与等待热点。

### P2：采样完整性噪声存在，影响“函数级”精度

识别依据：

- `.sym.txt` 出现 `ERROR: failed to look up stack id -17`。
- 仍有一定比例地址未符号化。

结论：

- 不影响“热点类别与风险方向”判断；
- 但会影响精细到函数行级的最终归因准确性。

## 3. 证据片段（可追溯）

- `trace_20260402_151824_stacks.sym.txt`：
  - `--- futex (top 25) ---` 后出现 `failed to look up stack id -17`
  - `ds_spdlog::level::from_str(...)`
  - `--- read/write (top 15) ---` 下重复 `ds_spdlog::details::E_formatter...`
  - `libzmq.so.5.2.5+0x3deae`
- `bpftrace_trace_20260402_150017_report.md`：
  - grpc 日志命中充分，但聚合栈命中不足
- `bpftrace_trace_20260402_151824_report.md`：
  - KV set/get 下 `futex/rw` 热度显著抬升

## 3.1 调用栈级证据（futex / IO / net）

以下证据均来自 `trace_20260402_151824_stacks.sym.txt` 的聚合段（`--- futex` 起）。

### 3.1.1 入口接口映射（哪些 Datasystem KV 接口触发该路径）

本轮采集用例过滤器为 `KVCacheClientTest.`*（见 `trace_20260402_151824_stacks.sym.txt` 文件头部的 gtest filter 日志）。

对应的 KV 接口触发点（来自 `tests/st/client/kv_cache/kv_cache_client_test.cpp` 的直接调用）：

- `KVCacheClientTest.TestSingleKey`：
  - `KVClient::Set(key, value)`
  - `KVClient::Get(key, valueGet)` / `KVClient::Get(key, buffer)`
  - `KVClient::Del(key)`
- `KVCacheClientTest.TestMsetAndMGet`：
  - `KVClient::MSet(keys, values, ...)`
  - `KVClient::Get(keys, getVals)`（multi-get）
- `KVCacheClientTest.TestSetAndExistConcurrently`（并发场景）：
  - `KVClient::Set(...)` 与 `KVClient::Exist(...)` 并发

因此，“走到 futex / IO 热点路径”的上层入口接口至少包含：**Set / Get / MSet / Exist / Del**（客户端侧）。

- **futex 证据（等待主导）**
  - TOP1: `count=10000`
  - 关键帧包含：
    - `datasystem::worker::Authenticate<...>()`
    - `datasystem::worker::stream_cache::MemAllocRequestList<...>::HandleBlockedCreateTimeout(...)`
  - 说明：等待热点并非偶发，已经在业务路径形成高频聚集。
  TOP1 栈片段（展开更多帧，便于后续把“锁等待”落到具体接口/模块）：
  - `check_node_accept_bytes @ ./posix/regexec.c:3864:10`
  - `datasystem::worker::Authenticate<datasystem::CreateShmPageReqPb>(...) @ src/datasystem/worker/authenticate.h:100`
  - `... std::_Sp_counted_base<...>::_M_release() ...`（共享指针引用计数路径）
  - `datasystem::worker::stream_cache::MemAllocRequestList<...>::HandleBlockedCreateTimeout(...) @ src/datasystem/worker/stream_cache/client_worker_sc_service_impl.cpp:2489`
  - `std::_Hashtable<...>::_M_rehash(...) @ /usr/include/c++/9/bits/hashtable.h:2104`
  - `... ds_st_kv_cache+0x...`（部分地址帧尚未还原）
- **read/write 证据（IO主导）**
  - TOP1: `count=1625`
  - TOP2: `count=1082`
  - TOP3: `count=144`
  - 关键帧包含：
    - `ds_spdlog::level::from_str(...)`
    - `ds_spdlog::details::E_formatter<...>::format(...)`
  - 说明：`rw` 热簇与日志格式化/级别解析持续共现，支持“日志链路放大IO阻塞”判断。
  TOP1 / TOP2（均为 `count=1625`/`1082`）的共同片段显示 `ds_spdlog::level::from_str(...)` 紧贴在 `read/write` 系统调用栈上，属于“IO 系统调用可追溯到日志链路”的强证据。
- **recvfrom/sendto 证据（网络非主导）**
  - TOP 仅 `count=1` 级别（多个簇）
  - 说明：网络收发在本轮不是主瓶颈来源。
- **zmq 证据（存在但低频）**
  - 命中：`libzmq.so.5.2.5+0x3deae`
  - 说明：路径存在，但计数明显低于 `futex/rw` 主簇。
- **采样完整性噪声**
  - `ERROR: failed to look up stack id -17 (pid ...)`
  - 说明：会影响函数级精度，但不改变热点类别结论。

## 3.2 grpc 证据的边界说明（日志命中 vs 聚合栈命中）

来自 `trace_20260402_150017_stacks.sym.txt` 的统计：

- 全文件日志正文命中：
  - `grpc_session.h`：`234177`
  - `RPC unavailable`：`312252`
  - `etcd_watch.cpp`：`17`
  - `etcd_keep_alive.cpp`：`10`
- 聚合栈段（`--- futex` 起）命中：上述关键词均为 `0`

结论：

- grpc 链路“被触发”证据充分（日志侧）。
- 但 bpftrace 聚合 ustack 仍缺 grpc 可读帧，不足以完成函数级闭环归因。

## 4. 整改识别建议（按实施顺序）

1. **先做 P0**：KV 热路径日志治理（锁外写、批量化、降级开关、采样率策略）。
2. **再做 P1**：grpc 路径补证据（`perf dwarf` 与 bpftrace 交叉）。
3. **持续做 P2**：改进符号化与采样稳定性，减少 `stack id -17` 噪声。

---

本文件是“问题发现识别”总入口；具体运行记录见：

- `plans/lock_io_blocking_special_assessment/06_symbolization_execution_log.md`

