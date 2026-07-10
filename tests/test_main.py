from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import app.main as main_module
from app.main import main
from app.domain.ai_analysis import AiAnalysisResult
from app.pipelines.group_pipeline_service import GroupPipelineResult, PipelineStageResult
from app.storage.article_config_repo import ArticleAccountConfigRecord
from app.domain.trial_monitor_report import TrialMonitorReport
from app.storage.article_task_admin_repo import ArticleFailedTaskRecord
from app.storage.group_task_admin_repo import GroupFailedTaskRecord, GroupTaskRecord
from app.storage.group_runtime_summary_repo import (
    GroupConfigSummary,
    GroupRuntimeSummary,
    GroupTaskBacklogSummary,
    LatestGroupCollectLogSummary,
    UiLockRuntimeSummary,
)
from app.storage.group_runtime_metrics_repo import GroupRuntimeMetrics
from app.storage.group_repo import GroupConfigRecord, GroupRuntimeStatus
from app.rpa.wxauto_client import WxautoNotAvailableError


def test_main_check_config_outputs_key_settings(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "check-config", "--config", "config/config.dev.yaml"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "env=dev" in output
    assert "wechat_pc_version=4.1.8.107" in output
    assert "group_limit=5" in output
    assert "article_limit=20" in output


def test_main_wechat_health_outputs_status(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "wechat-health", "--config", "config/config.dev.yaml"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code in {0, 1}
    assert "wechat_health_status=" in output


def test_main_collect_group_once_uses_group_name(monkeypatch, capsys) -> None:
    @dataclass
    class FakeResult:
        group_name: str
        batch_id: str
        read_count: int
        insert_count: int
        duplicate_count: int

    class FakeService:
        def collect_once(self, group_name, batch_id, collect_time):
            assert group_name == "核心群A"
            assert batch_id.startswith("manual-")
            return FakeResult(group_name, batch_id, 2, 1, 1)

    monkeypatch.setattr(main_module, "build_real_group_collect_service", lambda config: FakeService())
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "collect-group-once",
            "--config",
            "config/config.dev.yaml",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_name=核心群A" in output
    assert "read_count=2" in output
    assert "insert_count=1" in output
    assert "duplicate_count=1" in output


def test_main_collect_group_once_reports_rpa_adapter_error(monkeypatch, capsys) -> None:
    def raise_adapter_error(config):
        raise WxautoNotAvailableError("wxauto adapter initialization failed")

    monkeypatch.setattr(main_module, "build_real_group_collect_service", raise_adapter_error)
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "collect-group-once",
            "--config",
            "config/config.dev.yaml",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "rpa_error=wxauto adapter initialization failed" in captured.err


def test_main_run_group_scheduler_once_outputs_counts(monkeypatch, capsys) -> None:
    class FakeResult:
        attempted_count = 2
        success_count = 1
        failed_count = 1
        lock_timeout_count = 0

    class FakeRunner:
        def run_once(self, now):
            return FakeResult()

    monkeypatch.setattr(main_module, "build_real_group_polling_runner", lambda config: FakeRunner())
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "run-group-scheduler",
            "--once",
            "--config",
            "config/config.dev.yaml",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "attempted_count=2" in output
    assert "success_count=1" in output
    assert "failed_count=1" in output


def test_main_group_config_upsert_outputs_group_name(monkeypatch, capsys) -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.calls = []

        def upsert_group_config(self, **kwargs) -> None:
            self.calls.append(kwargs)

    fake_repo = FakeRepo()
    monkeypatch.setattr(main_module, "build_real_group_config_repo", lambda config: fake_repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-config-upsert",
            "--config",
            "config/config.dev.yaml",
            "--group-name",
            "核心群A",
            "--core",
            "--priority",
            "1",
            "--poll-interval-seconds",
            "30",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_config_upserted=核心群A" in output
    assert fake_repo.calls[0]["group_name"] == "核心群A"
    assert fake_repo.calls[0]["is_core_group"] is True


def test_main_group_config_list_outputs_rows(monkeypatch, capsys) -> None:
    class FakeRepo:
        def list_groups(self):
            return [
                GroupConfigRecord(
                    group_name="核心群A",
                    priority=1,
                    poll_interval_seconds=30,
                    enabled=True,
                    is_core_group=True,
                    backtrack_pages=1,
                    extra_backtrack_pages=3,
                    remark="授权测试群",
                )
            ]

    monkeypatch.setattr(main_module, "build_real_group_config_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "group-config-list", "--config", "config/config.dev.yaml"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_name=核心群A" in output
    assert "enabled=1" in output
    assert "is_core_group=1" in output


def test_main_group_config_disable_outputs_group_name(monkeypatch, capsys) -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.disabled: list[str] = []

        def disable_group(self, group_name: str) -> None:
            self.disabled.append(group_name)

    fake_repo = FakeRepo()
    monkeypatch.setattr(main_module, "build_real_group_config_repo", lambda config: fake_repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-config-disable",
            "--config",
            "config/config.dev.yaml",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_config_disabled=核心群A" in output
    assert fake_repo.disabled == ["核心群A"]


def test_main_article_account_upsert_outputs_account_name(monkeypatch, capsys) -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.calls = []

        def upsert_account_config(self, **kwargs) -> None:
            self.calls.append(kwargs)

    fake_repo = FakeRepo()
    monkeypatch.setattr(main_module, "build_real_article_account_config_repo", lambda config: fake_repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-account-upsert",
            "--config",
            "config/config.dev.yaml",
            "--account-name",
            "行业观察",
            "--account-type",
            "subscription",
            "--priority",
            "2",
            "--poll-interval-minutes",
            "60",
            "--daily-window-start",
            "07:30",
            "--daily-window-end",
            "19:30",
            "--max-articles-per-round",
            "5",
            "--remark",
            "授权账号",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "article_account_upserted=行业观察" in output
    assert fake_repo.calls[0]["account_name"] == "行业观察"
    assert fake_repo.calls[0]["poll_interval_minutes"] == 60
    assert fake_repo.calls[0]["collect_today_only"] is True
    assert fake_repo.calls[0]["dedup_key"] == "article_hash"


def test_main_article_account_list_outputs_rows(monkeypatch, capsys) -> None:
    class FakeRepo:
        def list_accounts(self):
            return [
                ArticleAccountConfigRecord(
                    account_name="行业观察",
                    account_type="subscription",
                    priority=2,
                    poll_interval_minutes=60,
                    daily_window_start="07:30:00",
                    daily_window_end="19:30:00",
                    max_articles_per_round=5,
                    enabled=True,
                    collect_today_only=True,
                    dedup_key="article_hash",
                    last_success_collect_time=None,
                    remark="授权账号",
                )
            ]

    monkeypatch.setattr(main_module, "build_real_article_account_config_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "article-account-list", "--config", "config/config.dev.yaml"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "account_name=行业观察" in output
    assert "account_type=subscription" in output
    assert "enabled=1" in output
    assert "poll_interval_minutes=60" in output
    assert "daily_window_start=07:30:00" in output
    assert "daily_window_end=19:30:00" in output
    assert "collect_today_only=1" in output


def test_main_article_account_disable_outputs_account_name(monkeypatch, capsys) -> None:
    class FakeRepo:
        def __init__(self) -> None:
            self.disabled: list[str] = []

        def disable_account(self, account_name: str) -> None:
            self.disabled.append(account_name)

    fake_repo = FakeRepo()
    monkeypatch.setattr(main_module, "build_real_article_account_config_repo", lambda config: fake_repo)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-account-disable",
            "--config",
            "config/config.dev.yaml",
            "--account-name",
            "行业观察",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "article_account_disabled=行业观察" in output
    assert fake_repo.disabled == ["行业观察"]


def test_main_collect_article_once_requires_explicit_account_name(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "collect-article-once", "--config", "config/config.dev.yaml"],
    )

    try:
        main()
        raised = False
    except SystemExit:
        raised = True

    assert raised is True


def test_main_collect_article_once_runs_single_explicit_account(monkeypatch, capsys) -> None:
    class FakeResult:
        attempted_count = 1
        success_count = 1
        failed_count = 0
        lock_timeout_count = 0
        link_count = 1
        raw_insert_count = 1
        duplicate_count = 0
        skipped_count = 0
        task_created_count = 1

    class FakeRunner:
        def __init__(self) -> None:
            self.calls = []

        def run_once(self, now):
            self.calls.append(now)
            return FakeResult()

    fake_runner = FakeRunner()

    def build_runner(config, account_name: str, max_articles_per_round: int):
        assert account_name == "行业观察"
        assert max_articles_per_round == 3
        return fake_runner

    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(main_module, "build_real_article_poc_runner", build_runner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "collect-article-once",
            "--config",
            "config/config.dev.yaml",
            "--account-name",
            "行业观察",
            "--max-articles-per-round",
            "3",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert len(fake_runner.calls) == 1
    assert "account_name=行业观察" in output
    assert "attempted_count=1" in output
    assert "success_count=1" in output
    assert "failed_count=0" in output
    assert "lock_timeout_count=0" in output
    assert "link_count=1" in output
    assert "raw_insert_count=1" in output
    assert "duplicate_count=0" in output
    assert "task_created_count=1" in output


def test_main_collect_article_once_reports_rpa_adapter_error(monkeypatch, capsys) -> None:
    def raise_adapter_error(config, account_name: str, max_articles_per_round: int):
        raise WxautoNotAvailableError("wxauto adapter initialization failed")

    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(main_module, "build_real_article_poc_runner", raise_adapter_error)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "collect-article-once",
            "--config",
            "config/config.dev.yaml",
            "--account-name",
            "行业观察",
        ],
    )

    exit_code = main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "rpa_error=wxauto adapter initialization failed" in captured.err


def test_main_parse_article_once_outputs_counts_without_wechat_health(monkeypatch, capsys) -> None:
    class FakeResult:
        read_count = 2
        success_count = 1
        failed_count = 1

    class FakeService:
        def __init__(self) -> None:
            self.calls = []

        def parse_once(self, limit, parse_time):
            self.calls.append((limit, parse_time))
            return FakeResult()

    fake_service = FakeService()
    health_calls: list[object] = []

    monkeypatch.setattr(main_module, "build_real_article_parse_service", lambda config: fake_service)
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: health_calls.append(config))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "parse-article-once",
            "--config",
            "config/config.dev.yaml",
            "--limit",
            "7",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert fake_service.calls[0][0] == 7
    assert health_calls == []
    assert "read_count=2" in output
    assert "success_count=1" in output
    assert "failed_count=1" in output
    assert "https://mp.weixin.qq.com" not in output


def test_main_analyze_article_once_outputs_counts_without_body_or_url(monkeypatch, capsys) -> None:
    class FakeResult:
        read_count = 2
        success_count = 2
        failed_count = 0

    class FakeService:
        def __init__(self) -> None:
            self.calls = []

        def analyze_once(self, limit, analyze_time):
            self.calls.append((limit, analyze_time))
            return FakeResult()

    fake_service = FakeService()
    monkeypatch.setattr(main_module, "build_real_article_analysis_service", lambda config: fake_service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "analyze-article-once",
            "--config",
            "config/config.dev.yaml",
            "--limit",
            "7",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert fake_service.calls[0][0] == 7
    assert "read_count=2" in output
    assert "success_count=2" in output
    assert "failed_count=0" in output
    assert "https://mp.weixin.qq.com" not in output
    assert "raw_row_json" not in output
    assert "正文" not in output


def test_main_group_status_outputs_runtime_status(monkeypatch, capsys) -> None:
    class FakeRepo:
        def get_group_status(self, group_name: str):
            assert group_name == "核心群A"
            return GroupRuntimeStatus(
                group_name="核心群A",
                enabled=True,
                is_core_group=True,
                priority=1,
                poll_interval_seconds=30,
                last_collect_batch_id="batch-1",
                last_success_collect_time=None,
                consecutive_fail_count=0,
                cursor_error_msg=None,
                latest_log_status="success",
                latest_log_read_count=3,
                latest_log_insert_count=2,
                latest_log_duplicate_count=1,
                latest_log_error_code=None,
                latest_log_screenshot_path=None,
                ui_lock_owner_pipeline=None,
                ui_lock_owner_task_id=None,
            )

    monkeypatch.setattr(main_module, "build_real_group_status_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-status",
            "--config",
            "config/config.dev.yaml",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_name=核心群A" in output
    assert "latest_log_status=success" in output
    assert "latest_log_read_count=3" in output
    assert "ui_lock_owner_pipeline=" in output
    assert "msg_content" not in output


def test_main_clean_group_once_outputs_counts(monkeypatch, capsys) -> None:
    class FakeResult:
        read_count = 3
        success_count = 2
        failed_count = 1

    class FakeService:
        def clean_once(self, limit, clean_time):
            assert limit == 5
            return FakeResult()

    monkeypatch.setattr(main_module, "build_real_group_clean_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "clean-group-once",
            "--config",
            "config/config.dev.yaml",
            "--limit",
            "5",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "read_count=3" in output
    assert "success_count=2" in output
    assert "failed_count=1" in output


def test_main_analyze_group_once_outputs_counts(monkeypatch, capsys) -> None:
    class FakeResult:
        read_count = 4
        success_count = 3
        failed_count = 1

    class FakeService:
        def analyze_once(self, limit, analyze_time):
            assert limit == 7
            return FakeResult()

    def build_service(config, rules_config_path):
        assert rules_config_path == Path("config/group_analysis_rules.yaml")
        return FakeService()

    monkeypatch.setattr(main_module, "build_real_group_analysis_service", build_service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "analyze-group-once",
            "--config",
            "config/config.dev.yaml",
            "--limit",
            "7",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "read_count=4" in output
    assert "success_count=3" in output
    assert "failed_count=1" in output


def test_main_analyze_group_once_accepts_rules_config(monkeypatch, capsys) -> None:
    class FakeResult:
        read_count = 1
        success_count = 1
        failed_count = 0

    class FakeService:
        def analyze_once(self, limit, analyze_time):
            assert limit == 3
            return FakeResult()

    def build_service(config, rules_config_path):
        assert rules_config_path == Path("config/custom_rules.yaml")
        return FakeService()

    monkeypatch.setattr(main_module, "build_real_group_analysis_service", build_service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "analyze-group-once",
            "--config",
            "config/config.dev.yaml",
            "--rules-config",
            "config/custom_rules.yaml",
            "--limit",
            "3",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "read_count=1" in output
    assert "success_count=1" in output
    assert "failed_count=0" in output


def test_main_group_daily_report_once_outputs_generated_count(monkeypatch, capsys) -> None:
    class FakeResult:
        report_date = date(2026, 7, 3)
        generated_count = 1

    class FakeService:
        def generate_once(self, report_date, group_name, generate_time):
            assert report_date == date(2026, 7, 3)
            assert group_name == "核心群A"
            return FakeResult()

    monkeypatch.setattr(main_module, "build_real_group_daily_report_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-daily-report-once",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "report_date=2026-07-03" in output
    assert "generated_count=1" in output


def test_main_group_daily_report_list_outputs_summary_without_body(monkeypatch, capsys) -> None:
    class FakeSummary:
        report_date = date(2026, 7, 3)
        group_name = "核心群A"
        title = "核心群A 2026-07-03 群日报草稿"
        message_count = 14
        sender_count = 7
        demand_count = 0
        supply_count = 1
        contact_count = 0
        peak_hour = 10
        generate_time = "2026-07-03 18:00:00"

    class FakeService:
        def list_reports(self, report_date, group_name, limit):
            assert report_date == date(2026, 7, 3)
            assert group_name is None
            assert limit == 10
            return [FakeSummary()]

    monkeypatch.setattr(main_module, "build_real_group_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-daily-report-list",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--limit",
            "10",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_name=核心群A" in output
    assert "message_count=14" in output
    assert "markdown_body" not in output


def test_main_group_daily_report_show_outputs_markdown(monkeypatch, capsys) -> None:
    class FakeDetail:
        markdown_body = "# 核心群A 2026-07-03 群日报草稿\n\n## 核心指标\n- 消息数：14\n"

    class FakeService:
        def get_report(self, report_date, group_name):
            assert report_date == date(2026, 7, 3)
            assert group_name == "核心群A"
            return FakeDetail()

    monkeypatch.setattr(main_module, "build_real_group_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-daily-report-show",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--group-name",
            "核心群A",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "# 核心群A 2026-07-03 群日报草稿" in output
    assert "msg_content" not in output
    assert "raw_content" not in output


def test_main_group_daily_report_export_outputs_path(monkeypatch, capsys) -> None:
    class FakeResult:
        export_path = Path("runtime/reports/group/2026-07-03/核心群A.md")
        bytes_written = 128

    class FakeService:
        def export_report(self, report_date, group_name, output_path):
            assert report_date == date(2026, 7, 3)
            assert group_name == "核心群A"
            assert output_path == Path("runtime/reports/group")
            return FakeResult()

    monkeypatch.setattr(main_module, "build_real_group_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-daily-report-export",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--group-name",
            "核心群A",
            "--output",
            "runtime/reports/group",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "export_path=runtime\\reports\\group\\2026-07-03\\核心群A.md" in output
    assert "bytes_written=128" in output


def test_main_article_daily_report_list_outputs_summary_without_body(monkeypatch, capsys) -> None:
    class FakeSummary:
        report_date = date(2026, 7, 6)
        account_name = "行业观察"
        title = "行业观察 2026-07-06 文章日报草稿"
        article_count = 2
        avg_content_length = 1300
        generate_time = "2026-07-06 20:00:00"

    class FakeService:
        def list_reports(self, report_date, account_name, limit):
            assert report_date == date(2026, 7, 6)
            assert account_name is None
            assert limit == 10
            return [FakeSummary()]

    monkeypatch.setattr(main_module, "build_real_article_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-daily-report-list",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-06",
            "--limit",
            "10",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "account_name=行业观察" in output
    assert "article_count=2" in output
    assert "markdown_body" not in output
    assert "article_url" not in output


def test_main_article_daily_report_show_outputs_markdown(monkeypatch, capsys) -> None:
    class FakeDetail:
        markdown_body = "# 行业观察 2026-07-06 文章日报草稿\n\n## 核心指标\n- 文章数：2\n"

    class FakeService:
        def get_report(self, report_date, account_name):
            assert report_date == date(2026, 7, 6)
            assert account_name == "行业观察"
            return FakeDetail()

    monkeypatch.setattr(main_module, "build_real_article_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-daily-report-show",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-06",
            "--account-name",
            "行业观察",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "# 行业观察 2026-07-06 文章日报草稿" in output
    assert "article_url" not in output
    assert "body_text" not in output


def test_main_article_daily_report_export_outputs_path(monkeypatch, capsys) -> None:
    class FakeResult:
        export_path = Path("runtime/reports/article/2026-07-06/行业观察.md")
        bytes_written = 128

    class FakeService:
        def export_report(self, report_date, account_name, output_path):
            assert report_date == date(2026, 7, 6)
            assert account_name == "行业观察"
            assert output_path == Path("runtime/reports/article")
            return FakeResult()

    monkeypatch.setattr(main_module, "build_real_article_daily_report_query_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-daily-report-export",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-06",
            "--account-name",
            "行业观察",
            "--output",
            "runtime/reports/article",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "export_path=runtime\\reports\\article\\2026-07-06\\行业观察.md" in output
    assert "bytes_written=128" in output


def test_main_summary_daily_report_show_outputs_markdown(monkeypatch, capsys) -> None:
    class FakeDraft:
        markdown_body = "# 2026-07-06 双链路汇总日报草稿\n\n## 总览\n"

    class FakeService:
        def generate(self, report_date, generate_time):
            assert report_date == date(2026, 7, 6)
            assert isinstance(generate_time, datetime)
            return FakeDraft()

    monkeypatch.setattr(main_module, "build_real_summary_daily_report_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "summary-daily-report-show",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-06",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "# 2026-07-06 双链路汇总日报草稿" in output
    assert "wechat_group_process_task" not in output
    assert "wechat_article_process_task" not in output
    assert "article_url" not in output


def test_main_summary_daily_report_export_outputs_path(monkeypatch, capsys, tmp_path) -> None:
    payload = "# 2026-07-06 双链路汇总日报草稿\n"

    class FakeDraft:
        markdown_body = payload

    class FakeService:
        def generate(self, report_date, generate_time):
            assert report_date == date(2026, 7, 6)
            assert isinstance(generate_time, datetime)
            return FakeDraft()

    monkeypatch.setattr(main_module, "build_real_summary_daily_report_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "summary-daily-report-export",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-06",
            "--output",
            str(tmp_path),
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out
    export_path = tmp_path / "2026-07-06" / "summary.md"

    assert exit_code == 0
    assert f"export_path={export_path}" in output
    assert f"bytes_written={len(payload.encode('utf-8'))}" in output
    assert export_path.read_text(encoding="utf-8") == payload


def test_main_run_group_pipeline_once_skip_collect_outputs_stage_counts(monkeypatch, capsys) -> None:
    class FakeService:
        def run_once(self, report_date, group_name, skip_collect, limit, run_time, batch_id):
            assert report_date == date(2026, 7, 3)
            assert group_name is None
            assert skip_collect is True
            assert limit == 20
            assert batch_id.startswith("pipeline-")
            return GroupPipelineResult(
                status="success",
                failed_stage=None,
                error_msg=None,
                stages=[
                    PipelineStageResult(stage="collect", status="skipped", metrics={}),
                    PipelineStageResult(stage="clean", status="success", metrics={"read_count": 0, "success_count": 0, "failed_count": 0}),
                    PipelineStageResult(stage="analyze", status="success", metrics={"read_count": 0, "success_count": 0, "failed_count": 0}),
                    PipelineStageResult(stage="report", status="success", metrics={"generated_count": 1}),
                ],
            )

    def build_service(config, rules_config_path, include_collect):
        assert rules_config_path == Path("config/group_analysis_rules.yaml")
        assert include_collect is False
        return FakeService()

    monkeypatch.setattr(main_module, "build_real_group_pipeline_service", build_service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "run-group-pipeline-once",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--skip-collect",
            "--limit",
            "20",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "pipeline_status=success" in output
    assert "stage=collect status=skipped" in output
    assert "stage=clean status=success read_count=0 success_count=0 failed_count=0" in output
    assert "stage=report status=success generated_count=1" in output


def test_main_run_group_pipeline_once_returns_failed_for_failed_stage(monkeypatch, capsys) -> None:
    class FakeService:
        def run_once(self, report_date, group_name, skip_collect, limit, run_time, batch_id):
            return GroupPipelineResult(
                status="failed",
                failed_stage="clean",
                error_msg="clean failed_count=1",
                stages=[
                    PipelineStageResult(stage="collect", status="skipped", metrics={}),
                    PipelineStageResult(stage="clean", status="failed", metrics={"read_count": 2, "success_count": 1, "failed_count": 1}),
                ],
            )

    monkeypatch.setattr(
        main_module,
        "build_real_group_pipeline_service",
        lambda config, rules_config_path, include_collect: FakeService(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "run-group-pipeline-once",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
            "--skip-collect",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "pipeline_status=failed" in output
    assert "failed_stage=clean" in output
    assert "error_msg=clean failed_count=1" in output


def test_main_group_runtime_summary_outputs_safe_counts(monkeypatch, capsys) -> None:
    class FakeRepo:
        def get_summary(self, limit: int):
            assert limit == 3
            return GroupRuntimeSummary(
                config=GroupConfigSummary(total_count=2, enabled_count=1, core_enabled_count=1),
                ui_lock=UiLockRuntimeSummary(
                    status="free",
                    owner_pipeline=None,
                    owner_task_id=None,
                    expire_time=None,
                ),
                task_backlogs=[
                    GroupTaskBacklogSummary(task_type="clean_group_msg", status="success", count=14),
                    GroupTaskBacklogSummary(task_type="analyze_group_msg", status="success", count=14),
                ],
                latest_collect_logs=[
                    LatestGroupCollectLogSummary(
                        source_name="核心群A",
                        batch_id="batch-1",
                        status="success",
                        start_time=None,
                        end_time=None,
                        read_count=4,
                        insert_count=1,
                        duplicate_count=3,
                        error_code=None,
                        screenshot_path=None,
                    )
                ],
            )

    monkeypatch.setattr(main_module, "build_real_group_runtime_summary_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-runtime-summary",
            "--config",
            "config/config.dev.yaml",
            "--limit",
            "3",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "group_config total_count=2 enabled_count=1 core_enabled_count=1" in output
    assert "ui_lock status=free" in output
    assert "task_backlog task_type=clean_group_msg status=success count=14" in output
    assert "latest_collect source_name=核心群A batch_id=batch-1 status=success read_count=4 insert_count=1 duplicate_count=3" in output
    assert "msg_content" not in output
    assert "raw_content" not in output
    assert "clean_content" not in output
    assert "markdown_body" not in output


def test_main_group_runtime_metrics_outputs_windowed_metrics(monkeypatch, capsys) -> None:
    class FakeRepo:
        def get_metrics(self, hours: int):
            assert hours == 12
            return GroupRuntimeMetrics(
                window_hours=12,
                collect_success_count=6,
                collect_failed_count=2,
                collect_total_count=8,
                collect_failure_rate=0.25,
                daily_report_count=4,
                task_backlogs=[
                    GroupTaskBacklogSummary(task_type="clean_group_msg", status="pending", count=3),
                    GroupTaskBacklogSummary(task_type="analyze_group_msg", status="failed", count=1),
                ],
            )

    monkeypatch.setattr(main_module, "build_real_group_runtime_metrics_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-runtime-metrics",
            "--config",
            "config/config.dev.yaml",
            "--hours",
            "12",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "runtime_metrics window_hours=12 collect_success_count=6 collect_failed_count=2 collect_total_count=8 collect_failure_rate=0.2500 daily_report_count=4" in output
    assert "task_backlog task_type=clean_group_msg status=pending count=3" in output
    assert "task_backlog task_type=analyze_group_msg status=failed count=1" in output
    assert "msg_content" not in output
    assert "raw_content" not in output
    assert "clean_content" not in output
    assert "markdown_body" not in output


def test_main_trial_monitor_report_outputs_two_link_counts(monkeypatch, capsys) -> None:
    class FakeService:
        def generate(self, hours, generate_time):
            assert hours == 12
            assert isinstance(generate_time, datetime)
            return TrialMonitorReport(
                hours=12,
                markdown_body="# 双链路试运行巡检报告\n",
                group_success_count=6,
                group_failed_count=2,
                group_backlog_count=4,
                article_success_count=7,
                article_failed_count=1,
                article_backlog_count=5,
                ui_lock_timeout_count=0,
                generate_time=generate_time,
            )

    monkeypatch.setattr(main_module, "build_real_trial_monitor_report_service", lambda config: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "trial-monitor-report",
            "--config",
            "config/config.dev.yaml",
            "--hours",
            "12",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "trial_monitor_report hours=12" in output
    assert "group_success_count=6" in output
    assert "group_failed_count=2" in output
    assert "group_backlog_count=4" in output
    assert "article_success_count=7" in output
    assert "article_failed_count=1" in output
    assert "article_backlog_count=5" in output
    assert "ui_lock_timeout_count=0" in output
    assert "msg_content" not in output
    assert "raw_content" not in output
    assert "markdown_body" not in output


def test_main_ai_analysis_sample_outputs_dry_run_shape(monkeypatch, capsys) -> None:
    class FakeService:
        def analyze_sample(self, service_input):
            assert service_input.source == "summary_daily_report"
            assert service_input.source_date == date(2026, 7, 7)
            return AiAnalysisResult(
                source="summary_daily_report",
                source_date=date(2026, 7, 7),
                dry_run=True,
                enabled=False,
                provider="none",
                prompt_version="poc-v1",
                model_version="dry-run",
                input_field_count=5,
                status="dry_run",
                model_called=False,
                error_summary=None,
            )

    monkeypatch.setattr(main_module, "build_real_ai_analysis_service", lambda ai_config_path: FakeService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "ai-analysis-sample",
            "--config",
            "config/config.dev.yaml",
            "--source",
            "summary_daily_report",
            "--date",
            "2026-07-07",
            "--dry-run",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "ai_analysis_sample source=summary_daily_report dry_run=1 input_field_count=5" in output
    assert "provider=none" in output
    assert "prompt_version=poc-v1" in output
    assert "model_version=dry-run" in output
    assert "raw_content" not in output
    assert "html_content" not in output
    assert "article_url" not in output


def test_main_group_task_list_outputs_task_metadata_without_content(monkeypatch, capsys) -> None:
    class FakeRepo:
        def list_tasks(self, task_type, status, ref_id, limit):
            assert task_type == "analyze_group_msg"
            assert status == "failed"
            assert ref_id == "hash-1"
            assert limit == 5
            return [
                GroupTaskRecord(
                    id=11,
                    task_type="analyze_group_msg",
                    ref_type="msg",
                    ref_id="hash-1",
                    status="failed",
                    retry_count=3,
                    next_run_time=None,
                    error_msg="analysis timeout",
                    update_time=datetime(2026, 7, 3, 12, 0, 0),
                )
            ]

    monkeypatch.setattr(main_module, "build_real_group_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-task-list",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "analyze_group_msg",
            "--status",
            "failed",
            "--ref-id",
            "hash-1",
            "--limit",
            "5",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task id=11 task_type=analyze_group_msg ref_type=msg ref_id=hash-1 status=failed retry_count=3" in output
    assert "error_msg=analysis timeout" in output
    assert "msg_content" not in output
    assert "raw_content" not in output
    assert "clean_content" not in output
    assert "markdown_body" not in output


def test_main_group_task_reset_outputs_reset_count(monkeypatch, capsys) -> None:
    class FakeRepo:
        def reset_task(self, task_type, ref_id):
            assert task_type == "clean_group_msg"
            assert ref_id == "hash-1"
            return 1

    monkeypatch.setattr(main_module, "build_real_group_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-task-reset",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "clean_group_msg",
            "--ref-id",
            "hash-1",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task_type=clean_group_msg" in output
    assert "ref_id=hash-1" in output
    assert "reset_count=1" in output


def test_main_group_task_reset_date_outputs_reset_count(monkeypatch, capsys) -> None:
    class FakeRepo:
        def reset_daily_report_date(self, report_date):
            assert report_date == date(2026, 7, 3)
            return 1

    monkeypatch.setattr(main_module, "build_real_group_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-task-reset-date",
            "--config",
            "config/config.dev.yaml",
            "--date",
            "2026-07-03",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task_type=group_daily_report" in output
    assert "ref_id=2026-07-03" in output
    assert "reset_count=1" in output


def test_main_group_task_failed_list_outputs_safe_error_summary(monkeypatch, capsys) -> None:
    class FakeRepo:
        def list_failed_tasks(self, task_type, limit):
            assert task_type == "analyze_group_msg"
            assert limit == 20
            return [
                GroupFailedTaskRecord(
                    id=21,
                    task_type="analyze_group_msg",
                    ref_type="msg",
                    ref_id="hash-2",
                    status="failed",
                    retry_count=3,
                    next_run_time=None,
                    error_summary="analysis timeout",
                    update_time=datetime(2026, 7, 3, 13, 0, 0),
                )
            ]

    monkeypatch.setattr(main_module, "build_real_group_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-task-failed-list",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "analyze_group_msg",
            "--limit",
            "20",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "failed_task id=21 task_type=analyze_group_msg ref_type=msg ref_id=hash-2 status=failed retry_count=3" in output
    assert "error_summary=analysis timeout" in output
    assert "error_msg" not in output
    assert "msg_content" not in output
    assert "raw_content" not in output
    assert "clean_content" not in output
    assert "markdown_body" not in output


def test_main_group_task_retry_failed_outputs_reset_count_with_limit(monkeypatch, capsys) -> None:
    class FakeRepo:
        def retry_failed_tasks(self, task_type, limit):
            assert task_type == "clean_group_msg"
            assert limit == 5
            return 5

    monkeypatch.setattr(main_module, "build_real_group_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "group-task-retry-failed",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "clean_group_msg",
            "--limit",
            "5",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task_type=clean_group_msg" in output
    assert "limit=5" in output
    assert "reset_count=5" in output


def test_main_article_task_failed_list_outputs_safe_error_summary(monkeypatch, capsys) -> None:
    class FakeRepo:
        def list_failed_tasks(self, task_type, limit):
            assert task_type == "clean_article"
            assert limit == 20
            return [
                ArticleFailedTaskRecord(
                    id=31,
                    task_type="clean_article",
                    ref_type="article",
                    ref_id="article-hash-1",
                    status="failed",
                    retry_count=3,
                    next_run_time=None,
                    error_summary="parse timeout",
                    update_time=datetime(2026, 7, 6, 13, 0, 0),
                )
            ]

    monkeypatch.setattr(main_module, "build_real_article_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-task-failed-list",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "clean_article",
            "--limit",
            "20",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "failed_task id=31 task_type=clean_article ref_type=article ref_id=article-hash-1 status=failed retry_count=3" in output
    assert "error_summary=parse timeout" in output
    assert "error_msg" not in output
    assert "article_url" not in output
    assert "article_body" not in output
    assert "body_text" not in output
    assert "html_content" not in output


def test_main_article_task_retry_failed_outputs_reset_count_with_limit(monkeypatch, capsys) -> None:
    class FakeRepo:
        def retry_failed_tasks(self, task_type, limit):
            assert task_type == "clean_article"
            assert limit == 5
            return 5

    monkeypatch.setattr(main_module, "build_real_article_task_admin_repo", lambda config: FakeRepo())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-task-retry-failed",
            "--config",
            "config/config.dev.yaml",
            "--task-type",
            "clean_article",
            "--limit",
            "5",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "task_type=clean_article" in output
    assert "limit=5" in output
    assert "reset_count=5" in output
