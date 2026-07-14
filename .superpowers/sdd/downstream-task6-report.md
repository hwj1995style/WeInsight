# Task 6 真实下游操作报告

执行时间：2026-07-14（Asia/Shanghai）

## 操作边界

- 用户已明确授权本次真实操作。
- 写操作仅通过 `ArticleDownstreamService` 与 `MysqlArticleDownstreamRepo` 执行。
- 未使用裸 SQL 修改业务表；SQL 仅用于前后只读核验。
- 仅执行 `missing_only`，未执行 `force_analyze`。
- 报告不包含数据库密码、Session/CSRF token、文章 URL、正文或完整文章哈希。

## 只读基线（2026-07-10 至 2026-07-14，含首尾）

WeRSS 当前目录操作集为 9 个 active 公众号。开关状态：8 个关闭，湖南三尖农牧公司已开启。

| 公众号 | 开关 | raw | clean | analysis | price item |
|---|---:|---:|---:|---:|---:|
| 贵阳鸡蛋价格 | 0 | 9 | 0 | 0 | 0 |
| 家美鲜鸡蛋 佳美鲜 | 0 | 19 | 0 | 0 | 0 |
| 河北馆陶鸡蛋报价 | 0 | 4 | 0 | 0 | 0 |
| 河南金咕咕蛋品 | 0 | 3 | 0 | 0 | 0 |
| 江西九江褐壳蛋 | 0 | 4 | 0 | 0 | 0 |
| 成都鸡蛋价格 | 0 | 6 | 0 | 0 | 0 |
| 蓝天禽蛋联盟 | 0 | 3 | 0 | 0 | 0 |
| 河北辛集城方蛋品 | 0 | 3 | 0 | 0 | 0 |
| 湖南三尖农牧公司 | 1 | 5 | 5 | 5 | 0 |
| 合计 | — | 56 | 5 | 5 | 0 |

基线任务：`clean_article success=5`、`analyze_article success=5`，其他状态为 0。

“一箱蛋”在 `wechat_public_account_config` 中无记录，因此不在当前 WeRSS 目录或操作集。其有效下游权限为默认拒绝（0）；不存在可被本次服务调用更新的来源 ID。

## 真实操作与幂等证据

1. 从当前 WeRSS 目录只读取得 9 个来源 ID。
2. 逐个调用 `ArticleDownstreamService.set_processing_enabled(source_id, True)`，后置核验 9/9 开启。
3. 调用 `scope=enabled`、`mode=missing_only`、日期 2026-07-10 至 2026-07-14。

第一次摘要：

```text
matched_article_count=56
clean_task_created_count=51
clean_task_recovered_count=0
analyze_task_created_count=0
analyze_task_recovered_count=0
existing_result_skipped_count=5
running_task_skipped_count=0
out_of_scope_skipped_count=0
```

立即以完全相同参数再次调用：

```text
matched_article_count=56
clean_task_created_count=0
clean_task_recovered_count=0
analyze_task_created_count=0
analyze_task_recovered_count=0
existing_result_skipped_count=5
running_task_skipped_count=51
out_of_scope_skipped_count=0
```

第二次没有新建或恢复任务，证明本次提交幂等。

## Worker 与监控

- 发现既有 pipeline worker PID `20364`，未启动第二实例。
- 最终状态：`running`；最新心跳 `2026-07-14 20:37:10`；无错误摘要。
- 监控过程中任务持续从 pending 转为 success，无 failed 或异常停滞。
- 最终窗口任务：`clean_article success=56`、`analyze_article success=56`；pending/running/failed 均为 0。

## 后置核验

| 公众号 | 开关 | raw | clean | analysis | price item | analysis 最新日 | price 最新日 |
|---|---:|---:|---:|---:|---:|---|---|
| 贵阳鸡蛋价格 | 1 | 9 | 9 | 9 | 1 | 2026-07-14 | 2026-07-14 |
| 家美鲜鸡蛋 佳美鲜 | 1 | 19 | 19 | 19 | 0 | 2026-07-14 | — |
| 河北馆陶鸡蛋报价 | 1 | 4 | 4 | 4 | 1 | 2026-07-14 | 2026-07-14 |
| 河南金咕咕蛋品 | 1 | 3 | 3 | 3 | 0 | 2026-07-14 | — |
| 江西九江褐壳蛋 | 1 | 4 | 4 | 4 | 0 | 2026-07-14 | — |
| 成都鸡蛋价格 | 1 | 6 | 6 | 6 | 0 | 2026-07-14 | — |
| 蓝天禽蛋联盟 | 1 | 3 | 3 | 3 | 0 | 2026-07-14 | — |
| 河北辛集城方蛋品 | 1 | 3 | 3 | 3 | 0 | 2026-07-14 | — |
| 湖南三尖农牧公司 | 1 | 5 | 5 | 5 | 0 | 2026-07-14 | — |
| 合计 | — | 56 | 56 | 56 | 2 | 2026-07-14 | 2026-07-14 |

全部 56 篇 raw 均已有 clean 与 analysis。2 条报价明细来自贵阳鸡蛋价格和河北馆陶鸡蛋报价；其余文章分析成功但未抽取到有效报价，这不是任务失败。

“一箱蛋”后置检查仍无配置记录、无来源 ID、未进入操作范围，默认拒绝语义保持为 0。
