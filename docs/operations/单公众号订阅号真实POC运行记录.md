# 单公众号订阅号真实POC运行记录

本文档用于第八阶段 Task 58。目标是在真实账户 POC 中，只使用 1 个实际授权公众号/订阅号，手动命令触发、有人值守，验证 article 链路最小闭环。

## 1. 范围限制

本轮只允许：

```text
1 个实际授权公众号/订阅号
每轮最多 3 篇
只采集当天发布数据
手动命令触发
有人值守
不注册 Windows 计划任务
不启用 run-article-scheduler 常驻调度
AI 仍保持 dry-run
```

不允许：

```text
一次配置多个实际账号
无人值守长时间运行
采集历史文章
长期保存文章正文
绕过 wechat_ui_lock 操作微信 UI
```

## 2. 前置复核

执行前先完成：

```text
docs/operations/真实POC前置复核清单.md
```

确认项：

```text
微信 PC 4.1.8.107 已登录
微信自动更新已关闭
实际授权公众号/订阅号已确认
只采集当天发布数据已确认
正文只运行时读取已确认
不长期保存文章正文已确认
AI dry-run 已确认 model_called=0
```

检查命令：

```powershell
python -m app.main wechat-health --config config/config.dev.yaml
python -m app.main ai-analysis-sample --source summary_daily_report --date 2026-07-07 --dry-run
```

## 3. 账号配置

配置 1 个实际授权公众号/订阅号：

```powershell
python -m app.main article-account-upsert --config config/config.dev.yaml --account-name "授权公众号名称" --account-type subscription --priority 1 --poll-interval-minutes 60 --max-articles-per-round 3
```

检查账号：

```powershell
python -m app.main article-account-list --config config/config.dev.yaml
```

记录：

```text
账号名称：
账号类型：
负责人：
配置时间：
是否只配置 1 个账号：
```

## 4. 手动采集

执行单次采集：

```powershell
python -m app.main collect-article-once --config config/config.dev.yaml --account-name "授权公众号名称" --max-articles-per-round 3
```

记录：

```text
执行时间：
attempted_count：
success_count：
failed_count：
lock_timeout_count：
是否只采集当天发布数据：
是否出现具体文章链接输出：
截图路径：
错误摘要：
```

判断：

```text
success_count 大于 0 且 failed_count=0：继续解析
failed_count 大于 0：查看失败原因，必要时停止本轮
lock_timeout_count 大于 0：优先确认核心群和 UI 锁状态
```

## 5. 释放微信 UI 后再解析

文章解析必须释放微信 UI 后再执行。解析不应获取 `wechat_ui_lock`，不得阻塞核心群。

执行：

```powershell
python -m app.main parse-article-once --config config/config.dev.yaml --limit 5
```

记录：

```text
执行时间：
read_count：
success_count：
failed_count：
是否释放微信 UI 后再解析：
是否出现文章全文或 HTML 输出：
错误摘要：
```

## 6. 指标巡检

执行：

```powershell
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 24
```

记录：

```text
article collect_success_count：
article collect_failed_count：
article collect_total_count：
article task_backlog：
群链路是否被阻塞：
核心群等待是否超过阈值：
```

## 7. 数据和隐私边界

必须满足：

```text
正文只运行时读取
不长期保存文章正文
落库只保存摘要、标签、关键词命中、表格结构化特征和 OCR 表格结构化特征
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
AI dry-run 输出不再包含 model_called=0
```

回滚到单账号模式：

```powershell
python -m app.main article-account-disable --config config/config.dev.yaml --account-name "授权公众号名称"
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
```

回滚后确认：

```text
article 链路不再占用微信 UI
群链路可继续运行
失败任务不再增加
```

## 9. POC 结果记录

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
是否出现连续失败 3 次：
是否触发回滚：
是否影响核心群：
是否进入 Task 59：
Go / Watch / No-Go：
备注：
```

## 10. Go / Watch / No-Go

Go：

```text
1 个实际授权公众号/订阅号成功完成采集和解析
每轮最多 3 篇限制生效
只采集当天发布数据
正文只运行时读取
不长期保存文章正文
核心群等待未超过阈值
AI 仍保持 dry-run 且 model_called=0
```

Watch：

```text
出现可定位失败，但未影响核心群
解析失败可重试
日报质量需要人工复盘
```

No-Go：

```text
连续失败 3 次
核心群等待超过阈值
出现文章全文、HTML 或具体文章链接输出
无法确认正文只运行时读取
无法确认不长期保存文章正文
```
