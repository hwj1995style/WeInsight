from __future__ import annotations

import sys

import pytest

import app.main as main_module
from app.main import main
from app.pipelines.article_polling_runner import ArticlePollingRunResult


def test_run_article_scheduler_requires_once(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "run-article-scheduler", "--config", "config/config.dev.yaml"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "--once is required for run-article-scheduler in development" in error


def test_run_article_scheduler_once_outputs_safe_counts(monkeypatch, capsys) -> None:
    class Guard:
        def __init__(self) -> None:
            self.calls = []

        def ensure_scheduler_allowed(self, now):
            self.calls.append(now)

    class FakeRunner:
        def run_once(self, now):
            return ArticlePollingRunResult(
                attempted_count=1,
                success_count=1,
                failed_count=0,
                lock_timeout_count=0,
                interrupted_count=0,
            )

    guard = Guard()
    monkeypatch.setattr(
        main_module, "build_managed_mode_guard", lambda config: guard
    )
    monkeypatch.setattr(main_module, "build_real_article_scheduler_runner", lambda config: FakeRunner())
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["weinsight", "run-article-scheduler", "--config", "config/config.dev.yaml", "--once"],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "attempted_count=1" in output
    assert "success_count=1" in output
    assert "failed_count=0" in output
    assert "lock_timeout_count=0" in output
    assert "interrupted_count=0" in output
    assert "mp.weixin.qq.com" not in output
    assert "article_url" not in output
    assert "article_body" not in output
    assert len(guard.calls) == 2
