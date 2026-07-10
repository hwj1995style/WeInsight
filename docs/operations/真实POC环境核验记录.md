# 真实POC环境核验记录

本文档用于第九阶段 Task 63。目标是在真实账户受控 POC 执行前，核验微信、配置、数据库、指标、AI dry-run 和回滚边界，确认是否允许进入单公众号/订阅号真实 POC 和单核心群真实轮询 POC。

## 1. 核验边界

本步骤只做环境核验，不执行真实采集。

允许：

```text
读取配置
检查微信健康
检查最近 24 小时试运行指标
检查 group/article 链路积压和失败概况
检查 AI dry-run 状态
填写 Go / No-Go 结论
```

不允许：

```text
不注册 Windows 计划任务
不启用无人值守
不启动后台常驻 article 调度
不临时扩大账号
不打开未授权公众号/订阅号
不打开未授权微信群
不输出聊天正文、文章全文、HTML 或具体文章链接
```

## 2. 必备条件

环境必须满足：

```text
微信 PC 4.1.8.107
微信自动更新已关闭
开发 MySQL 可连接
config/config.dev.yaml 可加载
1 个实际授权公众号/订阅号
1 个实际授权核心群
AI 继续 dry-run
model_called=0
不注册 Windows 计划任务
不启用无人值守
```

UI 条件：

```text
微信已登录
微信主窗口可见
Windows 未锁屏
微信窗口未卡死
wechat_ui_lock 无异常长期占用
群链路优先规则仍生效
核心群等待超过阈值时必须暂停 article 链路
```

## 3. 核验命令

在项目根目录执行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main check-config --config config/config.dev.yaml
python -m app.main wechat-health --config config/config.dev.yaml
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 24
python -m app.main group-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main ai-analysis-sample --source summary_daily_report --date 2026-07-07 --dry-run
```

命令输出只允许作为环境核验证据，不作为真实采集成功证据。

## 4. 结果记录

| 项目 | 期望 | 实际 | 结论 |
| --- | --- | --- | --- |
| check-config | 配置可加载 |  | Go / No-Go |
| wechat-health | 微信健康，版本为微信 PC 4.1.8.107 |  | Go / No-Go |
| 微信自动更新 | 微信自动更新已关闭 |  | Go / No-Go |
| trial-monitor-report | 指标可读，异常可解释 |  | Go / No-Go |
| group-runtime-metrics | 群链路无不可解释积压 |  | Go / No-Go |
| article-runtime-metrics | article 链路无不可解释积压 |  | Go / No-Go |
| AI dry-run | AI 继续 dry-run |  | Go / No-Go |
| model_called=0 | 未调用外部模型 |  | Go / No-Go |
| wechat_ui_lock | 无异常长期占用 |  | Go / No-Go |
| 截图目录 | 异常截图可落盘 |  | Go / No-Go |
| 日志目录 | 日志可落盘 |  | Go / No-Go |

## 5. 暂停条件

出现以下任一情况，Task 63 结论必须为 No-Go：

```text
微信 PC 版本不是 4.1.8.107
微信自动更新未关闭
配置无法加载
MySQL 无法连接
wechat-health 失败
wechat_ui_lock 异常长期占用
核心群等待超过阈值
任一账号连续失败 3 次
AI 不再是 dry-run
model_called 不等于 0
用户可见输出出现敏感内容
```

No-Go 后不得进入 Task 64 或 Task 65。

## 6. 回滚准备

Task 63 通过前必须确认以下回滚路径可执行：

```text
回滚到单账号模式
只保留群链路
关闭 article 链路
关闭 AI
保留日志
保留截图
保留失败任务状态
```

如果无法确认回滚路径，Task 63 结论为 Watch 或 No-Go。

## 7. Go / No-Go 结论

Go 条件：

```text
所有必备条件通过
所有核验命令可执行
AI 继续 dry-run 且 model_called=0
wechat_ui_lock 状态正常
无核心群等待超过阈值
无任一账号连续失败 3 次
回滚路径已确认
```

No-Go 条件：

```text
任一必备条件失败
任一核验命令失败且原因不可解释
微信 UI 状态不可控
核心群等待超过阈值
任一账号连续失败 3 次
AI dry-run 不成立
回滚路径不可执行
```

## 8. 最终记录

```text
核验日期：
值守人员：
微信 PC 版本：
微信自动更新是否关闭：
实际授权公众号/订阅号：
实际授权核心群：
check-config 结论：
wechat-health 结论：
trial-monitor-report 结论：
group-runtime-metrics 结论：
article-runtime-metrics 结论：
AI dry-run 结论：
model_called：
是否允许进入 Task 64：
是否允许进入 Task 65：
最终结论：Go / No-Go
备注：
```

最终结论为 No-Go 时，先修复环境问题，再重新执行本核验。
