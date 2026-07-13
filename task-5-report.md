# Task 5 实施报告

## 交付范围

- 新增 `ArticleGlobalCycle`：每轮先同步 WeRSS 清单，再基于本地最后已知的 active 来源协调系统采集任务。
- collector 启动后立即执行一轮，并按 `sync_interval_minutes` 注册 `max_instances=1`、`coalesce=True` 的 interval job。
- 新增 active WeRSS 来源查询；SQL 与周期层双重排除“一箱蛋”。
- 新增固定名称系统公众号任务协调：目标未变化时原位刷新，变化时完成旧任务并创建一个新的可运行系统任务，空 active 集合不创建可运行任务。
- runtime factory 复用同一数据库引擎装配 catalog client、同步服务、来源仓储和系统任务仓储。
- 禁止 Web 人工创建公众号任务；旧新建入口重定向到任务列表；群任务创建、公众号任务列表和历史详情仍保留；系统任务在列表标记为“系统管理”。
- 未改变现有 RSS Feed 获取器、公众号并发上限、无 UI 锁路径，以及 parse/analyze/报价增量状态机。

## RED → GREEN 记录

1. 新增周期与 scheduler 契约测试，首次运行因 `app.workers.article_global_cycle` 不存在而失败。
2. 实现最小周期和调度注册后，`4 passed`。
3. 新增 active 来源仓储测试，首次运行因 `list_active_werss_accounts` 不存在而失败。
4. 实现过滤查询后，仓储测试 `24 passed`。
5. 更新 Web 契约为系统管理，最终 Web 回归 `68 passed`。

## 测试与回归

最终指定及相关测试命令覆盖：全局周期、collector、managed collector、pipeline worker、Web jobs、RSS 入库、文章解析、分析、蛋价抽取、来源仓储和任务仓储。

结果：`237 passed in 3.33s`。

## 风险与关注点

- 系统任务目标变化采用“完成旧任务 + 创建新任务”，避免删除已有 target/run 历史或篡改历史快照；任务列表会保留历史系统任务，但任一时刻只有一个可运行系统任务。
- WeRSS catalog 的鉴权环境变量在测试命令中使用测试值注入，未写入仓库。
- catalog 预期错误与同步锁忙会降级到本地最后 active 快照；数据库协调失败仍向上抛出，使 collector 进入既有启动/运行错误处理，而不是静默吞掉持久化故障。

## Review findings 修复（2026-07-13）

- 增加固定协调表与 `article_global` 锁行。所有 collector 在读取或创建系统任务前执行 `SELECT ... FOR UPDATE`，空表首次并发也被数据库串行化。
- 为任务增加 nullable `managed_key` 及唯一索引。人工任务保持 `NULL`，系统仓储只写固定 `article_global` identity；数据库约束保证最多一个当前 managed job。
- 增加幂等迁移 `20260713_004_system_article_job_singleton.sql`。迁移认领已有最新系统任务，不删除历史，并把其他旧可运行副本改为 `stop_requested` 且清空 `next_run_at`。
- 目标变化时先查询固定系统 identity 全部历史任务的 queued/running run。存在活跃 run 时只请求停止当前 managed job并延后切换；确认全部终态后才把旧 job 置为 completed、释放 managed key并创建新快照，因此旧 job 不会在活跃 run 期间显示 completed。
- collector 角色仅对 `wechat_collection_job` 增加 INSERT、对 `wechat_collection_job_target` 增加 INSERT，并只读固定协调表；未增加 DELETE，也未扩展到无关表。
- 新增仓储状态机、缺失锁行拒绝运行、双 collector 首次并发、schema、幂等迁移及生产角色权限测试。

Review 修复后的 Task 5、权限与迁移定向回归：`387 passed in 4.25s`。仓库完整回归：`1826 passed, 2 skipped, 14 failed`；14 项均来自 Web 视觉/鉴权测试连接本地 MySQL 时返回 `1045 Access denied`，未出现本次系统任务、迁移或权限测试失败。
