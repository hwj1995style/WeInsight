# 三账号小规模交错POC运行记录

本文档用于第九阶段 Task 69。目标是在 Task 68 完成 3 个实际授权公众号/订阅号配置后，用人工值守的小窗口方式验证 3 个账号与 1 个核心群的交错运行能力。

## 1. 执行范围

本轮只允许：

```text
3 个账号
3 个实际授权公众号/订阅号
1 个实际授权核心群
每个公众号/订阅号每小时执行 1 次
每个账号每轮最多 3 篇
只采集当天发布数据
群链路优先
article 链路可中断
手动命令触发
有人值守
不注册 Windows 计划任务
不启用无人值守
AI 继续 dry-run
model_called=0
```

本轮不允许：

```text
扩到超过 3 个账号
启用最多 20 个账号
启动长期后台调度
绕过 wechat_ui_lock 操作微信 UI
在核心群等待超过阈值时继续执行 article 链路
输出聊天正文、文章全文、HTML 或具体文章链接
```

## 2. 前置条件

执行前必须完成：

```text
docs/operations/三公众号订阅号扩容配置记录.md
```

Task 68 必须为 Go，并确认：

```text
3 个实际授权公众号/订阅号配置完成
article-account-list 核验通过
任一账号失败都可单独关闭
每小时执行 1 次
每轮最多 3 篇
只采集当天发布数据
核心群等待未超过阈值
AI 继续 dry-run 且 model_called=0
```

如果 Task 68 为 Watch 或 No-Go，不进入本任务。

## 3. 启动前检查

执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-account-list --config config/config.dev.yaml
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main group-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 24
```

记录：

```text
检查时间：
3 个账号是否启用：
核心群是否启用：
article 任务积压：
group 任务积压：
UI 锁状态：
核心群等待是否超过阈值：
```

## 4. 小窗口运行安排

建议窗口：

```text
开始时间：
结束时间：
预计时长：1 到 2 小时
值守人员：
账号 A：
账号 B：
账号 C：
实际授权核心群：
```

执行节奏：

```text
00 分钟：检查账号、核心群、UI 锁和指标
05 分钟：执行 run-group-scheduler --once
10 分钟：执行 run-article-scheduler --once
15 分钟：检查 group/article 指标和失败任务
后续每 15 分钟重复一次指标巡检
每个公众号/订阅号每小时执行 1 次
```

如果核心群到期需要采集，article 链路必须让出微信 UI。

## 5. 推荐命令

运行一次群链路：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-group-scheduler --once --config config/config.dev.yaml
```

运行一次 3 账号 article 链路：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-article-scheduler --once --config config/config.dev.yaml
```

巡检：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 2
python -m app.main article-task-failed-list --config config/config.dev.yaml --limit 20
python -m app.main group-task-failed-list --config config/config.dev.yaml --limit 20
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 2
python -m app.main group-runtime-metrics --config config/config.dev.yaml --hours 2
```

## 6. 交错运行记录

| 时间 | 链路 | 操作 | 是否持有 wechat_ui_lock | 持有时长 | 是否释放 | 结果 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  | 群链路 | run-group-scheduler --once |  |  |  |  |  |
|  | article 链路 | run-article-scheduler --once |  |  |  |  |  |

必须记录：

```text
群链路是否优先获取 UI
article 链路是否可中断
article 链路是否按 3 个账号轮询
每个账号是否每小时执行 1 次
每个账号是否只采集当天发布数据
核心群等待是否超过阈值
UI 锁是否出现超时
```

## 7. 指标记录

每 15 分钟记录：

```text
记录时间：
group collect_success_count：
group collect_failed_count：
group task_backlog：
article collect_success_count：
article collect_failed_count：
article task_backlog：
article failed_task_count：
group failed_task_count：
核心群等待是否超过阈值：
AI dry-run 结论：
model_called：
```

## 8. 失败隔离

任一账号失败都可单独关闭。

如果账号 A 失败：

```text
记录错误摘要
确认是否连续失败 3 次
必要时关闭账号 A
继续观察账号 B、账号 C 和核心群
```

如果账号 B 失败：

```text
记录错误摘要
确认是否连续失败 3 次
必要时关闭账号 B
继续观察账号 A、账号 C 和核心群
```

如果账号 C 失败：

```text
记录错误摘要
确认是否连续失败 3 次
必要时关闭账号 C
继续观察账号 A、账号 B 和核心群
```

## 9. 暂停和回滚

立即暂停 article 链路：

```text
任一账号连续失败 3 次
核心群等待超过阈值
article 链路长时间占用微信 UI
UI 锁超时持续出现
run-article-scheduler --once 不可中断
AI 不再是 dry-run
model_called 不等于 0
CLI 或日志出现聊天正文、文章全文、HTML 或具体文章链接
```

回滚到单账号模式：

```text
关闭失败账号和非必要账号
保留 1 个已通过账号
重新执行 article-account-list
重新执行 article-runtime-metrics
重新执行 Task 64 单账号记录模板
```

只保留群链路：

```text
关闭全部 article 账号
确认 article 链路不再占用微信 UI
继续执行 run-group-scheduler --once
保留日志、截图和失败任务状态
```

## 10. Go / Watch / No-Go

Go：

```text
3 个账号均按每小时执行 1 次运行
3 个账号均只采集当天发布数据
群链路优先保持有效
article 链路可中断且可恢复
核心群等待未超过阈值
任一账号失败都可单独关闭
AI 继续 dry-run 且 model_called=0
```

Watch：

```text
存在可定位失败
失败账号可单独关闭
群链路未受明显影响
需要补充 3 账号小窗口运行证据
```

No-Go：

```text
任一账号连续失败 3 次
核心群等待超过阈值
article 链路不可中断
article 链路长时间占用微信 UI
UI 锁超时持续出现
AI 不再是 dry-run
用户可见输出出现敏感内容
```

## 11. 最终记录

```text
POC 日期：
值守人员：
开始时间：
结束时间：
账号 A 运行结果：
账号 B 运行结果：
账号 C 运行结果：
核心群运行结果：
每小时执行 1 次是否满足：
只采集当天发布数据是否满足：
群链路优先是否满足：
article 链路是否可中断：
核心群等待是否超过阈值：
是否触发回滚到单账号模式：
是否触发只保留群链路：
AI dry-run 结论：
model_called：
最终结论：Go / Watch / No-Go
备注：
```

最终结论为 Go 时，才允许继续推进 Task 70。
