# 第九阶段单公众号订阅号真实POC执行记录

> **公众号 article-RPA 历史记录（已退役）**：本文中的 `article-rpa-probe`、`collect-article-once`、`run-article-scheduler` 等命令已移除，**禁止执行**，不得作为现行操作指引。公众号现行采集路径仅为 **WeRSS + WeInsight RSS**；请使用 `docs/operations/公众号RSS采集运行手册.md`。

本文档用于第九阶段 Task 64。目标是在 Task 63 环境核验通过后，只使用 1 个实际授权公众号/订阅号，手动命令触发、有人值守，执行一次受控真实 POC，并记录采集、解析、指标和 Go / Watch / No-Go 结论。

## 1. 执行范围

本轮只允许：

```text
1 个实际授权公众号/订阅号
每轮最多 3 篇
只采集当天发布数据
手动命令触发
有人值守
不注册 Windows 计划任务
不启用无人值守
不启用后台常驻 article 调度
AI 继续 dry-run
model_called=0
```

本轮不允许：

```text
一次配置多个实际账号
采集历史文章
无人值守长时间运行
长期保存文章正文
绕过 wechat_ui_lock 操作微信 UI
在核心群等待超过阈值时继续占用微信 UI
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
1 个实际授权公众号/订阅号已确认
1 个实际授权核心群已确认
AI 继续 dry-run
model_called=0
wechat_ui_lock 无异常长期占用
```

若 Task 63 为 Watch 或 No-Go，不进入本任务。

## 3. 账号配置

在项目根目录执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-account-upsert --config config/config.dev.yaml --account-name "授权公众号名称" --account-type subscription --priority 1 --poll-interval-minutes 60 --max-articles-per-round 3
python -m app.main article-account-list --config config/config.dev.yaml
```

记录：

```text
账号名称：
账号类型：
负责人：
配置时间：
是否只配置 1 个实际授权公众号/订阅号：
是否每轮最多 3 篇：
是否只采集当天发布数据：
```

## 4. 单次采集

执行单次采集：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main collect-article-once --config config/config.dev.yaml --account-name "授权公众号名称" --max-articles-per-round 3
```

采集必须满足：

```text
采集前获取 wechat_ui_lock
采集范围仅限该授权账号
采集当天发布数据
每轮最多 3 篇
采集完成后释放微信 UI
不输出文章全文、HTML 或具体文章链接
```

记录：

```text
执行时间：
attempted_count：
success_count：
failed_count：
lock_timeout_count：
是否只采集当天发布数据：
是否每轮最多 3 篇：
是否释放微信 UI：
截图路径：
错误摘要：
```

## 5. 释放微信 UI 后再解析

文章解析必须释放微信 UI 后再执行。解析阶段不得获取 `wechat_ui_lock`，不得阻塞核心群。

执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main parse-article-once --config config/config.dev.yaml --limit 5
```

记录：

```text
执行时间：
read_count：
success_count：
failed_count：
是否释放微信 UI 后再解析：
是否未占用 wechat_ui_lock：
错误摘要：
```

## 6. 指标巡检

执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 24
```

记录：

```text
collect_success_count：
collect_failed_count：
collect_total_count：
article_task_backlog：
latest_error_summary：
群链路是否被阻塞：
核心群等待是否超过阈值：
```

## 7. 数据边界

必须满足：

```text
正文只运行时临时读取
不长期保存文章正文
落库只保存摘要、标签、关键词命中和结构化特征
CLI 输出不包含聊天正文、文章全文、HTML 或具体文章链接
日志不包含聊天正文、文章全文、HTML 或具体文章链接
日报和汇总日报不包含文章全文
```

若发现边界破坏，立即停止本轮 POC。

## 8. 暂停和回滚

暂停条件：

```text
连续失败 3 次
核心群等待超过阈值
微信掉线
锁屏
窗口卡死
UI 锁长时间未释放
CLI 或日志出现文章全文、HTML 或具体文章链接
AI 不再是 dry-run
model_called 不等于 0
```

回滚到单账号模式：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-account-disable --config config/config.dev.yaml --account-name "授权公众号名称"
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
```

只保留群链路：

```text
关闭 article 链路
确认核心群可继续轮询
确认 article 链路不再占用微信 UI
保留日志、截图和失败任务状态
```

## 9. Go / Watch / No-Go

Go：

```text
Task 63 结论为 Go
单次采集成功
解析成功
只采集当天发布数据
每轮最多 3 篇
释放微信 UI 后再解析
核心群等待未超过阈值
AI 继续 dry-run 且 model_called=0
```

Watch：

```text
存在可定位失败
失败可手动恢复
没有连续失败 3 次
群链路未受明显影响
需要再次执行单账号验证
```

No-Go：

```text
连续失败 3 次
核心群等待超过阈值
article 链路长时间占用微信 UI
解析阶段仍占用 wechat_ui_lock
AI 不再是 dry-run
用户可见输出出现敏感内容
```

## 10. 最终记录

```text
POC 日期：
值守人员：
账号名称：
开始时间：
结束时间：
采集文章数：
解析成功数：
去重是否生效：
是否只采集当天发布数据：
是否每轮最多 3 篇：
是否出现连续失败 3 次：
是否核心群等待超过阈值：
是否触发回滚到单账号模式：
是否只保留群链路：
AI dry-run 结论：
model_called：
最终结论：Go / Watch / No-Go
备注：
```

最终结论为 Go 时，才允许继续推进 Task 65。
