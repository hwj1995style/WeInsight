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
