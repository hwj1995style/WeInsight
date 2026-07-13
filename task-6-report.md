# Task 6 实施报告

## 状态

- 已实现公众号只读状态查询服务、预聚合仓储、后台状态页和依赖注入。
- 已删除公众号新增/编辑模板及所有公众号 POST 写路由；微信群管理路由保持不变。
- 刷新为普通 GET 查询，不触发同步、采集或写入。

## 行为边界

- 状态优先级：`excluded > missing > disabled > collect_error > stale > normal`。
- active 且无成功采集记录显示“等待首轮”；陈旧阈值为全局周期的两倍。
- raw、process task、collect log 先各自按公众号聚合后再 JOIN，避免多表行数倍增。
- 最近错误通过现有 `sanitize_output` 脱敏并限制为 200 字符。
- `ArticleSourceStatusService` 可由 `create_app` 注入，Web 测试无需数据库。

## 测试

- RED 1：`tests/test_article_source_status_service.py` 首次运行因服务模块不存在失败。
- RED 2：只读 Web 测试首次运行因 `create_app` 不接受状态服务注入失败。
- GREEN：状态服务测试、完整来源 Web 测试通过。
- Web/安全组合回归存在 3 个既有环境失败：测试误连本地 MySQL，账号 `weinsight` 被拒绝；其余通过。

## Concerns

- 本工作树未提供可用的开发 MySQL 密码，因此 3 个既有 dashboard 认证测试无法完成数据库型验证；该问题在 Task 6 修改前基线已复现。
- 真实 MySQL 8 上的 CTE/窗口函数查询仍应在集成环境执行一次 EXPLAIN 与结果抽查。
