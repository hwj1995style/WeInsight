# 阶段四 Task 4 实施报告：自动后处理 Pipeline Worker

## 交付结论

阶段四 Task 4 已按正式计划、设计和实施简报完成。新增独立的非 UI 后处理 Worker、共享 Engine 运行时工厂和 BlockingScheduler 入口；未修改或提前实现 Web，也未导入、持有或写入微信 UI 锁和真实 RPA。

新增文件：

- `app/workers/pipeline_worker.py`
- `app/workers/pipeline_runtime_factory.py`
- `app/workers/pipeline_main.py`
- `tests/test_pipeline_worker.py`

## Worker 实现

### 固定流水线与故障隔离

每个 tick 使用同一个 Asia/Shanghai aware `now`，固定执行：

1. group clean；
2. group analysis；
3. article parse；
4. article analysis；
5. 最多领取一个日报请求。

四个阶段分别使用 `WorkersConfig` 中的批次大小。每个阶段保留既有 Service 内部的逐条失败计数，同时在最外层捕获异常、将该阶段成功数置零、写结构化安全事件并继续后续阶段。事件写入本身失败也不会阻断其他链路或下一次 tick。

日报部分只调用 `claim_next` 和 `ReportGenerationService.execute_request`。Worker 不直接调用任何 success/partial/failed 状态更新方法，继续由 Task 3 的 owned CAS 负责终态。每个 tick 只领取一次；执行或事件写入失败不会在 Worker 内留下阻止下一 tick 重新领取的进程状态，过期恢复继续由请求 Repo 负责。

### 输出安全

Pipeline 异常事件只保存：

- 独立的 `stage` 字段；
- `metrics_json.exception_type`；
- 固定中文失败摘要。

异常详情、URL、手机号、正文和 traceback 均不进入事件。该边界同时覆盖四个处理阶段、日报领取执行、heartbeat、compensation 和 scheduled tick 入口。

### 心跳与补偿

- 心跳记录复用 `WorkerHeartbeatRecord`，`worker_type` 固定为 `pipeline`。
- worker ID、hostname、PID 和版本生成方式沿用 collector 的主机摘要、进程 ID 和随机后缀约定。
- `ensure_daily_compensation(now)` 严格校验上海时区，并为前一自然日创建确定性补偿请求。
- 显式 `heartbeat(now)`、`ensure_daily_compensation(now)` 和 `run_tick(now)` 保留严格抛错语义。
- 供 APScheduler 使用的 `*_now` wrapper 捕获 clock、数据库和服务异常，只写固定安全事件；scheduled tick 失败返回全零且 report status 为 failed 的完整结果，避免 APScheduler 输出原异常 traceback。

## Runtime Factory

`build_pipeline_worker` 只创建或接收一个受控 SQLAlchemy Engine，并将同一个 Engine 传给：

- Group clean / analysis Repo；
- Article parse / analysis Repo；
- Group / article / summary 日报依赖；
- Report request Repo；
- Collection event Repo；
- Worker heartbeat Repo。

所有 Repo 仍按现有约定自行开启短事务，Worker 不保存数据库连接。Factory 仅构建数据库后处理、Playwright 文章解析/瞬态提取和日报服务，不引用微信 UI 锁、wxauto 或采集命令。

## 入口与调度

`python -m app.workers.pipeline_main --config <path>` 使用 `BlockingScheduler(timezone="Asia/Shanghai")`，精确注册三项任务：

- tick：interval `pipeline_tick_seconds`；
- heartbeat：interval `heartbeat_seconds`；
- compensation：cron `hour=0, minute=10`。

三项任务均设置 `max_instances=1, coalesce=True`。入口启动调度前写一次 running heartbeat；`--once` 执行一次 tick 后安全退出，不创建 scheduler。

退出顺序固定为：

1. 写 stopping；
2. `scheduler.shutdown(wait=True)`，等待正在执行的后处理任务完成；
3. 写 stopped。

这样不会在活动任务仍访问数据库或生成日报时提前宣布 stopped。配置、运行时、执行和退出错误只输出固定错误码与异常类型，不输出配置路径、密码或异常正文；原始运行错误不会被 shutdown 错误覆盖。

## TDD 与复审闭环

测试从三个新模块不存在的导入 RED 开始，逐步覆盖：

- 固定阶段顺序、配置批次和同一 now；
- 四阶段 outer 异常隔离和安全事件；
- event 写失败仍继续；
- 每 tick 最多一个 report；
- execute/event 双失败后下一 tick 仍可重新 claim；
- 前一自然日补偿和 pipeline heartbeat；
- shared Engine 依赖图；
- 禁止 UI 锁、真实 RPA、采集命令和直接 report mark；
- 三项 scheduler job 的精确 trigger/参数；
- once、配置/工厂安全错误和停止顺序；
- scheduled tick/heartbeat/compensation 不向 APScheduler 泄漏异常。

内部复审发现并关闭三个同类问题：

1. scheduled heartbeat/compensation 异常可能由 APScheduler 输出完整 traceback；
2. `shutdown(wait=False)` 可能在活动 tick 完成前写 stopped；
3. scheduled tick 的 clock 异常仍可能逃逸到 APScheduler。

修复后复审结论为 Ready，Critical、Important、Minor 均无。

## 验证结果

- Pipeline Worker 定向测试：`21 passed`
- Task 4 + Task 3 请求/生成服务 + 四个处理 Service 回归：`97 passed`
- 全量测试：`1484 passed, 1 skipped`
- `python -m compileall -q app tests`：通过
- `python -m app.workers.pipeline_main --help`：通过
- MySQL 8.4.9 临时库集成：通过
  - pipeline heartbeat 写入 running；
  - pending summary 请求被领取并通过 Task 3 owned 终态完成为 success；
  - 前一自然日 compensation 重复调用返回同一请求 ID；
  - `wechat_ui_lock` 唯一哨兵行在执行前后逐字段完全一致；
  - 临时数据库在 `finally` 中清理成功。

## 后续衔接与风险

- 生产部署需为 pipeline Worker 使用设计中的最小数据库权限，明确禁止写 UI 锁。
- `shutdown(wait=True)` 会等待当前非 UI 批次完成；批次大小和浏览器解析超时应保持受控，避免 Windows 服务停止时间无界增长。
- 后续 Task 5 Web 只创建日报请求并查询状态，不应同步调用本 Worker 或生成服务。
- 若未来增加新 scheduled job，必须复用安全 wrapper，避免异常详情进入 APScheduler 默认日志。
