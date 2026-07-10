from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.config import load_config


def test_load_config_expands_mysql_password() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.mysql.host == "127.0.0.1"
    assert config.mysql.port == 3307
    assert config.mysql.database == "weinsight_dev"
    assert config.mysql.password == "weinsight_dev"


def test_pipeline_capacity_defaults_match_design() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.wechat.pc_version == "4.1.8.107"
    assert config.runtime.log_dir == "runtime/logs"
    assert config.runtime.screenshot_dir == "runtime/screenshots"
    assert config.runtime.report_dir == "runtime/reports"
    assert config.pipelines.group.core_group_limit == 5
    assert config.pipelines.article.account_limit == 20
    assert config.pipelines.article.crawl_time == "07:30"
    assert config.pipelines.article.low_peak_windows == ("07:30-19:30",)
    assert config.pipelines.article.account_poll_interval_minutes == 60
    assert config.pipelines.article.max_accounts_per_ui_slice == 1
    assert config.pipelines.article.collect_today_only is True
    assert config.pipelines.article.dedup_enabled is True
    assert config.pipelines.article.dedup_key == "article_hash"
    assert config.pipelines.article.route_cache_enabled is True
    assert config.pipelines.article.route_probe_enabled is True
    assert config.pipelines.article.route_probe_failure_threshold == 3
    assert "蛋价资讯" in config.pipelines.article.route_entry_labels
    assert "今日价格" in config.pipelines.article.route_entry_labels
    assert config.pipelines.article.link_extract_methods == (
        "copy_link_menu",
        "uia_value",
        "visible_text",
    )
    assert config.pipelines.article.egg_price_extraction_enabled is True
    assert config.pipelines.article.price_items_json_preview_limit == 20
    assert config.pipelines.article.image_quote_note_enabled is True
    assert config.pipelines.article.browser_executable_path == "auto"
    assert config.pipelines.ui_resource.max_core_group_block_seconds == 10
    assert config.pipelines.ui_resource.lock_lease_seconds == 120


def test_admin_web_config_defaults_are_explicit() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8848
    assert config.web.secure_cookie is False
    assert config.auth.default_username == "admin"
    assert config.auth.session_cookie_name == "weinsight_session"
    assert config.auth.csrf_cookie_name == "weinsight_csrf"
    assert config.auth.session_idle_minutes == 480
    assert config.auth.session_absolute_minutes == 1440
    assert config.auth.login_failure_limit == 5
    assert config.auth.login_lock_minutes == 15


def test_worker_config_defaults_are_explicit_and_safe() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.workers.collector_mode == "fake"
    assert config.workers.schedule_tick_seconds == 5
    assert config.workers.heartbeat_seconds == 10
    assert config.workers.run_lease_seconds == 120
    assert config.workers.pipeline_tick_seconds == 5
    assert config.workers.group_clean_batch_size == 50
    assert config.workers.group_analysis_batch_size == 100
    assert config.workers.article_parse_batch_size == 20
    assert config.workers.article_analysis_batch_size == 20


def _write_changed_config(tmp_path: Path, change) -> Path:
    raw = yaml.safe_load(Path("config/config.dev.yaml").read_text(encoding="utf-8"))
    change(raw)
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_worker_config_rejects_invalid_mode_before_runtime_build(tmp_path) -> None:
    path = _write_changed_config(
        tmp_path,
        lambda raw: raw["workers"].update({"collector_mode": "unsafe"}),
    )
    with pytest.raises(ValueError, match="collector_mode"):
        load_config(path)


@pytest.mark.parametrize(
    "field",
    [
        "schedule_tick_seconds",
        "heartbeat_seconds",
        "run_lease_seconds",
        "pipeline_tick_seconds",
        "group_clean_batch_size",
        "group_analysis_batch_size",
        "article_parse_batch_size",
        "article_analysis_batch_size",
    ],
)
def test_worker_config_rejects_bool_and_nonpositive_integers(
    tmp_path, field
) -> None:
    for invalid in (True, 0, -1):
        path = _write_changed_config(
            tmp_path,
            lambda raw, value=invalid: raw["workers"].update(
                {field: value}
            ),
        )
        with pytest.raises(ValueError, match=field):
            load_config(path)


