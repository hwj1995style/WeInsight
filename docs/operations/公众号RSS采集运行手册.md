# 公众号 RSS 采集运行手册

本手册用于在 Windows 采集机的 Docker Desktop 中运行 WeRSS，并通过标准 RSS/Atom 向 WeInsight 提供公众号文章。WeRSS 只监听 `127.0.0.1`，连接现有外部 MySQL；禁止将管理端口开放到公网。WeInsight 不读取 WeRSS 私有表或管理 API。

## 上线前准备

1. 安装并启动 Docker Desktop，确认 `docker compose version` 可用。
2. 从可信来源选择已经过受控 POC 验证的固定镜像标签或摘要。生产值不得使用浮动标签；升级前记录旧值和新值，便于回滚。
3. 记录切换前的代码提交、WeInsight 数据库备份和 WeRSS 数据库备份位置。备份文件不得提交仓库。

## MySQL 建库与授权

由数据库管理员连接现有 MySQL 实例执行以下示例。账号必须独立且遵循最小权限；请替换主机范围与强密码，不要复制示例密码到真实环境。

```sql
CREATE DATABASE werss CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'werss_app'@'%' IDENTIFIED BY '<由密码管理器生成的强密码>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX ON werss.* TO 'werss_app'@'%';
```

若镜像的初始化文档要求额外 DDL 权限，仅在初始化期间临时授予，完成后回收。MySQL 需允许来自 Docker Desktop 网络的连接，但不得因此开放公网。WeRSS 与 WeInsight 使用不同数据库和账号，不存在跨库事务。

## 固定镜像部署

在仓库根目录执行：

```powershell
Copy-Item deploy\werss\.env.example deploy\werss\.env
notepad deploy\werss\.env
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml config
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml pull
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml up -d
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml ps
```

`.env` 中填写经验证的固定 `WERSS_IMAGE`、外部 MySQL 地址和真实凭据。MySQL 位于当前 Windows 主机时使用 `host.docker.internal`；位于其他受控主机时填写其内网 DNS 名。真实 `.env` 已被 `.gitignore` 排除，禁止提交、截图或复制到工单。

健康状态应在启动期后变为 `healthy`。浏览器仅从本机访问 `http://127.0.0.1:8001/`。查看脱敏后的容器日志：

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml logs --tail 200 werss
```

日志由 Docker 轮转为最多 5 个、每个 10 MB；日志或巡检记录不得包含密码、Cookie、文章正文或完整异常响应体。

## 添加公众号与 Feed URL 录入

1. 登录本机 WeRSS 管理界面，添加 1 个已授权公众号并确认授权状态正常。
2. 在 WeRSS 中打开生成的标准 Feed，确认标题、链接和发布时间可见。
3. 在 WeInsight 管理后台为对应来源选择 `rss`，录入完整 Feed URL；首期应为精确允许的本机 WeRSS 地址与端口。
4. 保存后人工触发或等待调度，确认新文章幂等进入 `wechat_article_raw`，并继续完成既有解析、清洗、报价、分析和日报链路。

## 单公众号 24 小时 POC

POC 期间仅运行单公众号 RSS，不同时运行该公众号的旧 RPA。连续观察至少 24 小时并逐篇对账：公众号实际发布记录、WeRSS Feed 条目和 WeInsight 原始文章三方的标题、链接与发布时间应一致；不得有重复业务文章。

验收记录至少包含每次 Feed 可见时间、入库时间、最近成功拉取时间、连续失败次数、连续空 Feed 次数和后处理积压。公众号新文章在 Feed 可见后须在 15 分钟内进入 `wechat_article_raw`。RSS 运行不得获取 `wechat_ui_lock`；退出微信客户端后 RSS 仍应正常。

## 扩容到 3 个公众号

只有单公众号 24 小时 POC 全部通过并由负责人确认后，才在 WeRSS 和 WeInsight 中逐个添加到总计 3 个公众号。每新增一个都重复 Feed URL 校验和发布记录对账，观察错误率、条目新增率、最新文章时间、MySQL 负载与后处理积压；3 个公众号未稳定前不继续扩大范围。

## 日常巡检与异常处理

- 每班检查容器健康、最近成功拉取、Feed 最新文章发布时间、连续失败、连续空 Feed、条目新增率和后处理积压。
- 连续空 Feed 不等于故障：先核对公众号是否确有发布，再检查 WeRSS 授权、风控提示、Feed 最新时间和 HTTP 错误。若有真实发布但连续为空，暂停该 Feed 的扩大使用并重新授权或回滚镜像。
- Docker Desktop 重启后执行 `docker compose ... ps`，等待 `healthy`，然后对所有启用 Feed 补拉一次并依靠幂等去重补齐；不要补跑每个遗漏的调度周期。
- WeRSS 停止或异常只影响公众号新 Feed。微信群采集和已有文章后处理必须继续运行，不能把微信群 Worker 标为不可运行。

## 备份、升级与恢复备份

每次镜像升级、授权变更和扩容前单独备份 `werss` 数据库，并记录镜像引用、备份时间、MySQL 版本和校验值。例如：

```powershell
mysqldump --single-transaction --routines --triggers -h <mysql-host> -u werss_backup -p werss > <受控备份目录>\werss_YYYYMMDD_HHMM.sql
```

不要在命令行写密码。用备份专用只读账号或交互式提示，并定期在隔离数据库做恢复演练。恢复前先停止 RSS：

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml stop werss
mysql -h <mysql-host> -u <恢复账号> -p -e "DROP DATABASE IF EXISTS werss_restore; CREATE DATABASE werss_restore CHARACTER SET utf8mb4;"
mysql -h <mysql-host> -u <恢复账号> -p werss_restore < <受控备份目录>\werss_YYYYMMDD_HHMM.sql
```

先在 `werss_restore` 校验表数量、关键配置和订阅数量。正式恢复须经变更批准，另备份当前库，再将已验证备份恢复到目标 `werss` 库并启动容器，随后检查健康和 Feed。WeInsight 数据库必须按其独立流程恢复，不能假定两库时间点天然一致。

## 停止 RSS 与回滚

紧急停止 RSS 时，先在 WeInsight 禁用所有公众号 RSS 调度并确认没有新运行实例，再停止 WeRSS：

```powershell
docker compose --env-file deploy\werss\.env -f deploy\werss\docker-compose.yml stop werss
```

镜像回滚时保留故障现场与脱敏日志，把 `.env` 中 `WERSS_IMAGE` 改回已记录的旧固定标签或摘要，必要时按上一节恢复备份，然后执行 `pull`、`up -d` 和健康检查。恢复后补拉一次并对账。不得同时恢复并运行公众号旧 RPA；微信群 RPA 不受此操作影响。

## 最终删除公众号 RPA 的准入条件

最终删除公众号 RPA 代码、配置、专属测试和数据库对象前，必须同时满足：

1. 单公众号 RSS 连续 24 小时验收通过，3 个公众号扩容观察也无阻断问题。
2. Feed 可见后 15 分钟内入库、无重复业务文章、既有后处理和日报无退化。
3. 已验证微信退出不阻塞 RSS，WeRSS 停止不阻塞微信群及已有文章后处理，RSS 不获取 `wechat_ui_lock`。
4. 已完成并验证 WeInsight 与 WeRSS 的独立备份，保留切换前代码提交和恢复记录，并获得人工变更批准。

最终删除后不再提供公众号旧 RPA 的运行时应急入口。此后的回滚只能停止 RSS 新链路，并恢复切换前代码与相应数据库备份。
