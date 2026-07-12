from pathlib import Path


def test_werss_compose_is_pinned_and_not_public():
    compose = Path("deploy/werss/docker-compose.yml").read_text("utf-8")
    assert "ghcr.io/rachelos/we-mp-rss@sha256:53912fcb3d523d1e640adcb7066cc18123f00e9510882a7982d0991f3113845f" in compose
    assert "WERSS_IMAGE" not in compose
    assert "latest" not in compose.lower()
    assert "restart: unless-stopped" in compose
    assert "healthcheck:" in compose
    assert '"python3"' in compose
    assert '127.0.0.1:${WERSS_PORT:-8001}:8001' in compose
    assert 'max-size: "2m"' in compose
    assert 'max-file: "2"' in compose


def test_werss_environment_template_uses_external_mysql_without_secrets():
    compose = Path("deploy/werss/docker-compose.yml").read_text("utf-8")
    example = Path("deploy/werss/.env.example").read_text("utf-8")
    assert "DB=mysql+pymysql://" in example
    assert "DB: ${DB:?" in compose
    assert "/app/data" in compose
    assert "mysql:" not in compose
    assert "latest" not in example.lower()
    assert "replace-with" not in example
    assert "..." not in example


def test_real_werss_environment_file_is_ignored():
    patterns = Path(".gitignore").read_text("utf-8")
    assert "deploy/werss/.env" in patterns
    assert "!deploy/werss/.env.example" in patterns
    assert "deploy/werss/data/" in patterns


def test_operations_guide_covers_rollout_and_recovery_contract():
    guide = Path("docs/operations/公众号RSS采集运行手册.md").read_text("utf-8")
    required = (
        "固定镜像", "MySQL 建库与授权", "最小权限", "备份", "恢复备份", "回滚",
        "添加公众号", "Feed URL", "单公众号", "24 小时", "15 分钟", "3 个公众号",
        "连续空 Feed", "Docker Desktop 重启", "停止 RSS", "最终删除公众号 RPA",
    )
    for phrase in required:
        assert phrase in guide
    for command in (
        "icacls deploy\\werss\\.env",
        "docker compose --env-file deploy\\werss\\.env",
        "docker inspect --format",
        "article-account-disable",
        "UPDATE wechat_collection_job",
        "FROM wechat_collection_job_run",
        "TIMESTAMPDIFF(MINUTE, publish_time, collect_time)",
        "FROM wechat_ui_lock",
        "cmd /c",
    ):
        assert command in guide
    assert "collect-article-once" not in guide
    assert "run-article-scheduler" not in guide


def test_active_operator_entrypoints_do_not_direct_article_rpa_usage():
    readme = Path("README.md").read_text("utf-8")
    guide = Path("docs/operations/公众号RSS采集运行手册.md").read_text("utf-8")
    for text in (readme, guide):
        assert "collect-article-once" not in text
        assert "run-article-scheduler" not in text


def test_every_operations_doc_with_removed_article_rpa_commands_has_top_banner():
    removed_commands = ("article-rpa-probe", "collect-article-once", "run-article-scheduler")
    matched = []
    for path in Path("docs/operations").glob("*.md"):
        text = path.read_text("utf-8")
        if not any(command in text for command in removed_commands):
            continue
        matched.append(path)
        top = "\n".join(text.splitlines()[:8])
        for phrase in ("历史", "禁止执行", "WeRSS", "docs/operations/公众号RSS采集运行手册.md"):
            assert phrase in top, f"{path} missing top banner phrase: {phrase}"
    assert matched


def test_readme_marks_real_rpa_validation_as_group_only_and_article_docs_historical():
    readme = Path("README.md").read_text("utf-8")
    assert "真实微信/RPA 验证仅适用于微信群" in readme
    assert "公众号 article-RPA 历史文档" in readme
    assert "公众号现行采集路径仅为 WeRSS + WeInsight RSS" in readme


def test_readme_links_to_werss_operations_guide():
    readme = Path("README.md").read_text("utf-8")
    assert "公众号 RSS / WeRSS 部署" in readme
    assert "docs/operations/公众号RSS采集运行手册.md" in readme


def test_werss_docs_accept_local_log_risk_without_building_an_internal_image():
    guide = Path("docs/operations/公众号RSS采集运行手册.md").read_text("utf-8")
    design = Path("docs/superpowers/specs/2026-07-12-WeRSS正文按需读取设计.md").read_text("utf-8")
    plan = Path("docs/superpowers/plans/2026-07-12-WeRSS正文按需读取实施计划.md").read_text("utf-8")
    for text in (guide, design, plan):
        for phrase in (
            "官方固定摘要",
            "不构建内部镜像",
            "仅保留在本机 Docker 日志",
            "不接入外部日志",
            "不复制到工单",
            "不纳入备份",
            "持续关注上游",
        ):
            assert phrase in text


def test_werss_docs_separate_nine_account_collection_from_single_account_downstream():
    guide = Path("docs/operations/公众号RSS采集运行手册.md").read_text("utf-8")
    design = Path("docs/superpowers/specs/2026-07-12-WeRSS正文按需读取设计.md").read_text("utf-8")
    plan = Path("docs/superpowers/plans/2026-07-12-WeRSS正文按需读取实施计划.md").read_text("utf-8")
    for text in (guide, design, plan):
        for phrase in (
            "9 个公众号全部启用采集",
            "仅湖南三尖农牧公司进入 clean/analyze",
            "其余 8 个只采集",
            "下游白名单",
            "采集完整率",
            "去重",
            "采集延迟",
            "分开验收",
        ):
            assert phrase in text