def test_worker_config_rejects_missing_and_unknown_fields(tmp_path) -> None:
    missing = _write_changed_config(
        tmp_path,
        lambda raw: raw["workers"].pop("run_lease_seconds"),
    )
    with pytest.raises((TypeError, KeyError, ValueError)):
        load_config(missing)

    unknown = _write_changed_config(
        tmp_path,
        lambda raw: raw["workers"].update({"real_without_review": True}),
    )
    with pytest.raises((TypeError, KeyError, ValueError)):
        load_config(unknown)


def test_admin_web_uses_secure_multipart_dependency() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "python-multipart==0.0.32" in requirements
    assert "python-multipart==0.0.20" not in requirements


def test_prod_example_config_loads_without_plaintext_password(monkeypatch) -> None:
    path = Path("config/config.prod.example.yaml")
    content = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "${WEINSIGHT_MYSQL_PASSWORD}" in content
    assert "weinsight_dev" not in content
    assert "pulsebrief-mysql" not in content
    assert "pweinsight" not in content.lower()

    monkeypatch.setenv("WEINSIGHT_MYSQL_PASSWORD", "prod-secret-for-test")
    monkeypatch.setenv("WEINSIGHT_WEB_HOST", "10.20.30.40")
    config = load_config(path)

    assert config.app.env == "prod"
    assert config.mysql.host == "prod-mysql.internal"
    assert config.mysql.port == 3306
    assert config.mysql.database == "weinsight_prod"
    assert config.mysql.username == "weinsight_prod"
    assert config.mysql.password == "prod-secret-for-test"
    assert config.runtime.log_dir == "runtime/logs"
    assert config.runtime.screenshot_dir == "runtime/screenshots"
    assert config.runtime.report_dir == "runtime/reports"
    assert config.pipelines.group.core_group_limit == 5
    assert config.pipelines.group.poll_interval_seconds == 30
    assert config.pipelines.article.account_limit == 20
    assert config.pipelines.article.crawl_time == "07:30"
    assert config.pipelines.article.low_peak_windows == ("07:30-19:30",)
    assert config.pipelines.article.account_poll_interval_minutes == 60
    assert config.pipelines.article.max_accounts_per_ui_slice == 1
    assert config.pipelines.article.collect_today_only is True
    assert config.pipelines.article.dedup_enabled is True
    assert config.pipelines.article.dedup_key == "article_hash"
    assert config.pipelines.article.route_cache_enabled is True
    assert config.pipelines.article.route_probe_enabled is True
    assert config.pipelines.article.route_probe_failure_threshold == 3
    assert "蛋价资讯" in config.pipelines.article.route_entry_labels
    assert config.pipelines.article.link_extract_methods == (
        "copy_link_menu",
        "uia_value",
        "visible_text",
    )
    assert config.pipelines.article.egg_price_extraction_enabled is True
    assert config.pipelines.article.price_items_json_preview_limit == 20
    assert config.pipelines.article.image_quote_note_enabled is True
    assert config.pipelines.article.browser_executable_path == "auto"
    assert config.web.host == "10.20.30.40"
    assert config.web.secure_cookie is True
    assert config.workers.collector_mode == "fake"
    assert config.workers.schedule_tick_seconds == 5
    assert config.workers.heartbeat_seconds == 10
    assert config.workers.run_lease_seconds == 120
    assert config.workers.pipeline_tick_seconds == 5
    assert config.workers.group_clean_batch_size == 50
    assert config.workers.group_analysis_batch_size == 100
    assert config.workers.article_parse_batch_size == 20
    assert config.workers.article_analysis_batch_size == 20

    raw = yaml.safe_load(content)
    assert raw["mysql"]["password"] == "${WEINSIGHT_MYSQL_PASSWORD}"
