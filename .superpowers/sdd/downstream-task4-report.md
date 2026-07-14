# Task 4 Web 接入报告

## 交付内容

- `create_app` 注入 `ArticleDownstreamService`，默认仓储复用同一个 MySQL engine。
- 新增公众号下游处理开关与历史补处理 POST 路由；沿用 Session/CSRF 中间件，严格限制字段、单值、枚举、布尔和日期输入，成功后均使用 303 PRG。
- PRG 汇总只携带八个受限非负计数，GET 端要求字段完整、单值且纯数字，不展示敏感内容。
- 公众号状态页明确 WeRSS 上游只读、WeInsight 仅管理下游；增加“下游处理”列、可操作账号开关、历史补处理表单、7 天默认值、31 天说明及强制分析确认。
- 一箱蛋等不可变账号不渲染开关或补处理选项；关闭账号标注“仅补历史”，说明不改变未来自动处理。
- 方向 A 样式全部限定在 `.article-downstream` 下，提供桌面、平板、手机响应式布局。

## 安全与测试

- 覆盖成功 PRG、未登录/CSRF、非法值、重复字段、未知字段、强制分析缺确认、自动转义及安全计数汇总。
- `pytest -q tests/test_web_sources.py tests/test_web_auth.py`：108 passed。
- 全部 Web 回归（`tests/test_web_*.py`）：323 passed。
- `git diff --check`：通过。
- 仓库不存在 `tests/test_web_app.py`，因此使用全部 Web 测试作为更强替代。
- 环境未安装 `ruff`，未执行 Ruff；Python 测试收集和运行均通过。

## 设计说明

复用已确认的 `docs/superpowers/specs/2026-07-14-公众号统一下游处理与历史补任务设计.md`。本次属于既有设计系统内的小型页面扩展，按 `frontend-app-builder` 规则无需 ImageGen。
