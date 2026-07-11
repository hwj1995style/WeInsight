from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine

from app.core.config import Config
from app.domain.collection_jobs import APPLICATION_TIMEZONE
from app.pipelines.rss_article_collect_service import RssArticleCollectService, RssArticleTarget
from app.pipelines.rss_article_polling_runner import RssArticlePollingRunner
from app.rss.feed_client import RssFeedClient
from app.pipelines.group_collect_service import GroupCollectService
from app.pipelines.group_polling_runner import (
    GroupPollingRunner,
    GroupPollingTarget,
)
from app.rpa.desktop_probe import (
    WechatDesktopProbe,
    WechatHealth,
    WechatHealthStatus,
)
from app.rpa.fake_clients import (
    FakeDesktopClient,
    FakeGroupRpaClient,
)
from app.services.wechat_health_monitor import WechatHealthMonitor
from app.storage.article_log_repo import MysqlArticleCollectLogRepo
from app.storage.article_config_repo import MysqlArticleAccountConfigRepo
from app.storage.article_raw_repo import MysqlArticleRawRepo
from app.storage.collection_event_repo import MysqlCollectionEventRepo
from app.storage.collection_runtime_repo import MysqlCollectionRuntimeRepo
from app.storage.db import create_mysql_engine
from app.storage.group_repo import (
    MysqlGroupCollectLogRepo,
    MysqlGroupMessageRepo,
)
from app.storage.lock_repo import MysqlUiLockRepo
from app.storage.wechat_health_repo import MysqlWechatHealthRepo
from app.storage.worker_heartbeat_repo import MysqlWorkerHeartbeatRepo
from app.workers.collector_worker import (
    ManagedCollectorWorker,
    default_worker_identity,
)


_ZONE = ZoneInfo(APPLICATION_TIMEZONE)


