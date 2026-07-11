# Task 6 Report: Collector Worker 装配和微信健康隔离

## 结果

- 托管 Collector 的 article 入口已改用 `RssArticlePollingRunner` 与 `RssArticleCollectService`。
- article 运行时不再装配公众号 RPA、UI lock、截图、进度仓储或核心群到期 Provider；group 仍保留原 RPA、截图和 UI lock。
- 微信健康门禁只作用于 `PipelineType.GROUP`；ARTICLE 不调用微信健康检查。
- article snapshot 现在携带并校验 `feed_url`、`source_type=rss` 与 `request_timeout_seconds`，下游 raw、清洗、解析和分析链路保持不变。
- `ArticlePipelineConfig` 和四套 YAML 已移除 article UI/RPA/路由配置，新增 RSS 并发、响应大小上限和精确的 `127.0.0.1:8001` 私网白名单。

## TDD 证据

### RED

命令：

```text
pytest tests/test_managed_collector_worker.py tests/test_pipeline_isolation.py tests/test_config.py -q
```

结果：`2 failed, 93 passed`。预期失败为：

- `ManagedCollectorWorker` 缺少 `can_claim`。
- `ArticlePipelineConfig` 缺少 `rss_max_concurrency`。

### GREEN

命令：

```text
pytest tests/test_managed_collector_worker.py tests/test_config.py tests/test_pipeline_isolation.py -v
```

结果：`95 passed in 1.98s`。

完整回归：

```text
pytest -q
```

结果：`1696 passed, 2 skipped, 1 warning in 21.67s`。唯一 warning 是 feedparser 已知的 `updated` 到 `published` 临时兼容映射弃用提示。

## 自审

- `git diff --check` 通过。
- RSS runner 装配对象上无 `lock_repo` 和 `screenshot_root`，测试明确覆盖。
- real RPA probe 只检查 group RPA 能力，不再初始化公众号 RPA。
- 精确 WeRSS 例外为单一 host:port，RSS 重定向仍沿用 Feed client 的默认重新校验规则。

## Blocking Review 修复（第二轮）

- `_source_creation_config` 的 article 锁定查询和 canonical snapshot 已补齐 `feed_url`、`source_type`、`request_timeout_seconds`；新增测试从真实 source snapshot 一直解析为 RSS runner target。
- `claim_next_due` 新增 SQL 级 `pipeline_types` 过滤。Worker 在 claim 前读取微信健康；异常时只允许 ARTICLE，GROUP 不创建 run、不获取 lease、仍保持 due 状态。
- RSS 配置新增正整数和非空精确 `host:port` 校验，拒绝裸 host、非法端口及带空白条目。
- `rss_max_response_bytes` 现注入 `RssFeedClient` 并实际限制解压后响应体。
- `rss_max_concurrency` 现构造共享 `BoundedSemaphore`，限制 RSS collect 临界操作；现有 job/run DB 状态机继续串行，避免并行 target 状态写入竞态。
- runtime factory 根据每个 target URL 精确匹配白名单 endpoint，不再索引并忽略其他配置项。

第二轮 RED：`10 failed, 39 passed`，失败分别对应 snapshot、claim 前过滤、配置校验和 Feed client 上限注入。

第二轮 GREEN：focused `178 passed`；完整回归 `1707 passed, 2 skipped, 1 warning in 23.26s`。

## Blocking Review 修复（第三轮）

- 私网例外改为按 target URL 精确匹配；公网或端口不匹配的 Feed 向 `RssFeedClient` 传入 `allowed_endpoint=None`，继续走默认 SSRF 校验。
- endpoint 规范化支持 IPv6 bracket 表示，例如配置 `[::1]:8001` 精确映射为 client endpoint `("::1", 8001)`。
- `RssArticlePollingRunner` 新增 `max_concurrency`，在 Feed target batch 边界使用 `ThreadPoolExecutor` 并行独立 target；聚合按输入顺序确定，线程池不涉及 UI 或 Collector run/target 状态变更。
- runtime factory 将 `rss_max_concurrency` 传给 runner。并发测试使用阻塞 fake feed 证明峰值大于 1 且不超过配置 2。

第三轮 RED：新增并发与 endpoint 测试初始 `5 failed`。GREEN：runner/worker focused `64 passed`。
