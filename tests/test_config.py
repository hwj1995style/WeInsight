from __future__ import annotations

from pathlib import Path

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


def test_prod_example_config_loads_without_plaintext_password(monkeypatch) -> None:
    path = Path("config/config.prod.example.yaml")
    content = path.read_text(encoding="utf-8")

    assert path.exists()
    assert "${WEINSIGHT_MYSQL_PASSWORD}" in content
    assert "weinsight_dev" not in content
    assert "pulsebrief-mysql" not in content
    assert "pweinsight" not in content.lower()

    monkeypatch.setenv("WEINSIGHT_MYSQL_PASSWORD", "prod-secret-for-test")
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

    raw = yaml.safe_load(content)
    assert raw["mysql"]["password"] == "${WEINSIGHT_MYSQL_PASSWORD}"
