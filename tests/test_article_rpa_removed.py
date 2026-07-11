from pathlib import Path


REMOVED_MODULES = (
    "app/pipelines/article_collect_service.py",
    "app/pipelines/article_polling_runner.py",
    "app/pipelines/article_pipeline.py",
    "app/pipelines/article_interrupt_resume.py",
    "app/pipelines/article_core_group_due_provider.py",
    "app/rpa/article_link_extraction.py",
    "app/storage/article_route_cache_repo.py",
    "app/storage/article_progress_repo.py",
)


def test_article_rpa_modules_and_cli_are_removed() -> None:
    for path in REMOVED_MODULES:
        assert not Path(path).exists(), path

    main = Path("app/main.py").read_text(encoding="utf-8")
    assert "collect-article-once" not in main
    assert "run-article-scheduler" not in main


def test_public_account_rpa_types_are_removed_but_group_rpa_remains() -> None:
    interfaces = Path("app/rpa/interfaces.py").read_text(encoding="utf-8")
    fake_clients = Path("app/rpa/fake_clients.py").read_text(encoding="utf-8")
    wxauto_client = Path("app/rpa/wxauto_client.py").read_text(encoding="utf-8")

    assert "WechatArticleRpaClient" not in interfaces
    assert "FakeArticleRpaClient" not in fake_clients
    assert "WxautoArticleRpaClient" not in wxauto_client
    assert "WechatGroupRpaClient" in interfaces
    assert "FakeGroupRpaClient" in fake_clients
    assert "WxautoGroupRpaClient" in wxauto_client


def test_drop_migration_has_operational_gate_and_validated_feed_url_backfill() -> None:
    migration = Path("sql/migrations/20260711_003_drop_article_rpa_state.sql")
    sql = migration.read_text(encoding="utf-8")
    normalized = sql.upper()

    assert "24" in sql and "POC" in normalized
    assert "BACKUP" in normalized or "备份" in sql
    assert "DROP TABLE IF EXISTS WECHAT_ARTICLE_ROUTE_CACHE" in normalized
    assert "DROP TABLE IF EXISTS WECHAT_ARTICLE_COLLECT_PROGRESS" in normalized
    assert normalized.index("FEED_URL IS NULL") < normalized.index("MODIFY COLUMN FEED_URL")
    assert "FEED_URL VARCHAR(2048) NOT NULL" in normalized
