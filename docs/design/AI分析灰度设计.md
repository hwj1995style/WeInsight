# AI分析灰度设计

本文档用于第七阶段 Task 54。目标是在无 AI 小规模试运行稳定后，设计一个默认关闭、输入受控、输出隔离、可随时回退的 AI 灰度能力。

## 1. 背景与现状

当前系统已经具备两条独立数据链路：

```text
微信群链路：采集、清洗、规则分析、群日报
公众号/订阅号链路：链接采集、解析、清洗、规则分析、文章日报
汇总日报：只读聚合群日报和文章日报
```

第七阶段前半段先验证无 AI 小规模试运行、双链路巡检和日报质量。AI 能力只能在这些链路稳定后灰度启用，且默认关闭 AI。AI 灰度不改变现有采集、清洗、分析、日报任务状态，不占用微信 PC UI，不获取 `wechat_ui_lock`。

## 2. 目标与非目标

目标：

```text
默认关闭 AI
建立输入白名单
记录 prompt 版本和模型版本
隔离 AI 输出和失败状态
支持随时关闭并回退到规则分析
```

非目标：

```text
不替代现有规则分析
不自动修改 group/article 链路任务状态
不参与微信 UI 自动化
不发送 raw 原文、文章全文、HTML
不在 Task 54 调用外部模型
```

## 3. 影响范围

影响范围：

```text
后续 AI 分析配置
后续 AI 输入 payload 构造
后续 AI 输出记录
后续 AI dry-run POC
```

不影响范围：

```text
微信群采集、清洗、规则分析和群日报生成
公众号/订阅号采集、解析、规则分析和文章日报生成
汇总日报只读聚合逻辑
微信 UI 锁
MySQL 原始数据表
```

## 4. 输入白名单

AI 灰度只读输入必须来自已脱敏、已结构化或已汇总的数据。只允许输入摘要、结构化特征、脱敏字段。

允许输入：

```text
日报标题
日报日期
群链路统计计数
article 链路统计计数
规则分析摘要
主题标签
关键词命中计数
供需计数
联系方式脱敏后的计数
表格解析后的结构化字段
OCR 表格解析后的结构化字段
人工质量评分
```

禁止输入：

```text
raw 原文
文章全文
HTML
完整聊天消息
完整联系方式
具体文章链接
截图原图
未脱敏错误堆栈
```

输入构造必须先经过白名单过滤。白名单之外的字段即使存在于上游对象中，也不得进入 AI payload、日志、CLI 输出或导出文件。

## 5. 输出模型

AI 输出必须独立于 group/article 原链路保存。建议首版输出结构：

```text
source：输入来源，例如 summary_daily_report
source_date：业务日期
prompt_version：prompt 版本
model_version：模型版本
input_field_count：输入字段数量
status：dry_run / success / failed
summary：AI 生成的短摘要
suggestions：AI 生成的建议列表
error_summary：失败摘要
create_time：生成时间
```

输出约束：

```text
AI 失败不得回写 group/article 链路状态
AI 输出不得覆盖群日报、文章日报或汇总日报
AI 输出不得创建、重置或重试 group/article 任务
AI 输出不得携带原文、全文、HTML 或具体文章链接
```

## 6. 权限和配置模型

建议新增独立配置文件：

```text
config/ai_analysis.yaml
```

配置原则：

```text
enabled 默认 false
dry_run 默认 true
provider 默认 none
prompt_version 必填
model_version 必填
allowed_sources 使用白名单
max_input_chars 设置上限
```

权限原则：

```text
AI 运行账号只读日报和结构化分析结果
AI 运行账号不具备更新 group/article 任务表的权限
AI 运行账号不读取原始正文表
AI 运行账号不访问微信 UI 锁表的写权限
```

## 7. 后端实现方案

后续 Task 55 采用 dry-run only 的最小 POC：

```text
读取安全来源
按白名单构造 AI 输入 payload
输出 payload 形状和字段数量
不调用外部模型
不写回 group/article 链路
不占用微信 UI
```

建议模块边界：

```text
app/domain/ai_analysis.py：输入白名单、payload 构造、结果模型
app/pipelines/ai_analysis_service.py：读取安全输入并生成 dry-run 结果
app/main.py：ai-analysis-sample --dry-run
app/security/output_policy.py：CLI 输出字段 allowlist
```

失败处理：

```text
配置未开启时返回 disabled
输入字段不在白名单时丢弃并计数
安全输入为空时返回 no_safe_input
dry-run 成功不调用模型
外部模型失败只写 AI 自身失败状态
```

## 8. 前端影响

当前项目没有前端后台。若后续增加管理界面，必须拆分以下开关：

```text
群链路开关
article 链路开关
AI 分析开关
AI dry-run 开关
```

前端不得提供一个同时启停 group、article 和 AI 的合并开关。AI 页面只能展示安全输入摘要、prompt 版本、模型版本、状态和失败摘要。

## 9. 测试与回归方案

Task 54 文档回归：

```powershell
pytest tests/test_ai_gray_design_docs.py tests/test_phase_seven_plan_docs.py -q
```

后续 Task 55 实现回归：

```powershell
pytest tests/test_ai_analysis_service.py tests/test_main.py tests/test_sensitive_output_guard.py -q
pytest -q
rg -n "\?\?" README.md docs app tests sql
```

必须覆盖：

```text
默认关闭 AI
不发送 raw 原文、文章全文、HTML
只允许输入摘要、结构化特征、脱敏字段
prompt 版本和模型版本可追踪
AI 失败不得回写 group/article 链路状态
AI dry-run 不调用外部模型
AI CLI 输出不包含正文、全文、HTML 或具体文章链接
```

## 10. 风险与分阶段落地建议

风险：

```text
输入过滤不严导致敏感内容进入 AI payload
AI 输出被误认为确定性结论
AI 失败误伤 group/article 链路状态
模型或 prompt 版本不可追踪导致结果不可复盘
```

分阶段落地：

```text
第一阶段：只做设计和输入白名单
第二阶段：dry-run POC，只输出安全 payload 形状
第三阶段：人工审核 AI 输出，不自动进入日报
第四阶段：连续复盘达标后，再评估是否把 AI 摘要作为独立附录
```

暂停条件：

```text
发现输入包含 raw 原文、文章全文或 HTML
发现 CLI 或日志输出具体文章链接
AI 失败影响 group/article 任务状态
prompt 版本或模型版本缺失
人工复盘低于质量阈值
```
