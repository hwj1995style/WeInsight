# 阶段五 Task 2 实施报告：Windows 管理栈脚本

## 交付结论

阶段五 Task 2 已按正式计划、部署设计和实施简报完成。新增三个进程启动脚本、管理栈注册/注销脚本和只读检查脚本，并补充 PowerShell 5.1 AST 与静态安全契约测试。

本任务只创建和解析脚本，没有执行任何 start/check 脚本，没有注册、注销或启动本机计划任务，没有启动 Web、Worker、微信采集、HTTPS 探测或真实命令，也没有修改防火墙、日志、数据库和证书。

## 三个 Start 脚本

新增：

- `start_admin_web.ps1`
- `start_collector_worker.ps1`
- `start_pipeline_worker.ps1`

三个脚本统一实现：

- `ProjectRoot` 和 `ConfigPath` 使用 `Resolve-Path -LiteralPath`；配置必须位于项目根内且为真实文件，入口模块也必须为文件；
- 使用 `Get-Command python -CommandType Application`，不硬编码 Python 路径；
- Python 参数使用数组和 splatting 传递，路径含空格时不经过 shell 拼接；
- Web、Collector、Pipeline 分别使用 `app.web`、`app.workers.collector_main`、`app.workers.pipeline_main`；
- 独立写入 `runtime\logs\admin_web`、`runtime\logs\collector_worker`、`runtime\logs\pipeline_worker`，文件名按 `yyyyMMdd` 拆分；
- 日志只记录固定进程/模块/规范配置路径、退出码和异常类型，不记录环境变量值、异常 Message 或 stack；
- 子进程 stdout/stderr 不复制到包装器日志，避免完整 traceback 或敏感输出泄漏；
- 不注册任务、不执行一次性采集、不删除或移动任何文件。

三个进程优先读取各自角色密码：

- `WEINSIGHT_WEB_MYSQL_PASSWORD`
- `WEINSIGHT_COLLECTOR_MYSQL_PASSWORD`
- `WEINSIGHT_PIPELINE_MYSQL_PASSWORD`

读取顺序为 Process → User → Machine，随后仅在当前子进程环境映射为现有 Python 配置使用的 `WEINSIGHT_MYSQL_PASSWORD`。角色密码缺失时默认 fail closed；公共密码仅在人工启动时显式传入 `AllowSharedMysqlPasswordFallback` switch 才可作为开发/旧版兼容 fallback，三个计划任务 action 均不传该开关。Web 还要求 host、TLS cert 和 TLS key 环境变量；任何值都不会进入参数或日志。

## Register 与 Unregister

`register_admin_stack.ps1` 在首次 `Register-ScheduledTask` 之前完成全部预检：

1. 通过一次 `Get-ScheduledTask -ErrorAction Stop` fail-closed 获取任务全集，再同时匹配并拒绝 `WeInsight-Group-Scheduler` 和 `WeInsight Group Scheduler`；查询异常会在任何注册前终止；
2. 校验项目根、三个 start 脚本和三份配置文件；
3. 保持 `ConfigPath` 兼容入口，并支持 `WebConfigPath`、`CollectorConfigPath`、`PipelineConfigPath` 独立 override；
4. 要求三个角色密码和 Web host/TLS 变量存在于 User 或 Machine 持久环境，避免仅 Process 变量导致下次登录任务启动失败；
5. 预检 Python 和 PowerShell 可执行文件。

注册固定任务：

- `WeInsight-Admin-Web`
- `WeInsight-Collector-Worker`
- `WeInsight-Pipeline-Worker`

当前交互用户通过 `WindowsIdentity.GetCurrent()` 获取限定域身份；注册前拒绝空名称、非 `UserInteractive`、SYSTEM、`NT AUTHORITY\*` 和 `NT SERVICE\*` 身份。三个任务使用同一 `Interactive`、`Limited` principal，AtLogOn trigger 明确绑定同一合格用户；设置 `IgnoreNew`、失败重启 3 次、间隔 1 分钟和无限执行时间。三个 action 分别接收各自规范配置路径。

`unregister_admin_stack.ps1` 只遍历上述三个固定新任务并使用 `-Confirm:$false` 注销。不存在时输出 `status=none`；不处理两个 legacy 名称，不删除日志、数据库、脚本或证书。

## 只读 Check

`check_admin_stack.ps1` 无论单项失败与否都输出且只输出七个固定键：

- `web_task_status`
- `collector_task_status`
- `pipeline_task_status`
- `legacy_group_scheduler_present`
- `web_https_reachable`
- `mysql_config_ok`
- `wechat_health_status`

检查行为：

- 只读查询三个新任务和两个 legacy 名称；
- 从私网 host 和固定端口 8848 构造 HTTPS URL；IPv4 要求规范、trimmed 表示，只允许 RFC1918，IPv6 只允许 ULA；
- `Invoke-WebRequest` 使用系统默认证书信任链，没有跳过 TLS 校验；
- Web、Collector、Pipeline 三份配置分别映射对应角色密码后执行 `python -m app.main check-config`；三项全部成功时 `mysql_config_ok=true`，任一失败不会跳过后续项；
- `wechat-health` 在独立 try/catch 中重新映射 Collector 密码并只使用 Collector 配置，不会回写 MySQL 配置检查结果；
- 两类 Python 命令 stdout/stderr 全部吞掉，只保留安全状态；
- 不包含真实采集、scheduler、Worker 启动、任务注册/注销、写配置、删除、移动或 `Invoke-Expression`。

## TDD 与复审

RED 首先确认六个脚本不存在，随后按 start、register/unregister、check 契约逐项转绿。追加 RED 并关闭的安全边界包括：

- 子进程 traceback 不复制到包装器日志；
- 注册只接受 User/Machine 持久环境；
- 三个角色密码和三份独立配置；
- check 三角色逐项检查和健康检查异常隔离；
- 配置路径必须为 Leaf 文件；
- 非规范整数式 IPv4 拒绝；
- principal 和 AtLogOn trigger 使用同一限定域身份。
- 共享 MySQL 密码 fallback 默认关闭且计划任务不 opt-in；
- legacy 任务枚举失败时在任何注册前 fail closed；
- SYSTEM、NT AUTHORITY、NT SERVICE 和非交互身份不得创建 principal。

初轮独立复审发现的三个 Important 和两个 Minor，以及提交前复核发现的三个 fail-closed Important 均已关闭。最终复审未发现 Critical、Important 或 Minor，Assessment 为 Ready。

## 最终验证

- Windows scheduler + admin stack 专项：`29 passed`
- 最终全量：`1583 passed, 1 skipped`
- 六个新脚本均通过 Windows PowerShell 5.1 AST Parser
- `git diff --check`：通过
- 新增/修改文件严格 UTF-8 解码：通过
- 静态危险命令与敏感值扫描：通过

## 后续衔接

- 本任务没有实际注册任务；生产注册必须在部署预检、证书 ACL、数据库角色和旧 scheduler 切换确认后由管理员人工执行。
- 三份生产配置应分别使用 Web、Collector、Pipeline 最小权限账号；密码通过对应角色环境变量提供。
- Task Scheduler、HTTPS、MySQL 和微信健康的真实运行验证属于后续受控部署/验收任务。
