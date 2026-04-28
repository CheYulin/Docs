# 默认远端构建（rsync + Bazel）与构建产物排查

在 **Bazel 7.4+** 与全量 third-party 依赖下，**推荐默认在远程主机**（如 `xqyun-32c32g`）完成 **datasystem** 的 `bazel build` / `bazel test`；本机可只做编辑，由 **rsync 推送代码** 后在远端执行编译。

- **全量构建脚本**（`build.sh` + CMake + ctest 流水线）：`remote_build_run_datasystem.sh`（同目录）。  
- **仅 Bazel 目标**（如 ST/单测）：用下面的 **`rsync_datasystem_remote_bazel.sh`**，快、且与 `.bazelversion` 对齐。

---

## 1. 约定

| 项 | 建议值 |
|----|--------|
| **远程主机** | `xqyun-32c32g`（`~/.ssh/config` 中配置的用户名/别名） |
| **远端父目录** | `~/workspace/git-repos`（与常见布局一致时：远端 `yuanrong-datasystem` 为 `${REMOTE_BASE}/yuanrong-datasystem`） |
| **第三方缓存** | **`DS_OPENSOURCE_DIR`** 指向**与 build 输出目录不同**的持久目录，例如 `~/.cache/yuanrong-datasystem-third-party`（与仓库根 `.cursor` 规则一致，避免每清一次 `build/` 就重下三方） |

---

## 2. 同步：rsync

- 使用仓库内 **exclude 列表**（忽略 `.git/build/output/bazel-*` 等大目录，减少传输与污染远端）见 **`remote_build_run_datasystem.rsyncignore`**。  
- 需要 **包含** 本地 **`.bazelversion`** 与业务源码，否则远端 Bazel 版本与策略不一致。  
- 若你在本地生成了 **需保留在远端的** 东西（如只有远端有的工具链脚本），**不要**用 `--delete` 覆盖整棵远端树里的无关目录；当前脚本对 **datasystem 单仓库根** 做 rsync，一般安全。

**手动示例**（与脚本等价的核心命令）：

```bash
export LOCAL_DS=/path/to/yuanrong-datasystem
export REMOTE=xqyun-32c32g
export REMOTE_DS='~/workspace/git-repos/yuanrong-datasystem'

rsync -az --delete --exclude-from=/path/to/remote_build_run_datasystem.rsyncignore \
  "${LOCAL_DS}/" "${REMOTE}:$(ssh "${REMOTE}" "echo \${HOME}")/workspace/git-repos/yuanrong-datasystem/"
```

---

## 3. 远端 Bazel 构建

```bash
ssh xqyun-32c32g 'set -euo pipefail
  export DS_OPENSOURCE_DIR="${HOME}/.cache/yuanrong-datasystem-third-party"
  mkdir -p "$DS_OPENSOURCE_DIR"
  cd "${HOME}/workspace/git-repos/yuanrong-datasystem"
  bazel build //tests/st/client/object_cache:po2_standby_switch_observability_st_test
'
```

**说明**：Bazel 的缓存与 `DS_OPENSOURCE_DIR` 无直接耦合；`DS_OPENSOURCE_DIR` 主要给 **CMake/build.sh 路径** 用。纯 Bazel 时至少要保证本机/远端已按仓库文档装好 **工具链与 Bazel 版本**（见根目录 `.bazelversion`）。

---

## 4. 排查构建产物（远端）

在 **`yuanrong-datasystem` 仓库根**下 Bazel 输出遵循「工作区 + bazel 输出基」；常用：

```bash
ssh xqyun-32c32g 'set -euo pipefail; cd "${HOME}/workspace/git-repos/yuanrong-datasystem"
  bazel info bazel-bin
  bazel info output_path
  bazel cquery "kind(cc_test,//tests/st/client/object_cache:all)" 2>/dev/null | head
'
```

| 需要找的 | 典型路径/命令 |
|----------|----------------|
| **某目标的可执行/测试** | `$(bazel info bazel-bin)/<package>/<name>`，例如 `bazel-bin/tests/st/client/object_cache/po2_standby_switch_observability_st_test` |
| **runfiles 树** | 同上目标旁常带 `*.runfiles` 目录 |
| **中间产物/配置** | `bazel info output_path` 下的 `execroot` / 外部 `~/.cache/bazel`（与仓库无关的 action cache） |
| **为何找不到符号** | 在远端对同一 `target` 做 `bazel build -s //path:target` 看完整命令行；或 `bazel aquery` |

**ST 长耗时 / 挂起**：先看远端 **`--test_output=errors` / `all`**，再确认测试是否打 **`manual` tag**（需显式 `bazel test //path:名` 才会跑）。

---

## 5. 入口脚本

同目录：

| 脚本 | 作用 |
|------|------|
| **`rsync_datasystem_remote_bazel.sh`** | **推荐默认**：`rsync` 本地 `yuanrong-datasystem` → 远端，再 `ssh` 执行 **`bazel`**；支持 **`--inspect-only`** 只打 `bazel info` 便于排查**产物根路径**；`--` 后接标准 bazel 参数。 |
| **`remote_build_run_datasystem.sh`** | 全量：`build.sh` + ctest + validate（见脚本 `--help`），也含 rsync 与 `DS_OPENSOURCE_DIR`。 |

**`rsync_datasystem_remote_bazel.sh` 示例**（在 **agent-workbench** 或任意目录，只要旁侧有平级 `yuanrong-datasystem` 或已设 `DATASYSTEM_ROOT`）：

```bash
chmod +x scripts/build/rsync_datasystem_remote_bazel.sh

# 仅查远端 bazel 输出根目录（不编译）
./scripts/build/rsync_datasystem_remote_bazel.sh --inspect-only

# 同步后编译指定 ST
./scripts/build/rsync_datasystem_remote_bazel.sh -- \
  build //tests/st/client/object_cache:po2_standby_switch_observability_st_test

# 已手 rsync 过，只跑 bazel
./scripts/build/rsync_datasystem_remote_bazel.sh --skip-sync -- test -c opt //path/to:target
```

**环境变量**：`REMOTE`（默认 `xqyun-32c32g`）、`DATASYSTEM_ROOT`（本地 datasystem 根）、`BAZEL_CMD`（默认 `bazel`）。
