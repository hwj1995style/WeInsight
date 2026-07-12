# Content Task 6 执行报告

## 状态

- 文档门禁：完成 RED/GREEN。
- 本机迁移：`20260712_001` 连续执行两次，完成。
- 本机 shadow：现有“一箱蛋”待处理批次 clean/analyze 完成；其 raw 记录无 locator，最终来源为 web。
- WeRSS 停止与恢复：回退自动化矩阵通过，容器最终恢复 `healthy`。
- 固定 POC：已于 2026-07-12 13:08:14 +08:00 启动，当前进行中；截止时间为 2026-07-13 13:08:14 +08:00，不宣称通过。

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
11. 固定镜像日志开关只读调查。
    - 容器环境变量名只有 `DB`、`LOG_LEVEL`/`DEBUG` 未实际注入等常规项，没有 SQL/查询参数日志开关。
    - 镜像 `/app/core/db.py` 在创建 engine 后无条件注册 `before_cursor_execute` 监听器，并无条件输出 SQL；参数非空时无条件输出参数。SQLAlchemy 自身已是 `echo=False`，因此设置 echo、`DEBUG=False` 或提高 `LOG_LEVEL` 都不能关闭这条 `print_info` 路径。
    - 镜像自带 Compose、示例配置和启动脚本未提供关闭 SQL/参数输出的配置。仓库 Compose 只有 json-file 轮转，不能净化应用 stdout。
    - 结论：当前固定镜像和现成 Compose/env 中没有可证明有效的安全开关；未改镜像、未构建镜像、未丢弃 Docker 日志，容器未因调查重建。
12. WeRSS 固定 Feed 核对。
    - 通过容器现有 DB 连接只读查询 `feeds.id`，目标 Feed ID 计数为 1；未输出 Feed 内容或连接凭据。

## POC 状态

- 固定目标：湖南三尖农牧公司，Feed ID `MP_WXS_3545051769`，最终目标总数 9。
- WeRSS `feeds` 中存在该固定目标；WeInsight `wechat_public_account_config` 中不存在该目标，当前唯一启用的 WeInsight 账号为“一箱蛋”。
- shadow 批次成功，但由于现有 raw 记录 locator 均为空，只观察到 web 来源，未获得同一真实文章的 WeRSS/网页长度、哈希和报价差异。
- 未满足切换 `werss_first` 的前提，未填写 24 小时开始/截止时间，不宣称通过。

## 未完成观察项与关注点

1. WeRSS 已有固定目标 Feed；需在 WeInsight 配置该目标，并取得含合法 locator 的新文章，完成正文接口真实契约和双路径差异对账。
2. 用真实待处理任务观察 WeRSS 停止时网页回退，以及恢复后的下一任务重新使用 WeRSS。本次未篡改既有数据制造任务。
3. 影子无不可解释差异后才能切单公众号 `werss_first`，记录基线并开始连续 24 小时观察。
4. 24 小时未结束前保持范围 1；后续只按 1 → 3 → 9 扩容。
5. 现有 24 小时采集指标仍有历史失败记录，最新错误摘要为结构化 RSS 采集错误；需在正式 POC 前另行处置，报告不包含响应体、正文或凭据。
6. 固定 WeRSS 镜像会输出正文相关 SQL 参数；用户已接受仅本机 Docker 日志的剩余风险，并采用 2 × 2 MB 轮转、最小本机访问、不外传/不备份控制。
7. 最小后续选择：由镜像上游提供关闭 SQL 语句及参数输出的受支持开关，或修复并发布新的固定镜像摘要；之后更新固定摘要、重跑正文接口契约、触发不含真实正文的受控数据库操作验证新日志窗口，再开始真实 shadow。禁止以 Docker `none` 日志驱动或丢弃 stdout 作为修复。

## 用户接受日志风险后的范围调整

