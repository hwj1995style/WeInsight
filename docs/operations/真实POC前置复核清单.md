# 真实POC前置复核清单

本文档用于第八阶段 Task 57。目标是在使用实际账户前，先完成授权、配置、隐私、回滚和人工值守复核，确保第一轮真实 POC 只在最小风险面内执行。

## 1. 验证范围

第一轮真实 POC 只允许：

```text
1 个实际授权公众号/订阅号
1 个实际授权核心群
手动命令触发
有人值守
不注册 Windows 计划任务
不启用后台常驻 article 调度
AI 仍保持 dry-run
```

不允许：

```text
一次性接入多个公众号/订阅号
无人值守长时间运行
绕过 wechat_ui_lock 操作微信窗口
长期保存文章正文
把 AI 输出写回 group/article 链路状态
```

## 2. 授权确认

实际授权公众号/订阅号：

```text
账号名称：
账号类型：公众号 / 订阅号
授权负责人：
允许采集范围：当天发布数据
是否允许运行时临时读取正文：
是否允许保存摘要和结构化特征：
是否禁止长期保存文章正文：是
```

实际授权核心群：

```text
群名称：
授权负责人：
是否为核心群：是
允许采集范围：群内授权业务消息
是否允许生成群日报：
是否需要额外脱敏：
```

## 3. 桌面和微信检查

执行前确认：

```text
微信 PC 4.1.8.107
微信自动更新已关闭
微信已登录
微信窗口可见
桌面未锁屏
当前人工值守人员在场
```

检查命令：

```powershell
python -m app.main wechat-health --config config/config.dev.yaml
```

通过标准：

```text
wechat-health 返回 ok
版本符合 4.1.8.107
窗口未卡死
```

## 4. 数据库和配置检查

开发 POC 使用开发库；生产 POC 使用独立生产库。执行前必须确认当前配置文件：

```powershell
python -m app.main check-config --config config/config.dev.yaml
```

检查项：

```text
核心群不超过5个
公众号/订阅号不超过20个
article 链路每次只处理 1 个账号
只采集当天发布数据
dedup_key=article_hash
article.browser_executable_path=auto 或明确 chrome.exe 路径
ui_resource.mode=exclusive
ui_resource.group_priority=true
```

## 5. AI dry-run 检查

AI 不参与第一轮真实 POC 结论，只允许 dry-run：

```powershell
python -m app.main ai-analysis-sample --source summary_daily_report --date 2026-07-07 --dry-run
```

通过标准：

```text
AI 仍保持 dry-run
model_called=0
输出不包含聊天正文、文章全文、HTML 或具体文章链接
```

## 6. 运行时数据边界

公众号/订阅号正文策略：

```text
正文只运行时读取
不长期保存文章正文
落库只保存摘要、标签、关键词命中、表格结构化特征和 OCR 表格结构化特征
日志、CLI、截图、日报和汇总日报不输出文章全文
```

微信群消息策略：

```text
仅采集实际授权核心群
清洗后执行脱敏
日报只输出聚合统计和规则摘要
失败任务只输出错误摘要和任务元数据
```

## 7. 手动命令顺序

先做健康检查：

```powershell
python -m app.main wechat-health --config config/config.dev.yaml
python -m app.main group-runtime-summary --config config/config.dev.yaml --limit 5
python -m app.main trial-monitor-report --config config/config.dev.yaml --hours 24
```

再做单账号或单群 POC。第一轮不得同时启动长时间双链路调度。

## 8. 暂停条件

出现以下任一情况，立即暂停真实 POC：

```text
微信掉线
锁屏
窗口卡死
UI 锁长时间未释放
核心群等待超过阈值
任一账号连续失败 3 次
CLI 输出出现聊天正文、文章全文、HTML 或具体文章链接
AI 输出不再是 dry-run
```

暂停后优先恢复群链路，再决定是否继续 article 链路。

## 9. Go / No-Go

Go：

```text
实际授权公众号/订阅号和实际授权核心群均已确认
微信健康检查通过
AI 仍保持 dry-run 且 model_called=0
数据库和配置检查通过
回滚入口已确认
人工值守人员已在场
```

Watch：

```text
存在可定位失败，但不影响核心群
article 链路失败可关闭并恢复到手动单账号模式
日报质量需要人工复盘
```

No-Go：

```text
授权范围不明确
微信健康检查失败
核心群等待超过阈值
AI 不再是 dry-run
无法确认正文只运行时读取
无法确认不长期保存文章正文
```

## 10. 复核签字

```text
复核日期：
复核人员：
实际授权公众号/订阅号：
实际授权核心群：
Go / Watch / No-Go：
备注：
```
