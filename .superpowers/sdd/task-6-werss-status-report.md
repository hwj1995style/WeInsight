# WeRSS Task 6：公众号只读状态查询与后台页面报告

## 交付状态

- 公众号后台仅保留 `GET /sources/articles`；旧新增、编辑、创建、更新、启用、停用和删除入口均返回 404/405，且不调用公众号写服务。
- 群管理路由、表单和写能力保持不变。
- 页面刷新为普通 GET，只执行注入的 `ArticleSourceStatusService.list_page` 查询。
- 状态优先级固定为 `excluded > missing > disabled > unknown > collect_error > stale > normal`；active 且无成功记录显示“等待首轮”。陈旧阈值为两倍全局周期。
- raw、process task、collect log 均先收敛到公众号粒度再 JOIN；错误使用既有输出脱敏。
- 综合状态更新时间取配置更新时间、上游最近确认时间、最近成功采集时间和最新采集日志时间的最大值，因此最新失败也会推进页面时间。

## TDD 证据

1. 初始实现 RED：状态服务模块不存在；GREEN 后状态派生测试通过。
2. 初始 Web RED：`create_app` 不接受可注入状态服务；GREEN 后只读 Web 测试通过。
3. 审查修复 RED：记录模型缺少 `upstream_last_seen_at` 和 `latest_collect_log_time`；GREEN 后综合状态更新时间测试通过。
4. Direction A 回归 RED：工具栏仍期待“公众号名单”；更新为“公众号状态”后通过。

## 验证结果

- `python -m pytest tests/test_web_sources.py tests/test_article_source_status_service.py -q`：64 passed。
- 使用 Windows User 级轮换 `WEINSIGHT_MYSQL_PASSWORD` 执行 `python -m pytest tests/test_article_source_status_mysql.py -q -rs`：2 passed。
- 合并执行 Task 6、真实 MySQL、Web、安全、运行与 Direction A 回归：163 passed。
- `python -m compileall -q app` 与 `git diff --check`：通过。
- MySQL 测试只执行 SELECT；逐公众号将页面仓储结果与独立相关子查询比较，并验证跨页结果无重复。空表时查询和分页仍会完整执行。

## Concerns

- 集成测试针对当前开发库的现有只读快照，不创建专用夹具；因此它验证真实 MySQL 8 语法、结果一致性和分页，但覆盖到的状态组合取决于当前库数据。

## 视觉 QA 修复：旧记录待绑定状态

- 真实页面发现 `upstream_status='unknown'` 的历史记录被误显示为“正常”。
- 新增派生状态 `unknown`，页面文案为“待绑定”；优先级为 `excluded > missing > disabled > unknown > collect_error > stale > normal`。
- 未隐藏或删除任何历史记录，active 的等待首轮、陈旧与正常逻辑保持不变。
- RED：unknown 服务与 Web 测试共 3 项按预期失败；GREEN：Task 6 focused、真实 MySQL 只读集成与 Direction A 视觉回归共 98 passed，`git diff --check` 通过。
