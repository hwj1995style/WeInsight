# WeInsight

微信信息采集分析系统。

第一阶段目标：

- 使用开发库 `weinsight_dev`
- 建立 group/article 双链路隔离骨架
- 使用 fake RPA 验证调度、任务状态和 UI 锁
- 后续 POC 再接入微信 PC 4.1.8.107

## 开发数据库

```yaml
host: 127.0.0.1
port: 3307
database: weinsight_dev
username: weinsight
password: WEINSIGHT_MYSQL_PASSWORD
```

## 生产配置模板

生产模板文件：

```text
config/config.prod.example.yaml
```

使用前复制为本地生产配置，并只在环境变量中设置密码：

```powershell
Copy-Item config\config.prod.example.yaml config\config.prod.yaml
$env:WEINSIGHT_MYSQL_PASSWORD='<生产库密码>'
python -m app.main check-config --config config/config.prod.yaml
```

模板不包含真实密码；`mysql.password` 固定使用 `${WEINSIGHT_MYSQL_PASSWORD}`。生产模板默认约束核心群不超过 5 个、公众号/订阅号不超过 20 个，并明确运行日志、截图和日报目录。

生产配置和回滚预案：

```text
docs/operations/生产配置和回滚预案.md
```

生产模板关键默认值：

- MySQL：`prod-mysql.internal:3306/weinsight_prod`，用户 `weinsight_prod`
- 运行日志目录：`runtime/logs`
- 截图目录：`runtime/screenshots`
- 日报导出目录：`runtime/reports`
- 群链路：核心群上限 `5`，轮询间隔 `30` 秒
- 公众号/订阅号链路：账号上限 `20`，默认窗口 `07:30-19:30`，每个账号每小时执行 `1` 次，每次 UI 锁只处理 `1` 个账号，只采当天发布数据并按 `article_hash` 去重；文章解析浏览器默认 `browser_executable_path=auto`，优先复用本机已有 Playwright Chromium 缓存；生产模板默认不启用真实采集

## 第一阶段验证

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m pip install -r requirements.txt
pytest -q
python -m app.main check-config --config config/config.dev.yaml
python -m app.main print-init-sql
cmd /c "docker exec -i pulsebrief-mysql mysql -uweinsight -pweinsight_dev weinsight_dev < sql\init.sql"
```

验收重点：

- `wechat_group_process_task` 和 `wechat_article_process_task` 分表
- `wechat_ui_lock` 支持租约和过期恢复
- 公众号/订阅号链路可按进度恢复
- Playwright 正文解析不持有微信 UI 锁

## 数据库初始化与升级

全新开发库初始化：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
cmd /c "docker exec -i pulsebrief-mysql mysql -uweinsight -pweinsight_dev weinsight_dev < sql\init.sql"
```

已有开发库升级时，不重复重建表，按文件名顺序执行增量迁移：

```powershell
Get-ChildItem sql\migrations\*.sql | Sort-Object Name
cmd /c "docker exec -i pulsebrief-mysql mysql -uweinsight -pweinsight_dev weinsight_dev < sql\migrations\20260703_001_add_group_analysis_quality_fields.sql"
```

脚本职责：

- `sql/init.sql`：全新库完整建表。
- `sql/migrations/`：历史库增量 DDL，文件名格式 `YYYYMMDD_NNN_英文说明.sql`。
- 开发库命令：只写在 README/运行手册中，不作为生产自动迁移脚本。

## 第二阶段 RPA POC 验证

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
pytest -q
python -m app.main wechat-health --config config/config.dev.yaml
cmd /c "docker exec -i pulsebrief-mysql mysql -uweinsight -pweinsight_dev weinsight_dev < sql\init.sql"
docker exec pulsebrief-mysql mysql -uweinsight -pweinsight_dev weinsight_dev -e "SHOW TABLES LIKE 'wechat%';"
```

当前第二阶段默认只做安全健康探测和 fake RPA 验证，不自动操作真实微信群窗口。

真实微信群 POC 前需要确认：

- 微信 PC 主进程健康检查为 `wechat_health_status=ok`
- 微信 PC 版本为 `4.1.8.107`
- 已提供明确测试群名称
- 测试群已授权采集

配置授权核心群：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-config-upsert --config config/config.dev.yaml --group-name "授权测试群名称" --core --priority 1 --poll-interval-seconds 30 --backtrack-pages 1 --extra-backtrack-pages 3
python -m app.main group-config-list --config config/config.dev.yaml
```

