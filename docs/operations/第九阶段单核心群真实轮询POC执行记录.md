# 第九阶段单核心群真实轮询POC执行记录

本文档用于第九阶段 Task 65。目标是在 Task 63 环境核验通过后，只使用 1 个实际授权核心群，手动命令触发、有人值守，执行一次受控真实轮询 POC，并记录采集、去重、截图、指标和 Go / Watch / No-Go 结论。

## 1. 执行范围

本轮只允许：

```text
1 个实际授权核心群
手动命令触发
有人值守
不注册 Windows 计划任务
不启用无人值守
不启动 article 链路
不启动长期后台调度
AI 继续 dry-run
model_called=0
```

本轮不允许：

```text
一次配置多个核心群
无人值守长时间运行
绕过 wechat_ui_lock 操作微信 UI
同时运行 article 真实采集
把失败截图对外公开
输出聊天正文、完整联系方式或具体文章链接
```

## 2. 前置条件

执行前必须完成：

```text
docs/operations/第九阶段真实POC执行准入冻结.md
docs/operations/真实POC环境核验记录.md
```

Task 63 必须为 Go，并确认：

```text
微信 PC 4.1.8.107
微信自动更新已关闭
config/config.dev.yaml 可加载
开发 MySQL 可连接
1 个实际授权核心群已确认
article 链路不启动
AI 继续 dry-run
model_called=0
wechat_ui_lock 无异常长期占用
```

若 Task 63 为 Watch 或 No-Go，不进入本任务。

## 3. 核心群配置

在项目根目录执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-config-upsert --config config/config.dev.yaml --group-name "授权核心群名称" --core --priority 1 --poll-interval-seconds 30 --backtrack-pages 1 --extra-backtrack-pages 3
python -m app.main group-status --config config/config.dev.yaml --group-name "授权核心群名称"
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

记录：

```text
群名称：
授权负责人：
配置时间：
是否只配置 1 个实际授权核心群：
poll_interval_seconds：
backtrack_pages：
extra_backtrack_pages：
是否为核心群：
```

## 4. 手动采集验证

先执行一次手动采集：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main collect-group-once --config config/config.dev.yaml --group-name "授权核心群名称"
```

记录：

```text
执行时间：
batch_id：
read_count：
insert_count：
duplicate_count：
是否发生去重：
是否生成失败截图：
截图路径：
错误摘要：
```

判断：

```text
insert_count 大于 0：继续单轮轮询
duplicate_count 大于 0：记录去重表现
出现截图：检查是否为失败截图，截图只用于内部排查
采集失败：先查看微信健康和 wechat_ui_lock 状态
```

## 5. 单轮轮询验证

执行一次轮询：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-group-scheduler --once --config config/config.dev.yaml
```

记录：

```text
执行时间：
attempted_count：
success_count：
failed_count：
lock_timeout_count：
UI 锁是否正常释放：
是否出现失败截图：
截图路径：
```

判断：

```text
success_count 大于 0 且 failed_count=0：继续指标巡检
failed_count 大于 0：查看失败任务
lock_timeout_count 大于 0：停止本轮并检查 UI 锁
```

## 6. 指标巡检

执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
python -m app.main group-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main group-task-failed-list --config config/config.dev.yaml --limit 20
```

记录：

```text
collect_success_count：
collect_failed_count：
collect_total_count：
collect_failure_rate：
daily_report_count：
task_backlog：
failed_task_count：
latest_error_summary：
```

## 7. 失败任务处理

查看失败任务：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-task-failed-list --config config/config.dev.yaml --limit 20
```

限量重试：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-task-retry-failed --config config/config.dev.yaml --limit 5
```

记录：

```text
失败任务类型：
失败任务数量：
错误摘要：
是否限量重试：
重试结果：
```

## 8. 安全边界

必须满足：

```text
只采集 1 个实际授权核心群
不启动 article 链路
不注册 Windows 计划任务
不启用无人值守
CLI 输出不包含聊天正文、完整联系方式或具体文章链接
日志和截图只用于内部排查
截图不得对外公开
UI 锁必须释放
AI 继续 dry-run
model_called=0
```

若发现边界破坏，立即停止本轮 POC。

## 9. 暂停和回滚

暂停条件：

```text
连续失败 3 次
微信掉线
锁屏
窗口卡死
UI 锁长时间未释放
失败截图无法解释
CLI 或日志出现聊天正文、完整联系方式或具体文章链接
AI 不再是 dry-run
model_called 不等于 0
```

回滚：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-config-disable --config config/config.dev.yaml --group-name "授权核心群名称"
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

回滚后确认：

```text
该群不再被轮询
UI 锁为空或可恢复
失败任务不再增加
article 链路仍未启动
```

## 10. Go / Watch / No-Go

Go：

```text
Task 63 结论为 Go
手动采集成功
单轮轮询成功
去重表现可解释
截图只用于内部排查
UI 锁正常释放
AI 继续 dry-run 且 model_called=0
```

Watch：

```text
存在可定位失败
失败可手动恢复
没有连续失败 3 次
截图原因可解释
需要再次执行单核心群验证
```

No-Go：

```text
连续失败 3 次
微信 UI 状态不可控
UI 锁长时间未释放
失败截图无法解释
article 链路被启动
AI 不再是 dry-run
用户可见输出出现敏感内容
```

## 11. 最终记录

```text
POC 日期：
值守人员：
群名称：
开始时间：
结束时间：
手动采集 read_count：
手动采集 insert_count：
手动采集 duplicate_count：
是否发生去重：
是否生成截图：
单轮轮询 attempted_count：
单轮轮询 success_count：
单轮轮询 failed_count：
是否出现连续失败 3 次：
是否触发回滚：
是否保持 article 链路不启动：
AI dry-run 结论：
model_called：
最终结论：Go / Watch / No-Go
备注：
```

最终结论为 Go 时，才允许继续推进 Task 66。
