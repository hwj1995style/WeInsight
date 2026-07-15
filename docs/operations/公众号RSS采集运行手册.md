# 公众号 RSS 采集运行手册

本手册用于在 Windows 采集机的 Docker Desktop 中运行 WeRSS，并通过标准 RSS/Atom 向 WeInsight 提供公众号文章。WeRSS 只监听 `127.0.0.1`，连接现有外部 MySQL；禁止将管理端口开放到公网。WeInsight 只通过固定本机只读 API `http://127.0.0.1:8001/api/v1/wx/mps` 的 GET 请求同步公众号清单；禁止跨库读取 WeRSS 私有表，禁止向 WeRSS 发起写请求。

## 只读清单凭据与边界

1. 由 controller 在 WeRSS 管理端创建专用凭据，名称固定为 `WeInsight read-only catalog`，权限只允许读取公众号清单；不得复用管理员凭据。
2. 将 AK/SK 写入 Windows User 环境变量 `WEINSIGHT_WERSS_ACCESS_KEY` 和 `WEINSIGHT_WERSS_SECRET_KEY`。仓库、YAML、数据库、日志、HTML、截图和测试输出均不得出现真实值。
3. 新进程只在启动时读取环境变量。凭据轮换时先创建新只读凭据、更新两个 User 环境变量并受控重启 WeInsight，再撤销旧凭据；核验日志仅允许出现稳定错误码。
4. 清单同步每 10 分钟运行一次，只读 API 不可用时保留最近一次完整清单和历史文章，不把来源误标为缺失，不尝试跨库或写 WeRSS。
5. 服务端始终排除“一箱蛋”，不得为其创建采集、清洗、分析或报价任务。公众号旧 RPA 继续禁止，禁止恢复旧命令、调度、探针或 UI 锁入口。

2026-07-13 本机开发环境已通过 WeRSS 自身授权机制创建专用凭据，并将 AK/SK 写入 Windows User 环境变量；本文只记录“已配置”，不记录、读取或输出真实值。迁移 `20260713_001_add_werss_catalog_state.sql` 和 `20260713_004_system_article_job_singleton.sql` 已应用。

## 只读清单切换顺序

1. 停止旧 collector 和 pipeline，记录运行中任务并备份 `weinsight_dev`。
2. 依次应用 `20260713_001_add_werss_catalog_state.sql`、`20260713_004_system_article_job_singleton.sql`，再启动 web、collector 和 pipeline。
3. 等待至少两个全局周期，确认范围内来源同步完整、“一箱蛋”新任务为 0、公众号 `article_ui_lock_count` 为 0、新文章按状态进入 parse/analyze/报价表且微信群 Worker 正常。
4. WeRSS 不可用时不得切回跨库或写接口；恢复 API 后等待完整清单成功，再观察下一全局周期。
5. 旧观察窗口因清单同步架构改造失效。只有首个 9/9 成功且增量流水线健康后，才重新开始连续 24 小时观察，旧轮次不得拼接。

本次开发环境切换的即时门禁已于 2026-07-13 18:39:49 +08:00 完成：唯一活动公众号任务为 ID 10、`managed_key=article_global`、间隔 600 秒；旧手工公众号任务均已停止或删除。run 206 于 18:39:32 调度、18:39:33 开始、18:39:49 结束，9/9 成功。“一箱蛋”保持 `enabled=0`、`upstream_status=excluded`，观察起点后新增 raw 和处理任务均为 0；公众号活动 UI 锁为 0。新的连续 24 小时观察从 2026-07-13 18:39:32 +08:00 开始，门禁时间为 2026-07-14 18:39:32 +08:00；门禁到达前不得标记验收通过。

公众号 RPA 已删除。现行回滚只能停止 RSS、恢复已批准的 RSS 代码版本和对应数据库备份；不得恢复或重新运行公众号 RPA。

## 上线前准备

1. 安装并启动 Docker Desktop，确认 `docker compose version` 可用。
2. 本仓库固定使用官方 `rachelos/we-mp-rss` 多架构镜像摘要 `sha256:53912fcb3d523d1e640adcb7066cc18123f00e9510882a7982d0991f3113845f`。禁止改用浮动标签；升级必须先验证新摘要并记录旧值和新值。
3. 记录切换前的代码提交、WeInsight 数据库备份和 WeRSS 数据库备份位置。备份文件不得提交仓库。

## MySQL 建库与授权

由数据库管理员连接现有 MySQL 实例执行以下 SQL。独立账号遵循最小权限。示例按 Docker Desktop 常见内部网段限制为 `192.168.65.%`；管理员必须先用 MySQL 连接日志或临时测试账号确认本机 Docker Desktop 的真实来源网段，再把下面两处主机值改成该网段。不得使用 `%` 全主机授权。

