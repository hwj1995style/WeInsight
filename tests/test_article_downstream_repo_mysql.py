from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import load_config
from app.domain.article_downstream import ArticleBackfillCommand
from app.storage.article_downstream_repo import MysqlArticleDownstreamRepo
from app.storage.db import create_mysql_engine


pytestmark = pytest.mark.mysql_integration


def _engine_or_skip():
    password = os.getenv("WEINSIGHT_MYSQL_PASSWORD") or os.getenv("WEINSIGHT_TEST_MYSQL_PASSWORD")
    if not password:
        pytest.skip("MySQL integration password is unavailable")
    os.environ["WEINSIGHT_MYSQL_PASSWORD"] = password
    os.environ.setdefault("WEINSIGHT_WERSS_ACCESS_KEY", "WK-test")
    os.environ.setdefault("WEINSIGHT_WERSS_SECRET_KEY", "SK-test")
    engine = create_mysql_engine(load_config(Path("config/config.dev.yaml")).mysql)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        engine.dispose()
        pytest.skip(f"MySQL integration database unavailable: {exc.orig.args[0]}")
    return engine


def test_two_real_connections_are_idempotent_and_leave_zero_synthetic_residue():
    engine = _engine_or_skip()
    prefix = f"CodexConcurrencyTest-{uuid.uuid4().hex}"
    hashes = {
        "new_clean": f"{prefix}-nc",
        "failed_analyze": f"{prefix}-fa",
        "pending_clean": f"{prefix}-pc",
        "running_analyze": f"{prefix}-ra",
    }
    source_id = None
    cleanup_verified = False
    try:
        with engine.begin() as connection:
            source_id = connection.execute(text("""
                INSERT INTO wechat_public_account_config (
                    account_name, account_type, feed_url, source_type, werss_source_id,
                    upstream_status, enabled, downstream_clean_enabled
                ) VALUES (
                    :prefix, 'subscription', :safe_url, 'rss', :prefix,
                    'active', 0, 1
                )
            """), {"prefix": prefix, "safe_url": f"https://invalid.example/{prefix}"}).lastrowid
            raw_rows = [
                {"article_hash": value, "account_name": prefix,
                 "title": f"{prefix}-synthetic", "article_url": "https://invalid.example/synthetic",
                 "publish_time": datetime(2026, 7, 14, 8), "publish_date": date(2026, 7, 14),
                 "collect_time": datetime(2026, 7, 14, 8, 1)}
                for value in hashes.values()
            ]
            connection.execute(text("""
                INSERT INTO wechat_article_raw (
                    article_hash, account_name, title, article_url,
                    publish_time, publish_date, collect_time
                ) VALUES (
                    :article_hash, :account_name, :title, :article_url,
                    :publish_time, :publish_date, :collect_time
                )
            """), raw_rows)
            clean_rows = [{"article_hash": hashes[key], "account_name": prefix,
                           "title": f"{prefix}-synthetic", "article_url": "https://invalid.example/synthetic",
                           "parse_time": datetime(2026, 7, 14, 8, 2)}
                          for key in ("failed_analyze", "running_analyze")]
            connection.execute(text("""
                INSERT INTO wechat_article_clean (
                    article_hash, account_name, title, article_url, parse_time
                ) VALUES (
                    :article_hash, :account_name, :title, :article_url, :parse_time
                )
            """), clean_rows)
            connection.execute(text("""
                INSERT INTO wechat_article_process_task (
                    task_type, ref_type, ref_id, status, retry_count, next_run_time, error_msg
                ) VALUES
                    ('analyze_article', 'article', :failed_hash, 'failed', 2, NULL, 'synthetic-safe-error'),
                    ('clean_article', 'article', :pending_hash, 'pending', 2, :old_time, 'keep-pending'),
                    ('analyze_article', 'article', :running_hash, 'running', 3, :old_time, 'keep-running')
            """), {"failed_hash": hashes["failed_analyze"],
                     "pending_hash": hashes["pending_clean"],
                     "running_hash": hashes["running_analyze"],
                     "old_time": datetime(2026, 7, 14, 7)})

        command = ArticleBackfillCommand(
            scope="single", source_id=int(source_id),
            start_date=date(2026, 7, 14), end_date=date(2026, 7, 14),
            mode="missing_only", force_confirmed=False,
        )
        barrier = threading.Barrier(2)

        def enqueue():
            # Keep a distinct real connection checked out in each thread while the
            # repository obtains its transaction connection from the same pool.
            with engine.connect() as witness:
                connection_id = witness.execute(text("SELECT CONNECTION_ID()" )).scalar_one()
                barrier.wait(timeout=10)
                summary = MysqlArticleDownstreamRepo(engine).enqueue_backfill(
                    command, datetime(2026, 7, 14, 12)
                )
            return connection_id, summary

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=20) for future in (pool.submit(enqueue), pool.submit(enqueue))]
        assert len({connection_id for connection_id, _ in results}) == 2
        summaries = [summary for _, summary in results]

        assert sum(item.clean_task_created_count for item in summaries) == 1
        assert sum(item.clean_task_recovered_count for item in summaries) == 0
        assert sum(item.analyze_task_created_count for item in summaries) == 0
        assert sum(item.analyze_task_recovered_count for item in summaries) == 1
        assert sum(item.running_task_skipped_count for item in summaries) == 6
        with engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT ref_id, status, retry_count, next_run_time, error_msg
                FROM wechat_article_process_task
                WHERE ref_id LIKE :prefix
                ORDER BY ref_id
            """), {"prefix": f"{prefix}%"}).mappings().all()
        assert len(rows) == 4
        by_hash = {row["ref_id"]: row for row in rows}
        assert by_hash[hashes["new_clean"]]["status"] == "pending"
        assert (by_hash[hashes["failed_analyze"]]["status"],
                by_hash[hashes["failed_analyze"]]["retry_count"],
                by_hash[hashes["failed_analyze"]]["error_msg"]) == ("pending", 0, None)
        for key, expected in (("pending_clean", ("pending", 2, "keep-pending")),
                              ("running_analyze", ("running", 3, "keep-running"))):
            row = by_hash[hashes[key]]
            assert (row["status"], row["retry_count"], row["error_msg"]) == expected
            assert row["next_run_time"] == datetime(2026, 7, 14, 7)
    finally:
        try:
            with engine.begin() as connection:
                params = {"prefix": f"{prefix}%"}
                connection.execute(text("DELETE FROM wechat_article_analysis WHERE article_hash LIKE :prefix"), params)
                connection.execute(text("DELETE FROM wechat_article_clean WHERE article_hash LIKE :prefix"), params)
                connection.execute(text("DELETE FROM wechat_article_process_task WHERE ref_id LIKE :prefix"), params)
                connection.execute(text("DELETE FROM wechat_article_raw WHERE article_hash LIKE :prefix"), params)
                connection.execute(text("DELETE FROM wechat_public_account_config WHERE account_name LIKE :prefix"), params)
            with engine.connect() as connection:
                residue = connection.execute(text("""
                    SELECT
                      (SELECT COUNT(*) FROM wechat_public_account_config WHERE account_name LIKE :prefix) +
                      (SELECT COUNT(*) FROM wechat_article_raw WHERE article_hash LIKE :prefix) +
                      (SELECT COUNT(*) FROM wechat_article_clean WHERE article_hash LIKE :prefix) +
                      (SELECT COUNT(*) FROM wechat_article_analysis WHERE article_hash LIKE :prefix) +
                      (SELECT COUNT(*) FROM wechat_article_process_task WHERE ref_id LIKE :prefix)
                      AS residue_count
                """), {"prefix": f"{prefix}%"}).scalar_one()
            assert residue == 0
            cleanup_verified = True
        finally:
            engine.dispose()
        assert cleanup_verified
