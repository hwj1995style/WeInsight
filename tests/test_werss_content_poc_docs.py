from pathlib import Path


RUNBOOK = Path("docs/operations/公众号RSS采集运行手册.md")
POC = Path("docs/operations/WeRSS正文按需读取POC记录.md")


def test_runbook_documents_werss_content_rollout_and_rollback() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "sha256:53912fcb3d523d1e640adcb7066cc18123f00e9510882a7982d0991f3113845f",
        "正文接口契约验证",
        "shadow",
        "werss_first",
        "正文成功",
        "网页回退",
        "正文失败",
        "正文任务积压",
        "WeRSS 重启恢复",
        "article_ui_lock_count",
        "数据库与日志无正文",
        "content_mode: web",
    ):
        assert required in content


def test_poc_record_freezes_scope_and_has_auditable_observation_fields() -> None:
    content = POC.read_text(encoding="utf-8")
    for required in (
        "湖南三尖农牧公司",
        "MP_WXS_3545051769",
        "目标总数：9",
        "正文长度",
        "内容哈希",
        "结构化报价差异",
        "网页回退次数",
        "正文失败次数",
        "开始时间",
        "截止时间",
        "基线计数",
        "1 → 3 → 9",
    ):
        assert required in content


def test_poc_record_does_not_claim_unfinished_24_hour_observation_passed() -> None:
    content = POC.read_text(encoding="utf-8")
    assert "24 小时观察：通过" not in content


def test_poc_record_invalidates_old_window_after_catalog_architecture_change() -> None:
    content = POC.read_text(encoding="utf-8")
    for required in (
        "旧 24 小时观察窗口：失效",
        "架构改造",
        "首个 9/9 成功",
        "增量流水线健康",
        "桌面截图",
        "窄屏截图",
        "待 controller 执行",
    ):
        assert required in content
    assert "当前有效连续 24 小时窗口开始" not in content


def test_poc_record_marks_observation_as_in_progress_with_explicit_window() -> None:
    content = POC.read_text(encoding="utf-8")
    assert "24 小时观察状态：进行中" in content
    assert "2026-07-12 13:08:14 +08:00" in content
    assert "2026-07-13 13:08:14 +08:00" in content


def test_poc_record_separates_collection_scope_from_downstream_scope() -> None:
    content = POC.read_text(encoding="utf-8")
    for required in (
        "9 个公众号全部启用采集",
        "仅湖南三尖农牧公司进入 clean/analyze",
        "其余 8 个只采集",
        "只有湖南 `downstream_clean_enabled=1`",
        "其余 8 个没有新增 clean/analyze 任务",
        "采集完整率",
        "去重",
        "采集延迟",
        "正文成功率",
        "回退",
        "分析",
    ):
        assert required in content


def test_poc_record_records_first_werss_success_without_claiming_pass() -> None:
    content = POC.read_text(encoding="utf-8")
    assert "content_mode: werss_first" in content
    assert "clean/analyze 均 success" in content
    assert "content_source=werss" in content
    assert "观察期尚未结束" in content


def test_werss_rollout_docs_use_confirmed_jiangxi_account_name() -> None:
    paths = (
        Path("docs/superpowers/specs/2026-07-12-WeRSS正文按需读取设计.md"),
        Path("docs/superpowers/plans/2026-07-12-WeRSS正文按需读取实施计划.md"),
        RUNBOOK,
        POC,
    )
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "江西九江褐壳蛋" in content
        assert "江西九江祺壳蛋" not in content
