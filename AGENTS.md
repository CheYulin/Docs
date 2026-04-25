# Agent 说明

本仓库 **`yuanrong-datasystem-agent-workbench`**（历史目录名 `yuanrong-datasystem-agent-workbench/`）与 **`yuanrong-datasystem`（Open Yuanrong DataSystem）** 配对使用：前者是 **Agent / vibe-coding 工作台**，承载 **脚本 + 文档 + 计划 + RFC + 验证产物 + Cursor Skills**；后者以 **源码与 `build.sh`** 为主。

## 工作角色（与本仓协作时）

- **架构师**：评估模块边界、依赖与演进是否合理。  
- **设计师 / 技术专家**：弄清接口语义、错误与可观测性细节，能引用代码证据。  
- **Code Review**：从正确性、并发、风格一致性给出可执行的评审意见。  
- **用户视角**：关注 SDK/文档/错误信息的易用性与可行动性。  
- **测试与验证**：功能验收路径、性能基线与门禁脚本（见 `docs/verification`、`scripts/verify`、`scripts/perf`）。

## 脚本与 Skill

- **新增可执行脚本**：放在仓库根目录 **`scripts/`** 合适子目录，并更新 [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md) 或对应 README。  
- **同一流程多次重复**：建议沉淀为 **Cursor Agent Skill**。现有 Skill：
  - [`.cursor/skills/feature-tree-to-docs/`](.cursor/skills/feature-tree-to-docs/SKILL.md) — 特性树 TSV → Markdown 文档
  - [`.cursor/skills/run-and-verify/`](.cursor/skills/run-and-verify/SKILL.md) — 远程 SSH 编译 → 测试 → 结果检查
  - [`.cursor/skills/perf-baseline/`](.cursor/skills/perf-baseline/SKILL.md) — 性能基线采集与对比
  - [`.cursor/skills/new-script-scaffold/`](.cursor/skills/new-script-scaffold/SKILL.md) — 新增脚本脚手架（含文档索引同步）

## Excel / PPT

- **Excel**：表格类交付优先脚本生成；见 [`docs/observable/workbook/README.md`](docs/observable/workbook/README.md)（`./ops docs.kv_observability_xlsx`），新脚本优先放 **`scripts/`**。  
- **PPT**：以 `docs/observable/*ppt*`、`ppt.md` 等 Markdown 素材为主；自动化导出可再加 `scripts/` 工具。

## 请先阅读

### 外部权威链接（给 Agent 查阅）

- 官方文档（latest）：<https://pages.openeuler.openatom.cn/openyuanrong-datasystem/docs/zh-cn/latest/index.html>
- 代码仓（上游镜像）：<https://gitcode.com/openeuler/yuanrong-datasystem>

### 配对仓库上下文（执行任务前）

当任务涉及 `yuanrong-datasystem` 行为、源码或验证时，先查看：

- `../yuanrong-datasystem/.cursor/rules/repo-context.mdc`
- `../yuanrong-datasystem/.repo_context/`（优先按 `README.md` → `index.md` → `maintenance.md` 的顺序）
- `../yuanrong-datasystem/.skills/`（复用现有 Skill，避免重复造轮子）

1. [`docs/agent/README.md`](docs/agent/README.md)  
2. [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md)（`scripts/{build,index,perf,verify}/` 何时用哪个）  
3. [`docs/verification/手动验证确认指南.md`](docs/verification/手动验证确认指南.md)（逐步验收）  
4. [`docs/verification/cmake-non-bazel.md`](docs/verification/cmake-non-bazel.md)  
5. [`docs/verification/构建产物目录与可复现工作流.md`](docs/verification/构建产物目录与可复现工作流.md)（第三方缓存与 `output`/`build` 结构）  
6. [`plans/agent开发载体_vibe与yuanrong分工.plan.md`](plans/agent开发载体_vibe与yuanrong分工.plan.md)  
7. 根目录 [`README.md`](README.md)（角色定位、脚本/Skill/Excel/PPT 约定）

执行本仓库脚本时，若未与 `yuanrong-datasystem` 同级放置，请设置 `DATASYSTEM_ROOT`。

### 远程执行与 rsync 同步（重要）

**当任务需要远程构建、测试或验证时，必须使用 rsync 同步工作流**：

1. **远程主机**：`xqyun-32c32g`（默认）
2. **同步方式**：使用 `scripts/build/remote_build_run_datasystem.sh` 进行 rsync 同步
3. **工作流**：
   ```
   本地修改 → rsync 同步到远程 → 远程构建/测试 → 结果在远程
   ```
