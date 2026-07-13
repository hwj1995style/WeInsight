# Task 1 实施报告

## RED

- 命令：`python -m pytest tests/test_article_source_status_service.py -q`
- 结果：预期失败，`16 passed, 1 failed`。
- 失败原因：新契约测试找不到 `config.werss_source_id IS NOT NULL`，证明原查询未限定当前 WeRSS 目录。

## GREEN 与验证

- 最小实现：在状态查询最后一个 `LEFT JOIN` 后、`ORDER BY` 前增加 `config.werss_source_id IS NOT NULL` 与 `config.upstream_status IN ('active', 'disabled')`。
- GREEN 命令：`python -m pytest tests/test_article_source_status_service.py -q`
- GREEN 结果：`17 passed in 0.32s`。
- 定向命令：`python -m pytest tests/test_article_source_status_service.py tests/test_article_source_status_mysql.py tests/test_web_sources.py -q`
- 定向结果：`68 passed, 2 skipped in 2.06s`；MySQL 行为测试因测试凭据/数据库不可用而跳过。
- 全量命令：`python -m pytest -q`
- 全量结果：`1861 passed, 4 skipped, 5 failed, 19 errors in 22.61s`。失败/错误来自缺少 `WEINSIGHT_WERSS_ACCESS_KEY` 等环境变量及 MySQL 用户访问被拒绝；定向范围无失败。
- 空白检查：提交前 `git diff --check` 退出码为 0。

## 变更摘要

- SQL 在排序和分页前仅选择有 `werss_source_id` 且上游状态为 `active` 或 `disabled` 的记录。
- 保留停用来源；`missing`、`excluded`、`unknown` 仅从状态页查询中排除，不删除任何历史数据。
- 服务层与 Web 层未增加分页后二次过滤。
- 新增 SQL 顺序契约测试及 MySQL 结果行为断言。

## 提交

- 实现提交：`fe3064f`（`fix: hide non-WeRSS sources from status page`）

## 担忧

- 当前环境无法执行两个只读 MySQL 行为测试，也无法让全量套件完全通过；需要在具备有效测试数据库凭据及完整 WeRSS 环境变量的 CI/环境中复验。
