from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import load_config
from app.storage.article_source_status_repo import MysqlArticleSourceStatusRepo
from app.storage.db import create_mysql_engine


def _engine_or_skip():
    password = os.getenv("WEINSIGHT_MYSQL_PASSWORD") or os.getenv("WEINSIGHT_TEST_MYSQL_PASSWORD")
    if not password:
        pytest.skip("rotated read-only test password is not available")
    os.environ["WEINSIGHT_MYSQL_PASSWORD"] = password
    os.environ.setdefault("WEINSIGHT_WERSS_ACCESS_KEY", "WK-test")
    os.environ.setdefault("WEINSIGHT_WERSS_SECRET_KEY", "SK-test")
    engine = create_mysql_engine(load_config(Path("config/config.dev.yaml")).mysql)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"MySQL 8 test database unavailable: {exc.orig.args[0]}")
    return engine


def test_read_only_status_query_matches_independent_mysql_aggregates():
    engine = _engine_or_skip()
    repo = MysqlArticleSourceStatusRepo(engine)
    rows = repo.list_status_page(limit=101, offset=0)
    assert len({row.account_name for row in rows}) == len(rows)
    assert all(row.werss_source_id is not None for row in rows)
    assert all(row.upstream_status in {"active", "disabled"} for row in rows)
    with engine.connect() as connection:
        for row in rows:
            expected_config = connection.execute(text("""
                SELECT id, enabled, downstream_clean_enabled
                FROM wechat_public_account_config
                WHERE id = :source_id AND account_name = :account_name
            """), {
                "source_id": row.source_id,
                "account_name": row.account_name,
            }).mappings().one()
            assert row.source_id == int(expected_config["id"])
            assert row.collection_enabled is bool(expected_config["enabled"])
            assert row.downstream_processing_enabled is bool(expected_config["downstream_clean_enabled"])
            expected = connection.execute(text("""
                SELECT
                  (SELECT COUNT(*) FROM wechat_article_raw r WHERE r.account_name = :name) article_count,
                  (SELECT COUNT(*) FROM wechat_article_process_task t JOIN wechat_article_raw r ON r.article_hash=t.ref_id WHERE r.account_name=:name AND t.ref_type='article' AND t.task_type='clean_article' AND t.status IN ('pending','running')) pending_parse_count,
                  (SELECT COUNT(*) FROM wechat_article_process_task t JOIN wechat_article_raw r ON r.article_hash=t.ref_id WHERE r.account_name=:name AND t.ref_type='article' AND t.task_type='analyze_article' AND t.status IN ('pending','running')) pending_analyze_count,
                  (SELECT COUNT(*) FROM wechat_article_process_task t JOIN wechat_article_raw r ON r.article_hash=t.ref_id WHERE r.account_name=:name AND t.ref_type='article' AND t.status='failed') failed_count,
                  (SELECT l.status FROM wechat_article_collect_log l WHERE l.account_name=:name ORDER BY l.start_time DESC,l.id DESC LIMIT 1) last_collect_status
            """), {"name": row.account_name}).mappings().one()
            assert (row.article_count, row.pending_parse_count, row.pending_analyze_count, row.failed_count, row.last_collect_status) == tuple(expected.values())


def test_read_only_status_query_pagination_has_no_duplicate_rows():
    repo = MysqlArticleSourceStatusRepo(_engine_or_skip())
    all_rows = repo.list_status_page(limit=1000, offset=0)
    paged = []
    for offset in range(0, len(all_rows) + 1, 2):
        paged.extend(repo.list_status_page(limit=2, offset=offset))
    assert [row.account_name for row in paged] == [row.account_name for row in all_rows]
