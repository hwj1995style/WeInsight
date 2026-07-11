# 阶段五 Task 1 实施报告：生产 TLS 与 Worker 配置

## 交付结论

阶段五 Task 1 已按正式计划、设计和实施简报完成。开发环境继续使用 loopback、非安全 Cookie、空 TLS 路径和 fake collector；生产示例改为显式私网 IP、环境变量 TLS 路径、安全 Cookie 和 real collector，并保持 tick=5、heartbeat=10、lease=120。

本任务没有创建证书、读取证书或私钥内容、检查证书文件存在性/ACL，也没有注册 Windows 任务或启动 Worker。

## 配置契约

`WebConfig` 新增 `tls_certfile` 和 `tls_keyfile`，均为 `str | None`，并在配置构造阶段执行 fail-closed 校验：

- TLS 证书与私钥路径必须同时配置或同时为空；
- `secure_cookie=true` 时两项必须同时存在；
- 有值路径必须非空、前后无空白；
- 路径拒绝全部 Unicode `C*` 类字符，包括 C0/C1、零宽、双向控制和代理字符；
- 校验异常只包含固定字段/规则文案，不包含私钥内容。

`AppConfig.env` 严格限定为 `dev` 或 `prod`，未知值、大小写错误、尾随空白和空值均拒绝，避免环境名拼写错误绕过生产安全门禁。

生产 `web.host` 必须是明确的 RFC1918 IPv4 或 IPv6 ULA 地址。配置拒绝空值、主机名、loopback、`0.0.0.0`、`::`、公网、多播及其他非私网地址；开发配置继续允许 `127.0.0.1`。该检查只解析地址，不进行网络探测。

## Web 启动与依赖边界

Web 入口在 `create_app`、管理员 bootstrap 和数据库初始化之前检查安全 Cookie/TLS 组合，缺失时抛出固定错误：

`secure_cookie requires TLS certificate and key`

Uvicorn 固定接收 `ssl_certfile` 和 `ssl_keyfile`；开发环境将两个 `None` 原样传入，生产环境只传递配置中的路径字符串。入口不打开 TLS 文件、不输出路径对应的文件内容。

fresh-process import 测试发现原有 Web 路由会通过 runtime monitor 间接导入 `app.rpa.desktop_probe`。为保持 Web import 无 Worker/RPA 副作用，本任务做了最小依赖整理：

- 将 `WechatHealthStatus` 提取到 `app/domain/wechat_health.py`；
- `desktop_probe` 从 domain 导入并继续 re-export，保持旧 import 兼容；
- runtime monitor service/repo 改为依赖 domain；
- `create_app` 只在构建缺省 runtime monitor 依赖时局部导入 service/repo。

独立子进程测试确认仅导入 `app.web.__main__` 不加载 main、Worker 或 RPA，也不执行配置加载、应用构建、bootstrap 或 Uvicorn。

## TDD 与复审

先观察 RED，再做最小实现，覆盖：

- dev TLS null/fake 和 prod env TLS/real；
- TLS 成对、secure 必需、空白及 Unicode 控制字符拒绝；
- prod 私网地址接受与 wildcard/public/multicast/empty 拒绝；
- 未知环境名 fail closed；
- 入口校验先于应用构建和 bootstrap；
- Uvicorn TLS 参数与 dev `None` 行为；
- 固定错误不泄漏私钥标记；
- fresh Web import 不加载 Worker/RPA；
- 安全 Cookie 既有 auth 行为和健康状态枚举兼容。

独立初审发现并关闭两个 Important：Unicode C1/Cf/bidi 路径字符漏拒，以及未知 `app.env` 可绕过生产私网门禁。复审确认两个问题均关闭，未发现新的 Critical 或 Important，Assessment 为 Ready。

复审保留一个非阻塞 Minor：真实配置缺失 TLS 时会先由 `WebConfig` 抛同文案 `ValueError`，入口固定 `RuntimeError` 主要覆盖已构造但无效的 config；两条路径都发生在应用/数据库初始化前，且不泄漏敏感内容。

## 最终验证

- 最终配置与入口专项：`42 passed`
- Unicode/env RED→GREEN：`10 passed`
- 配置、入口、auth、desktop/runtime monitor 相关回归：`108 passed, 1 skipped`
- Web/auth 扩展回归：`306 passed`
- 最终全量：`1557 passed, 1 skipped`
- `python -m compileall -q app tests`：通过
- `git diff --check`：通过
- 改动文件严格 UTF-8 解码：通过
- 生产 YAML 私钥/密码内容扫描：通过，仅保留明确环境变量占位符

## 后续衔接

- 部署任务负责准备证书文件、限制私钥 ACL，并在启动前检查文件存在性和权限。
- 生产配置必须显式提供 `WEINSIGHT_WEB_HOST`、`WEINSIGHT_TLS_CERTFILE`、`WEINSIGHT_TLS_KEYFILE` 和数据库密码环境变量。
- 本任务只提供 TLS 启动参数；Windows 任务、Worker 注册、预检和回滚由阶段五后续任务完成。
