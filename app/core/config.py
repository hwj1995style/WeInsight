from __future__ import annotations

import os
import re
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from unicodedata import category

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass(frozen=True)
class AppConfig:
    env: str
    timezone: str
    log_level: str

    def __post_init__(self) -> None:
        if self.env not in {"dev", "prod"}:
            raise ValueError("app.env must be dev or prod")


@dataclass(frozen=True)
class WechatConfig:
    pc_version: str
    window_title: str
    fixed_window: bool
    check_login_interval_seconds: int


@dataclass(frozen=True)
class MysqlConfig:
    host: str
    port: int
    database: str
    username: str
    password: str


@dataclass(frozen=True)
class RuntimeConfig:
    log_dir: str
    screenshot_dir: str
    report_dir: str


@dataclass(frozen=True)
class GroupPipelineConfig:
    enabled: bool
    core_group_limit: int
    poll_interval_seconds: int
    max_group_per_round: int
    rpa_timeout_seconds: int
    target_round_seconds: int


@dataclass(frozen=True)
class ArticlePipelineConfig:
    enabled: bool
    account_limit: int
    crawl_time: str
    account_poll_interval_minutes: int
    max_articles_per_account: int
    collect_today_only: bool
    dedup_enabled: bool
    dedup_key: str
    browser_executable_path: str | None
    parse_after_release_ui: bool
    egg_price_extraction_enabled: bool
    price_items_json_preview_limit: int
    image_quote_note_enabled: bool
    rss_max_concurrency: int = 4
    rss_max_response_bytes: int = 5_242_880
    rss_allowed_private_hosts: tuple[str, ...] = ("127.0.0.1:8001",)
    content_base_url: str = "http://127.0.0.1:8001"
    content_timeout_seconds: int = 30
    content_max_response_bytes: int = 5_242_880
    content_mode: str = "web"

    def __post_init__(self) -> None:
        if self.content_mode not in {"web", "shadow", "werss_first"}:
            raise ValueError("content_mode must be web, shadow or werss_first")
        parsed = urlsplit(self.content_base_url)
        endpoint = (
            parsed.scheme, parsed.hostname, parsed.port, parsed.path,
            parsed.query, parsed.fragment, parsed.username, parsed.password,
        )
        if endpoint != ("http", "127.0.0.1", 8001, "", "", "", None, None):
            raise ValueError("content_base_url must be http://127.0.0.1:8001")
        if isinstance(self.content_timeout_seconds, bool) or not isinstance(self.content_timeout_seconds, int) or not 5 <= self.content_timeout_seconds <= 120:
            raise ValueError("content_timeout_seconds must be an integer from 5 to 120")
        if isinstance(self.content_max_response_bytes, bool) or not isinstance(self.content_max_response_bytes, int) or self.content_max_response_bytes < 1:
            raise ValueError("content_max_response_bytes must be a positive integer")
        for field in ("rss_max_concurrency", "rss_max_response_bytes"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field} must be a positive integer")
        if not self.rss_allowed_private_hosts:
            raise ValueError("rss_allowed_private_hosts must not be empty")
        pattern = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\]):([1-9][0-9]{0,4})$")
        for endpoint in self.rss_allowed_private_hosts:
            if not isinstance(endpoint, str) or endpoint != endpoint.strip():
                raise ValueError("rss_allowed_private_hosts entries must be exact host:port values")
            match = pattern.fullmatch(endpoint)
            if match is None or int(match.group(1)) > 65535:
                raise ValueError("rss_allowed_private_hosts entries must be exact host:port values")


@dataclass(frozen=True)
class UiResourceConfig:
    mode: str
    group_priority: bool
    max_core_group_block_seconds: int
    lock_acquire_timeout_seconds: int
    lock_lease_seconds: int
    lock_heartbeat_interval_seconds: int
    stale_lock_recover_seconds: int
    metrics_enabled: bool


@dataclass(frozen=True)
class PipelineConfig:
    group: GroupPipelineConfig
    article: ArticlePipelineConfig
    ui_resource: UiResourceConfig


