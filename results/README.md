# `results/` — 本地验证输出（不提交）

本目录用于存放你或 Agent **按 [`docs/verification/手动验证确认指南.md`](../docs/verification/手动验证确认指南.md) 等文档执行验证时**的终端输出、环境快照等，便于**对照文档中的「验证执行记录」复现**。

- **Git**：除本 `README.md` 外，`results/` 下文件均被忽略，不会进入版本库。  
- **命名建议**：每次跑一套步骤建子目录，例如 `20260406-smoke/`、`20260406-executor-full/`。

## 可复现记录应包含什么

在每条日志**开头**粘贴（便于他人同环境对比）：

```text
# date: （UTC 或本地时区注明）
# hostname: $(hostname)
# DS=...  VIBE=...
# yuanrong-datasystem: $(cd $DS && git rev-parse --short HEAD 2>/dev/null || echo no-git)
# vibe-coding-files: $(cd $VIBE && git rev-parse --short HEAD 2>/dev/null || echo no-git)
```

然后粘贴**与文档一致的命令**及完整标准输出（可用 `tee`）。

## 示例：冒烟步骤写入文件

```bash
export DS="/绝对路径/yuanrong-datasystem"
export VIBE="/绝对路径/vibe-coding-files"
RUN="$VIBE/results/$(date +%Y%m%d)-smoke"
mkdir -p "$RUN"

{
  echo "# date: $(date -Iseconds)"
  echo "# hostname: $(hostname)"
  echo "# DS=$DS  VIBE=$VIBE"
  echo "# ds: $(git -C "$DS" rev-parse --short HEAD 2>/dev/null)"
  echo "# vibe: $(git -C "$VIBE" rev-parse --short HEAD 2>/dev/null)"
  echo "---- commands ----"
  set -x
  test -f "$DS/build.sh" && echo OK build.sh
  test -f "$VIBE/scripts/verify/validate_kv_executor.sh" && echo OK validate_kv_executor
  test -f "$DS/build/CMakeCache.txt" && echo OK CMakeCache
  test -x "$DS/build/tests/st/ds_st_kv_cache" && echo OK ds_st_kv_cache
  python3 "$VIBE/scripts/index/refresh_urma_index_db.py"
  CTEST_OUTPUT_ON_FAILURE=1 ctest --test-dir "$DS/build" --output-on-failure \
    -R "KVClientExecutorRuntimeE2ETest.SubmitAndWaitWithInjectedExecutor"
} 2>&1 | tee "$RUN/log.txt"
```

完整门禁（8 个 ST + 锁 perf）可把 [`手动验证确认指南.md`](../docs/verification/手动验证确认指南.md) **记录 B** 中的命令同样包进 `tee`。

## Client 故障与错误码（跑大批量用例时）

审视 **client 侧可能出现的故障与 `StatusCode`**：见 [`docs/reliability/03-status-codes.md`](../docs/reliability/03-status-codes.md)；日志 grep 与 Trace 粒度定位见 [`docs/observable/04-triage-handbook.md`](../docs/observable/04-triage-handbook.md)。建议在每次全量或夜间跑测目录下按需增加 **`CLIENT_FAULT_OBSERVATIONS.md`**。

## 与文档的对应关系

文档末尾 **「验证执行记录（维护用）」** 中的 **记录 A / 记录 B** 应与你在 `results/` 下保存的日志**命令行一致**；若环境不同（路径、分支），以你日志里的 `DS` / `git rev` 为准判断是否可比。
