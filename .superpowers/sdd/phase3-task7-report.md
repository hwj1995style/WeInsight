# 阶段三 Task 7 实施报告：托管模式 CLI 互斥

## 交付范围

本任务按阶段三计划 Task 7、正式设计 8.5 和实施简报完成。新增 `ManagedModeGuard`，只改造以下四条真实采集命令：

- `run-group-scheduler`
- `run-article-scheduler`
- `collect-group-once`
- `collect-article-once`

Fake RPA、配置检查、微信健康检查、纯数据库后处理及 Web/SSE 均未纳入 Guard。

## Guard 契约

`ManagedModeGuard` 提供：

- `ensure_scheduler_allowed(now) -> None`
- `run_manual(pipeline, owner_task_id, now, action) -> T`

构造时注入 Worker heartbeat Repo、UI lock Repo、hostname、collector heartbeat TTL、UI lease 秒数和 heartbeat 周期。公开时间只接受真实 `ZoneInfo("Asia/Shanghai")` aware datetime；pipeline 只接受 `group/article`；owner id 必须非空、去除首尾空白后不变且不超过 100 字符。

Scheduler 查询同 hostname 的 live collector，沿用 Task 4 的 `starting/running/degraded/stopping` 和 TTL 规则。命中时抛固定 `ManagedModeActiveError`，不包含 hostname、SQL 或数据库连接信息。

## Scheduler 互斥

两条 scheduler 均在微信健康检查和真实 RPA Runner 构造前完成第一次 Guard 检查：

- group scheduler 在每轮 `run_once` 前再次检查，使旧 scheduler 能在 collector 后启动时退出；
- article scheduler 在 Runner 构造后、执行前再次检查，缩小构造期间 collector 启动造成的竞争窗口。

所有 scheduler 时间均来自上海 aware clock。托管模式拒绝使用固定退出码 `3` 和 `managed_mode_error=collector_active`；Guard/数据库异常只输出异常类型。

## 人工采集、锁与续租

两个 collect-once 都先由 Guard 获取唯一 `wechat_ui` 锁，随后才在 action 内执行健康检查、构造真实 RPA adapter/Runner 并采集。获取失败时 action 调用数为 0。

Guard 使用 daemon 线程按配置周期刷新 UI lease；后台线程只调用锁 Repo heartbeat，不执行 RPA。heartbeat 返回 False 或抛异常时标记 lease lost，action 完成后固定抛出 `WechatUiLeaseLostError`，并仍尝试释放锁。action 自身异常保持原样传播，即使 release 同时失败也不覆盖 action 异常；成功 action 若 release 失败则抛 `WechatUiReleaseError`，不会伪报成功。

人工 article 的 `ArticlePollingRunner` 原本会自行获取同一非重入锁。本任务给 POC builder 注入严格 `HeldUiLockAdapter("article")`：只接受 `wechat_ui/article` 和合法 owner/time/lease，内部 acquire/release 为 no-op，不让真实 `MysqlUiLockRepo` 二次加锁。外层 Guard 仍负责真实锁、续租和释放。

## Article aware checkpoint 修复

四条 CLI 改用上海 aware 时间后，article 的 core-group due provider 和 checkpoint clock 必须保持同一时区。两个真实 article builder 现均：

- 给 `ReadOnlyCoreGroupDueProvider` 注入 `_shanghai_now`；
- 给 `ArticlePollingRunner.checkpoint_now_provider` 注入 `_shanghai_now`。

真实 builder + fake group Repo 测试会执行 OPEN_ACCOUNT、COPY_LINKS、SAVE_LINKS 三个 checkpoint，确认每次查询都使用 `Asia/Shanghai` aware datetime，不再出现 naive/aware 比较异常。

## CLI 安全与无副作用

- `--help` 和必填参数错误发生在配置加载、数据库连接和 Guard 构造前；
- parse/analyze/clean 等纯数据库命令不构造 Guard；
- manual busy、lease lost、release failed 使用固定短错误码；
- Guard 构造或运行异常只输出安全异常类型，不输出 DSN、SQL、hostname 或 traceback；
- collect-once 原有成功结果字段和 RPA adapter 错误路径保持兼容。

## TDD 证据

按 RED → GREEN 实施：

1. Guard 测试最初因 `app.services.managed_mode_guard` 不存在而收集失败；实现后 20 项通过。
2. CLI 筛选测试最初为 `13 failed / 4 passed`，失败分别证明四条命令未调用 Guard、manual 在锁外构造 RPA、scheduler 未在 builder 前拒绝、group 未逐轮复查及安全错误输出缺失；实现后全部通过。
3. aware builder 补充测试最初 3 项失败：article scheduler 仅检查一次 Guard，两个真实 builder 均在首 checkpoint 触发 offset-naive/offset-aware 比较错误；修复后 3 项通过。
4. 首轮全量发现一个旧 article scheduler CLI 测试未注入 Guard，表现为 `1297 passed / 1 failed`；更新兼容测试并验证构造前后两次 Guard 后，全量恢复通过。

## 真实 MySQL 8.4 验证

使用本机 MySQL `8.4.9` 创建仅属于本任务的 `weinsight_task7_*` 临时数据库，全程未构造任何微信或 RPA 对象：

- `starting/running/degraded/stopping` live collector 均阻止 scheduler；
- `stopped`、TTL 外 stale collector 和 pipeline worker 均放行；
- managed owner 持有 `wechat_ui` 时，manual action 调用数为 0 并返回 busy；
- DB-only 长 action 完成 2 次真实 UI lease heartbeat，结束后锁已释放。

验证结束后已删除临时数据库，并通过 `INFORMATION_SCHEMA.SCHEMATA` 确认不存在（`temporary_database_removed=True`）。

## 最终验证

- Task 7 + main/UI lock/heartbeat/Task 6 Worker/article/group runner 定向回归：`221 passed`。
- 全量测试：`1300 passed`。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过。
- UTF-8 替换字符扫描：通过。
