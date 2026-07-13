from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from app.core.config import ArticlePipelineConfig, load_config


@pytest.fixture
def config_path() -> Path:
    return Path("config/config.dev.yaml")


@pytest.fixture(autouse=True)
def werss_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WEINSIGHT_WERSS_ACCESS_KEY", "WK-test-default")
    monkeypatch.setenv("WEINSIGHT_WERSS_SECRET_KEY", "secret-test-default")


def valid_article_config() -> ArticlePipelineConfig:
    return load_config(Path("config/config.dev.yaml")).pipelines.article


def test_article_catalog_defaults_and_secrets(config_path, monkeypatch):
    monkeypatch.setenv("WEINSIGHT_WERSS_ACCESS_KEY", "WK-test")
    monkeypatch.setenv("WEINSIGHT_WERSS_SECRET_KEY", "secret-test")
    config = load_config(config_path)
    assert config.pipelines.article.sync_interval_minutes == 10
    assert config.pipelines.article.werss_catalog_base_url == "http://127.0.0.1:8001"
    assert config.pipelines.article.werss_access_key == "WK-test"
    assert config.pipelines.article.werss_secret_key == "secret-test"


@pytest.mark.parametrize("minutes", [0, 9, True])
def test_article_catalog_interval_rejects_values_below_ten(minutes):
    with pytest.raises(ValueError, match="sync_interval_minutes"):
        replace(valid_article_config(), sync_interval_minutes=minutes)


def test_load_config_expands_mysql_password() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.mysql.host == "127.0.0.1"
    assert config.mysql.port == 3307
    assert config.mysql.database == "weinsight_dev"
    assert config.mysql.password == os.environ["WEINSIGHT_MYSQL_PASSWORD"]


def test_pipeline_capacity_defaults_match_design() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.wechat.pc_version == "4.1.8.107"
    assert config.runtime.log_dir == "runtime/logs"
    assert config.runtime.screenshot_dir == "runtime/screenshots"
    assert config.runtime.report_dir == "runtime/reports"
    assert config.pipelines.group.core_group_limit == 5
    assert config.pipelines.article.account_limit == 20
    assert config.pipelines.article.crawl_time == "07:30"
    assert config.pipelines.article.account_poll_interval_minutes == 60
    assert config.pipelines.article.rss_max_concurrency == 4
    assert config.pipelines.article.rss_max_response_bytes == 5_242_880
    assert config.pipelines.article.rss_allowed_private_hosts == ("127.0.0.1:8001",)
    assert config.pipelines.article.content_base_url == "http://127.0.0.1:8001"
    assert config.pipelines.article.content_timeout_seconds == 30
    assert config.pipelines.article.content_max_response_bytes == 5_242_880
    assert config.pipelines.article.content_mode == "werss_first"
    assert config.pipelines.article.collect_today_only is True
    assert config.pipelines.article.dedup_enabled is True
    assert config.pipelines.article.dedup_key == "article_hash"
    assert config.pipelines.article.egg_price_extraction_enabled is True
    assert config.pipelines.article.price_items_json_preview_limit == 20
    assert config.pipelines.article.image_quote_note_enabled is True
    assert config.pipelines.article.browser_executable_path == "auto"
    assert config.pipelines.ui_resource.max_core_group_block_seconds == 10
    assert config.pipelines.ui_resource.lock_lease_seconds == 120


@pytest.mark.parametrize("field,value", [("content_mode", "bad"), ("content_base_url", "http://localhost:8001"), ("content_timeout_seconds", 4), ("content_timeout_seconds", 121), ("content_max_response_bytes", 0)])
def test_article_content_config_rejects_unsafe_values(tmp_path, field, value):
    raw = yaml.safe_load(Path("config/config.dev.yaml").read_text(encoding="utf-8"))
    raw["pipelines"]["article"][field] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="content_"):
        load_config(path)


@pytest.mark.parametrize("field", ["rss_max_concurrency", "rss_max_response_bytes"])
def test_rss_config_rejects_nonpositive_limits(tmp_path, field) -> None:
    path = _write_changed_config(
        tmp_path, lambda raw: raw["pipelines"]["article"].update({field: 0})
    )
    with pytest.raises(ValueError, match=field):
        load_config(path)


@pytest.mark.parametrize("hosts", [[], ["127.0.0.1"], ["127.0.0.1:0"], [" host:8001"]])
def test_rss_config_requires_exact_nonempty_host_port_entries(tmp_path, hosts) -> None:
    path = _write_changed_config(
        tmp_path,
        lambda raw: raw["pipelines"]["article"].update(
            {"rss_allowed_private_hosts": hosts}
        ),
    )
    with pytest.raises(ValueError, match="rss_allowed_private_hosts"):
        load_config(path)