禁用群采集：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-config-disable --config config/config.dev.yaml --group-name "授权测试群名称"
```

真实群单次采集命令：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main collect-group-once --config config/config.dev.yaml --group-name "授权测试群名称"
```

该命令会打开指定微信群窗口。只对已授权测试群执行。

群链路调度单轮验证：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-group-scheduler --once --config config/config.dev.yaml
```

调度器会从 `wechat_group_config` 读取已启用核心群，采集前获取 `wechat_ui_lock`，成功或失败均写入 `wechat_group_collect_log`。RPA 异常时截图保存到 `runtime/screenshots/group/YYYYMMDD/`。

查看单个群采集状态：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-status --config config/config.dev.yaml --group-name "授权测试群名称"
```

该命令只输出配置、cursor、最近采集日志和 UI 锁状态，不输出消息正文。

群 raw 到 clean 单批清洗：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main clean-group-once --config config/config.dev.yaml --limit 50
```

该命令只消费 `wechat_group_process_task` 中的 `clean_group_msg` 任务，写入 `wechat_group_msg_clean`，并创建下一阶段 `analyze_group_msg` 任务；清洗过程不占用微信 UI，不输出 raw 原文。

群 clean 到基础分析：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main analyze-group-once --config config/config.dev.yaml --limit 100
```

该命令只消费 `wechat_group_process_task` 中的 `analyze_group_msg` 任务，读取 `wechat_group_msg_clean`，写入 `wechat_group_msg_analysis`，并创建或重置当天 `group_daily_report` 任务；不调用外部 AI，不占用微信 UI。

群分析规则词典默认读取：

```text
config/group_analysis_rules.yaml
```

可在执行分析时指定自定义词典：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main analyze-group-once --config config/config.dev.yaml --rules-config config/group_analysis_rules.yaml --limit 100
```

词典包含规则版本号、变更说明、需求词、供应词、地区词、品类词、商机词和扩展统计词。词典变更只影响后续分析；如需重算历史结果，需要先重置对应 `analyze_group_msg` 任务。

生成群日报草稿：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-daily-report-once --config config/config.dev.yaml --date 2026-07-03
```

可选增加 `--group-name "授权测试群名称"` 只重生成单个群的日报草稿。该命令写入 `wechat_group_daily_report`，默认输出生成计数，不输出消息正文。

日报 v2 会基于 `wechat_group_msg_analysis` 的结构化字段生成可疑商机数、地区 TOP、品类 TOP、商机词 TOP 和联系方式概览。它不回查 raw/clean 消息正文；规则变更后需要先重跑分析，再重生成日报。

查看群日报摘要：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-daily-report-list --config config/config.dev.yaml --date 2026-07-03 --limit 20
```

查看单份群日报 Markdown：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-daily-report-show --config config/config.dev.yaml --date 2026-07-03 --group-name "授权测试群名称"
```

导出单份群日报 Markdown：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-daily-report-export --config config/config.dev.yaml --date 2026-07-03 --group-name "授权测试群名称" --output runtime/reports/group
```

导出文件默认写入 `runtime/reports/group/YYYY-MM-DD/<群名>.md`。以上查看和导出命令只读取 `wechat_group_daily_report`，不回查 raw/clean 消息表。

## 第四阶段公众号/订阅号 POC

第四阶段任务清单：

```text
docs/superpowers/plans/2026-07-03-微信信息采集分析系统第四阶段公众号订阅号POC计划.md
```

当前阶段先落地公众号/订阅号账号配置管理，不启动真实公众号/订阅号采集。

账号配置默认规则：

- 默认窗口：`07:30-19:30`
- 每个公众号/订阅号默认每小时执行 `1` 次
- 每轮最多采集 `5` 篇当天发布文章
- 默认按 `article_hash` 去重
- 每次 UI 锁只处理 `1` 个账号

配置授权公众号/订阅号：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-account-upsert --config config/config.dev.yaml --account-name "授权公众号名称" --account-type subscription --priority 2 --poll-interval-minutes 60 --daily-window-start 07:30 --daily-window-end 19:30 --max-articles-per-round 5 --remark "授权账号"
```

