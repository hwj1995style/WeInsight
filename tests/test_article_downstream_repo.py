from datetime import date, datetime

import pytest

from app.domain.article_downstream import ArticleBackfillCommand, ArticleBackfillSummary
from app.storage.article_downstream_repo import MysqlArticleDownstreamRepo


class Result:
    def __init__(self, rows=(), rowcount=1): self.rows, self.rowcount = rows, rowcount
    def mappings(self): return self
    def all(self): return self.rows


class Connection:
    def __init__(self, rows=()): self.rows, self.calls = rows, []
    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        if "SELECT raw.article_hash" in str(statement): return Result(self.rows)
        return Result()
    def __enter__(self): return self
    def __exit__(self, *args): return False


class Engine:
    def __init__(self, rows=()): self.connection = Connection(rows)
    def begin(self): return self.connection


def command(**changes):
    values = dict(scope="single", source_id=7, start_date=date(2026, 7, 10),
                  end_date=date(2026, 7, 14), mode="missing_only", force_confirmed=False)
    values.update(changes)
    return ArticleBackfillCommand(**values)


def test_domain_dtos_have_exact_contract_and_are_immutable():
    cmd = command()
    assert cmd.scope == "single"
    with pytest.raises(Exception): cmd.scope = "enabled"
    assert ArticleBackfillSummary(1, 2, 3, 4, 5, 6, 7, 8).matched_article_count == 1


def test_set_processing_enabled_is_catalog_scoped_and_excludes_normalized_yixiangdan():
    engine = Engine()
    MysqlArticleDownstreamRepo(engine).set_processing_enabled(7, True)
    sql, params = engine.connection.calls[0]
    assert "downstream_clean_enabled = :processing_enabled" in sql
    assert "werss_source_id IS NOT NULL" in sql and "upstream_status = 'active'" in sql
    assert "REPLACE" in sql and "一箱蛋" in sql
    assert " enabled =" not in sql and "upstream_status = :" not in sql
    assert params == {"source_id": 7, "processing_enabled": 1}


def test_missing_only_status_matrix_and_bound_parameters():
    rows = [
        dict(article_hash="a", has_clean=0, has_analysis=0, clean_status=None, analyze_status=None),
        dict(article_hash="b", has_clean=0, has_analysis=0, clean_status="failed", analyze_status=None),
        dict(article_hash="c", has_clean=1, has_analysis=0, clean_status="success", analyze_status=None),
        dict(article_hash="d", has_clean=1, has_analysis=0, clean_status="success", analyze_status="failed"),
        dict(article_hash="e", has_clean=1, has_analysis=1, clean_status="success", analyze_status=None),
        dict(article_hash="f", has_clean=0, has_analysis=0, clean_status="running", analyze_status=None),
        dict(article_hash="g", has_clean=1, has_analysis=0, clean_status="success", analyze_status="pending"),
    ]
    engine = Engine(rows)
    summary = MysqlArticleDownstreamRepo(engine).enqueue_backfill(command(), datetime(2026, 7, 14, 12))
    assert summary == ArticleBackfillSummary(7, 1, 1, 1, 1, 1, 2, 0)
    select_sql, params = engine.connection.calls[0]
    assert "raw.publish_date BETWEEN :start_date AND :end_date" in select_sql
    assert "config.id = :source_id" in select_sql and "downstream_clean_enabled" not in select_sql
    assert "FOR UPDATE" in select_sql and "一箱蛋" in select_sql
    assert params["start_date"] == date(2026, 7, 10)
    writes = engine.connection.calls[1:]
    assert all("ON DUPLICATE KEY UPDATE" in sql for sql, _ in writes)
    assert all("status IN ('pending', 'running')" in sql for sql, _ in writes)


def test_enabled_scope_and_force_analyze_matrix():
    rows = [
        dict(article_hash="a", has_clean=0, has_analysis=0, clean_status=None, analyze_status=None),
        dict(article_hash="b", has_clean=1, has_analysis=1, clean_status="success", analyze_status="success"),
        dict(article_hash="c", has_clean=1, has_analysis=0, clean_status="success", analyze_status="running"),
        dict(article_hash="d", has_clean=1, has_analysis=0, clean_status="success", analyze_status=None),
        dict(article_hash="e", has_clean=1, has_analysis=0, clean_status="success", analyze_status="pending"),
    ]
    engine = Engine(rows)
    summary = MysqlArticleDownstreamRepo(engine).enqueue_backfill(
        command(scope="enabled", source_id=None, mode="force_analyze", force_confirmed=True),
        datetime(2026, 7, 14, 12),
    )
    assert summary == ArticleBackfillSummary(5, 0, 0, 1, 2, 0, 1, 1)
    sql, params = engine.connection.calls[0]
    assert "config.downstream_clean_enabled = 1" in sql
    assert "config.id = :source_id" not in sql
    assert "DELETE" not in " ".join(call[0] for call in engine.connection.calls)
    assert "source_id" not in params
    assert "status = 'running'" in engine.connection.calls[-1][0]