def test_admin_web_config_defaults_are_explicit() -> None:
    config = load_config(Path("config/config.dev.yaml"))

    assert config.web.host == "127.0.0.1"
    assert config.web.port == 8848
    assert config.web.secure_cookie is False
    assert config.web.tls_certfile is None
    assert config.web.tls_keyfile is None
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
    monkeypatch.setenv("WEINSIGHT_TLS_CERTFILE", "C:/certs/weinsight.crt")
    monkeypatch.setenv("WEINSIGHT_TLS_KEYFILE", "C:/certs/weinsight.key")
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
    assert config.pipelines.article.account_poll_interval_minutes == 60
    assert config.pipelines.article.collect_today_only is True
    assert config.pipelines.article.dedup_enabled is True
    assert config.pipelines.article.dedup_key == "article_hash"
    assert config.pipelines.article.rss_max_concurrency == 4
    assert config.pipelines.article.egg_price_extraction_enabled is True
    assert config.pipelines.article.price_items_json_preview_limit == 20
    assert config.pipelines.article.image_quote_note_enabled is True
    assert config.pipelines.article.browser_executable_path == "auto"
    assert config.web.host == "10.20.30.40"
    assert config.web.secure_cookie is True
    assert config.web.tls_certfile == "C:/certs/weinsight.crt"
    assert config.web.tls_keyfile == "C:/certs/weinsight.key"
    assert config.workers.collector_mode == "real"
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
    assert raw["web"]["tls_certfile"] == "${WEINSIGHT_TLS_CERTFILE}"
    assert raw["web"]["tls_keyfile"] == "${WEINSIGHT_TLS_KEYFILE}"


def test_web_config_rejects_tls_certificate_without_key(tmp_path: Path) -> None:
    path = _write_changed_config(
        tmp_path,
        lambda raw: raw["web"].update(
            {
                "tls_certfile": "C:/certs/weinsight.crt",
                "tls_keyfile": None,
            }
        ),
    )

    with pytest.raises(ValueError, match="configured together"):
        load_config(path)


def test_web_config_requires_tls_when_secure_cookie_is_enabled(
    tmp_path: Path,
) -> None:
    path = _write_changed_config(
        tmp_path,
        lambda raw: raw["web"].update(
            {
                "secure_cookie": True,
                "tls_certfile": None,
                "tls_keyfile": None,
            }
        ),
    )

    with pytest.raises(
        ValueError,
        match="secure_cookie requires TLS certificate and key",
    ):
        load_config(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tls_certfile", ""),
        ("tls_keyfile", " C:/certs/weinsight.key"),
        ("tls_certfile", "C:/certs/weinsight\n.crt"),
        ("tls_certfile", "C:/certs/weinsight\u0080.crt"),
        ("tls_keyfile", "C:/certs/weinsight\u200b.key"),
        ("tls_keyfile", "C:/certs/weinsight\u202e.key"),
    ],
)
def test_web_config_rejects_unsafe_tls_paths(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = _write_changed_config(
        tmp_path,
        lambda raw: raw["web"].update(
            {
                "tls_certfile": "C:/certs/weinsight.crt",
                "tls_keyfile": "C:/certs/weinsight.key",
                field: value,
            }
        ),
    )

    with pytest.raises(ValueError, match=field):
        load_config(path)


@pytest.mark.parametrize(
    "host",
    ["", "localhost", "0.0.0.0", "::", "8.8.8.8", "224.0.0.1"],
)
def test_prod_config_rejects_non_private_bind_host(
    tmp_path: Path,
    host: str,
) -> None:
    def configure_prod(raw) -> None:
        raw["app"]["env"] = "prod"
        raw["web"].update(
            {
                "host": host,
                "secure_cookie": True,
                "tls_certfile": "C:/certs/weinsight.crt",
                "tls_keyfile": "C:/certs/weinsight.key",
            }
        )

    path = _write_changed_config(tmp_path, configure_prod)

    with pytest.raises(ValueError, match="private IP"):
        load_config(path)


@pytest.mark.parametrize(
    "host",
    [3232235777, b"\xc0\xa8\x01\x01"],
    ids=["integer", "bytes"],
)
def test_prod_config_rejects_non_string_private_bind_host(
    tmp_path: Path,
    host: object,
) -> None:
    def configure_prod(raw) -> None:
        raw["app"]["env"] = "prod"
        raw["web"].update(
            {
                "host": host,
                "secure_cookie": True,
                "tls_certfile": "C:/certs/weinsight.crt",
                "tls_keyfile": "C:/certs/weinsight.key",
            }
        )

    path = _write_changed_config(tmp_path, configure_prod)

    with pytest.raises(ValueError, match="private IP"):
        load_config(path)


@pytest.mark.parametrize("host", ["10.0.0.8", "172.16.0.8", "192.168.1.8"])
def test_prod_config_accepts_explicit_private_bind_host(
    tmp_path: Path,
    host: str,
) -> None:
    def configure_prod(raw) -> None:
        raw["app"]["env"] = "prod"
        raw["web"].update(
            {
                "host": host,
                "secure_cookie": True,
                "tls_certfile": "C:/certs/weinsight.crt",
                "tls_keyfile": "C:/certs/weinsight.key",
            }
        )

    config = load_config(_write_changed_config(tmp_path, configure_prod))

    assert config.web.host == host


@pytest.mark.parametrize("env", ["production", "Prod", "prod ", ""])
def test_config_rejects_unknown_environment_before_host_safety_check(
    tmp_path: Path,
    env: str,
) -> None:
    def configure_unknown_environment(raw) -> None:
        raw["app"]["env"] = env
        raw["web"]["host"] = "0.0.0.0"

    path = _write_changed_config(tmp_path, configure_unknown_environment)

    with pytest.raises(ValueError, match="app.env"):
        load_config(path)
