# KV Client 性能关键路径与采集手册（SDK + Worker）

目标：针对读写性能问题，给出可执行的关键路径拆解与采集方法，特别关注：
- 线程切换与线程池排队
- RPC 框架等待与重试
- URMA 数据面与降级到 TCP 的影响

## 1. 关键路径（建议先看 Excel Sheet4）

请结合 [`../workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx`](../workbook/kv-client/kv-client-观测-调用链与URMA-TCP.xlsx) 的 `Sheet4_性能关键路径`：
- 读路径：`client1->worker1` -> `worker1->worker2` -> `worker1->worker3` -> `worker3(URMA)` -> `client1解析`
- 写路径：`client1->worker1` 控制面 + `worker1->worker3` 数据面

核心判定：
- **P99上升 + 重试增多**：先看 RPC/网络与 worker 排队；
- **fallback to TCP/IP payload 增多**：URMA退化导致 CPU 拷贝放大；
- **context switch 高**：优先排查锁竞争、线程池配置、阻塞 syscall。

## 2. 采集命令（按优先级）

### 2.1 基础（必做）
- `top -H -p <worker_pid>`
- `pidstat -w -p <worker_pid> 1`
- `pidstat -u -p <worker_pid> 1`
- `grep -E "RPC timeout|Retry|fallback to TCP/IP payload|poll jfc|wait jfc" worker.log sdk.log`

### 2.2 syscall 与阻塞
- `strace -f -tt -T -p <worker_pid> -e trace=network,ipc,memory`
- 重点看：`recvmsg/sendmsg/futex/epoll_wait/mmap`

### 2.3 若有 perf（当前环境未安装）
- `perf stat -p <pid> -e context-switches,cpu-migrations,cache-misses,cycles,instructions -- sleep 30`
- `perf top -p <pid>`
- `perf record -g -p <pid> -- sleep 30 && perf report`

## 3. ST 验证建议（读写各一条）

可优先用以下 ST 做定向复现：
- 读：`tests/st/client/object_cache/client_get_test.cpp`
- 写：`tests/st/client/kv_cache/kv_client_mset_test.cpp`

建议流程：
1. 启动 worker + sdk 测试；
2. 同时采集 `pidstat/top/strace`；
3. 对齐日志时间窗，映射到 Excel `Sheet1 + Sheet4`；
4. 输出结论：瓶颈段位 + 责任域（RPC/OS/URMA/系统逻辑）。

## 4. 自动化判定思路

可将日志与系统指标统一成一条记录：
- `time, interface, stage, location, status_code, keyword, cswch, nvcswch, cpu, syscall_hotspot`

判定规则示例：
- 命中 `fallback to TCP/IP payload` 且 `cpu%`、`MemoryCopy` 上升 -> `URMA降级导致性能退化`
- `1001/1002` 增多且 worker 入口日志减少 -> `client1->worker1 控制面瓶颈`
- `cswch/nvcswch` 异常升高 + `futex` 热点 -> `线程/锁竞争瓶颈`

