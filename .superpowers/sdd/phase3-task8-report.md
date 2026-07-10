# 阶段三 Task 8 实施报告：运行监控、结构化日志、SSE 与实时总览

## 交付范围

本任务按阶段三计划 Task 8、正式设计 13.4/13.5 和实施简报完成服务端与响应式前端实现，未读取群原始消息、文章正文或本机截图文件，未新增表结构。

- 新增安全 `RuntimeMonitorService` 和 `MysqlRuntimeMonitorRepo`，提供运行列表/详情、日志筛选、Worker/微信/UI 锁、任务历史和实时 Dashboard 聚合。
- 新增 `/runs`、`/runs/{id}`、`/events`、`/events/stream`、`/workers`，并在任务详情展示最近运行和操作事件。
- Dashboard 保留原采集结果构成图，新增 Worker、微信、UI 锁、活动/停止中任务、今日运行和最近 24 小时明确终态趋势。
- 导航、表格和详情页适配窄屏；大表只在 `.table-scroll` 内横向滚动。

## 查询与安全边界

运行列表支持链路、运行状态、上海自然日、任务 ID/名称和分页；日志支持任务、运行、目标运行、链路、级别、上海起止时间和分页。路由严格拒绝未知 query、重复单值、非规范 enum/date/datetime/int 和越界 page size。Repo 只拼接固定 allowlist 条件，所有值绑定；任务名称 LIKE 对反斜杠、`%` 和 `_` 转义。

运行详情展示 worker/hostname、租约、起止时间、目标状态/stage/batch、四类计数、错误码、安全摘要和截图路径。截图根先 `resolve(strict=False)`；候选必须是绝对路径、resolve 后位于唯一 root 下。根外、遍历、相邻前缀、类型错误和符号链接逃逸只显示“截图路径无效”，不回显原值。模板不生成 `<img>`、下载链接、`file://` 或文件响应。

同步 Service/Repo 调用全部通过 `run_in_threadpool`；默认 runtime/event 和既有 Web 服务复用同一 Engine。

## SSE 契约

`/events/stream` 受管理员 Session 保护。`run_id` 只接受正整数；`Last-Event-ID` 和 query `after_id` 只接受规范非负十进制，标准 header 优先。每轮调用 Task 4 event Repo 的 `list_events(run_id, after_id, 200)`，Repo 在调用内开关连接，返回后才 yield，不跨 yield 持有事务或连接。

事件格式固定为 `id`、`event: collection` 和单行 canonical JSON `data`。level/event type/stage 使用枚举或结构化 allowlist；message 统一脱敏。metrics 递归清洗 HTML、完整 URL 和控制字符，限制 3 层、字典/列表各 20 项、字符串 200 字符、最终 4096 UTF-8 字节；超限明确截断。空闲 15 秒输出 keepalive；每秒检查断开，取消异常不被吞掉。

响应使用 `text/event-stream`、`Cache-Control: no-cache, no-store` 和 `X-Accel-Buffering: no`。生产流保持无限；测试使用可注入 poll/sleep/clock/max-polls 的有限异步迭代器，避免 TestClient 挂起。run detail 初始渲染最近事件作为无 JS fallback，EventSource 仅以 `textContent` 创建节点，最多保留 200 条，并显示连接/重连状态。

## Worker 与实时总览

Worker 页展示全部 heartbeat、类型、hostname、PID、版本、状态、最近心跳、启动时间、live/stale 和安全错误摘要；TTL 为 collector heartbeat 的 3 倍。每个 hostname 只展示最新完整微信健康记录。UI 锁展示 owner/task/获得/心跳/到期，`expire_time <= now` 明确为 expired。

Dashboard 的 24 小时趋势按上海整点补齐 24 个 bucket，只统计 `success`、`partial_success`、`failed`、`cancelled`、`aborted`；running、queued 和未知状态不进入终态趋势。成功系列为 success+partial，失败系列为 failed+aborted，取消独立。服务端逐 bucket 计算守恒总数，模板提供 24 行可聚焦文本表。

数据可视化实现遵循实时运维 Dashboard 路径：页面最多两个本地 ECharts Canvas，无动画、整数轴、ARIA 描述；新增趋势采用终态堆叠柱。KPI、更新时间、逐小时表和 noscript/chart-failure 提示均服务端渲染，脚本失败时证据仍可读。390px 设计以 KPI 和图表为主要阅读路径，筛选和宽表不占据页面级宽度。

## TDD 与审查修复

先写失败测试并观察到预期 RED：RuntimeMonitor Service/Repo 模块缺失；create_app 无 runtime 注入导致 14 个 Web setup error；events route 缺失；Dashboard 未调用 runtime service；SSE metrics 原样输出；`datetime` 被当作 `date`；Event/Worker 控制标签未清洗；MySQL 8.4 最新健康查询使用保留别名；metrics 摘要整体脱敏改写结构化 key。

实现后覆盖 Repo allowlist/绑定/分页、严格 query、截图路径、认证、threadpool/shared engine、SSE 游标/200 上限/JSON/XSS/metrics/keepalive/断连/取消/连接生命周期、worker/health/lock、24 bucket/守恒/零数据/fallback、任务历史和响应式结构。

## 真实 MySQL 8.4 验证

使用本机 MySQL `8.4.9` 和独立临时库 `weinsight_review_p3t8_final` 验证：

- run 筛选、run detail、目标指标和 root 内截图绝对路径映射；
- job/run/target/pipeline/level 事件筛选与安全 metrics；
- live collector、最新微信 OK 健康记录、live `wechat_ui` 锁；
- active job、今日 failed run、任务运行/事件历史；
- 最近 24 小时准确补齐 24 bucket，终态总数为 1。

最终结果 `MYSQL_RUNTIME_MONITOR=PASS`，所有检查项均为 True。每轮（包括集成脚本设置错误和 SQL 别名修复轮次）均在 `finally` 删除临时库，并通过 `INFORMATION_SCHEMA.SCHEMATA` 确认不存在。实测发现 MySQL 8.4 不接受窗口函数别名 `row_number`，已先补 RED 后改为 `row_rank` 并通过。

## 浏览器 QA 状态

因收尾协调时间窗口终止，未启动 Browser bridge 或 Playwright fallback，也未生成桌面/390px 截图与控制台证据。服务端模板、响应式 CSS、EventSource 脚本和无横向溢出的结构已由单元/Web 测试覆盖，但桌面→390px 的真实渲染、console 0 error、SSE 增量追加与自动重连仍需在后续发布前执行人工或 Playwright QA。该项未声明为已通过。

## 最终验证

- Task 8、jobs、dashboard 合并定向回归：`133 passed, 1 skipped`；skip 原因为当前 Windows 环境无符号链接创建权限，普通路径、遍历、相邻前缀和根外路径测试均通过。
- 全量测试：`1371 passed, 1 skipped`。
- 真实 MySQL 8.4 临时库验证：通过并清库。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过（仅 Git 提示 Windows CRLF 转换策略）。
