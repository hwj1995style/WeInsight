from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.group_analysis import AnalyzedGroupMessage, DailyReportDraft, DailyReportStats
from app.domain.group_analysis_rules import AnalysisRuleSet
from app.domain.group_cleaning import CleanGroupMessage
from app.domain.report_lifecycle import ReportLifecycle, ReportStatus
from app.pipelines.group_analysis_service import GroupAnalysisService, GroupDailyReportService


LIFECYCLE = ReportLifecycle.provisional(
    cutoff=datetime(2026, 7, 3, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    generated_by="admin",
)


class FakeAnalysisRepo:
    def __init__(self, clean_messages: list[CleanGroupMessage]) -> None:
        self.clean_messages = clean_messages
        self.analyses: list[AnalyzedGroupMessage] = []
        self.report_tasks: list[date] = []
        self.successes: list[str] = []
        self.failures: list[tuple[str, str]] = []

    def list_pending_analyze_clean_messages(self, limit: int) -> list[CleanGroupMessage]:
        return self.clean_messages[:limit]

    def upsert_message_analysis(self, analysis: AnalyzedGroupMessage) -> None:
        self.analyses.append(analysis)

    def create_daily_report_task(self, report_date: date) -> None:
        self.report_tasks.append(report_date)

    def mark_analyze_task_success(self, msg_hash: str) -> None:
        self.successes.append(msg_hash)

    def mark_analyze_task_failed(self, msg_hash: str, error_msg: str) -> None:
        self.failures.append((msg_hash, error_msg))


class FakeDailyReportRepo:
    def __init__(self, stats: list[DailyReportStats], expected_group_name: str | None = "核心群A") -> None:
        self.stats = stats
        self.expected_group_name = expected_group_name
        self.reports: list[DailyReportDraft] = []
        self.lifecycles: list[ReportLifecycle] = []
        self.successes: list[date] = []

    def list_daily_report_stats(self, report_date: date, group_name: str | None) -> list[DailyReportStats]:
        assert report_date == date(2026, 7, 3)
        assert group_name == self.expected_group_name
        return self.stats

    def upsert_daily_report(self, report: DailyReportDraft, lifecycle: ReportLifecycle) -> None:
        self.reports.append(report)
        self.lifecycles.append(lifecycle)

    def mark_daily_report_task_success(self, report_date: date) -> None:
        self.successes.append(report_date)


def _clean_message() -> CleanGroupMessage:
    return CleanGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_hash="sender-hash",
        sender_display="张***",
        msg_time_display="09:15",
        msg_time_inferred=None,
        msg_type="text",
        clean_content="求深圳兼职，需要今天到岗",
        content_length=12,
        is_empty=False,
        has_phone=False,
        has_wechat_id=False,
        clean_version="v1",
        source_collect_batch_id="batch-1",
        clean_time=datetime(2026, 7, 3, 9, 15, 0),
    )


def test_group_analysis_service_analyzes_pending_clean_messages() -> None:
    repo = FakeAnalysisRepo([_clean_message()])
    service = GroupAnalysisService(repo=repo)

    result = service.analyze_once(limit=10, analyze_time=datetime(2026, 7, 3, 10, 0, 0))

    assert result.read_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    assert repo.analyses[0].intent_type == "demand"
    assert repo.report_tasks == [date(2026, 7, 3)]
    assert repo.successes == ["hash-1"]
    assert repo.failures == []


def test_group_analysis_service_uses_injected_rule_set() -> None:
    custom_clean = CleanGroupMessage(
        msg_hash="hash-custom",
        group_name="核心群A",
        sender_hash="sender-hash",
        sender_display="张***",
        msg_time_display="09:15",
        msg_time_inferred=None,
        msg_type="text",
        clean_content="广州客服招人，日结",
        content_length=9,
        is_empty=False,
        has_phone=False,
        has_wechat_id=False,
        clean_version="v1",
        source_collect_batch_id="batch-1",
        clean_time=datetime(2026, 7, 3, 9, 15, 0),
    )
    rule_set = AnalysisRuleSet(
        version="custom-v2",
        change_note="新增广州客服规则",
        demand_keywords=("招人",),
        supply_keywords=("派单",),
        region_keywords=("广州",),
        category_keywords=("客服",),
        opportunity_keywords=("合作",),
        extra_tracked_keywords=("日结",),
    )
    repo = FakeAnalysisRepo([custom_clean])
    service = GroupAnalysisService(repo=repo, rule_set=rule_set)

    result = service.analyze_once(limit=10, analyze_time=datetime(2026, 7, 3, 10, 0, 0))

    assert result.success_count == 1
    assert repo.analyses[0].intent_type == "demand"
    assert repo.analyses[0].analysis_version == "custom-v2"
    assert repo.analyses[0].keyword_hits == ["招人", "广州", "客服", "日结"]


def test_group_daily_report_service_generates_markdown_drafts() -> None:
    stats = DailyReportStats(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        message_count=3,
        sender_count=2,
        demand_count=1,
        supply_count=1,
        contact_count=1,
        opportunity_count=1,
        peak_hour=9,
        top_keywords=[("深圳", 2)],
        top_regions=[("深圳", 2)],
        top_categories=[("兼职", 1)],
        top_opportunity_keywords=[("合作", 1)],
    )
    repo = FakeDailyReportRepo([stats])
    service = GroupDailyReportService(repo=repo)

    result = service.generate_once(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        generate_time=datetime(2026, 7, 3, 18, 0, 0),
        lifecycle=LIFECYCLE,
    )

    assert result.report_date == date(2026, 7, 3)
    assert result.generated_count == 1
    assert repo.reports[0].title == "核心群A 2026-07-03 群日报草稿"
    assert "消息数：3" in repo.reports[0].markdown_body
    assert "可疑商机数：1" in repo.reports[0].markdown_body
    assert repo.lifecycles[0].report_status is ReportStatus.PROVISIONAL
    assert repo.successes == []


def test_group_daily_report_service_marks_global_date_task_success() -> None:
    stats = DailyReportStats(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        message_count=3,
        sender_count=2,
        demand_count=1,
        supply_count=1,
        contact_count=1,
        opportunity_count=1,
        peak_hour=9,
        top_keywords=[("深圳", 2)],
        top_regions=[("深圳", 2)],
        top_categories=[("兼职", 1)],
        top_opportunity_keywords=[("合作", 1)],
    )
    repo = FakeDailyReportRepo([stats], expected_group_name=None)
    service = GroupDailyReportService(repo=repo)

    result = service.generate_once(
        report_date=date(2026, 7, 3),
        group_name=None,
        generate_time=datetime(2026, 7, 3, 18, 0, 0),
        lifecycle=LIFECYCLE,
    )

    assert result.generated_count == 1
    assert repo.successes == [date(2026, 7, 3)]
