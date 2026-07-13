# Task 3 实施报告：WeRSS 只读清单客户端

## 状态

已实现固定 WeRSS 清单端点的只读客户端；未实现任何写接口。

## 实现范围

- 新增 `app/integrations/werss_catalog.py`：
  - 固定 `GET /api/v1/wx/mps`，`limit=100`，显式递增 `offset`。
  - 使用 `Authorization: AK-SK <AK>:<SK>`，并禁止自动重定向。
  - 单响应正文上限 1 MiB、清单上限 1000 项。
  - 校验响应 envelope、分页元数据、总数稳定性、字段类型和值、空白 ID/名称和重复 ID。
  - 仅输出不可变的 `WeRSSCatalogItem(source_id, name, enabled)`。
  - 将失败收敛为五个稳定错误码，不携带凭据、异常详情或响应正文。
- 新增 `tests/test_werss_catalog_client.py`，覆盖 HTTP、分页、鉴权、大小、数量、重复 ID、字段契约、总数不一致和敏感输出边界。
- 更新 `tests/test_sensitive_output_guard.py`，静态守卫客户端不得记录日志或读取 `response.text`。

## TDD 证据

### RED 1

命令：

```text
python -m pytest tests/test_werss_catalog_client.py tests/test_sensitive_output_guard.py -q
```

结果：测试收集失败，`ModuleNotFoundError: No module named 'app.integrations'`，符合功能模块尚不存在的预期。

### GREEN 1

实现最小客户端后，同一命令结果为 `27 passed`。

### RED 2

补充空白 ID、空白名称、浮点 `status` 契约测试后，客户端测试出现 3 个预期失败。

### GREEN 2

收紧字段校验后，客户端与敏感输出测试结果为 `30 passed`。

## 错误码映射

- 401/403：`werss_catalog_auth_failed`
- `httpx.TimeoutException`：`werss_catalog_timeout`
- 网络错误、重定向、HTTP 4xx/5xx：`werss_catalog_unavailable`
- 超限、畸形 JSON/envelope/page/字段、重复 ID、超过 1000 项：`werss_catalog_invalid`
- 总数变化、分页提前结束或最终数量不一致：`werss_catalog_incomplete`

## 自检

- 只存在 GET 请求；无 POST/PUT/PATCH/DELETE 或数据库写入。
- 异常文本只有稳定错误码。
- 实现中无日志调用、无 `response.text`、无响应正文拼入异常。
- 未输出 AK/SK 或响应正文。
- `git diff --check` 通过（仅有 Git 的 LF/CRLF 工作区提示）。
