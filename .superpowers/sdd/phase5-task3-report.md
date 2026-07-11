# 阶段五 Task 3 实施报告：MySQL 最小权限与安全部署回滚

## 交付结论

阶段五 Task 3 已按正式计划、权限/部署设计和实施简报完成。新增固定生产 schema 的三角色最小权限 SQL、严格 GRANT 契约测试和中文部署回滚手册，并修正生产 Web 最小权限与运行监控查询的兼容性。

本任务没有连接数据库或执行 SQL，没有创建用户或修改权限，没有注册/注销/启动计划任务，没有修改防火墙、证书 ACL 或环境变量，也没有启动 Web、Worker、微信探测和采集。代码改动仅限于移除 Web runtime monitor 对 UI lock 表的直接查询，并保留兼容的安全不可用状态。

## Role SQL

`sql/operations/grant_admin_stack_roles.sql` 固定使用 `weinsight_prod`，文件头要求 DBA 在 schema 不同时只在受控副本逐项替换并重新审计。SQL 只创建：

- `weinsight_web_role`
- `weinsight_collector_role`
- `weinsight_pipeline_role`

模板不创建用户、不包含凭据或密钥，不使用数据库级通配，不授予 `GRANT OPTION`、`SUPER`、`FILE`、`PROCESS` 或 `ALL PRIVILEGES`，不包含动态 SQL、DROP 或初始 REVOKE。所有授权逐表声明。

### Web

Web 对管理员、Session、名单、job/target、日报请求拥有现有代码路径所需的最小写权限；事件允许只读和写入 Web 任务操作的审计事件。运行、心跳、健康、collect log、安全 clean/analysis/egg/daily/process 摘要只读。

Web 明确没有群/文章 raw、UI lock、cursor、route cache 和 article progress 权限。

### Collector

Collector 只读群配置和 job target；公众号配置额外只允许 UPDATE 采集成功时间所需字段所在表，job 允许调度状态更新。run/target-run、heartbeat、cursor、route cache 和 progress 使用实际路径所需读写权限；健康检查表只允许 SELECT + INSERT，不允许修改历史探测记录。

进一步按 Repo 操作收窄：

- group raw 仅 INSERT；article raw 为 SELECT + INSERT，用于 URL 去重；
- group/article collect log 仅 INSERT，避免篡改审计；
- group/article process task 仅 INSERT；
- UI lock 使用 SELECT、INSERT、UPDATE、DELETE，以支持过期清理、心跳和 owned release。

Collector 没有管理员、Session、clean/analysis/egg、日报和日报请求权限。

### Pipeline

Pipeline 对 raw 只读；对 process task、clean、analysis、daily report 和 report request 使用实际处理路径所需权限；事件只 INSERT，heartbeat 只 INSERT + UPDATE。egg item 采用 DELETE + INSERT 的 replace 路径，不授无用 SELECT/UPDATE。

Pipeline 没有管理员、Session、UI lock、source/job/job target、job run/target run 和健康表权限。

## 契约测试

`tests/test_admin_stack_mysql_roles.py` 先移除行注释和块注释，再只解析真实 GRANT 语句，避免注释文字制造权限假阳性。解析器拒绝除 `CREATE ROLE IF NOT EXISTS` 和逐表 GRANT 之外的任何额外 SQL 语句。

测试覆盖：

- 三角色创建集合；
- 固定 schema 和逐表、无重复授权；
- 每个角色关键正向 privilege；
- raw/UI lock/admin/report/job-run 等负向边界；
- 高权、用户、凭据、通配、DROP/REVOKE 禁止项；
- `sql/init.sql` 29 张表全部有明确角色策略，模板也不得引用未知表；
- 中文手册章节、命令顺序、四回滚、敏感扫描和 summary 生命周期准确性。

## 部署与回滚手册

`docs/operations/微信采集管理后台部署与回滚手册.md` 按实际执行顺序覆盖：