查看公众号/订阅号配置：

```powershell
python -m app.main article-account-list --config config/config.dev.yaml
```

禁用公众号/订阅号：

```powershell
python -m app.main article-account-disable --config config/config.dev.yaml --account-name "授权公众号名称"
```

以上命令只读写 `wechat_public_account_config`，不占用微信 UI，不读写微信群任务表、游标、采集日志或日报。

真实 UI 拿链接 POC：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main collect-article-once --config config/config.dev.yaml --account-name "授权公众号名称" --max-articles-per-round 1
```

`collect-article-once` 必须显式传入 `--account-name`，只对该账号执行一次，不自动扫描全部公众号/订阅号。该命令会占用 `wechat_ui_lock`，拿到链接或失败后释放锁；输出只包含账号名和计数，不输出文章链接或正文。开发阶段仍然手动执行，不注册 Windows 计划任务。

公众号/订阅号真实取链会优先使用“复制链接”，失败时使用 UIA Value 兜底；账号级路由缓存只保存入口能力，不保存真实文章链接。

如果执行期间检测到核心群已到期，article 链路会在安全检查点写入 `wechat_article_collect_progress` 并中断，本轮释放微信 UI；后续再次执行时会从记录的阶段和最近已保存文章链接后继续。

文章链接解析：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main parse-article-once --config config/config.dev.yaml --limit 10
```

`parse-article-once` 只消费文章链路待解析任务，使用浏览器打开已入库链接并写入解析后的元数据和正文长度；该阶段不占用微信 UI 锁，不打开微信窗口，输出只包含 read/success/failed 计数。

公众号/订阅号 POC 监控指标：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-runtime-metrics --config config/config.dev.yaml --hours 24
```

该命令输出账号总数、启用账号数、最近 N 小时采集成功数、失败数、跳过数、采集总数、当前 article 任务积压和最近错误摘要。`skipped` 口径包含被核心群打断的中断记录；命令只读 article 配置、采集日志和任务表，不占用微信 UI，不输出文章链接或正文。

## 第五阶段公众号/订阅号受控真实 POC

第五阶段任务清单：

```text
docs/superpowers/plans/2026-07-06-微信信息采集分析系统第五阶段受控真实POC计划.md
```

阶段五从 1 个授权公众号/订阅号人工值守 POC 开始，验证拿链接、释放微信 UI、浏览器解析、去重入库、失败恢复、指标巡检和双链路隔离。开发阶段继续不注册 Windows 计划任务，不默认开启后台真实采集；1 个账号闭环通过后，才允许扩大到 3 个授权公众号/订阅号人工值守。3 个账号 POC 期间任一账号连续失败 3 次，或核心群等待超过阈值，立即暂停 article 链路并回滚到手动单账号模式，最后再评估是否进入最多 20 个账号的小规模试运行。

公众号/订阅号受控真实 POC 运行手册：

```text
docs/operations/公众号订阅号受控真实POC运行手册.md
```

公众号/订阅号受控真实 POC 验收报告模板：

```text
docs/operations/公众号订阅号受控真实POC验收报告模板.md
```

## 第六阶段清洗和日报

第六阶段任务清单：

```text
docs/superpowers/plans/2026-07-06-微信信息采集分析系统第六阶段清洗和日报计划.md
```

阶段六先补齐 article 后处理能力：文章基础摘要、主题标签分析、文章日报生成、文章日报查看与导出；再设计只读汇总日报层。article 分析采用中间方案：运行时临时读取正文，落库只保存摘要和结构化特征，不保存正文或 HTML。该阶段不打开微信 UI，不获取 `wechat_ui_lock`，不注册 Windows 计划任务。汇总日报只允许读取 group/article 日报结果，汇总日报失败不得回写 group/article 链路状态。

汇总日报运行手册：

```text
docs/operations/汇总日报运行手册.md
```

查看公众号/订阅号文章日报摘要：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-daily-report-list --config config/config.dev.yaml --date 2026-07-06 --limit 20
```