@dataclass(frozen=True)
class WebConfig:
    host: str
    port: int
    secure_cookie: bool
    tls_certfile: str | None
    tls_keyfile: str | None

    def __post_init__(self) -> None:
        for field in ("tls_certfile", "tls_keyfile"):
            value = getattr(self, field)
            if value is None:
                continue
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or any(category(character).startswith("C") for character in value)
            ):
                raise ValueError(f"{field} must be a non-empty trimmed path")

        has_cert = self.tls_certfile is not None
        has_key = self.tls_keyfile is not None
        if has_cert != has_key:
            raise ValueError("tls_certfile and tls_keyfile must be configured together")
        if self.secure_cookie and not (has_cert and has_key):
            raise ValueError("secure_cookie requires TLS certificate and key")


@dataclass(frozen=True)
class AuthConfig:
    default_username: str
    session_cookie_name: str
    csrf_cookie_name: str
    session_idle_minutes: int
    session_absolute_minutes: int
    login_failure_limit: int
    login_lock_minutes: int


@dataclass(frozen=True)
class WorkersConfig:
    collector_mode: str
    schedule_tick_seconds: int
    heartbeat_seconds: int
    run_lease_seconds: int
    pipeline_tick_seconds: int
    group_clean_batch_size: int
    group_analysis_batch_size: int
    article_parse_batch_size: int
    article_analysis_batch_size: int

    def __post_init__(self) -> None:
        if self.collector_mode not in {"fake", "real"}:
            raise ValueError("collector_mode must be fake or real")
        for field in (
            "schedule_tick_seconds",
            "heartbeat_seconds",
            "run_lease_seconds",
            "pipeline_tick_seconds",
            "group_clean_batch_size",
            "group_analysis_batch_size",
            "article_parse_batch_size",
            "article_analysis_batch_size",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field} must be a positive integer")


@dataclass(frozen=True)
class Config:
    app: AppConfig
    wechat: WechatConfig
    runtime: RuntimeConfig
    pipelines: PipelineConfig
    mysql: MysqlConfig
    web: WebConfig
    auth: AuthConfig
    workers: WorkersConfig

    def __post_init__(self) -> None:
        if self.app.env != "prod":
            return
        host_value = self.web.host
        if (
            not isinstance(host_value, str)
            or not host_value
            or host_value != host_value.strip()
            or any(category(character).startswith("C") for character in host_value)
        ):
            raise ValueError("prod web.host must be an explicit private IP")
        try:
            host = ip_address(host_value)
        except ValueError:
            raise ValueError("prod web.host must be an explicit private IP") from None
        private_networks = (
            ip_network("10.0.0.0/8"),
            ip_network("172.16.0.0/12"),
            ip_network("192.168.0.0/16"),
            ip_network("fc00::/7"),
        )
        if not any(host in network for network in private_networks):
            raise ValueError("prod web.host must be an explicit private IP")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise RuntimeError(f"Missing environment variable: {name}")
            return os.environ[name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = _expand_env(raw)
    article_data = {
        "browser_executable_path": "auto",
        "rss_max_concurrency": 4,
        "rss_max_response_bytes": 5_242_880,
        "rss_allowed_private_hosts": ["127.0.0.1:8001"],
        "content_base_url": "http://127.0.0.1:8001",
        "content_timeout_seconds": 30,
        "content_max_response_bytes": 5_242_880,
        "content_mode": "web",
        "egg_price_extraction_enabled": True,
        "price_items_json_preview_limit": 20,
        "image_quote_note_enabled": True,
        **data["pipelines"]["article"],
    }

    return Config(
        app=AppConfig(**data["app"]),
        wechat=WechatConfig(**data["wechat"]),
        runtime=RuntimeConfig(**data["runtime"]),
        pipelines=PipelineConfig(
            group=GroupPipelineConfig(**data["pipelines"]["group"]),
            article=ArticlePipelineConfig(
                **{
                    **article_data,
                    "rss_allowed_private_hosts": tuple(article_data["rss_allowed_private_hosts"]),
                }
            ),
            ui_resource=UiResourceConfig(**data["pipelines"]["ui_resource"]),
        ),
        mysql=MysqlConfig(**data["mysql"]),
        web=WebConfig(**data["web"]),
        auth=AuthConfig(**data["auth"]),
        workers=WorkersConfig(**data["workers"]),
    )