1. 版本、Windows/Python/MySQL、微信 PC 4.1.8.107、交互用户、备份和维护窗口；
2. TLS cert/key 占位路径、证书与私钥的 `icacls` 运行账号读取 ACL、私钥继承/普通组移除、`Get-Acl` 审计和私钥不入仓库/日志；
3. DBA 交互登录、三个 `IDENTIFIED BY RANDOM PASSWORD` 用户、secret manager、role 分配、default role 和 `SHOW GRANTS`；
4. 三份配置、三个角色密码环境变量和生产不启用共享密码 fallback；
5. 指定 `<ADMIN_LAN_CIDR>` 到 8848 的防火墙规则和系统信任链 HTTPS；
6. 两个 legacy scheduler 名称切换、Interactive/Limited 当前用户任务注册；
7. 七键只读检查、独立日志、本机截图路径、微信健康和次日 00:10 补偿验收；
8. Web 业务只读、article 单链路暂停、全部托管采集暂停、恢复旧手动 CLI 四种回滚；
9. 首次登录不强制改密的剩余风险和补偿控制。

全部托管采集回滚先在 Web 请求停止所有 job，等待 run/target-run 终态和 UI lock 释放，之后才停止 Collector 任务。紧急强停后必须等待 lease 过期并核对数据库状态。日报验收只声明群/文章子日报为 final，summary 通过 compensation all 请求与只读页面/下载复核，不伪造统一生命周期。

## 生产改名限制与后续技术债

Web role 按明确安全边界不能读取 raw/cursor/progress。现有 `MysqlSourceMutationRepo` 的 rename 历史守卫直接查询这些表，因此生产最小权限模式下改名会 fail closed。

手册已明确禁止生产名单改名，并固定使用“停用旧配置并新建替代配置”的操作路径。后续若要恢复安全改名，需新增不暴露 raw 的安全投影、引用表或受控判定接口，替换 Web 对 raw 的直接查询；不得通过给 Web 授 raw 权限绕过。

## TDD 与复审

先观察 SQL/手册不存在的 RED，再逐项实现。实际 Repo 复审发现并关闭：

- Collector UI lock 缺 DELETE、公众号成功时间缺 UPDATE；
- Collector log/process/group raw 与 Pipeline heartbeat 过权；
- Pipeline egg replace 缺 DELETE 且存在无用 SELECT/UPDATE；
- 全部托管回滚先停进程后等安全检查点的错误顺序；
- summary 不存在统一 final 字段的文档错误；
- SQL parser 静默忽略额外语句的测试缺口。

Web rename/raw 冲突没有以越权方式处理，已转为明确的生产限制和后续安全重构项。

最终复审还发现 Web runtime monitor 会直接读取 `wechat_ui_lock`，与 Web role 明确不含 UI lock 权限冲突。新增失败测试后，Repo 改为只读取 heartbeat 与 health，并返回兼容的 `UiLockView(state="unavailable")`；Dashboard 和 Worker 页面明确显示“最小权限下不可用 / 不代表 UI 锁空闲”。空快照也使用 unavailable，避免数据库异常时误报空闲。

## 最终验证

- runtime monitor + Role SQL + 部署手册专项：`62 passed, 1 skipped`
- 最终全量：`1599 passed, 1 skipped`
- `git diff --check`：通过
- 新增文件严格 UTF-8 解码：通过
- SQL/文档敏感内容和危险授权扫描：通过
- 独立最终复审：`Ready`，Critical / Important / Minor 均无

## 后续衔接

- DBA 在受控生产环境执行前仍需复核 schema、29 张表、三用户 host 限制和 `SHOW GRANTS` 输出。
- 部署人员必须先完成备份、TLS ACL、CIDR 防火墙和 legacy 切换，再注册任务。
- 真实数据库 role 集成验证、Windows 任务注册、HTTPS 和单目标 POC 属于后续受控任务，不在本任务执行。
