# Task 4 独立高级审查报告

## 结论

**不建议进入 Task 5。** 提交 `2e61fb0..71a11c5` 的服务注入、路由隔离、Session/CSRF 基础保护、业务字段 allowlist、422 错误映射、模板转义、上游只读语义和响应式框架总体成立，但当前有 2 个 P1 会分别阻断 `enabled` 范围的正常操作并允许伪造成功汇总；另有 3 个 P2 与严格单值、确认交互和样式质量不符。

本次仅做静态独立审查，未修改实现，也未重复执行报告中已有的 `108 passed` / `323 passed`。

## 规格核对

- 符合：`create_app` 仅在依赖缺失时创建一个 engine，默认 `ArticleDownstreamService(MysqlArticleDownstreamRepo(engine))` 与其他默认服务复用该 engine（`app/web/app.py:98-126`）。
- 符合：两个 POST 路由不会互相吞掉。动态路由要求末段为 `downstream-processing`，静态 backfill 路由末段为 `backfill`，因此即使动态路由先注册也不匹配 backfill 路径（`app/web/routes/sources.py:190-233`）。
- 符合：管理员 Session 与所有非公开 POST 的 CSRF 中间件覆盖新增接口（`app/web/middleware.py:20-60`）；业务字段重复值、未知字段、布尔/checkbox/source ID 的 Web 层校验存在（`app/web/routes/sources.py:193-224,299-334`）。
- 符合：业务校验异常映射为 422、来源不可用映射为 404，错误页不回显内部异常（`app/web/routes/sources.py:201-204,228-231,358-366`）。
- 符合：成功路径均为 303 PRG；页面显示默认 7 天、最多 31 天说明、关闭账号“仅补历史”提示；不可操作账号无开关且不进入单账号选项（`app/web/routes/sources.py:173-185,205,232-233`；`app/web/templates/sources/articles.html:6-17,24`）。
- 符合：账号名等动态文本由 Jinja 自动转义；页面明确 WeRSS 上游采集仍为只读，新增写能力仅管理 WeInsight 下游（`app/web/templates/sources/articles.html:5,11,24`）。
- 部分符合：新增 CSS 选择器均以 `.article-downstream` 为祖先且有 1100/640px 断点，但使用了未定义变量，见 P2。
- 不符合：`single/enabled` 联动、安全不可伪造汇总、全部表单字段严格单值以及操作确认要求，详见问题。

## 问题分级

### P1 — `enabled` 范围在浏览器中无法提交

`scope` 可以选择“全部已开启公众号”，但 `source_id` 的 `<select>` 永久带有 `required`，且默认空值；页面没有任何脚本或服务端渲染联动去在 `scope=enabled` 时禁用/移除该约束（`app/web/templates/sources/articles.html:9-10`）。因此管理员选择“全部已开启公众号”后，浏览器会在发出请求前因空的单账号字段而阻止提交。若选一个账号绕过，后端会忽略它，但 UI 语义仍错误。此问题直接破坏设计与计划要求的“单账号 / 全部已开启账号”入口。

建议：实现可访问的 scope 联动；`enabled` 时禁用并清空单账号选择，`single` 时恢复并要求选择，同时保证无 JavaScript/恶意请求仍由服务端严格校验。补充真实表单提交测试，而不是仅手工构造 POST。

### P1 — PRG 成功汇总可由任意已登录用户伪造

成功后把八个计数以裸 query string 重定向（`app/web/routes/sources.py:232-233`），GET 端只校验“字段齐全、单值、纯数字并截断上限”（`app/web/routes/sources.py:344-355`）。任何已登录管理员都可直接构造 `/sources/articles?...` 显示“补处理任务已提交”和任意计数；这不是计划要求的“短期 Session flash 或受限 query token”，也无法证明汇总来自本次 POST。模板会把伪造值作为成功操作结果展示（`app/web/templates/sources/articles.html:7`）。这会误导审计/运维判断，违反“安全汇总不可伪造”。

建议：优先使用一次性 Session flash；若保留 query，必须使用绑定当前会话、短有效期且完整性受保护的签名 token，并在消费后失效。测试应直接构造合法数字 query 并证明页面不展示伪造成功提示。

### P2 — CSRF 字段未满足严格单值要求

