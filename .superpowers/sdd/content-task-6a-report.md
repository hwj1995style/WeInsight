# Content Task 6A 实施报告

## 状态

已实现持久化账号级下游白名单与受控 WeRSS locator 标准字段映射。未启用或不存在的账号配置默认拒绝创建 `clean_article`；raw 仍正常写入。湖南账号需由配置仓储显式设置 `downstream_clean_enabled=true`。

## RED / GREEN

- RED：`tests/test_article_raw_repo.py` 首次运行显示默认拒绝与历史重复补录失败；`tests/test_rss_feed_client.py` 显示标准 `guid` 无 locator；schema 测试显示迁移缺失。
- 复审 RED：setter 对不存在账号静默成功；URL 重复与 `INSERT IGNORE` 竞态使用传入新 hash 或不补任务；真实标准字段与手写 fixture 不一致；九账号 seed 缺失。
- GREEN：复审定向回归 `90 passed`，全量回归 `1693 passed, 2 skipped`。

## 接口与语义

- `MysqlArticleAccountConfigRepo.set_downstream_clean_enabled(account_name, enabled)`：只接受严格 `bool`，且 UPDATE 必须恰好命中一行；账号不存在抛出 `LookupError`。
- `wechat_public_account_config.downstream_clean_enabled TINYINT NOT NULL DEFAULT 0`：安全默认拒绝，进程重启后语义由数据库保持。
- raw 新增和重复/历史补录都会查询持久化开关；URL/hash 重复时使用数据库返回的 canonical `article_hash`，`INSERT IGNORE rowcount=0` 竞态也重新查询 canonical hash 后幂等补任务。
- `RssFeedClient` 对真实标准字段只接受 `id == link`、固定 `https://mp.weixin.qq.com`、精确 `/s/<[A-Za-z0-9_-]{1,200}>` 且无 query/fragment；仍兼容受控扩展字段的精确相对 view 路径。拒绝外域、字段不一致、查询参数、路径穿越和任意 URL。
- `WeRSSContentProvider` 请求固定 loopback 同源的 `/article/<id>`。

## 迁移与真实契约证据

- `20260712_002_add_article_downstream_whitelist.sql` 使用 `information_schema.COLUMNS` 与存储过程实现 MySQL 8.4 可重入迁移，未使用 `ADD COLUMN IF NOT EXISTS`。
- 迁移在本机 MySQL 8.4 `weinsight_dev` 连续执行两次成功。随后以 UTF-8 安全 seed 九个真实 Feed 映射；数据库聚合核验为 `9` 个目标、`9` 个 enabled、`1` 个 downstream，且该 1 个为湖南、其余异常 downstream 数为 `0`。
- 真实无凭据请求 `http://127.0.0.1:8001/feed/MP_WXS_3545051769.rss`：HTTP 200、RSS 2.0、25 条；真实字段为相同的官方微信 `id/link`，受控适配后 locator 为 25/25（100%）。
- 使用其中一个 locator 对本机 `/article/<id>` 发起流式请求且不读取/输出正文：HTTP 200，`text/html; charset=utf-8`；对照 `/views/article/<id>` 为 404 JSON，因此实现按真实契约恢复 `/article/<id>`。

## 验证

`python -m pytest tests/test_article_raw_repo.py tests/test_article_account_config_repo.py tests/test_article_downstream_whitelist_schema.py tests/test_rss_feed_client.py tests/test_rss_article_mapper.py tests/test_werss_content_provider.py tests/test_article_parse_repo.py tests/test_article_content_sql_schema.py tests/test_config.py -q`

结果（复审定向）：`90 passed, 1 warning`（feedparser 已知弃用警告）。

全量回归：`python -m pytest -q`，结果 `1693 passed, 2 skipped, 1 warning`。

## Concerns

- 九账号名称已按用户确认使用“江西九江褐壳蛋”；`sql/deploy/20260712_seed_werss_nine_accounts.sql` 可重入部署，采集全部启用，仅湖南下游启用。
- 湖南 24 小时 POC 尚未执行，不能标记 POC 通过。
