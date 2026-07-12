# Content Task 6A 实施报告

## 状态

已实现持久化账号级下游白名单与受控 WeRSS locator 标准字段映射。未启用或不存在的账号配置默认拒绝创建 `clean_article`；raw 仍正常写入。湖南账号需由配置仓储显式设置 `downstream_clean_enabled=true`。

## RED / GREEN

- RED：`tests/test_article_raw_repo.py` 首次运行显示默认拒绝与历史重复补录失败；`tests/test_rss_feed_client.py` 显示标准 `guid` 无 locator；schema 测试显示迁移缺失。
- RED：`tests/test_werss_content_provider.py::test_requests_verified_werss_views_article_contract` 显示旧请求为 `/article/<id>`，不符合已核验接口。
- GREEN：相关回归 `156 passed`。

## 接口与语义

- `MysqlArticleAccountConfigRepo.set_downstream_clean_enabled(account_name, enabled)`：只接受严格 `bool`，持久化至账号配置。
- `wechat_public_account_config.downstream_clean_enabled TINYINT NOT NULL DEFAULT 0`：安全默认拒绝，进程重启后语义由数据库保持。
- raw 新增和重复/历史补录都会查询持久化开关；允许时使用幂等 `INSERT IGNORE` 补建 clean 任务，不删除既有任务。
- `RssFeedClient` 仅从受控扩展字段及标准 `guid/id` 的精确相对路径 `/views/article/<[A-Za-z0-9_-]{1,200}>` 提取 ID；拒绝绝对外链、查询参数、路径穿越和任意 ID。
- `WeRSSContentProvider` 请求固定 loopback 同源的 `/views/article/<id>`。

## 迁移与真实契约证据

- `20260712_002_add_article_downstream_whitelist.sql` 使用 `information_schema.COLUMNS` 与存储过程实现 MySQL 8.4 可重入迁移，未使用 `ADD COLUMN IF NOT EXISTS`。
- 脱敏真实结构契约固定为标准 RSS `guid=/views/article/MP_WXS_3545051769_abc-123`，契约测试经 feedparser 全链路映射 locator；负例覆盖外域 URL、微信外链查询参数和带 query 的 view 路径。
- 正文接口契约测试验证最终请求路径为 `/views/article/MP_WXS_3545051769_abc-123`，响应仅使用合成安全正文；未记录真实正文或凭据。

## 验证

`python -m pytest tests/test_article_raw_repo.py tests/test_article_account_config_repo.py tests/test_article_downstream_whitelist_schema.py tests/test_rss_feed_client.py tests/test_rss_article_mapper.py tests/test_werss_content_provider.py tests/test_article_parse_repo.py tests/test_article_content_sql_schema.py tests/test_config.py -q`

结果：`156 passed, 1 warning`（feedparser 已知弃用警告）。

全量回归：`python -m pytest -q`，结果 `1685 passed, 2 skipped, 1 warning`。

## Concerns

- 未修改或启用九账号真实配置，避免在“江西九江祺壳蛋/褐壳蛋”名称未确认时猜测。
- 本任务没有携带真实凭据，因此未对本机真实 WeRSS 发请求；接口验证采用脱敏 Feed 契约与 loopback MockTransport。上线前仍需在受控本机执行真实 HTTP 200 探测，且不得输出正文。
- 湖南 24 小时 POC 尚未执行，不能标记 POC 通过。
