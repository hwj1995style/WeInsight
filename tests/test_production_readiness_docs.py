from __future__ import annotations

from pathlib import Path

from app.security.output_policy import USER_FACING_DOC_PATHS


DOC = Path("docs/operations/生产配置和回滚预案.md")
README = Path("README.md")
PROD_CONFIG = Path("config/config.prod.example.yaml")


def test_production_readiness_doc_documents_disable_switches_and_rollback() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "关闭 article 链路" in content
    assert "关闭 AI" in content
    assert "只保留群链路" in content
    assert "微信掉线" in content
    assert "锁屏" in content
    assert "窗口卡死" in content
    assert "核心群不超过5个" in content
    assert "公众号/订阅号不超过20个" in content
    assert "恢复到手动单账号模式" in content


def test_production_readiness_doc_references_real_config_and_commands() -> None:
    content = DOC.read_text(encoding="utf-8")
    readme = README.read_text(encoding="utf-8")

    assert PROD_CONFIG.exists()
    assert "config/config.prod.example.yaml" in content
    assert "WEINSIGHT_MYSQL_PASSWORD" in content
    assert "python -m app.main check-config --config config/config.prod.yaml" in content
    assert "article-account-disable" in content
    assert "ai-analysis-sample" in content
    assert "group-runtime-summary" in content
    assert "生产配置和回滚预案.md" in readme


def test_production_readiness_doc_is_covered_by_sensitive_output_guard() -> None:
    assert DOC.as_posix() in USER_FACING_DOC_PATHS
