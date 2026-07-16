# Git 分支交付与清理标准流程

## 目的

统一任务代码从开发到合并的动作，避免改动混杂、漏推送，以及已合并分支持续堆积。

## 分支生命周期

一个任务分支只服务一个独立任务，标准生命周期如下：

1. 从最新 `origin/main` 创建 `codex/<task-name>`。
2. 在任务分支完成实现、测试和回归。
3. 用户要求“提交并推送”后，提交并推送任务分支，创建或更新 Draft PR。
4. 用户要求“合并到 main”后，确认 PR 检查通过，将 PR 转为 Ready 并合并。
5. 同步本地 `main`，删除已合并的本地和远程任务分支。
6. 执行远程引用清理并复核分支状态。

## 开始任务

开始前检查：

- 当前工作区没有需要保留但尚未提交的改动。
- 本地 `main` 已与 `origin/main` 同步。
- 新任务不会复用已经承担其他需求的分支。
- 分支名称简短、可识别，并使用 `codex/` 前缀。

参考命令：

```powershell
git status --short --branch
git switch main
git pull --ff-only origin main
git switch -c codex/<task-name>
```

## 提交并推送

“提交并推送”是发布任务分支的授权，不等同于合并授权。执行前应确认：

- 变更范围只包含当前任务。
- 相关测试和必要的完整回归已通过。
- 未提交运行时文件、密钥、备份或临时产物。
- 提交信息能够说明业务结果。

标准动作：

```powershell
git status --short
git diff --check
git add <本任务文件>
git commit -m "<type>: <summary>"
git push -u origin codex/<task-name>
```

随后创建或更新 Draft PR，并在交付说明中给出测试结果、风险和数据变更情况。除非用户明确要求，否则停在 Draft PR，不自动合并到 `main`。

## 合并到 main

“合并到 main”授权完成整个合并和清理闭环。合并前确认：

- PR 对应当前任务分支，且不存在未处理的阻塞性审查意见。
- 必需检查通过；没有检查时，至少已完成与风险相称的本地测试。
- PR 已从 Draft 转为 Ready。
- 合并不会覆盖 `main` 上的新提交。

合并后同步：

```powershell
git fetch origin
git switch main
git pull --ff-only origin main
```

## 已合并分支清理

只有在确认 PR 已合并、提交已进入 `origin/main` 后才执行清理：

```powershell
git branch -d codex/<task-name>
git push origin --delete codex/<task-name>
git fetch --prune
git branch -vv
git branch -r
```

如果远程平台已自动删除分支，远程删除命令提示分支不存在可视为已完成，仍需执行 `git fetch --prune`。

以下分支不得自动删除：

- 尚未合并的任务分支。
- 含有未推送提交或无法确认归属的提交的分支。
- 被其他 worktree 使用的分支。
- `main`、发布分支或其他受保护分支。
- 有明确长期维护用途且已记录负责人和用途的分支。

## 定期盘点

在一次合并完成后顺带检查 `codex/*` 分支。已合并分支立即清理；未合并分支保留并标注对应 PR 或任务。无法判断用途时只报告，不直接删除。

建议使用以下命令辅助盘点：

```powershell
git fetch --prune
git branch --merged main
git branch -r --merged origin/main
git worktree list
```

## 完成标准

一次“合并到 main”只有同时满足以下条件才算完整结束：

- PR 已合并，目标提交可从 `origin/main` 到达。
- 本地 `main` 与 `origin/main` 一致。
- 当前任务的本地和远程分支均已删除。
- 远程跟踪引用已清理。
- 工作区干净，未遗留临时文件。
