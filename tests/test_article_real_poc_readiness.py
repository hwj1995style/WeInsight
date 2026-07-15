from pathlib import Path


def test_legacy_article_rpa_poc_entrypoints_are_absent() -> None:
    main = Path("app/main.py").read_text(encoding="utf-8")
    for value in ("article-rpa-probe", "collect-article-once", "run-article-scheduler", "build_real_article_rpa_probe", "build_real_article_rpa_client"):
        assert value not in main