```sql
CREATE DATABASE werss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'werss_app'@'192.168.65.%' IDENTIFIED BY '由密码管理器生成并仅写入本机env的强密码';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON werss.* TO 'werss_app'@'192.168.65.%';
```

官方镜像通过 `DB` 环境变量接收 SQLAlchemy URL，格式为 `mysql+pymysql://用户:URL编码后的密码@host.docker.internal:3306/werss?charset=utf8mb4`。若密码含 `@`、`:`、`/` 等保留字符，必须先做 URL 编码。额外 DDL 权限仅在初始化需要时授予，完成后回收。MySQL 防火墙只允许确认过的 Docker Desktop 内部网段；Docker Desktop 仅限受控 Windows 管理员账号访问，禁止开启不受控 TCP daemon。

## 固定镜像部署

在仓库根目录执行：

```powershell
Copy-Item deploy\werss\.env.example deploy\werss\.env
notepad deploy\werss\.env
icacls deploy\werss\.env /inheritance:r /grant:r "${env:USERNAME}:(R,W)"
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml config
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml pull
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml up -d
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml ps
```

`.env` 只填写端口和 `DB` URL；固定镜像摘要已跟踪在 Compose 中。MySQL 位于当前 Windows 主机时使用 `host.docker.internal`；位于其他受控主机时填写其内网 DNS 名。`icacls` 会移除继承权限并仅授权当前运维用户读写。随后用 `icacls deploy\werss\.env` 复核，不得出现普通用户组。真实 `.env` 已被 `.gitignore` 排除，禁止提交、截图或复制到工单。`deploy/werss/data` 是官方 `/app/data` 的持久化目录，也要限制 ACL 并纳入受控备份。

