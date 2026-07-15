# 单核心群真实轮询POC运行记录

本文档用于第八阶段 Task 59。目标是在真实账户 POC 中，只使用 1 个实际授权核心群，手动命令触发、有人值守，验证微信群链路最小轮询闭环。

## 1. 范围限制

本轮只允许：

```text
1 个实际授权核心群
手动命令触发
有人值守
不注册 Windows 计划任务
不启动 article 链路
不启动长期后台调度
```

不允许：

```text
一次配置多个核心群
无人值守长时间运行
绕过 wechat_ui_lock 操作微信 UI
同时运行 article 真实采集
把失败截图对外公开
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
实际授权核心群已确认
群链路配置只包含本轮 POC 群
article 链路不启动
AI 仍保持 dry-run
```

检查命令：

```powershell
python -m app.main wechat-health --config config/config.dev.yaml
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

## 3. 核心群配置

配置 1 个实际授权核心群：

```powershell
python -m app.main group-config-upsert --config config/config.dev.yaml --group-name "授权核心群名称" --core --priority 1 --poll-interval-seconds 30
```

检查配置：

```powershell
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
是否为核心群：
```

## 4. 手动采集验证

先执行一次手动采集：

```powershell
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
出现截图：检查是否为失败截图，避免对外公开
采集失败：先查看 UI 锁和微信健康状态
```

## 5. 单轮轮询验证

执行一次轮询：

```powershell
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
```

## 7. 失败任务处理

查看失败任务：

```powershell
python -m app.main group-task-failed-list --config config/config.dev.yaml --limit 20
```

限量重试：

```powershell
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
CLI 输出不包含聊天正文、完整联系方式或具体文章链接
日志和截图只用于内部排查
UI 锁必须释放
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
```

回滚：

```powershell
python -m app.main group-config-disable --config config/config.dev.yaml --group-name "授权核心群名称"
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

回滚后确认：

```text
该群不再被轮询
UI 锁为空或可恢复
失败任务不再增加
```

## 10. POC 结果记录

```text
POC 日期：
值守人员：
群名称：
开始时间：
结束时间：
手动采集 read_count：
手动采集 insert_count：
手动采集 duplicate_count：
单轮轮询 success_count：
单轮轮询 failed_count：
是否出现截图：
截图路径：
是否发生去重：
是否出现连续失败 3 次：
是否触发回滚：
是否进入 Task 60：
Go / Watch / No-Go：
备注：
```

## 11. Go / Watch / No-Go

Go：

```text
1 个实际授权核心群成功完成手动采集和单轮轮询
UI 锁正常释放
去重记录可解释
截图记录可解释
失败任务可查看且可限量重试
```

Watch：

```text
存在可定位失败，但未出现连续失败 3 次
截图可解释
UI 锁可恢复
```

No-Go：

```text
连续失败 3 次
UI 锁长时间未释放
微信掉线、锁屏或窗口卡死无法恢复
CLI 或日志出现聊天正文、完整联系方式或具体文章链接
```
