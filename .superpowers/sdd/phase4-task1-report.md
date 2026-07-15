# 阶段四 Task 1 实施报告：日报请求表与生命周期字段

## 交付范围

本任务严格按阶段四正式计划 Task 1 和实施简报交付：

- 新增 `wechat_report_generation_request` 请求表迁移；
- 为群日报和文章日报新增四个生命周期字段的增量迁移；
- 同步 `sql/init.sql` 的全新库最终结构；
- 新增日报生命周期 SQL Schema 契约测试。

未提前实现 Task 2 的 Python 生命周期类型、日报 Repo、后处理 Worker 或 Web 生成入口，也未修改已有日报正文和业务统计逻辑。

## 请求表结构

`wechat_report_generation_request` 包含请求幂等键、日报类型、业务日期、可选对象、生成触发方式、数据截止时间、申请人、请求状态、Worker 租约、脱敏错误摘要及开始/结束时间。

- `idempotency_key` 使用唯一键 `uk_report_request_idempotency`；
- `status` 默认 `pending`，支持 `pending/running/success/partial_success/failed`；
- 待领取查询使用 `(status, create_time)` 索引；
- 日期与类型查询使用 `(report_date, report_type)` 索引；
- migration 与 init 的完整建表 DDL 保持一致。

## 日报生命周期与历史数据

`wechat_group_daily_report` 和 `wechat_article_daily_report` 均增加：

- `report_status`：默认 `final`；
- `data_cutoff_time`：允许为空，迁移后由原 `generate_time` 回填；
- `generation_trigger`：默认 `legacy`；
- `last_generated_by`：默认 `system`。

历史回填仅执行两条有条件 UPDATE：分别对群日报和文章日报设置 `data_cutoff_time = generate_time WHERE data_cutoff_time IS NULL`。迁移不更新 `markdown_body` 或任何消息数、发送人数、文章数、平均正文长度等业务统计字段。

## 迁移安全

- 请求表使用 `CREATE TABLE IF NOT EXISTS`；
- 生命周期迁移逐表逐列查询 `information_schema.COLUMNS`，共八个探测；
- 每个探测都直接限定 `TABLE_SCHEMA = DATABASE()`，不会被其他库同名表误导；
- 动态变量和 PREPARE 名称使用本任务专属的 `@report_lifecycle_ddl` 与 `report_lifecycle_stmt`；
- 两份迁移不包含 `DROP TABLE`、`DROP COLUMN`、`TRUNCATE TABLE` 或 `DELETE FROM`；
- 未删除、清空或重建现有日报表。

## TDD 证据

1. 先新增 `tests/test_report_lifecycle_sql_schema.py`，初次运行 `4 failed`，均因两份目标迁移不存在而失败。
2. 最小实现请求表迁移、生命周期迁移和 init 同步后，同一测试转为 `4 passed`。
3. Schema 定向回归覆盖新契约、迁移目录规则、群日报与文章日报已有结构，共 `13 passed`。

## 真实 MySQL 8.4 验证

使用本机 MySQL `8.4.9` 和唯一命名的临时数据库完成：

1. 全新执行 `sql/init.sql`，确认请求表和两张日报表共八个生命周期字段存在；
2. 在全新 init 后连续执行两份迁移两轮，均成功；
3. 重建为旧式群/文章日报结构，各插入一条历史行，再连续执行两份迁移两轮；
4. 两条历史行均得到 `final/legacy/system`，`data_cutoff_time` 等于原 `generate_time`；
5. 原 Markdown 和群消息数、发送人数、文章数、平均正文长度保持不变；
6. 重复写入同一 `idempotency_key` 返回 MySQL `1062`，表内仅保留一条请求；
7. `finally` 删除临时数据库，并通过 `information_schema.SCHEMATA` 确认不存在。

验证结果：`INIT_SCHEMA=PASS`、`MIGRATION_FIRST_AND_REPEAT=PASS`、`LEGACY_CUTOFF_ONLY_BACKFILL=PASS`、`IDEMPOTENCY_UNIQUE_KEY=PASS`、`TEMPORARY_DATABASE_REMOVED=True`。

## 最终验证

- Schema 定向回归：`13 passed`；
- 全量测试：`1378 passed, 1 skipped`；
- `python -m compileall -q app tests`：通过；
- `git diff --check`：通过；
- UTF-8 替换字符扫描：通过。