def build_managed_collector_worker(
    config: Config,
    *,
    engine: Engine | None = None,
    worker_id: str | None = None,
    hostname: str | None = None,
    process_id: int | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> ManagedCollectorWorker:
    mode = config.workers.collector_mode
    if mode not in {"fake", "real"}:
        raise ValueError("collector_mode must be fake or real")
    shared_engine = engine or create_mysql_engine(config.mysql)
    clock = now_provider or _shanghai_now
    identity = default_worker_identity()
    selected_worker_id = worker_id or identity[0]
    selected_hostname = hostname or identity[1]
    selected_process_id = process_id or identity[2]

    runtime_repo = MysqlCollectionRuntimeRepo(shared_engine)
    event_repo = MysqlCollectionEventRepo(shared_engine)
    heartbeat_repo = MysqlWorkerHeartbeatRepo(shared_engine)
    health_repo = MysqlWechatHealthRepo(shared_engine)
    ui_lock_repo = MysqlUiLockRepo(shared_engine)
    group_message_repo = MysqlGroupMessageRepo(shared_engine)
    group_log_repo = MysqlGroupCollectLogRepo(shared_engine)
    article_raw_repo = MysqlArticleRawRepo(shared_engine)
    article_log_repo = MysqlArticleCollectLogRepo(shared_engine)
    article_config_repo = MysqlArticleAccountConfigRepo(shared_engine)

    if mode == "fake":
        group_rpa: Any = FakeGroupRpaClient([])
        screenshot_client: Any = FakeDesktopClient(
            version=config.wechat.pc_version,
            logged_in=True,
        )
        desktop_probe: Any = _FixedDesktopProbe(config.wechat.pc_version)
        window_probe: Any = _TrueProbe()
        login_probe: Any = _TrueProbe()
        rpa_probe: Any = _TrueProbe()
        real_bundle = None
    else:
        real_bundle = _LazyRealAdapters(config, shared_engine)
        group_rpa = _LazyGroupRpa(real_bundle)
        screenshot_client = _LazyScreenshot(real_bundle)
        desktop_probe = WechatDesktopProbe(
            expected_version=config.wechat.pc_version
        )
        window_probe = _RealWindowProbe()
        login_probe = _RealLoginProbe()
        rpa_probe = _RealRpaProbe(real_bundle)

    group_collect_service = GroupCollectService(
        rpa=group_rpa,
        repo=group_message_repo,
    )
    allowed_host = config.pipelines.article.rss_allowed_private_hosts[0]
    host, _, port = allowed_host.partition(":")
    article_collect_service = RssArticleCollectService(
        feed_client=RssFeedClient(allowed_endpoint=(host, int(port or 8001))),
        raw_repo=article_raw_repo,
        state_repo=article_config_repo,
    )

    def group_runner_factory(
        target: GroupPollingTarget, batch_id: str
    ) -> GroupPollingRunner:
        return GroupPollingRunner(
            collect_service=group_collect_service,
            lock_repo=ui_lock_repo,
            group_provider=lambda current, limit: (target,),
            log_repo=group_log_repo,
            screenshot_client=screenshot_client,
            screenshot_root=Path(config.runtime.screenshot_dir).resolve(),
            lease_seconds=config.pipelines.ui_resource.lock_lease_seconds,
            lock_acquire_timeout_seconds=(
                config.pipelines.ui_resource.lock_acquire_timeout_seconds
            ),
            max_groups_per_round=1,
            batch_id_factory=lambda group_name: batch_id,
        )

    def article_runner_factory(
        target: RssArticleTarget,
        batch_id: str,
        stop_provider: Callable[[], bool],
    ):
        runner = RssArticlePollingRunner(
            collect_service=article_collect_service,
            log_repo=article_log_repo,
            batch_id_factory=lambda account_name: batch_id,
        )
        return _SingleRssTargetRunner(runner, target, stop_provider)

    health_monitor = WechatHealthMonitor(
        desktop_probe=desktop_probe,
        window_probe=window_probe,
        login_probe=login_probe,
        rpa_probe=rpa_probe,
        ui_lock_repo=ui_lock_repo,
        health_repo=health_repo,
        event_repo=event_repo,
        hostname=selected_hostname,
        worker_id=selected_worker_id,
        check_login_interval_seconds=(
            config.wechat.check_login_interval_seconds
        ),
    )
    return ManagedCollectorWorker(
        runtime_repo=runtime_repo,
        event_repo=event_repo,
        heartbeat_repo=heartbeat_repo,
        health_monitor=health_monitor,
        group_runner_factory=group_runner_factory,
        article_runner_factory=article_runner_factory,
        worker_id=selected_worker_id,
        hostname=selected_hostname,
        process_id=selected_process_id,
        version="managed-collector-v1",
        start_time=clock(),
        run_lease_seconds=config.workers.run_lease_seconds,
        now_provider=clock,
    )


class _FixedDesktopProbe:
    def __init__(self, version: str) -> None:
        self.version = version

    def check(self) -> WechatHealth:
        return WechatHealth(
            status=WechatHealthStatus.OK,
            message="Fake WeChat desktop probe is healthy.",
            version=self.version,
        )


class _TrueProbe:
    def check(self) -> bool:
        return True


class _LazyRealAdapters:
    def __init__(self, config: Config, engine: Engine) -> None:
        self.config = config
        self.engine = engine
        self._group = None
        self._screenshot = None

    def group(self):
        self._ensure_rpa()
        return self._group

    def screenshot(self):
        if self._screenshot is None:
            from app.rpa.screenshots import DesktopScreenshotClient

            self._screenshot = DesktopScreenshotClient()
        return self._screenshot

    def _ensure_rpa(self) -> None:
        if self._group is not None:
            return
        from app.rpa.wxauto_client import WxautoGroupRpaClient

        group = WxautoGroupRpaClient()
        self._group = group


class _LazyGroupRpa:
    def __init__(self, bundle: _LazyRealAdapters) -> None:
        self.bundle = bundle

    def open_group(self, group_name: str) -> None:
        self.bundle.group().open_group(group_name)

    def read_visible_messages(self):
        return self.bundle.group().read_visible_messages()

    def scroll_up_messages(self, pages: int = 1) -> None:
        self.bundle.group().scroll_up_messages(pages)


class _SingleRssTargetRunner:
    def __init__(self, runner, target, stop_provider) -> None:
        self.runner = runner
        self.target = target
        self.stop_provider = stop_provider

    def run_once(self, now: datetime):
        return self.runner.run((self.target,), now, self.stop_provider)


class _LazyScreenshot:
    def __init__(self, bundle: _LazyRealAdapters) -> None:
        self.bundle = bundle

    def save_screenshot(self, path: str) -> str:
        return self.bundle.screenshot().save_screenshot(path)


_MAIN_WINDOW_CLASSES = ("mmui::MainWindow", "WeChatMainWndForPC")
_LOGIN_WINDOW_CLASSES = ("mmui::LoginWindow", "WeChatLoginWndForPC")


class _RealWindowProbe:
    def __init__(self, desktop_factory: Callable[[], Any] | None = None) -> None:
        self.desktop_factory = desktop_factory

    def check(self) -> bool:
        desktop = _desktop(self.desktop_factory)
        return _any_window_exists(
            desktop,
            _MAIN_WINDOW_CLASSES + _LOGIN_WINDOW_CLASSES,
        )


class _RealLoginProbe:
    def __init__(self, desktop_factory: Callable[[], Any] | None = None) -> None:
        self.desktop_factory = desktop_factory

    def check(self) -> bool:
        desktop = _desktop(self.desktop_factory)
        return _any_window_exists(desktop, _MAIN_WINDOW_CLASSES)


class _RealRpaProbe:
    def __init__(self, bundle: _LazyRealAdapters) -> None:
        self.bundle = bundle

    def check(self) -> bool:
        group = self.bundle.group()
        return all(
            callable(value)
            for value in (
                getattr(group, "open_group", None),
                getattr(group, "read_visible_messages", None),
            )
        )


def _shanghai_now() -> datetime:
    return datetime.now(_ZONE)


def _desktop(factory: Callable[[], Any] | None):
    if factory is not None:
        return factory()
    from pywinauto import Desktop

    return Desktop(backend="uia")


def _any_window_exists(desktop, class_names: tuple[str, ...]) -> bool:
    for class_name in class_names:
        try:
            if desktop.window(class_name=class_name).exists(timeout=1):
                return True
        except Exception:
            continue
    return False
