from __future__ import annotations

from pathlib import Path

from app.security.output_policy import (
    EXPORTED_GROUP_REPORT_GLOB,
    SAFE_CLI_OUTPUT_KEYS_BY_COMMAND,
    SENSITIVE_BODY_FIELD_NAMES,
    USER_FACING_DOC_PATHS,
)


REQUIRED_OPERATIONAL_COMMANDS = {
    "wechat-health",
    "article-account-list",
    "article-account-upsert",
    "article-account-disable",
    "parse-article-once",
    "analyze-article-once",
    "article-runtime-metrics",
    "article-task-failed-list",
    "article-task-retry-failed",
    "article-daily-report-list",
    "article-daily-report-export",
    "summary-daily-report-export",
    "trial-monitor-report",
    "ai-analysis-sample",
    "collect-group-once",
    "run-group-scheduler",
    "group-status",
    "clean-group-once",
    "analyze-group-once",
    "group-daily-report-once",
    "group-daily-report-list",
    "group-daily-report-export",
    "run-group-pipeline-once",
    "group-runtime-summary",
    "group-runtime-metrics",
    "group-task-list",
    "group-task-reset",
    "group-task-reset-date",
    "group-task-failed-list",
    "group-task-retry-failed",
}


def _sensitive_hits(text: str) -> list[str]:
    return [field for field in SENSITIVE_BODY_FIELD_NAMES if field in text]


def test_user_facing_docs_do_not_expose_sensitive_body_field_names() -> None:
    violations: list[str] = []
    for path in USER_FACING_DOC_PATHS:
        content = Path(path).read_text(encoding="utf-8")
        hits = _sensitive_hits(content)
        if hits:
            violations.append(f"{path}: {', '.join(hits)}")

    assert violations == []


def test_user_facing_docs_do_not_expose_wechat_article_urls() -> None:
    violations: list[str] = []
    for path in USER_FACING_DOC_PATHS:
        content = Path(path).read_text(encoding="utf-8")
        if "mp.weixin.qq.com" in content:
            violations.append(path)

    assert violations == []


def test_exported_group_reports_do_not_contain_sensitive_body_field_names() -> None:
    violations: list[str] = []
    for path in sorted(Path().glob(EXPORTED_GROUP_REPORT_GLOB)):
        content = path.read_text(encoding="utf-8")
        hits = _sensitive_hits(content)
        if hits:
            violations.append(f"{path}: {', '.join(hits)}")

    assert violations == []


def test_cli_output_key_allowlist_covers_operational_commands() -> None:
    missing = sorted(REQUIRED_OPERATIONAL_COMMANDS - set(SAFE_CLI_OUTPUT_KEYS_BY_COMMAND))

    assert missing == []


def test_cli_output_key_allowlist_excludes_sensitive_body_fields() -> None:
    violations: list[str] = []
    for command, allowed_keys in SAFE_CLI_OUTPUT_KEYS_BY_COMMAND.items():
        for key in allowed_keys:
            hits = _sensitive_hits(key)
            if hits:
                violations.append(f"{command}: {key}")

    assert violations == []


def test_readme_documents_sensitive_output_guard_command() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "pytest tests/test_sensitive_output_guard.py -q" in readme


def test_werss_content_poc_doc_is_covered_by_sensitive_output_guard() -> None:
    assert "docs/operations/WeRSS正文按需读取POC记录.md" in USER_FACING_DOC_PATHS
