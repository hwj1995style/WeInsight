# Task 5 发布前 QA 报告

## 服务与测试

- 隔离开发服务：`http://127.0.0.1:8857`
- 服务 PID：`89540`
- 启动方式：`python -m app.web --config config/config.dev.yaml --port 8857`
- 数据源：当前 `config/config.dev.yaml` MySQL；未占用或重启 8848。
- 全量测试：`pytest -q` → `2015 passed, 2 skipped`。
- `git diff --check`：通过。

## 发布前风险修复

- 下游一次性结果 flash 保持服务端可信并增加上限与 TTL：最多 128 个 Session 项、5 分钟过期。
- 写入和读取前均淘汰过期项，超量时按最早项淘汰；同一 Session 的新结果覆盖旧结果。
- 新增过期与容量边界测试。
- Web CLI 增加可选 `--port` 覆盖，默认仍使用配置端口，便于隔离 QA。
- 目视检查发现普通模式下 `hidden` 被 grid display 覆盖，已增加作用域内 `[hidden] { display:none }` 并重新截图确认。

## Playwright CLI 证据

当前环境未提供 Browser/IAB 插件，按 `playwright` skill 使用 `npx --package @playwright/cli playwright-cli` fallback，命名 Session 为 `task5`。

- 登录：填写 `admin` 与开发管理员密码，点击登录后到达 `/dashboard`，再通过“公众号”导航进入 `/sources/articles`。
- 桌面视口：`resize 1440 1000`；页面级 `bodyWidth=clientWidth=1440`。
- `scope=enabled`：`sourceDisabled=true`、`sourceRequired=false`、`formValid=true`。
- 切回 `scope=single`：`sourceDisabled=false`、`sourceRequired=true`。
- 默认日期：`2026-07-08` 至 `2026-07-14`，包含当天共 7 天；页面显示“单次最多 31 天”。
- `mode=force_analyze`：确认字段显示、启用且 required；切回 `missing_only` 后隐藏、禁用、取消 required 并清空 checked。
- 开关确认取消：触发“确认开启下游处理”原生 confirm 后取消，URL 保持 `/sources/articles`；8857 访问日志中无 `POST /sources/articles...`。
- 740×1000：`bodyWidth=clientWidth=740`，主内容可见，导航遮罩保持 hidden，无白屏或页面级横向溢出（宽表在自身滚动容器内）。
- Console：`0 Errors, 0 Warnings`。

## 截图与视觉复核

- 截图：`output/playwright/article-downstream-management.png`
- 使用 `view_image` 检查桌面全页截图：标题、说明、表单、按钮、状态表和侧栏均正常；修复普通模式误显强制确认后再次截图，未见遮挡、裁切或未完成组件。

## 数据安全声明

QA 未提交任何公众号下游开关或历史补处理请求；服务访问日志不存在对应 POST，因此公众号配置、处理任务及业务结果表未发生本次 QA 引起的变更。登录仅使用既有鉴权流程创建/刷新管理员 Session，不执行业务数据修改。隔离服务已在 QA 完成后关闭。
