from __future__ import annotations

import sys
from pathlib import Path

import app.main as main_module
from app.main import main
from app.security.output_policy import USER_FACING_DOC_PATHS


RUNBOOK = Path("docs/operations/公众号订阅号受控真实POC运行手册.md")
REPORT_TEMPLATE = Path("docs/operations/公众号订阅号受控真实POC验收报告模板.md")
README = Path("README.md")


def test_article_rpa_probe_requires_account_name(monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["weinsight", "article-rpa-probe", "--config", "config/config.dev.yaml"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2

    error = capsys.readouterr().err
    assert "--account-name is required for article-rpa-probe" in error


def test_article_rpa_probe_outputs_safe_status(monkeypatch, capsys) -> None:
    class FakeProbe:
        def probe_account(self, account_name: str):
            assert account_name == "授权公众号名称"
            return {
                "status": "ok",
                "account_found": 1,
                "link_count": 1,
                "message": "ready",
            }

    monkeypatch.setattr(main_module, "build_real_article_rpa_probe", lambda config: FakeProbe())
    monkeypatch.setattr(main_module, "ensure_wechat_health", lambda config: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "weinsight",
            "article-rpa-probe",
            "--config",
            "config/config.dev.yaml",
            "--account-name",
            "授权公众号名称",
        ],
    )

    exit_code = main()
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "article_rpa_probe status=ok account_found=1 link_count=1 message=ready" in output
    assert "mp.weixin.qq.com" not in output
    assert "article_url" not in output
    assert "article_body" not in output
    assert "body_text" not in output


def test_real_article_rpa_probe_builder_injects_route_cache(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(main_module, "WxautoArticleRpaClient", FakeClient)
    monkeypatch.setattr(main_module, "create_mysql_engine", lambda mysql: object())
    monkeypatch.setattr(main_module, "MysqlArticleRouteCacheRepo", lambda engine: "route-repo")

    config = main_module.load_config(Path("config/config.dev.yaml"))
    main_module.build_real_article_rpa_probe(config)

    assert captured["route_cache_repo"] == "route-repo"
    assert captured["route_cache_enabled"] is True
    assert captured["route_probe_failure_threshold"] == 3
    assert captured["close_browser_after_extract"] is True
    assert captured["open_account_search_fallback_enabled"] is True


def test_article_real_poc_runbook_contains_one_account_checklist() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "1 个授权公众号/订阅号" in content
    assert "article-account-list" in content
    assert "article-rpa-probe" in content
    assert "collect-article-once" in content
    assert "parse-article-once" in content
    assert "article-runtime-metrics" in content
    assert "不注册 Windows 计划任务" in content


def test_article_real_poc_runbook_contains_three_account_expansion_gate() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "扩大到 3 个授权公众号/订阅号" in content
    assert "1 个账号闭环通过后" in content
    assert "连续失败" in content
    assert "回滚" in content


def test_article_real_poc_runbook_documents_route_cache_and_copy_link() -> None:
    content = RUNBOOK.read_text(encoding="utf-8")

    assert "route cache" in content or "路由缓存" in content
    assert "复制链接" in content
    assert "UIA Value" in content
    assert "不输出具体文章链接" in content


def test_article_real_poc_report_template_has_go_no_go_decision() -> None:
    content = REPORT_TEMPLATE.read_text(encoding="utf-8")

    assert "是否进入最多 20 个账号小规模试运行" in content
    assert "通过条件" in content
    assert "停止条件" in content
    assert "单机串行交错限制" in content


def test_readme_references_article_real_poc_runbook() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "docs/operations/公众号订阅号受控真实POC运行手册.md" in readme


def test_article_real_poc_runbook_is_guarded_by_sensitive_output_policy() -> None:
    assert "docs/operations/公众号订阅号受控真实POC运行手册.md" in USER_FACING_DOC_PATHS
