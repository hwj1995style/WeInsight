# 阶段三 Task 6 实施报告：安全停止与托管采集 Worker

## 交付范围

本任务按阶段三计划 Task 6、正式设计 8.2—8.5 和实施简报完成，未修改控制面表结构，未实现旧 CLI 互斥、Web/SSE 或后处理 Worker。

- 新增九项 `WorkersConfig` 并接入根配置；开发和生产示例均逐项显式配置，生产示例首版保持 `collector_mode: fake`。
- 新增文章安全停止异常和三个安全 checkpoint，停止进度以固定错误码 `ARTICLE_STOP_REQUESTED` 持久化，释放 UI 锁后结束，不归类为 RPA 失败且不额外截图。
- 扩展群和公众号单目标 Runner 结果，向运行目标映射读取、新增、重复、跳过、错误摘要和采集机本地截图路径。
- 新增 `ManagedCollectorWorker`、运行时工厂和 `python -m app.workers.collector_main` 入口。
- 为运行 Repo 增加只取消 queued 目标的收束接口；为心跳 Repo 增加同主机原子启动注册。

## 核心实现契约

### 配置、时间与运行模式

`collector_mode` 只允许 `fake/real`，其余八项必须是非 bool 正整数；缺失或未知配置直接失败，不会静默进入真实模式。Worker、调度入口、租约和持久化边界均要求真实 `ZoneInfo("Asia/Shanghai")`。

`fake` 模式复用单一 MySQL Engine 和现有带历史写保护的 Repo，但只构造 Fake RPA、Fake 截图和固定 OK 探针；不会导入或实例化 wxauto、pywinauto、真实浏览器。`real` 模式通过惰性适配器构造真实能力，窗口探针可区分“客户端窗口不可用”和“处于登录窗口但未登录”，RPA 探针才会惰性创建 wxauto。

### 任务领取、快照与安全停止

每次 tick 在 claim 前先检查最近完整健康状态，不健康时不访问 claim；每次最多领取一个 run。目标完全使用 claim 中的 immutable snapshot，按 priority、name、id 排序，群与公众号快照均严格校验对象、精确字段集合和字段类型，不回读当前名单覆盖运行快照。

每个目标使用同一 batch id 执行 `start_target → 单目标 Runner → finish_target`。Runner 构造、执行和结果类型异常分别安全落为 failed；错误摘要统一清洗，结构化事件不包含正文、HTML、完整 URL 或 traceback。目标开始/完成及 run 领取/完成均写结构化事件。

领取前、目标之间和文章三个内部 checkpoint 都会检查停止。群采集只在当前目标完成并释放 UI 锁后停止；文章在 checkpoint 保存 interrupted progress 后停止。剩余目标只将 queued 收束为 cancelled，已运行或终态目标不会被覆盖；最终 run 状态只写一次，并使用新的上海时区时间写 target/run 结束时间。

### 心跳、竞态与生命周期

Worker 使用线程锁维护 active run id 和租约状态。后台 heartbeat 只刷新数据库租约和 Worker 心跳，不执行 RPA；租约失败 fail closed 到 degraded。活动 run 已进入 degraded 时，即使同轮租约刷新成功也不会误报 running；活动 run 已清除后，迟到的 false/异常结果不会反向污染新状态。仅在没有 active run 且 Worker 心跳成功后允许从 transient degraded 恢复。

同主机启动通过独立 MySQL advisory lock 串行化“检查 live collector + 写 starting heartbeat”。starting 心跳在释放 advisory lock 前显式 commit，避免并发实例在可见性窗口内同时通过。默认 worker id 使用主机名哈希、PID 和随机 UUID 片段，长度不超过 100，并能避免 PID 复用后的身份碰撞。

入口先完成原子注册和首次完整健康检查，再启动 `BackgroundScheduler(timezone="Asia/Shanghai")`。heartbeat、health、expired-run recovery 均使用 `max_instances=1, coalesce=True`，真实/假 RPA 只在主线程执行。调度器构造、注册或启动失败也进入统一 shutdown；停止心跳失败不阻止 scheduler shutdown 和信号处理器恢复，错误输出只包含异常类型。

## TDD 与审查修复证据

先写失败测试并观察到预期 RED，覆盖九项配置、文章三个 stage 停止、健康门禁、多目标停止、Runner 结果映射、恶意/错型快照、活动租约竞态、原子重复实例、fake/real 适配器隔离、调度参数、时区和 shutdown。

审查过程中新增并固定以下边界：

- starting 心跳必须在 advisory lock 释放前 commit；
- 只取消 queued 目标；target 开始/完成事件和结束时间必须完整；
- active-degraded 成功续租不能误恢复，活动清理后的迟到失败不能误降级；
- 默认 worker 身份在 PID 复用时仍唯一且满足字段长度；
- 真实窗口/登录探针不依赖提前构造 RPA；故障截图保存绝对本机路径；
- 非法 Runner 返回值落为 `RUNNER_RESULT_ERROR`；
- 调度器 `start()` 失败仍执行停止心跳、scheduler shutdown 和信号恢复。该边界先观察到异常直接逃逸的 RED，修复后入口相关 10 项测试通过。

## 真实 MySQL 8.4 验证

使用本机 MySQL `8.4.9` 创建仅属于本任务的 `weinsight_review_p3t6_0710` 临时数据库并执行真实 Repo 验证，不连接真实微信：

- 两线程在同一 hostname 并发注册 collector，结果严格为 `[False, True]`；第三个 live 实例继续被拒绝，数据库仅有一条 starting 心跳。
- 使用真实 `MysqlCollectionRuntimeRepo`、事件 Repo 和心跳 Repo 领取含两个目标的群任务；第一个目标成功后写入 stop request，第二个 queued 目标被取消。
- 最终 run 为 cancelled，目标状态为 success/cancelled，job 为 stopped；第一目标指标为 read=3、insert=2、duplicate=1，run/target 时间、计数和租约均正确收束。
- 结构化事件依次为 run claimed、target started、target finished、run finished；Worker 心跳最终为 running。

首轮集成脚本曾因 PyMySQL 临时连接未指定 `utf8mb4`，使中文测试名称转换为 `??` 并触发测试数据唯一键冲突；确认属于测试脚本连接字符集后，以 `utf8mb4` 和 ASCII 测试标识重跑通过，未修改产品代码。每轮结束均删除临时数据库，并通过 `INFORMATION_SCHEMA.SCHEMATA` 确认不存在。

## 最终验证

- Managed Worker 专项：`47 passed`。
- Task 6 + Runner/Config/Task 4/Task 5 组合回归：`215 passed`。
- 全量测试：`1256 passed`。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过（仅 Git 提示现有 Windows CRLF 转换策略，无空白错误）。