健康状态应在启动期后变为 `healthy`。浏览器仅从本机访问 `http://127.0.0.1:8001/`。查看脱敏后的容器日志：

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml logs --tail 200 werss
docker inspect --format '{{.State.Health.Status}}' $(docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml ps -q werss)
```

继续使用官方固定摘要，不构建内部镜像。已知官方版本的 SQL 参数可能包含正文，用户接受其仅保留在本机 Docker 日志的剩余风险。Docker Desktop 仅允许最小范围本机管理员访问；日志不接入外部日志，不复制到工单，不纳入备份，也不得截图或导出。Docker 轮转为最多 2 个、每个 2 MB，并持续关注上游关闭参数日志的受支持开关。WeInsight 自身日志或巡检记录仍不得包含密码、Cookie、文章正文或完整异常响应体。

## 添加公众号与 Feed URL 录入

1. 登录本机 WeRSS 管理界面，添加 1 个已授权公众号并确认授权状态正常。
2. 在 WeRSS 中打开生成的标准 Feed，确认标题、链接和发布时间可见。
3. 在 WeInsight 管理后台为对应来源选择 `rss`，录入完整 Feed URL；首期应为精确允许的本机 WeRSS 地址与端口。
4. 保存后人工触发或等待调度，确认新文章幂等进入 `wechat_article_raw`，并继续完成既有解析、清洗、报价、分析和日报链路。

## 单公众号 24 小时 POC

POC 期间仅运行单公众号 RSS。连续观察至少 24 小时并逐篇对账：公众号实际发布记录、WeRSS Feed 条目和 WeInsight 原始文章三方的标题、链接与发布时间应一致；不得有重复业务文章。

验收记录至少包含每次 Feed 可见时间、入库时间、最近成功拉取时间、连续失败次数、连续空 Feed 次数和后处理积压。公众号新文章在 Feed 可见后须在 15 分钟内进入 `wechat_article_raw`。RSS 运行不得获取 `wechat_ui_lock`；退出微信客户端后 RSS 仍应正常。

在 MySQL 客户端中以只读巡检账号执行以下精确检查。将 `授权公众号名称` 改为本次 POC 名称；返回的 `over_15_minute_count` 必须为 0，`article_ui_lock_count` 必须为 0：

```powershell
mysql -h 127.0.0.1 -P 3307 -u weinsight_monitor -p weinsight_prod -e "SELECT account_name, COUNT(*) AS article_count, MAX(collect_time) AS latest_collect_time, MAX(TIMESTAMPDIFF(MINUTE, publish_time, collect_time)) AS max_delay_minutes, SUM(TIMESTAMPDIFF(MINUTE, publish_time, collect_time) > 15) AS over_15_minute_count FROM wechat_article_raw WHERE account_name='授权公众号名称' AND collect_time >= NOW() - INTERVAL 24 HOUR GROUP BY account_name;"
mysql -h 127.0.0.1 -P 3307 -u weinsight_monitor -p weinsight_prod -e "SELECT COUNT(*) AS article_ui_lock_count FROM wechat_ui_lock WHERE owner_pipeline='article';"
mysql -h 127.0.0.1 -P 3307 -u weinsight_monitor -p weinsight_prod -e "SELECT account_name, start_time, end_time, feed_item_count, insert_count, duplicate_count, invalid_count, http_status, elapsed_ms, status, error_code FROM wechat_article_collect_log WHERE account_name='授权公众号名称' AND start_time >= NOW() - INTERVAL 24 HOUR ORDER BY start_time;"
```

`publish_time` 是文章发布时间，不一定等于 Feed 首次可见时间，因此 SQL 是保守巡检；最终 15 分钟 SLA 仍以人工记录的 Feed 首次可见时间与 `collect_time` 对账。

## WeRSS 正文按需读取切换

正文链路只允许在固定镜像摘要下启用。每次部署或升级先执行正文接口契约验证：确认本机受控文章查看路由仍返回允许的内容类型，locator 不能越界，重定向、响应上限、空正文和超时行为与自动化契约测试一致。契约不一致时保持 `content_mode: web`，不得进入影子验证。

首轮范围固定为“湖南三尖农牧公司”（Feed ID `MP_WXS_3545051769`）。先把该来源配置为 `content_mode: shadow`，以同一篇安全样本分别走 WeRSS 与网页路径，只记录正文长度、内容哈希是否一致、结构化报价差异和结构化错误码，不记录或打印正文。影子结果无不可解释差异后，才能切为 `content_mode: werss_first` 并开始至少 24 小时观察；观察未满时状态只能写“进行中”。

每轮巡检记录正文成功、网页回退、正文失败和正文任务积压指标，同时检查 `article_ui_lock_count=0`。切换前后都执行数据库与日志无正文检查，禁止保存或输出文章正文、原始 HTML、Cookie、令牌或完整敏感 URL。

WeRSS 重启恢复演练按以下顺序进行：先记录基线并停止 WeRSS，触发一个受控任务确认网页回退成功；随后立即恢复容器并等待 `healthy`，再触发下一任务确认来源回到 WeRSS。停机窗口不得扩大公众号范围，演练结束必须确认 WeRSS 为 `healthy`。

若出现接口契约变化、不可解释报价差异、永久任务失败、WeInsight 日志或数据库正文泄漏，或官方 Docker 日志超出已接受的本机短轮转边界，立即把单公众号配置回滚到 `content_mode: web`，停止观察扩容，并保留不含正文与凭据的结构化证据。

### 九账号采集与湖南下游分开验收

当前状态：9 个公众号全部启用采集，但仅湖南三尖农牧公司进入 clean/analyze，其余 8 个只采集。隔离由可测试的下游白名单控制任务创建，不能手工删除任务或靠停止通用 worker 实现。下游白名单已实现并完成自动化验证；运行巡检仍须确认其余 8 个账号没有新增 clean/analyze 任务。

能力补齐后分开验收：采集层对 9 个账号检查采集完整率、去重和采集延迟；下游仅对湖南三尖农牧公司检查正文成功率、网页回退、失败恢复、结构化报价和分析。湖南 POC 通过后才扩展下游白名单。此处的 9 账号采集扩展不等于正文下游扩展。

湖南真实 Feed 与正文接口契约已完成验证，25/25 locator 可映射；WeRSS 的九个 Feed 均存在，“江西九江褐壳蛋”已确认与实际 Feed 名一致。后续镜像升级仍须重新执行 locator 与正文接口契约检查，未通过时保持 `content_mode: web`。

## 扩容到 3 个公众号

只有单公众号 24 小时 POC 全部通过并由负责人确认后，才在 WeRSS 和 WeInsight 中逐个添加到总计 3 个公众号。每新增一个都重复 Feed URL 校验和发布记录对账，观察错误率、条目新增率、最新文章时间、MySQL 负载与后处理积压；3 个公众号未稳定前不继续扩大范围。

## 日常巡检与异常处理

- 每班检查容器健康、最近成功拉取、Feed 最新文章发布时间、连续失败、连续空 Feed、条目新增率和后处理积压。
- 连续空 Feed 不等于故障：先核对公众号是否确有发布，再检查 WeRSS 授权、风控提示、Feed 最新时间和 HTTP 错误。若有真实发布但连续为空，暂停该 Feed 的扩大使用并重新授权或回滚镜像。
- Docker Desktop 重启后执行 `docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml ps`，等待 `healthy`，然后对所有启用 Feed 补拉一次并依靠幂等去重补齐；不要补跑每个遗漏的调度周期。
- WeRSS 停止或异常只影响公众号新 Feed。微信群采集和已有文章后处理必须继续运行，不能把微信群 Worker 标为不可运行。

## 备份、升级与恢复备份

每次镜像升级、授权变更和扩容前单独备份 `werss` 数据库，并记录镜像引用、备份时间、MySQL 版本和校验值。以下命令可直接在 PowerShell 执行；MySQL 会交互读取密码：

```powershell
$BackupDir = 'D:\WeInsightBackups\werss'
New-Item -ItemType Directory -Force -Path $BackupDir
$BackupPath = Join-Path $BackupDir ("werss_{0}.sql" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
cmd /c "mysqldump --single-transaction --routines --triggers -h 127.0.0.1 -P 3306 -u werss_backup -p werss > `"$BackupPath`""
Get-FileHash -Algorithm SHA256 -LiteralPath $BackupPath
```

不要在命令行写密码。用备份专用只读账号或交互式提示，并定期在隔离数据库做恢复演练。恢复前先停止 RSS：

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml stop werss
$BackupPath = 'D:\WeInsightBackups\werss\werss_20260711_230000.sql'
mysql -h 127.0.0.1 -P 3306 -u werss_restore_admin -p -e "DROP DATABASE IF EXISTS werss_restore; CREATE DATABASE werss_restore CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
cmd /c "mysql -h 127.0.0.1 -P 3306 -u werss_restore_admin -p werss_restore < `"$BackupPath`""
mysql -h 127.0.0.1 -P 3306 -u werss_restore_admin -p -e "SELECT COUNT(*) AS table_count FROM information_schema.tables WHERE table_schema='werss_restore';"
```

先在 `werss_restore` 校验表数量、关键配置和订阅数量。正式恢复须经变更批准，另备份当前库，再将已验证备份恢复到目标 `werss` 库并启动容器，随后检查健康和 Feed。WeInsight 数据库必须按其独立流程恢复，不能假定两库时间点天然一致。

## 停止 RSS 与回滚

紧急停止 RSS 时，先逐个禁用来源，再请求停止所有 article 调度。下列 SQL 必须在变更单批准后由控制面数据库账号执行；它不会杀死正在运行的进程，因此随后必须确认活动运行数为 0：

```powershell
python -m app.main article-account-disable --config config/config.prod.yaml --account-name "授权公众号名称"
mysql -h 127.0.0.1 -P 3307 -u weinsight_control -p weinsight_prod -e "UPDATE wechat_collection_job SET status='stop_requested', stop_requested_at=NOW(), stop_requested_by='werss-rollback', version=version+1 WHERE pipeline_type='article' AND status IN ('scheduled','active');"
mysql -h 127.0.0.1 -P 3307 -u weinsight_monitor -p weinsight_prod -e "SELECT COUNT(*) AS active_article_run_count FROM wechat_collection_job_run r INNER JOIN wechat_collection_job j ON j.id=r.job_id WHERE j.pipeline_type='article' AND r.status IN ('queued','running');"
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml stop werss
```

镜像回滚时保留故障现场与脱敏日志，把 Compose 中镜像改回变更记录中的旧固定摘要，必要时按上一节恢复备份，然后执行以下命令。恢复后重新启用来源与调度前先人工打开 Feed 并完成一次对账。不得恢复或运行任何公众号旧 RPA；微信群 RPA 不受此操作影响。

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml pull werss
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml up -d werss
docker inspect --format '{{.State.Health.Status}}' $(docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml ps -q werss)
python -m app.main article-account-list --config config/config.prod.yaml
```

## 最终删除公众号 RPA（已完成退役审计）

公众号 RPA 已删除，以下条目仅保留为切换决策的历史审计条件，不再是可执行的删除步骤：

1. 单公众号 RSS 连续 24 小时验收通过，3 个公众号扩容观察也无阻断问题。
2. Feed 可见后 15 分钟内入库、无重复业务文章、既有后处理和日报无退化。
3. 已验证微信退出不阻塞 RSS，WeRSS 停止不阻塞微信群及已有文章后处理，RSS 不获取 `wechat_ui_lock`。
4. 已完成并验证 WeInsight 与 WeRSS 的独立备份，保留切换前代码提交和恢复记录，并获得人工变更批准。

当前不提供公众号旧 RPA 的运行时应急入口。此后的回滚只能停止 RSS 新链路，并恢复已批准的 RSS 代码版本与相应数据库备份；不得恢复或重新运行公众号 RPA。
