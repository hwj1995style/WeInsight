# Task 7 执行报告

## 状态

- 代码库内文档、文档契约测试、README 和 POC 记录更新：完成。
- 文档提交：`4e3412060d2ff12d0aa8cd87f7b0121d62bfda13`（`docs: operate read-only WeRSS catalog sync`）。
- 真实凭据创建、环境变量设置、数据库迁移、服务重启、两轮真实全局周期、浏览器登录和截图：未执行；这些动作依赖 controller 的 WeRSS 管理端、数据库权限、运行窗口或当前登录态，不能伪造完成。

## RED → GREEN

RED 命令：

```text
python -m pytest tests/test_werss_deployment_docs.py tests/test_werss_content_poc_docs.py tests/test_article_rpa_removed.py -q
```

结果：3 failed、22 passed。失败点分别为运行手册缺少固定本机只读 API 契约、README 缺少新边界、POC 未将旧窗口标记失效，均为预期失败。

GREEN 使用同一命令，结果：25 passed in 0.14s。

UTF-8 核验：中文探针 `中文探针：只读` 使用无 BOM UTF-8 写入并核对字节；`README.md`、运行手册和 POC 记录均通过 Python `encoding='utf-8'` 严格解码。`git diff --check` 通过，仅有 Git 对工作区 CRLF 转换的提示。

## 全套测试

命令：`python -m pytest -q`

结果：1834 passed、4 skipped、5 failed、19 errors，耗时 29.72s。

已确认的环境阻断：

- Windows User 环境变量 `WEINSIGHT_WERSS_ACCESS_KEY`、`WEINSIGHT_WERSS_SECRET_KEY` 均未配置；仅检查是否存在，未读取或输出值。
- 真实 MySQL 返回 `Access denied for user 'weinsight'@'172.20.0.1'`，导致部分真实数据库测试失败。
- 失败/错误集中在依赖 `config.dev.yaml` 的 Web/视觉用例、真实数据库鉴权以及关联运行时用例；目标文档回归已单独全绿。

## 安全联调准备检查

- `sql/migrations/20260713_001_add_werss_catalog_state.sql`：存在。
- `rg -n "article-rpa-probe|collect-article-once|run-article-scheduler" app`：无匹配，旧公众号 RPA 可执行入口未恢复。
- `127.0.0.1:8001`：监听中，归属 Docker backend。
- `127.0.0.1:8848`：监听中，归属 Python 进程。
- Docker Desktop 和多个 Python 进程正在运行；为避免影响现有运行，未停止、重启或修改它们。
- 未发现本机 3306 监听；真实数据库可能在容器网络或其他地址，需由 controller 按批准配置确认。

## 待 controller 精确步骤

1. 在本机 WeRSS 管理端创建名称为 `WeInsight read-only catalog` 的专用 AK/SK，只授予公众号清单读取权限；不要在聊天、日志或仓库粘贴真实值。
2. 将真实值写入当前 Windows User 环境变量 `WEINSIGHT_WERSS_ACCESS_KEY`、`WEINSIGHT_WERSS_SECRET_KEY`，新开终端后只检查变量是否非空，不打印值。
3. 确认维护窗口，记录并停止旧 collector/pipeline；备份 `weinsight_dev`，验证备份可读并记录仓库外路径。
4. 使用获批数据库管理员连接应用 `sql/migrations/20260713_001_add_werss_catalog_state.sql`；随后确认应用账号迁移后所需最小权限，并解决当前 1045 鉴权失败。
5. 按 web → collector → pipeline 顺序启动服务；不得恢复公众号旧 RPA。等待至少两个每 10 分钟全局周期。
6. 用安全计数核对：批准范围来源全部同步；“一箱蛋”新采集/清洗/分析/报价任务为 0；公众号 UI 锁为 0；新文章按状态进入 parse/analyze/报价表；微信群 Worker 正常；无重复原始、清洗、分析或报价记录。
7. 在已有登录态或由 controller 提供临时测试登录方式后，以 Playwright 打开 `http://127.0.0.1:8848/sources/articles`，分别使用 `1440x900` 和 `390x844` 截图。检查状态标签、横向滚动、长名称、空值、错误状态、侧栏折叠以及无新增/编辑/启停/删除入口；把实际仓库外截图路径写回 POC 记录。
8. 填写真实迁移版本、应用提交、当前 WeRSS 镜像摘要和首个健康周期时间。只有首个 9/9 成功且增量流水线健康后，才重新开始连续 24 小时观察；旧窗口不得拼接。
9. 在真实环境变量和数据库权限就绪的新终端中重新运行 `python -m pytest -q`，保存不含 AK/SK 的测试摘要。

## 安全声明

本次未创建、读取或输出真实 AK/SK；未修改 User 环境变量、数据库、WeRSS、运行服务或浏览器登录态；未声称真实联调、视觉验收或新 24 小时窗口已经完成。
