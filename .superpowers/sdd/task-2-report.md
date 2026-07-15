# Task 2 Report: WeRSS 来源身份/状态迁移与存储映射

## 状态

已实现 Task 2 brief 约定的数据库迁移、初始化 schema 和仓储读取映射；未修改 Task 1 的 `ArticlePipelineConfig`，未触碰旧 RPA，也未删除历史数据或跨库操作。

## RED 证据

命令：

```text
python -m pytest tests/test_werss_catalog_sql_schema.py tests/test_article_account_config_repo.py tests/test_sql_migrations.py -q
```

首次运行结果：`4 failed, 26 passed in 2.33s`。

- 迁移文件不存在（2 项）。
- `sql/init.sql` 缺少 `werss_source_id`（1 项）。
- `ArticleAccountConfigRecord` 缺少 `werss_source_id`（1 项）。

这些失败均由目标功能缺失导致，而非测试语法或环境错误。

## GREEN 证据

同一命令实现后运行结果：`30 passed in 0.42s`。

## 变更文件

- `sql/migrations/20260713_001_add_werss_catalog_state.sql`
- `sql/init.sql`
- `app/storage/article_config_repo.py`
- `tests/test_werss_catalog_sql_schema.py`
- `tests/test_article_account_config_repo.py`
- `tests/test_sql_migrations.py`

## 实现与自检

- 新增四个上游目录字段：`werss_source_id`、`upstream_status`、`upstream_last_seen_at`、`upstream_missing_at`。
- `upstream_status` 数据库默认值为 `unknown`；允许值留给应用层校验。
- `werss_source_id` 可空，唯一索引 `uk_public_account_werss_source_id` 因而兼容多条 NULL 历史记录。
- 迁移对四列逐列使用 `information_schema.COLUMNS` 守卫，对索引使用 `information_schema.STATISTICS` 守卫，可重复执行。
- 迁移不包含 `DROP TABLE`、`TRUNCATE TABLE` 或 `DELETE FROM`；只删除迁移过程自身的存储过程。
- `ArticleAccountConfigRecord`、五处账号 SELECT 列表和 `_record_from_row` 均已加入四字段。
- `git diff --check` 无空白错误（仅 Git 提示工作区行尾转换）。

## 全量回归与 concerns

全量 `python -m pytest -q` 结果为 `52 failed, 1422 passed, 2 skipped, 298 errors in 23.43s`，不能作为本任务通过证据。大量错误由本地未配置 `WEINSIGHT_WERSS_ACCESS_KEY` 引发；其余失败位于本任务范围外。Task 2 指定的迁移与仓储测试独立通过，未观察到本任务范围内 concern。
