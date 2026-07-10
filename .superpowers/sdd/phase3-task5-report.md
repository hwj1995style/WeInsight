# 阶段三 Task 5 实施报告：微信健康探测与调度门禁

## 交付范围

本任务按阶段三计划 Task 5 和正式设计 6.6、8.2、8.4 完成，未修改表结构，未实现 Worker 主循环或 Web 健康页面。

- 扩展 `WechatHealthStatus` 为六种正式状态，旧 `NOT_FOUND` 保留为 `NOT_RUNNING = "not_running"` 的枚举别名。
- 新增 `MysqlWechatHealthRepo`，提供完整健康检查的写入、按主机读取最新记录和读取连续失败次数。
- 新增 `WechatHealthMonitor`，固定执行浅检查和深检查顺序，并提供 `run_check(now)`、只读 `latest_status` 和 `can_collect(now)`。
- 为真实 MySQL UI 锁仓库补充最小只读 `current_owner(lock_name)`；未改变 acquire、heartbeat、release 行为。

## 关键契约

### 检查顺序与状态

完整检查顺序固定为：进程/版本（`WechatDesktopProbe`）→ 窗口 → 登录 → RPA。浅检查失败立即保存，不调用任何深探针；深检查逐项短路。

探针异常使用固定安全摘要并 fail closed 到对应状态，不返回异常原文、HTML、URL、手机号或微信号。`message` 和 `detected_version` 在 Repo 写入和读回时均执行统一输出清洗；数据库字段状态、长度、标识和连续失败次数严格校验，拒绝 bool 冒充整数。

### UI busy 与 deferred

浅检查通过后才读取 `wechat_ui` owner。锁繁忙时：

- 窗口、登录和 RPA 探针调用次数均为 0；
- 不写 `wechat_client_health_check`，不改变连续失败次数；
- 返回最近完整记录的状态、消息、版本、连续失败次数和原始 `checked_at`，仅将 `deep_check_deferred` 设为 `True`；
- 通过注入的事件 Repo 写入 `wechat_health_deep_check_deferred` 结构化事件；
- 没有完整历史时返回临时 `rpa_unavailable` deferred snapshot，但不持久化，`can_collect` 仍因缺少完整历史而返回 `False`。

### 门禁与时间

所有公开时间参数必须使用真实 `ZoneInfo("Asia/Shanghai")`。MySQL 写入上海本地 naive datetime，读回恢复为真实上海 ZoneInfo。

`can_collect` 始终读取最后一条完整记录；仅当状态为 `ok` 且 `0 <= now - checked_at <= 2 * check_login_interval_seconds` 时返回 `True`。缺记录、非 OK、未来时间和过期记录均 fail closed。

### 连续失败与并发约束

完整 OK 将连续失败次数重置为 0，完整非 OK 在上一条同主机完整记录基础上加 1。计数读取和写入位于同一事务，已有历史记录使用 `SELECT ... FOR UPDATE` 串行化重叠写入。

现有表没有每主机唯一锁行或 hostname 唯一键，本任务又明确禁止修改表结构，因此正式运行必须遵守“同一 hostname 只有一个健康监控写者”的约束，由 Task 6 的 collector heartbeat/重复实例门禁负责建立该所有权边界。Repo 不应被用于绕过该单写者约束。

## TDD 证据

先写失败测试并观察到预期 RED：

- 新服务尚不存在时，测试收集因 `ModuleNotFoundError: app.services.wechat_health_monitor` 失败；
- 桌面状态和真实 MySQL 锁只读能力分别因缺少 `NOT_RUNNING` 和 `current_owner` 产生 3 个失败；
- 数据库超长 message 严格校验测试先因未抛错失败；
- `detected_version` 输出清洗测试先因原始 HTML/控制字符被直接写入失败。

实现后覆盖六状态、固定顺序/短路、busy 零深调用、deferred 只写事件、旧 OK 不续期、无历史 fail closed、恢复重置、异常脱敏、2 倍间隔边界、时区、Repo SQL 参数绑定/稳定排序/严格校验和真实锁 owner 查询。

## 真实 MySQL 8.4 验证

使用本机 MySQL `8.4.9` 创建仅属于本任务的 `weinsight_task5_*` 临时数据库并验证：

- 顺序非 OK、非 OK、OK 的连续失败次数为 `1, 2, 0`，latest 为 OK；
- 中文消息保留业务文本，手机号、微信号、完整 URL 被脱敏，版本 HTML 被清洗；
- `checked_at` 读回为 `Asia/Shanghai` ZoneInfo；
- `MysqlUiLockRepo.current_owner("wechat_ui")` 在锁存在/删除后分别返回 `group`/`None`；
- 同 hostname 首次并发两次写入均成功，持久化计数为 `[1, 2]`；
- 同 hostname 已有历史时并发观察到一次成功和一次 MySQL deadlock `1213`，持久化计数为 `[1, 2]`，没有静默写入重复计数。这进一步证明正式运行必须维持同主机单写者约束。

验证结束后已删除临时数据库，并通过 `INFORMATION_SCHEMA.SCHEMATA` 确认不存在（`temporary_database_removed=True`）。

## 最终验证

- Task 5 + desktop/main + Task 4 event/lock/runtime 定向回归：`148 passed`。
- 全量测试：`1179 passed`。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过（仅 Git 提示现有 Windows CRLF 转换策略，无空白错误）。