查看单个账号文章日报：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-daily-report-show --config config/config.dev.yaml --date 2026-07-06 --account-name "授权公众号名称"
```

导出单个账号文章日报：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main article-daily-report-export --config config/config.dev.yaml --date 2026-07-06 --account-name "授权公众号名称" --output runtime/reports/article
```

导出文件默认写入 `runtime/reports/article/YYYY-MM-DD/<账号名>.md`。以上命令只读取 `wechat_article_daily_report`，不回查文章采集、解析或分析明细表；列表命令只输出摘要，查看和导出命令输出的是已生成日报草稿。

查看汇总日报：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main summary-daily-report-show --config config/config.dev.yaml --date 2026-07-06
```

导出汇总日报：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main summary-daily-report-export --config config/config.dev.yaml --date 2026-07-06 --output runtime/reports/summary
```

汇总日报只读取 `wechat_group_daily_report` 和 `wechat_article_daily_report`，不占用微信 UI，不回写 group/article 链路状态。

群链路一键流水线手动验证：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-group-pipeline-once --config config/config.dev.yaml --date 2026-07-03 --skip-collect --limit 20 --rules-config config/group_analysis_rules.yaml
```

`--skip-collect` 只执行清洗、分析、日报生成，不打开微信 UI。需要真实采集时必须显式传入已授权群名：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main run-group-pipeline-once --config config/config.dev.yaml --date 2026-07-03 --group-name "授权测试群名称" --limit 20 --rules-config config/group_analysis_rules.yaml
```

真实采集会打开微信窗口；开发阶段仍然手动执行，不注册 Windows 计划任务。

群链路运行状态汇总：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
```

该命令汇总群配置数量、`wechat_group_process_task` 任务状态、`wechat_ui_lock` 当前锁状态和每个群最近一条采集日志。输出只包含状态、计数、错误码和截图路径，不输出消息正文。

群链路试运行监控指标：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-runtime-metrics --config config/config.dev.yaml --hours 24
```

该命令输出最近 N 小时采集成功数、失败数、失败率、当前任务积压和日报生成数。采集和日报指标受 `--hours` 限制，任务积压是当前快照；命令只读状态表和聚合表，不读取消息正文。

