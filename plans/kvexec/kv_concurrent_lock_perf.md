# KV 高并发批量接口延迟基准（验证 client 锁范围优化）

**执行目录**：以下命令在 **Datasystem 仓库根目录** 下执行；`build/` 为相对该根的 CMake 构建目录。

## 目的

在 **多线程共享同一 `KVClient`** 的前提下，对 **`MCreate` → 填 Buffer → `MSet(buffers)` → `Get(keys, vals)`（批量 MGet）→ `Exist`** 做重复压测，输出各段 **avg / p95 / p99**（微秒），用于对比锁范围优化前后的尾延迟。

单 key 的 `Set`/`Get` 不再作为本用例主路径。

## 用例

- 源码：`tests/st/client/kv_cache/kv_client_executor_runtime_e2e_test.cpp`
- 用例名：`KVClientExecutorRuntimeE2ETest.PerfConcurrentMCreateMSetMGetExistUnderContention`
- 每轮：唯一 key 前缀、`batch_keys` 个 key、每 key `buffer_bytes` 字节；`MCreate` 后 `WLatch`/`MemoryCopy`/`UnWLatch`，再 `MSet`；然后 `Get(vector)`、`Exist`；最后 `Del(keys)` 清理。
- 成功时 stdout 一行：  
  `PERF_CONCURRENT_BATCH threads=... ops_per_thread=... batch_keys=... buffer_bytes=... mcreate_avg_us=... mcreate_p95_us=... mcreate_p99_us=... mset_... mget_... exist_...`

## 运行方式

```bash
cmake --build build --target ds_st_kv_cache -j8
bash scripts/perf/run_kv_concurrent_lock_perf.sh build
# 或
ctest --test-dir build --output-on-failure -R PerfConcurrentMCreateMSetMGetExistUnderContention
```

## 环境变量（可选）

| 变量 | 默认 | 含义 |
|------|------|------|
| `DS_KV_CONC_PERF_THREADS` | 16 | 并发线程数 |
| `DS_KV_CONC_PERF_OPS` | 20 | 每线程正式计量「整批」轮数 |
| `DS_KV_CONC_PERF_WARMUP` | 3 | 每线程预热批次数 |
| `DS_KV_CONC_BATCH_KEYS` | 4 | 每批 key 数（**1～16**） |
| `DS_KV_CONC_BUF_BYTES` | 4096 | 每 key 分配/写入字节数（**256～524288**） |

## 对比方法

1. 固定机器与 worker 配置，优化前后各跑一遍，保存 `PERF_CONCURRENT_BATCH` 行。  
2. 优先看 **`mcreate_p99_us` / `mset_p99_us` / `mget_p99_us` / `exist_p99_us`**（mmap、ZMQ、ref 等更易体现在 MCreate/MSet/MGet 链上）。  
3. 调整 `DS_KV_CONC_BATCH_KEYS` 与 `DS_KV_CONC_BUF_BYTES` 可放大 client 侧批处理与 shm 路径压力。

## 说明

- 依赖 ST 集群（与 `KVClientExecutorRuntimeE2ETest` 相同）。  
- 不设硬性性能阈值：通过表示逻辑与采样完整；性能结论由人工对比打印行得出。  
- API 对应关系：**批量读**使用 `KVClient::Get(const std::vector<std::string> &keys, std::vector<std::string> &vals, ...)`，与产品语义上的 MGet 一致。
