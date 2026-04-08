# /kind refactor

**这是什么类型的 PR？**

/kind refactor（内部实现与性能/可调度性；默认不改变对外 API）

---

**这个 PR 是做什么的 / 我们为什么需要它**

- **收缩 client 侧关键锁临界区**，将持锁段聚焦在本地结构一致性维护，避免锁内执行 RPC、mmap、epoll_ctl 等潜在阻塞操作。
- 目标是降低高并发下的 `futex` 等待与长尾，缓解死锁风险，同时保持原有语义（成功路径等价，失败路径可回滚）。
- 本 MR 聚焦三个主路径：`MmapManager` 三段式、`globalRef` 加减引用锁外 RPC、`ZMQ` 出站队列与 `SetPollOut` 分离。

---

**此 PR 修复了哪些问题**

关联：client 锁范围治理（mmap / globalRef / ZMQ 出站）专项。  
Fixes #（请替换为实际 RFC / issue 编号）

---

**PR 对程序接口进行了哪些修改？**

- 无客户可见 API 签名变更；主要为锁范围与调用顺序调整。
- 对外行为语义保持：成功路径与改造前一致，异常路径通过回滚与清理逻辑收敛。

---

**关键信息**

- **正确性**：  
  - `GIncreaseRef/GDecreaseRef`：锁内只更新 `globalRefCount_`，RPC 失败可回滚；Decrease 后清理 `<=0` 条目。  
  - `LookupUnitsAndMmapFds`：三段式保证分类/回填一致性，RPC+mmap 移到锁外。  
- **性能与可调度性**：减少锁内阻塞调用，预期降低高并发下 `futex` 等待和尾时延抖动。  
- **死锁风险**：通过减少“持锁 + 阻塞操作”重叠窗口来缓解，而不是放宽数据一致性约束。

---

**实现思路（摘要，按实际改动填写）**

- **统一模式**：快照/本地表更新（短锁） → 解锁执行 RPC/系统调用 → 短锁回写或回滚。  
- **本 MR 主要文件**：  
  - `src/datasystem/client/mmap_manager.cpp`  
  - `src/datasystem/client/object_cache/object_client_impl.cpp`  
  - `src/datasystem/common/rpc/zmq/zmq_stub_conn.cpp`  
  - `tests/st/client/kv_cache/kv_client_executor_runtime_e2e_test.cpp`
- **关键点**：`outMux_` 仅保护出队列入队，`SetPollOut`（epoll_ctl 路径）在锁外执行。

---

**验证结果（简版）**

- 构建与用例：  
  - `ctest --test-dir build --output-on-failure -R "PerfConcurrentMCreateMSetMGetExistUnderContention"`  
  - 压测重点：`KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention`
- eBPF 采集与分析：  
  - `scripts/perf/trace_kv_lock_io_bpftrace.sh`（sudo 手动）  
  - `scripts/perf/analyze_kv_lock_bpftrace.py`（非 sudo）  
  - 流程：`scripts/perf/run_kv_lock_ebpf_workflow.sh`
- 文档：  
  - 操作手册：`plans/lock_io_blocking_special_assessment/08_ebpf_bpftrace_operator_runbook.md`  
  - 客户交流稿：`plans/client_lock_remediation_phases/CLIENT_LOCK_SCOPE_COMMUNICATION.md`

---

**Commit 提交信息说明**

**MR 标题格式（示例）**：`refactor[client]: 收缩 MmapManager 临界区（三段式 GetClientFd/mmap）`

**Commit 信息格式（建议）**：

```text
refactor(client): narrow lock scope for <module>

- move RPC/mmap/syscalls out of <mutex> critical sections
- preserve invariants for shutdown/ref/table updates
- update LOCK_SCOPE_INVENTORY / phase doc if applicable

Signed-off-by: <YourName> <your.email@example.com>
```

---

**Self-checklist**（请在提交前确认）

- [ ] **设计**：临界区内无新增 RPC/长等待；必要时已文档化例外。  
- [ ] **测试**：相关 ST / 门禁已通过（按触及模块勾选）。  
- [ ] **清单**：`LOCK_SCOPE_INVENTORY.md` 与阶段 md 与实现一致。  
- [ ] **接口**：无未声明的对外 API 行为变化。  
- [ ] **性能**：有简要的时延或基线说明（若 claim 性能收益）。
