# 公众号订阅号受控真实 POC 运行手册

> **公众号 article-RPA 历史记录（已退役）**：本文中的 `article-rpa-probe`、`collect-article-once`、`run-article-scheduler` 等命令已移除，**禁止执行**，不得作为现行操作指引。公众号现行采集路径仅为 **WeRSS + WeInsight RSS**；请使用 `docs/operations/公众号RSS采集运行手册.md`。

本文档适用于第五阶段公众号/订阅号链路的人工值守真实 POC。当前阶段只验证最小真实闭环，不注册 Windows 计划任务，不默认开启后台真实采集。

## 1. POC 范围

首轮 POC 只允许使用 1 个授权公众号/订阅号。

目标是验证：

1. 微信 PC 4.1.8.107 已登录且健康检查通过。
2. `article-rpa-probe` 能打开指定公众号/订阅号并返回安全探测状态。
3. `collect-article-once` 能在持有 `wechat_ui_lock` 时获取当天文章链接并释放微信 UI。
4. `parse-article-once` 能在不占用微信 UI 的情况下解析已入库文章元数据。
5. `article-runtime-metrics` 能查看最近 24 小时账号、成功、失败、跳过、积压和最近错误摘要。
6. CLI 输出不展示文章正文，不展示具体文章链接。

## 2. 前置检查

执行前确认：

```text
微信 PC 已登录
微信版本为 4.1.8.107
微信自动更新已关闭
目标公众号/订阅号已授权
当前只测试 1 个授权公众号/订阅号
核心微信群链路处于可人工观察状态
```

开发环境继续手动执行命令，不注册 Windows 计划任务。

## 3. 手动执行顺序

设置开发库密码：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
```

查看授权账号配置：

```powershell
python -m app.main article-account-list --config config/config.dev.yaml
```

探测指定公众号/订阅号 RPA 状态：

```powershell
python -m app.main article-rpa-probe --config config/config.dev.yaml --account-name "授权公众号名称"
```

## 历史文章取链增强

增强后 article 链路会按账号维护路由缓存。缓存只保存入口类型、入口标签、链接提取方式和失败计数，不保存具体文章链接。

真实取链优先级：

1. 微信内置浏览器右上角 `...` -> `复制链接`，读取后立即恢复原剪贴板。
2. 如果复制链接失败，从微信内置浏览器 UIA Value 中筛选 `/s` 文章详情链接。
3. 如果详情页未打开，重新 probe 底部菜单、公众号主页、文章卡片等入口。

CLI 和日志只输出计数、状态、route 类型和错误摘要，不输出具体文章链接或正文。

执行单账号真实 UI 拿链接：

```powershell
python -m app.main collect-article-once --config config/config.dev.yaml --account-name "授权公众号名称" --max-articles-per-round 1
```

释放微信 UI 后解析文章链接：

```powershell
python -m app.main parse-article-once --config config/config.dev.yaml --limit 5
```

查看 article POC 监控指标：

```powershell
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
```

查看文章日报摘要：

```powershell
python -m app.main article-daily-report-list --config config/config.dev.yaml --date 2026-07-06 --limit 20
```

查看单个账号文章日报：

```powershell
python -m app.main article-daily-report-show --config config/config.dev.yaml --date 2026-07-06 --account-name "授权公众号名称"
```

导出单个账号文章日报：

```powershell
python -m app.main article-daily-report-export --config config/config.dev.yaml --date 2026-07-06 --account-name "授权公众号名称" --output runtime/reports/article
```

文章日报查看和导出只读取 `wechat_article_daily_report`，不占用微信 UI，不回查文章采集、解析或分析明细表。列表命令只显示日期、账号、标题、文章数和生成时间；查看和导出命令输出的是已生成日报草稿。

查看并重试 article 失败任务：

```powershell
python -m app.main article-task-failed-list --config config/config.dev.yaml --limit 20
python -m app.main article-task-retry-failed --config config/config.dev.yaml --task-type clean_article --limit 5
```

以上命令只操作 `wechat_article_process_task`，用于查看和重试 article 链路失败任务；不得用于修改微信群链路任务。

可选：按账号到期规则执行一轮手动 article 调度：

```powershell
python -m app.main run-article-scheduler --config config/config.dev.yaml --once
```

`run-article-scheduler` 在开发阶段必须显式带 `--once`，只执行一轮到期账号调度，不注册 Windows 计划任务，不进入后台常驻采集。真实 POC 首轮仍建议优先使用 `collect-article-once` 针对 1 个授权账号手动验证；该调度入口用于后续人工值守时验证账号级到期规则。

## 4. 人工观察点

执行期间重点观察：

```text
article-rpa-probe 是否返回 status=ok
collect-article-once 是否及时释放微信 UI
collect-article-once 是否输出 link_count >= 1
collect-article-once 是否输出 raw_insert_count + duplicate_count >= 1
parse-article-once 是否不打开微信窗口
article-runtime-metrics 是否显示成功、失败、跳过和积压计数
核心微信群采集窗口是否被阻塞超过阈值
失败时是否有错误码和截图路径
```

如果核心群到期，article 链路必须在安全检查点释放微信 UI，并记录中断或失败状态。

## 5. 通过条件

首轮 1 个授权公众号/订阅号 POC 通过条件：

```text
article-rpa-probe 返回 status=ok
collect-article-once 返回 success_count=1、failed_count=0、lock_timeout_count=0
collect-article-once 返回 link_count >= 1
collect-article-once 返回 raw_insert_count + duplicate_count >= 1
parse-article-once 成功处理待解析任务；如果 read_count=0，必须确认 collect 命中 duplicate 而不是 link_count=0
article-runtime-metrics 可显示最近 24 小时指标
微信 UI 锁没有长时间残留
微信群链路状态未被 article 链路修改
CLI 输出没有文章正文和具体文章链接
```

如果 `collect-article-once` 出现 `link_count=0`，或 `raw_insert_count + duplicate_count=0`，本轮真实 POC 视为未闭环，即使命令过程没有抛出 RPA 异常也不能判为通过。

## 6. 3 个账号扩容门禁

只有首轮 1 个授权公众号/订阅号 POC 闭环通过后，才允许扩大到 3 个授权公众号/订阅号。

3 个账号 POC 仍然是人工值守，不注册 Windows 计划任务，不进入后台常驻采集。执行前必须确认 3 个账号均已授权、均只采集当天发布数据，并且每个账号仍按每小时最多执行 1 次的规则观察。

扩大到 3 个授权公众号/订阅号后，必须遵守：

```text
1 个账号闭环通过后，才允许扩大到 3 个授权公众号/订阅号
3 个账号 POC 必须人工值守
任一账号连续失败 3 次，暂停 article 链路
核心群等待超过阈值，立即停止 article POC 并回滚到手动单账号模式
```

3 个账号值守期间，article 链路只允许通过 `wechat_ui_lock` 串行交错占用微信 PC UI；如果核心群到期或群链路等待超过阈值，article 链路必须释放 UI 并优先保证群链路。

## 7. 暂停和回滚

出现以下任一情况，暂停本轮 POC：

```text
微信健康检查失败
article-rpa-probe 返回 failed
collect-article-once 连续失败
任一账号连续失败 3 次
微信 UI 卡死或长时间不释放
核心群等待超过 max_core_group_block_seconds
CLI、日志或文档输出出现文章正文或具体文章链接
```

回滚方式：

```powershell
python -m app.main article-account-disable --config config/config.dev.yaml --account-name "授权公众号名称"
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

回滚后恢复到手动单账号模式，继续观察微信群链路，确认群链路可独立运行。