4. **关键约束**：
   - 不要在远程 clone/pull 仓库（远程是纯源码目录，无 .git）
   - 所有代码修改在本地完成，通过 rsync 同步
   - 使用 `--skip-sync` 仅在需要重复执行远程步骤时跳过同步

5. **示例命令**：
   ```bash
   # 完整流程：rsync 同步 + 构建 + 测试
   bash scripts/build/remote_build_run_datasystem.sh \
     --remote xqyun-32c32g \
     --local-ds ~/workspace/git-repos/yuanrong-datasystem \
     --local-vibe ~/workspace/git-repos/yuanrong-datasystem-agent-workbench

   # 仅执行远程构建步骤（跳过 rsync）
   bash scripts/build/remote_build_run_datasystem.sh --skip-sync
   ```

6. **冒烟测试**：
   ```bash
   ssh xqyun-32c32g 'cd ~/workspace/git-repos/yuanrong-datasystem-agent-workbench && python3 scripts/testing/verify/smoke/run_smoke.py'
   ```

详见：[`scripts/build/remote_build_run_datasystem.sh`](scripts/build/remote_build_run_datasystem.sh) 和 [`docs/agent/scripts-map.md`](docs/agent/scripts-map.md)。

---

## GitCode PR 操作指南

本仓库关联的源码仓库 **yuanrong-datasystem** 托管在 GitCode (gitcode.com/openeuler/yuanrong-datasystem)。以下指南用于自动化 PR 审查、评论读取、评论回复等操作。

### 认证

所有 GitCode API 调用使用 **Bearer Token** 认证：

```bash
curl -H "Authorization: Bearer $GITCODE_TOKEN" "https://api.gitcode.com/api/v5/..."
```

环境变量：`GITCODE_TOKEN` — 在 GitCode 设置 → 访问令牌 中创建，需具备 PR 读写权限。

### 关键 API 端点

Base URL: `https://api.gitcode.com/api/v5`

| 操作 | 方法 | 端点 |
|------|------|------|
| 获取 PR 详情 | GET | `/repos/:owner/:repo/pulls/:number` |
| 获取 PR diff | GET | `/repos/:owner/:repo/pulls/:number/files` |
| 获取评论列表 | GET | `/repos/:owner/:repo/pulls/:number/comments` |
| 发表 PR 评论 | POST | `/repos/:owner/:repo/pulls/:number/comments` |
| 回复评论 | POST | `/repos/:owner/:repo/pulls/:number/comments` (带 `in_reply_to_id`) |

### 常用操作示例

```bash
# 获取 PR 详情（标题、状态、作者、base/head 分支）
curl -s -H "Authorization: Bearer $GITCODE_TOKEN" \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706"

# 获取 PR 变更文件列表
curl -s -H "Authorization: Bearer $GITCODE_TOKEN" \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706/files"

# 获取所有评论
curl -s -H "Authorization: Bearer $GITCODE_TOKEN" \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706/comments"

# 发表普通评论（Markdown 支持）
curl -s -X POST -H "Authorization: Bearer $GITCODE_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"body":"LGTM overall. One suggestion: consider adding unit tests for the new metrics."}' \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706/comments"

# 回复已有评论（串入讨论线程）
curl -s -X POST -H "Authorization: Bearer $GITCODE_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"body":"Fixed in latest commit, PTAL.","in_reply_to_id":12345678}' \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706/comments"

# 行内代码评论（指定文件和行号）
curl -s -X POST -H "Authorization: Bearer $GITCODE_TOKEN" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{
    "body": "Consider using const here for better compiler optimization.",
    "path": "src/datasystem/common/rpc/zmq/zmq_stub_impl.h",
    "new_position": 42
  }' \
  "https://api.gitcode.com/api/v5/repos/openeuler/yuanrong-datasystem/pulls/706/comments"
```

### PR 审查工作流

1. **读取 PR 详情**：`GET /pulls/:number` → 获取标题、正文、状态、作者、base/head refs
2. **读取变更文件**：`GET /pulls/:number/files` → 获取变更文件列表和 diff
3. **读取现有评论**：`GET /pulls/:number/comments` → 获取所有审查评论
4. **分析 Review 意见**：按评论 ID 和 `in_reply_to_id` 梳理讨论线程
5. **自动回复评论**：对每个待回复的评论用 `in_reply_to_id` 参数 POST 回复
6. **发表新评论**：没有 `in_reply_to_id` 时作为独立评论发表

### 注意事项

- 评论内容支持 Markdown 格式
- 批量发表评论时注意频率限制，每次 POST 之间建议添加短暂间隔
- `in_reply_to_id` 用于将回复串入指定评论线程
- 行内评论通过 `path` + `new_position` 指定目标位置
- 评论 ID 从获取评论列表的返回中获取
