from __future__ import annotations

from datetime import date, datetime

from app.domain.group_analysis import AnalyzedGroupMessage, DailyReportDraft
from app.storage.group_analysis_repo import MysqlGroupAnalysisRepo


class FakeResult:
    def __init__(self, rows=None, rowcount: int = 1) -> None:
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executions.append((sql, params))
        if "JOIN wechat_group_msg_clean" in sql:
            return FakeResult(
                rows=[
                    {
                        "msg_hash": "hash-1",
                        "group_name": "核心群A",
                        "sender_hash": "sender-hash",
                        "sender_display": "张***",
                        "msg_time_display": "09:15",
                        "msg_time_inferred": None,
                        "msg_type": "text",
                        "clean_content": "求深圳兼职，需要今天到岗",
                        "content_length": 12,
                        "is_empty": 0,
                        "has_phone": 0,
                        "has_wechat_id": 0,
                        "clean_version": "v1",
                        "source_collect_batch_id": "batch-1",
                        "clean_time": datetime(2026, 7, 3, 9, 15, 0),
                    }
                ]
            )
        if "FROM wechat_group_msg_analysis" in sql:
            return FakeResult(
                rows=[
                    {
                        "group_name": "核心群A",
                        "sender_hash": "sender-1",
                        "activity_hour": 9,
                        "intent_type": "demand",
                        "keyword_hits": '[\"深圳\", \"需要\"]',
                        "region_hits": '[\"深圳\"]',
                        "category_hits": '[\"兼职\"]',
                        "opportunity_hits": '[\"合作\"]',
                        "opportunity_score": 4,
                        "has_contact": 1,
                    },
                    {
                        "group_name": "核心群A",
                        "sender_hash": "sender-2",
                        "activity_hour": 10,
                        "intent_type": "supply",
                        "keyword_hits": '[\"深圳\", \"供应\"]',
                        "region_hits": '[\"深圳\"]',
                        "category_hits": '[\"岗位\"]',
                        "opportunity_hits": '[]',
                        "opportunity_score": 2,
                        "has_contact": 0,
                    },
                ]
            )
        return FakeResult()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self) -> None:
        self.connection = FakeConnection()

    def begin(self):
        return self.connection


def test_mysql_group_analysis_repo_lists_pending_clean_messages() -> None:
    engine = FakeEngine()
    repo = MysqlGroupAnalysisRepo(engine)

    messages = repo.list_pending_analyze_clean_messages(limit=5)

    assert len(messages) == 1
    assert messages[0].msg_hash == "hash-1"
    sql, params = engine.connection.executions[0]
    assert "wechat_group_process_task" in sql
    assert "JOIN wechat_group_msg_clean" in sql
    assert "task_type = 'analyze_group_msg'" in sql
    assert "wechat_article_process_task" not in sql
    assert params["limit"] == 5


def test_mysql_group_analysis_repo_upserts_analysis_and_report_task() -> None:
    engine = FakeEngine()
    repo = MysqlGroupAnalysisRepo(engine)
    analysis = AnalyzedGroupMessage(
        msg_hash="hash-1",
        group_name="核心群A",
        sender_hash="sender-hash",
        msg_time_display="09:15",
        msg_time_inferred=None,
        activity_date=date(2026, 7, 3),
        activity_hour=9,
        intent_type="demand",
        keyword_hits=["深圳", "需要"],
        region_hits=["深圳"],
        category_hits=["兼职"],
        opportunity_hits=["合作"],
        opportunity_score=4,
        has_contact=True,
        content_length=12,
        analysis_version="v1",
        analyze_time=datetime(2026, 7, 3, 10, 0, 0),
    )

    repo.upsert_message_analysis(analysis)
    repo.create_daily_report_task(date(2026, 7, 3))
    repo.mark_analyze_task_success("hash-1")
    repo.mark_daily_report_task_success(date(2026, 7, 3))

    analysis_sql, analysis_params = engine.connection.executions[0]
    task_sql, task_params = engine.connection.executions[1]
    success_sql, success_params = engine.connection.executions[2]
    daily_success_sql, daily_success_params = engine.connection.executions[3]
    assert "INSERT INTO wechat_group_msg_analysis" in analysis_sql
    assert "region_hits" in analysis_sql
    assert "category_hits" in analysis_sql
    assert "opportunity_hits" in analysis_sql
    assert "opportunity_score" in analysis_sql
    assert "ON DUPLICATE KEY UPDATE" in analysis_sql
    assert "深圳" in analysis_params["keyword_hits"]
    assert "深圳" in analysis_params["region_hits"]
    assert "兼职" in analysis_params["category_hits"]
    assert "合作" in analysis_params["opportunity_hits"]
    assert analysis_params["opportunity_score"] == 4
    assert "INSERT INTO wechat_group_process_task" in task_sql
    assert "ON DUPLICATE KEY UPDATE" in task_sql
    assert task_params["task_type"] == "group_daily_report"
    assert task_params["ref_id"] == "2026-07-03"
    assert "status = 'success'" in success_sql
    assert success_params["ref_id"] == "hash-1"
    assert "task_type = 'group_daily_report'" in daily_success_sql
    assert daily_success_params["ref_id"] == "2026-07-03"


def test_mysql_group_analysis_repo_builds_daily_stats_and_upserts_report() -> None:
    engine = FakeEngine()
    repo = MysqlGroupAnalysisRepo(engine)

    stats = repo.list_daily_report_stats(report_date=date(2026, 7, 3), group_name="核心群A")

    assert len(stats) == 1
    assert stats[0].message_count == 2
    assert stats[0].sender_count == 2
    assert stats[0].demand_count == 1
    assert stats[0].supply_count == 1
    assert stats[0].contact_count == 1
    assert stats[0].opportunity_count == 1
    assert stats[0].peak_hour == 9
    assert stats[0].top_keywords[0] == ("深圳", 2)
    assert stats[0].top_regions[0] == ("深圳", 2)
    assert stats[0].top_categories == [("兼职", 1), ("岗位", 1)]
    assert stats[0].top_opportunity_keywords == [("合作", 1)]

    report = DailyReportDraft(
        report_date=date(2026, 7, 3),
        group_name="核心群A",
        title="核心群A 2026-07-03 群日报草稿",
        markdown_body="# 核心群A 2026-07-03 群日报草稿",
        message_count=2,
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
        report_version="v1",
        generate_time=datetime(2026, 7, 3, 18, 0, 0),
    )
    repo.upsert_daily_report(report)

    report_sql, report_params = engine.connection.executions[-1]
    assert "INSERT INTO wechat_group_daily_report" in report_sql
    assert "ON DUPLICATE KEY UPDATE" in report_sql
    assert report_params["markdown_body"].startswith("# 核心群A")
