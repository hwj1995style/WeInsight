from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/design/公众号订阅号最多20账号扩容设计.md")


def test_article_20_account_expansion_design_documents_boundaries() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "允许进入最多 20 个账号扩容设计",
        "不允许直接一次性启用 20 个账号",
        "max_accounts_per_ui_slice=1",
        "max_articles_per_round=1",
        "poll_interval_minutes=60",
        "每批最多新增 4 个账号",
        "取链后关闭微信内置浏览器和公众号单聊窗口",
        "直接启用最多 20 个账号：No-Go",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_documents_gates() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "article-rpa-probe status=ok",
        "link_count>=1",
        "browser_window_present=0",
        "account_window_present=0",
        "article_backlog_count=0",
        "group_backlog_count=0",
        "ui_lock_timeout_count=0",
        "model_called：0",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_records_batch_one_probe_results() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "福建闽融鸡蛋报价平台：status=failed account_found=1 link_count=0",
        "信立鸡蛋当日价格：status=failed account_found=1 link_count=0",
        "福建闽融鸡蛋报价平台：status=ok account_found=1 link_count=1",
        "信立鸡蛋当日价格：status=ok account_found=1 link_count=1",
        "上海禽蛋价格综合报价：status=ok account_found=1 link_count=1",
        "上海禽蛋价格综合报价：status=needs_recheck account_found=1 link_count=0",
        "上海禽蛋价格综合报价曾出现 link_count=1 但误入非当天正文的风险",
        "不允许为了匹配当天日期下探第二条或更低行",
        "上海蛋凰价格综合报价",
    ]:
        if keyword == "上海蛋凰价格综合报价":
            assert keyword not in content
        else:
            assert keyword in content


def test_article_20_account_expansion_design_records_batch_one_controlled_collect_gate() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "2026-07-09 Batch 1 Controlled Collect 推进记录",
        "2026-07-09 信立复核恢复与闭环记录",
        "上海禽蛋价格综合报价：因 needs_recheck 已禁用",
        "福建闽融鸡蛋报价平台：raw=1，clean=1，analysis=1，daily_report=1",
        "信立鸡蛋当日价格：用户截图确认 2026年7月9日 09:11 当日正文已发布",
        "上海禽蛋价格综合报价：用户截图确认列表第一条为 2026年7月8日",
        "信立鸡蛋当日价格：collect-article-once success_count=1 failed_count=0",
        "信立鸡蛋当日价格：raw=1，clean=1，analysis=1，daily_report=1，article_count=1",
        "信立鸡蛋当日价格：route cache status=active，failure_count=0",
        "当时判断（已被第 12 节 no-data 验证更新）",
        "全账号无当日正文 no-data 流程门禁",
        "所有公众号账号的正常 no-data 结果",
        "上海只是本轮真实验证样本，不是账号特例",
        "任意公众号账号在目标日期无文章时",
        "点击第一条正文读取详情页发布时间",
        "success_count=0，failed_count=0，skipped_count=1，link_count=0",
        "WECHAT_ARTICLE_NO_TODAY_ARTICLE",
        "修正复测 collect-article-once --account-name 上海禽蛋价格综合报价",
        "修正复测 wechat_article_collect_log 最新记录 id=36",
        "wechat_article_collect_progress：crawl_date=2026-07-09，stage=done，status=success",
        "不需要等待某个公众号当日正文实际发布后再让流程继续",
        "Batch 1 全候选：可进入受控小窗口，不再因任一账号当天未发文阻断",
        "article-task-failed-list --limit 20：no rows",
        "article-runtime-metrics：collect_skipped_count=1",
        "直接启用最多 20 个账号：仍为 No-Go",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_records_universal_no_data_window() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "2026-07-09 Batch 1 通用 no-data 受控小窗口",
        "验证 no-data 是所有公众号账号通用语义，不是上海账号特例",
        "福建闽融鸡蛋报价平台：attempted_count=1，success_count=1，failed_count=0",
        "信立鸡蛋当日价格：attempted_count=1，success_count=1，failed_count=0",
        "上海禽蛋价格综合报价：attempted_count=1，success_count=0，failed_count=0",
        "上海 id=39 status=skipped stage=copy_links error_code=WECHAT_ARTICLE_NO_TODAY_ARTICLE",
        "wechat_article_process_task backlog：none",
        "全账号 no-data 语义：Go，任意账号当天无正文时均应 skipped/no-data",
        "全局 scheduler 小窗口：待单独推进",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_records_batch_one_scheduler_window() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "2026-07-09 Batch 1 全局 Scheduler 小窗口",
        "runtime/article_account_config_snapshot_batch1_scheduler_20260709.json",
        "临时只启用 Batch 1 三个账号",
        "第 1 次 run-article-scheduler --once：attempted_count=1，success_count=1",
        "第 3 次 run-article-scheduler --once：attempted_count=1，success_count=0，failed_count=0",
        "第 4 次 run-article-scheduler --once：attempted_count=0",
        "福建 id=40 status=success stage=save_links link_count=1 insert_count=0",
        "信立 id=41 status=success stage=save_links link_count=1 insert_count=0",
        "上海 id=42 status=skipped stage=copy_links error_code=WECHAT_ARTICLE_NO_TODAY_ARTICLE",
        "Batch 1 全局 scheduler 小窗口：Go",
        "全账号 no-data 语义在 scheduler 路径闭环验证通过",
        "上海 enabled=0，旧四账号 enabled 状态恢复",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_records_current_account_pool_closure() -> None:
    content = DOC.read_text(encoding="utf-8")

    for keyword in [
        "2026-07-09 当前 7 账号稳定运行收口",
        "当前真实需要采集的公众号账号共 7 个",
        "上海禽蛋价格综合报价已启用：enabled=1",
        "当前账号池已满足采集需求，不再继续推进 Batch 2 或最多 20 账号扩容",
        "连续运行 run-article-scheduler --once 7 次",
        "第 8 次 run-article-scheduler --once：attempted_count=0",
        "parse-article-once --limit 50：read_count=4，success_count=4，failed_count=0",
        "article_analyze_once：read_count=4，success_count=4，failed_count=0",
        "article_daily_report_once：report_date=2026-07-09，generated_count=6",
        "wechat_article_process_task backlog：none",
        "上海禽蛋价格综合报价：raw=0，clean=0，analysis=0，daily_report=0；这是正常 no-data 结果",
        "Batch 2 / 20 账号扩容：No-Need",
    ]:
        assert keyword in content


def test_article_20_account_expansion_design_is_scanned() -> None:
    assert DOC.as_posix() in USER_FACING_DOC_PATHS