- 保留官方固定摘要，不构建内部镜像。官方 SQL 参数/正文日志风险由用户明确接受，控制为仅本机 Docker Desktop 最小访问、不接外部日志、不进工单、不纳入备份，轮转改为 2 × 2 MB，并持续关注上游开关。
- 目标拆成两层：9 个公众号全部启用采集；下游仅湖南三尖农牧公司进入 clean/analyze，其余 8 个只采集。两层分别验收采集完整率/去重/延迟与湖南正文/回退/分析。
- 安全配置未执行：当前 `MysqlArticleRawRepo` 对所有新 raw 无条件创建 `clean_article`，没有下游白名单。启用 9 账号会误消费其余 8 个；已在设计和计划新增实现任务，未用手工删任务规避。
- WeRSS 数据库已有 9 个 Feed；“江西九江褐壳蛋”已由用户确认，与实际 Feed 名一致。
- 湖南真实 Feed 核验：HTTP 200、25 条；locator 兼容整改后 25/25 可提取，真实 `/article/{locator}` 路由已接入。
- Compose 已将官方容器日志轮转从 5 × 10 MB 缩短为 2 × 2 MB，并以同一官方固定摘要强制重建。重建后实际 LogConfig 为 `json-file`、`max-file=2`、`max-size=2m`，容器恢复 `healthy`；数据卷和镜像摘要未改变。
- WeInsight 九账号来源未配置：下游白名单与湖南 locator 两项实现缺口仍在，执行配置会造成误消费或只能网页回退，不满足新范围设计。
- 调整后验证：文档/采集覆盖测试 60 passed；全量 1669 passed、2 skipped、1 个第三方弃用警告；Compose config、diff check、UTF-8 检查均通过，最终 WeRSS `healthy`。

## 江西账号名称确认

- 用户确认正确名称为“江西九江褐壳蛋”，与 WeRSS Feed 映射一致。
- 设计、实施计划、运行手册和 POC 记录中的旧误写及待确认措辞已移除，并增加门禁防止旧名称回归。

## Task 6 真实运行启动尝试

- 配置核对：运行配置为 `content_mode: shadow`；数据库共 9 个目标来源启用采集，仅湖南三尖农牧公司 `downstream_clean_enabled=1`。
- 九账号安全单轮：attempted 9、success 9、failed 0、首次 raw insert 81、duplicate 5、task 0；其余 8 个本轮未新增 clean/analyze 任务，article UI lock 为 0。
- 湖南首次采集因首次接入只保留最近 24 小时且当前条目均早于窗口，HTTP 成功但 raw 0。首次成功建立游标后按正常路径执行湖南第二轮：success 1、insert 25、duplicate 0、clean task 25；未修改发布时间或伪造数据。
- shadow 闭环：湖南 clean 25/25 success、analyze 25/25 success、analysis 25 行、最终任务积压 0、article UI lock 0。组合命令超时后先查数据库确认 analyze 18 success/7 pending，再只补跑一次，最终完成，未重复启动批次。
- Shadow 差异已归因为网页侧受限降级响应并通过复审；随后按门禁切换 `werss_first`。
- collector 与 pipeline worker 均为单实例常驻，数据库 heartbeat 为 running。

## Task 6 POC 正式启动

- Fresh 全量门禁：1702 passed、2 skipped；启动前 `git diff --check` 通过。
- dev 配置已从 `shadow` 切换为 `werss_first`。真实契约调试发现 provider 仍请求旧 `/views/article/{locator}` 并得到结构化 `werss_not_found`；以失败契约测试复现后，最小修复为官方实际 `/article/{locator}`。相关测试 80 passed。
- collector 与 pipeline worker 均以隐藏窗口、正确环境变量单实例常驻；WeRSS 为 `healthy`。
- 受控重处理一条湖南记录后，clean/analyze 均 success、`content_source=werss`、analysis 记录存在；9 个采集账号 pending/processing 均为 0，其余 8 个没有下游消费，article UI lock 为 0。
- 24 小时观察开始：2026-07-12 13:08:14 +08:00；截止：2026-07-13 13:08:14 +08:00。当前状态仅为“进行中”，观察期尚未结束，不宣称通过。
- 官方固定镜像日志风险继续按用户接受边界控制：日志只在本机 Docker Desktop，轮转 2 × 2 MB，不接外部日志、不进工单或备份。

## WeRSS 故障回退与恢复闭环

- 基线：collector/pipeline 各 1 个，article UI lock 0；湖南 clean/analyze 无积压。
- 停止 WeRSS 后，受控重置一条湖南既有任务：clean/analyze 均 success、`content_source=web`、analysis 记录存在。collector 进程与 collector/pipeline heartbeat 均保持 running，群链路未被停止或改配，article UI lock 0。
- 随即恢复 WeRSS 并轮询到 `healthy`；受控重置另一条湖南任务后，clean/analyze 均 success、`content_source=werss`、analysis 记录存在。
- 闭环结束时 clean/analyze 全部为 success、积压 0、article UI lock 0、WeRSS healthy。24 小时观察的开始/截止时间未改变，状态仍为进行中。