`_form_values` 在检查重复前无条件跳过所有 `csrf_token`（`app/web/routes/sources.py:299-310`）；中间件对 URL encoded body 又只取 `tokens[0]`（`app/web/middleware.py:90-98`）。因此重复 CSRF 字段不会被 422 拒绝，带 `X-CSRF-Token` 时正文中的任意数量/任意值 CSRF 字段也被完全忽略。虽然当前未形成直接 CSRF 绕过，但与设计“只接受单值表单字段”和审查要求不符，并留下解析器差异风险。

建议：在中间件或统一严格解析器中要求 CSRF 恰好一个值（选择 header 模式时明确禁止或一致校验正文 token），补重复 CSRF 与 header/body 冲突测试。

### P2 — 确认和模式联动不足

逐账号开关只有 hover `title="不会改变 WeRSS 采集状态"`，没有设计要求的“操作前确认”；触屏和键盘用户也不一定能获得该信息（`app/web/templates/sources/articles.html:24`）。`confirm_force` 则始终显示且在 `missing_only` 下仍可勾选，没有随模式联动；服务端虽正确阻止未确认的 `force_analyze`，但交互尚未满足计划中真实浏览器要验证的联动和明确确认。

建议：开关提交前提供可键盘操作的确认机制或清晰、持久的临近文案；只在 `force_analyze` 时启用并要求确认，切回普通模式时清空。保留服务端校验作为最终边界。

### P2 — 新增说明文字使用不存在的 CSS 变量

新增规则引用 `var(--color-text-muted)`（`app/web/static/app.css:340,343`），但根变量只有 `--color-muted`（`app/web/static/app.css:8`）。无 fallback 时 `color` 声明失效，导致说明文字继承默认色，方向 A 的弱化层级没有生效。

建议：改用既有 `var(--color-muted)`，并在 Task 5 的桌面与窄屏视觉检查中确认文本层级和对比度。

## 测试与质量评价

现有新增测试覆盖开关 PRG、业务字段重复/未知、非法布尔、未登录/CSRF、force 缺确认、汇总展示和转义，方向正确；但缺少以下关键反例：浏览器原生提交 `scope=enabled`、直接伪造汇总 query、重复 CSRF、scope/mode 的可访问联动、一箱蛋/不可操作行与选项的明确断言，以及切换按钮确认行为。当前测试通过不能证明上述规格成立。

代码质量方面，路由职责清楚、线程池调用正确、异常输出稳定；主要问题集中在把未认证的 query 当 flash、HTML 约束未按 scope 改变，以及 CSS token 拼写。`git diff --check` 无静态格式问题。

## Task 5 准入判断

**否。** 先修复两个 P1，并为它们补回归测试；同时建议在进入真实浏览器验证前一并修复三个 P2。修复后至少应证明：`enabled` 可从真实页面成功提交、伪造 query 不产生成功提示、所有字段（含 CSRF）严格单值、single/enabled 与 force 确认可用且键盘可达、开关动作具有明确确认语义。

## 审查修复（2026-07-14）

上述 2 个 P1 与 3 个 P2 已全部修复：

1. `scope=enabled` 时前端禁用并清空单账号选择；`scope=single` 时恢复 `required`。服务端仍独立执行严格范围校验。
2. 删除裸 query 汇总。POST 结果写入以当前 Session token 为键的服务端一次性 flash，GET 原子消费；直接伪造八项数字 query 不会展示成功提示，刷新也不会重复展示。
3. CSRF 表单值纳入严格单值校验；URL encoded 和 multipart 的重复 token、header/body 冲突统一返回安全 422，不进入业务服务。
4. 单账号开关使用键盘可触发的提交确认，并通过持久的无障碍说明明确不改变 WeRSS。范围和模式通过原生控件及 JS 联动；仅强制分析时显示、启用并要求风险确认，切回普通模式会清空确认。
5. 新增说明文字统一改用现有 `--color-muted`；无障碍隐藏说明样式继续限定在 `.article-downstream` 范围。

新增回归覆盖伪造 query、flash 一次性、重复 CSRF、可访问控件关联和联动脚本。验证结果：

- 聚焦 Web/Auth：`111 passed`
- 全部 `tests/test_web_*.py`：`326 passed`
- `git diff --check`：通过
- 未连接或修改真实数据库。
