# Content Task 6 执行报告

## 状态

- 文档门禁：完成 RED/GREEN。
- 本机迁移：`20260712_001` 连续执行两次，完成。
- 本机 shadow：现有“一箱蛋”待处理批次 clean/analyze 完成；其 raw 记录无 locator，最终来源为 web。
- WeRSS 停止与恢复：回退自动化矩阵通过，容器最终恢复 `healthy`。
- 固定 POC：进行中/未启动 24 小时计时。目标“湖南三尖农牧公司”未配置在本机开发库，未切换 `werss_first`，未扩大范围。

## 命令与结果

1. `python -m pytest tests/test_sensitive_output_guard.py tests/test_werss_content_poc_docs.py -q`
   - RED：4 failed、6 passed；失败原因为 POC 文档缺失、运行手册条目缺失、敏感输出文档名单缺失。
   - GREEN：10 passed。
2. 连续两次把 `sql/migrations/20260712_001_add_article_content_metadata.sql` 输入本机 MySQL 8.4 开发容器。
   - 两次 exit 0；raw 的 locator 两列和 clean 的来源、哈希、获取状态三列均存在。
3. `python -m app.main parse-article-once --config config/config.dev.yaml`
   - read 3、success 3、failed 0。
4. `python -m app.main analyze-article-once --config config/config.dev.yaml`
   - read 3、success 3、failed 0。
5. 安全元数据 SQL 检查。
   - clean 新增 `web/success` 3；article UI lock 计数 0；raw/clean 禁止正文列计数 0。
6. 停止 WeRSS 后运行 `pytest tests/test_article_content_fallback.py tests/test_pipeline_runtime_factory.py -q`，再启动 WeRSS 并轮询健康状态。
   - 14 passed；最终 `healthy`。
7. UTF-8 校验。
   - 两份中文运维文档可按 UTF-8 解码，连续问号替换计数 0。
8. `python -m pytest -q` 与 `git diff --check`。
   - 1665 passed、2 skipped、1 个第三方弃用警告；diff check exit 0。
9. `rg -n "content_html|content_text|body_text" sql app/storage`。
   - 无匹配，WeInsight SQL 与持久化 repo 未出现这些正文存储字段或参数。
10. WeRSS 最近 200 行 Docker 日志敏感模式检查。
    - 不通过：固定镜像自身的 SQL 调试日志包含正文相关字段，并出现了参数值片段。报告不复制该片段；正式 POC 前必须关闭或净化该日志输出并复验。

## POC 状态

- 固定目标：湖南三尖农牧公司，Feed ID `MP_WXS_3545051769`，最终目标总数 9。
- 本机账号清单中不存在该固定目标；唯一启用账号为“一箱蛋”。
- shadow 批次成功，但由于现有 raw 记录 locator 均为空，只观察到 web 来源，未获得同一真实文章的 WeRSS/网页长度、哈希和报价差异。
- 未满足切换 `werss_first` 的前提，未填写 24 小时开始/截止时间，不宣称通过。

## 未完成观察项与关注点

1. 配置并授权固定目标 Feed 后，取得含合法 locator 的新文章，完成正文接口真实契约和双路径差异对账。
2. 用真实待处理任务观察 WeRSS 停止时网页回退，以及恢复后的下一任务重新使用 WeRSS。本次未篡改既有数据制造任务。
3. 影子无不可解释差异后才能切单公众号 `werss_first`，记录基线并开始连续 24 小时观察。
4. 24 小时未结束前保持范围 1；后续只按 1 → 3 → 9 扩容。
5. 现有 24 小时采集指标仍有历史失败记录，最新错误摘要为结构化 RSS 采集错误；需在正式 POC 前另行处置，报告不包含响应体、正文或凭据。
6. 固定 WeRSS 镜像当前日志会输出正文相关 SQL 参数，是启动真实 24 小时观察的阻断项；在日志配置或镜像修复并复验前保持 `content_mode: web`/shadow，不切 `werss_first`。
