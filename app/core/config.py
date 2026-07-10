from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


@dataclass(frozen=True)
class AppConfig:
    env: str
    timezone: str
    log_level: str


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
    max_accounts_per_ui_slice: int
    collect_today_only: bool
    dedup_enabled: bool
    dedup_key: str
    ui_slice_timeout_seconds: int
    rpa_timeout_seconds: int
    browser_executable_path: str | None
    state_machine_enabled: bool
    parse_after_release_ui: bool
    resume_from_progress: bool
    min_article_ui_window_seconds: int
    low_peak_windows: tuple[str, ...]
    route_cache_enabled: bool
    route_probe_enabled: bool
    route_probe_failure_threshold: int
    route_entry_labels: tuple[str, ...]
    link_extract_methods: tuple[str, ...]
    egg_price_extraction_enabled: bool
    price_items_json_preview_limit: int
    image_quote_note_enabled: bool


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
        "route_cache_enabled": True,
        "route_probe_enabled": True,
        "route_probe_failure_threshold": 3,
        "route_entry_labels": [
            "历史消息",
            "全部消息",
            "往期文章",
            "文章",
            "资讯",
            "蛋价资讯",
            "今日价格",
            "闽融平台",
        ],
        "link_extract_methods": [
            "copy_link_menu",
            "uia_value",
            "visible_text",
        ],
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
                    "low_peak_windows": tuple(article_data["low_peak_windows"]),
                    "route_entry_labels": tuple(article_data["route_entry_labels"]),
                    "link_extract_methods": tuple(article_data["link_extract_methods"]),
                }
            ),
            ui_resource=UiResourceConfig(**data["pipelines"]["ui_resource"]),
        ),
        mysql=MysqlConfig(**data["mysql"]),
        web=WebConfig(**data["web"]),
        auth=AuthConfig(**data["auth"]),
        workers=WorkersConfig(**data["workers"]),
    )
