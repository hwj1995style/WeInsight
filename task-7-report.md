# Task 7 执行报告

## 状态

- 代码库内文档、文档契约测试、README 和 POC 记录更新：完成。
- 文档提交：`4e3412060d2ff12d0aa8cd87f7b0121d62bfda13`（`docs: operate read-only WeRSS catalog sync`）。
- 真实专用凭据、用户环境变量、数据库迁移、服务重启、全局周期和浏览器视觉验收：已由 controller 完成并提供安全证据；本报告不记录或输出 AK/SK 值。

## RED → GREEN

RED 命令：

```text
python -m pytest tests/test_werss_deployment_docs.py tests/test_werss_content_poc_docs.py tests/test_article_rpa_removed.py -q
```

结果：3 failed、22 passed。失败点分别为运行手册缺少固定本机只读 API 契约、README 缺少新边界、POC 未将旧窗口标记失效，均为预期失败。

GREEN 使用同一命令，结果：25 passed in 0.14s。

UTF-8 核验：中文探针 `中文探针：只读` 使用无 BOM UTF-8 写入并核对字节；`README.md`、运行手册和 POC 记录均通过 Python `encoding='utf-8'` 严格解码。`git diff --check` 通过，仅有 Git 对工作区 CRLF 转换的提示。

## 初次文档阶段全套测试（历史）

命令：`python -m pytest -q`

结果：1834 passed、4 skipped、5 failed、19 errors，耗时 29.72s。

该次运行当时的环境阻断（后续已由 controller 处理）：

- Windows User 环境变量 `WEINSIGHT_WERSS_ACCESS_KEY`、`WEINSIGHT_WERSS_SECRET_KEY` 均未配置；仅检查是否存在，未读取或输出值。
- 真实 MySQL 返回 `Access denied for user 'weinsight'@'172.20.0.1'`，导致部分真实数据库测试失败。
- 失败/错误集中在依赖 `config.dev.yaml` 的 Web/视觉用例、真实数据库鉴权以及关联运行时用例；目标文档回归已单独全绿。

## 初次安全联调准备检查（历史）

- `sql/migrations/20260713_001_add_werss_catalog_state.sql`：存在。
- `rg -n "article-rpa-probe|collect-article-once|run-article-scheduler" app`：无匹配，旧公众号 RPA 可执行入口未恢复。
- `127.0.0.1:8001`：监听中，归属 Docker backend。
- `127.0.0.1:8848`：监听中，归属 Python 进程。
- Docker Desktop 和多个 Python 进程正在运行；为避免影响现有运行，未停止、重启或修改它们。
- 未发现本机 3306 监听；真实数据库可能在容器网络或其他地址，需由 controller 按批准配置确认。

## 真实联调与观察证据

- 专用 WeRSS AK/SK 已通过 WeRSS 自身授权机制创建并写入 Windows User 环境变量；只确认已配置，不记录值。
- 迁移 `20260713_001_add_werss_catalog_state.sql`、`20260713_004_system_article_job_singleton.sql` 已应用。
- 唯一活动公众号任务为 ID 10、`managed_key=article_global`、间隔 600 秒；旧手工任务均 stopped/deleted。
- 家美鲜真实 Feed 为 6,357,020 bytes；提交 `05bec95` 将旧 5 MiB 上限调整为 10 MiB。collector 重启后 run 206 于 2026-07-13 18:39:32 调度、18:39:33 开始、18:39:49 结束，9/9 success。
- “一箱蛋”保持 `enabled=0`、`upstream_status=excluded`；观察起点后新增 raw=0、process task=0；active UI locks=0。
- article queue 当前 success=124、pending=1；唯一 pending 是历史 `article_daily_report` ID 268，不属于新采集链路。
- 桌面截图：`output/playwright/werss-status-desktop-final.png`；窄屏截图：`output/playwright/werss-status-mobile-final.png`；浏览器 console 为 0 error、0 warning。
- 新连续 24 小时观察起点：2026-07-13 18:39:32 +08:00；门禁：2026-07-14 18:39:32 +08:00。当前仅可标记“进行中”，不得提前宣称通过。

## 安全声明

本次文档更新未读取或输出真实 AK/SK。真实环境变更与联调由 controller 执行并提供上述安全计数；连续 24 小时观察仍在进行中，未声称最终验收通过。
