# 阶段四 Task 2 实施报告：日报生命周期元数据

## 结论

Task 2 已按正式计划完成。群日报和文章日报现已在领域、生成、存储、查询及既有 CLI/pipeline 调用链中显式携带生命周期元数据；未提前实现日报请求 Repo、Worker 或 Web 请求交互。

## 实现范围

- 新增 frozen `ReportLifecycle`、`ReportStatus` 与 `GenerationTrigger`。
- lifecycle 四字段全部必填并主动校验：
  - `data_cutoff_time` 必须使用真实的 `ZoneInfo("Asia/Shanghai")` aware datetime。
  - `last_generated_by` 去除两端空白后必须为 1–100 字符，且不能包含控制字符。
  - provisional 固定为 manual；final 接受四种已知 trigger；未知 enum 拒绝。
  - 手动生成今日为 provisional，历史日期为 final/manual，未来日期拒绝。
- 群/文章 `generate_once` 和 Repo Protocol 增加必填 lifecycle，不提供默认值。
- 两类日报 INSERT 与 `ON DUPLICATE KEY UPDATE` 均覆盖 `report_status`、`data_cutoff_time`、`generation_trigger`、`last_generated_by`；cutoff 写库前转换为 naive 上海本地时间。
- 两类 summary/detail 读取模型暴露四个 lifecycle 字段；Repo 明确 SELECT 四列，通过完整 `ReportLifecycle` 重建跨字段不变量，并将数据库时间恢复为 `Asia/Shanghai` aware datetime。未知 status/trigger、非法组合及非法 actor 均 fail closed。
- `GroupPipelineService` 显式接收并传递 lifecycle。
- `group-daily-report-once` 与 `run-group-pipeline-once` 使用同一个上海时区 `now` 调用 `manual_for_date(..., "cli")`；生成时间保留既有 MySQL naive 约定；未来日期输出安全错误并返回 1。
- 现有 Web 报表 fake/test double 已显式补齐 lifecycle，未增加新页面交互。

## TDD 记录

依次观察到以下预期 RED，再做最小实现转 GREEN：

1. 生命周期模块不存在，`tests/test_report_lifecycle.py` 收集失败。
2. 两类 `generate_once` 不接受 lifecycle，4 个服务测试失败。
3. 两类 Repo 不接受 lifecycle，2 个持久化测试失败。
4. summary/detail 缺少 lifecycle 字段且未知 enum 未拒绝，8 个查询测试失败。
5. pipeline `run_once` 未接收 lifecycle，4 个测试失败。
6. 两个 CLI 未构造/传递 lifecycle 且未来日期未前置拒绝，5 个测试失败。
7. 代码复审后补充非法 status/trigger 组合及空白/NULL actor 测试，观察到 6 个查询 RED；查询 Repo 改为重建完整 `ReportLifecycle` 后转 GREEN。

新增测试覆盖 frozen、字段校验、今日/历史/未来规则、两类持久化四列、upsert lifecycle 更新、summary/detail 时区与严格 enum、pipeline/CLI 显式传递和安全错误。

## 调用点审计

执行：

```powershell
rg -n "generate_once\(" app tests -g '*.py'
```

结果共 11 个匹配，均为方法定义或显式传入 lifecycle 的调用；未通过默认参数掩盖旧调用。

正式计划中的 `tests/test_group_daily_report.py` 在仓库中不存在；群日报生成测试实际位于 `tests/test_group_analysis_service.py`，定向验证已使用该现有文件。

## MySQL 8.4 实库验证

在本机 `mysql:8.4.9` 容器建立独立临时库，执行 `sql/init.sql` 与 `20260710_004_add_report_lifecycle.sql` 后验证：

- 群日报 provisional 首次写入及 final/compensation 重复 upsert。
- 文章日报 provisional 首次写入及 final/automatic 重复 upsert。
- 两类唯一键均保持单条记录。
- 两类 summary/detail 正确读回 enum、actor 和 `Asia/Shanghai` aware cutoff。
- 人工写入 `provisional + automatic` 和空白 actor 后，两类查询均 fail closed。

结果：初次验证 `MYSQL_8_4_REPORT_LIFECYCLE=PASS`，复审修复后验证 `MYSQL_8_4_REPORT_LIFECYCLE_REVIEW_FIX=PASS`。每轮均在 `finally` 删除临时库并确认：`MYSQL_TEMP_DATABASE_CLEANED=True`。

## 代码复审

只读复审未发现 Critical。发现并修复 1 个 Important：原查询映射分别解析 enum/cutoff，却用 `str(...)` 宽松转换 actor，可能放行非法组合、NULL 或空白 actor。修复后两类 Repo 统一通过完整 lifecycle 构造执行严格校验，并新增 6 个回归用例。复审指出报告文件被 `.gitignore` 忽略，提交时使用 `git add -f` 纳入。

## 验证结果

- Task 2 定向及 summary/Web/main 相关回归：`131 passed`。
- 全量测试：`1406 passed, 1 skipped`。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过。
- UTF-8 canary：字节校验通过，无 BOM、无中文乱码。

## 范围边界

本任务没有实现日报请求 Repository、请求 Worker、补偿调度或 Web 手动生成页面；这些继续由阶段四后续任务完成。
