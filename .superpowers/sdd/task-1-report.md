# Task 1 实施报告：WeRSS 只读目录同步配置契约

## 完成范围

- `ArticlePipelineConfig` 新增 `sync_interval_minutes`、`werss_catalog_base_url`、`werss_access_key`、`werss_secret_key`。
- 同步周期仅接受非布尔整数且不得小于 10。
- 目录端点仅接受精确值 `http://127.0.0.1:8001`。
- AK/SK 必须为非空字符串，且不得包含 Unicode 控制类字符。
- dev、e2e、poc、prod example 四份 YAML 均只通过指定环境变量引用 AK/SK。
- 未修改旧 RPA 代码或配置边界之外的运行逻辑。

## RED 失败证据

在仅添加需求测试、尚未修改生产配置模型时运行：

```text
python -m pytest tests/test_config.py -q
FFFF.................................................. [100%]
4 failed, 50 passed in 1.01s
```

首个失败为 `AttributeError: 'ArticlePipelineConfig' object has no attribute 'sync_interval_minutes'`；三个参数化边界用例均因构造函数不接受 `sync_interval_minutes` 而失败。失败原因与缺少新配置契约一致。

## GREEN 命令与结果

```text
python -m pytest tests/test_config.py -q
...................................................... [100%]
54 passed in 1.91s
```

## 变更文件

- `app/core/config.py`
- `config/config.dev.yaml`
- `config/config.e2e.yaml`
- `config/config.poc.yaml`
- `config/config.prod.example.yaml`
- `tests/test_config.py`
- `.superpowers/sdd/task-1-report.md`

## 自检

- `git diff --check`：通过，无空白错误。
- `rg -n "werss_(access|secret)_key:" config`：四份目标 YAML 的 AK/SK 均为 `${WEINSIGHT_WERSS_ACCESS_KEY}` / `${WEINSIGHT_WERSS_SECRET_KEY}`，无明文凭据。
- `git diff --name-only`：仅涉及 brief 指定的实现/测试/配置文件及本报告，未触碰旧 RPA。
- 已确认当前历史保留基线测试修复提交 `9aaf4bd` 和 `017ae57`，未改写或回退。

## Concerns

无已知阻塞或遗留 concerns。Git 在 Windows 工作区提示未来可能将 LF 转换为 CRLF，此为仓库行尾策略提示，不影响测试或配置契约。

## Review fix：严格边界回归测试

根据 `task-1-review.md` 补充以下覆盖：

- 非精确目录端点：localhost、尾随路径、查询参数、用户信息。
- AK/SK 非法值：空字符串、首尾空白、换行控制字符、零宽格式字符。
- `config/config.e2e.yaml` 与 `config/config.poc.yaml` 的加载、环境变量展开及 dataclass 构造。

### Review fix RED

测试先行运行：

```text
python -m pytest tests/test_config.py -q
..........FF........................................................     [100%]
2 failed, 66 passed in 1.01s
```

两个失败分别为 `werss_access_key` 与 `werss_secret_key` 的首尾空白值未抛出 `ValueError`。其他新增安全边界用例在既有实现上通过。

### Review fix GREEN

最小修复为要求 AK/SK 与其 `strip()` 结果完全一致。随后运行：

```text
python -m pytest tests/test_config.py -q
....................................................................     [100%]
68 passed in 0.92s
```

### Review fix 变更与 concerns

- 修改：`tests/test_config.py`、`app/core/config.py`、`.superpowers/sdd/task-1-report.md`。
- 未修改 YAML、旧 RPA 或其他运行逻辑。
- 无遗留 concerns。