群任务补偿工具：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
python -m app.main group-task-list --config config/config.dev.yaml --status failed --limit 20
python -m app.main group-task-reset --config config/config.dev.yaml --task-type analyze_group_msg --ref-id "消息hash"
python -m app.main group-task-reset-date --config config/config.dev.yaml --date 2026-07-03
python -m app.main group-task-failed-list --config config/config.dev.yaml --task-type analyze_group_msg --limit 20
python -m app.main group-task-retry-failed --config config/config.dev.yaml --task-type analyze_group_msg --limit 5
```

补偿命令只访问 `wechat_group_process_task`，用于重置 `clean_group_msg`、`analyze_group_msg` 或 `group_daily_report`。它不占用微信 UI，不读写 `wechat_article_process_task`，也不输出 raw/clean 消息正文。

`group-task-failed-list` 将 `status=failed` 的群任务视为当前阶段死信队列，只输出任务元数据和 `error_summary`。`group-task-retry-failed` 必须带有限量语义，默认和显式 `--limit` 都会进入 SQL，避免一次性重放过多失败任务。

## 第七阶段小规模试运行和AI灰度准备

第七阶段任务清单：

```text
docs/superpowers/plans/2026-07-07-微信信息采集分析系统第七阶段小规模试运行和AI灰度计划.md
```

第七阶段先做无 AI 小规模试运行和日报质量评估，再进入 AI 灰度设计和最小 POC。试运行规模保持核心群不超过 5 个、公众号/订阅号不超过 20 个；AI 默认关闭，灰度阶段只允许输入摘要、结构化特征和脱敏字段，不发送原文、文章全文或 HTML。AI 失败不得回写 group/article 链路状态。

小规模试运行方案：

```text
docs/operations/小规模试运行方案.md
```

日报质量人工评估表和阈值模板：

```text
docs/operations/日报质量人工评估表.md
config/report_quality_review.yaml
```

AI 分析最小 POC 仅支持 dry-run，不调用外部模型：

```powershell
python -m app.main ai-analysis-sample --source summary_daily_report --date 2026-07-07 --dry-run
```

## 第八阶段受控真实账号POC

第八阶段任务清单：

```text
docs/superpowers/plans/2026-07-07-微信信息采集分析系统第八阶段受控真实账号POC计划.md
```

真实 POC 前置复核清单：

```text
docs/operations/真实POC前置复核清单.md
```

第一轮真实 POC 只允许 1 个实际授权公众号/订阅号和 1 个核心群，手动命令触发、有人值守、不注册 Windows 计划任务。AI 仍保持 dry-run，输出必须确认 `model_called=0`。

## 第九阶段真实账户受控 POC 执行与 3 账号小规模扩容

第九阶段任务清单：

```text
docs/superpowers/plans/2026-07-07-微信信息采集分析系统第九阶段真实账户POC执行计划.md
```

第九阶段准入冻结：

```text
docs/operations/第九阶段真实POC执行准入冻结.md
```

第九阶段先执行真实账户受控 POC，再判断是否扩到 3 个公众号/订阅号。第一轮仍只允许 1 个实际授权公众号/订阅号和 1 个实际授权核心群；不注册 Windows 计划任务，不启用无人值守，AI 继续 dry-run 且必须确认 `model_called=0`。3 个账号稳定前，最多 20 个只做后续评估，不在本阶段直接启用。

## 群链路常驻运行

前台启动一次轮询，用于验证启动脚本和日志：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
.\scripts\windows\start_group_scheduler.ps1 -Once
```

常驻运行：

```powershell
$env:WEINSIGHT_MYSQL_PASSWORD='weinsight_dev'
.\scripts\windows\start_group_scheduler.ps1
```

脚本日志写入：

```text
runtime\logs\group_scheduler\group_scheduler_YYYYMMDD.log
```

启动脚本每次运行会在日志中记录启动参数、日志轮转提示和退出码。日志按日期拆分，脚本只提示人工保留/清理策略，不自动删除历史日志；如果 `run-group-scheduler` 异常退出，日志和控制台都会出现异常退出提示。

开发阶段暂不注册 Windows 计划任务。需要进入生产或长稳试运行前，先把 `WEINSIGHT_MYSQL_PASSWORD` 配置为用户或机器级环境变量；注册脚本不会把密码写入计划任务：

```powershell
.\scripts\windows\register_group_scheduler_task.ps1
```

注销计划任务：

```powershell
.\scripts\windows\unregister_group_scheduler_task.ps1
```

## 敏感输出回归

第三阶段新增安全回归检查，用于扫描 CLI 安全输出白名单、README/运行手册示例和已导出的群日报文件：

```powershell
pytest tests/test_sensitive_output_guard.py -q
```

验收要求：巡检、补偿、监控类命令只输出元数据；用户可见文档示例不直接展示敏感正文列名；导出的 Markdown 日报不包含 raw 表字段。

## 第三阶段运维化

第三阶段任务清单：

```text
docs/superpowers/plans/2026-07-03-微信信息采集分析系统第三阶段运维化计划.md
```

微信群链路运行手册与验收清单：

```text
docs/operations/微信群链路运行手册与验收清单.md
```

当前第三阶段从运行手册、任务补偿、失败任务管理、试运行监控、日报质量、生产配置、数据库升级脚本、长稳运行、安全回归和公众号/订阅号启动前复核逐项推进。
