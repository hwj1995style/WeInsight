from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROLE_SQL = ROOT / "sql" / "operations" / "grant_admin_stack_roles.sql"
INIT_SQL = ROOT / "sql" / "init.sql"
DEPLOYMENT_GUIDE = ROOT / "docs" / "operations" / "微信采集管理后台部署与回滚手册.md"
SCHEMA = "weinsight_prod"
ROLES = {
    "weinsight_web_role",
    "weinsight_collector_role",
    "weinsight_pipeline_role",
}
FORBIDDEN_PRIVILEGES = {
    "ALL",
    "ALL PRIVILEGES",
    "FILE",
    "PROCESS",
    "SUPER",
    "GRANT OPTION",
}


def _strip_sql_comments(sql: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*--.*$", "", without_blocks)


def _parse_grants(sql: str) -> dict[str, dict[str, set[str]]]:
    parsed: dict[str, dict[str, set[str]]] = defaultdict(dict)
    uncommented = _strip_sql_comments(sql)
    pattern = re.compile(
        r"^GRANT\s+(?P<privileges>[A-Z, ]+)\s+"
        r"ON\s+`(?P<schema>[a-z0-9_]+)`\.`(?P<table>[a-z0-9_]+)`\s+"
        r"TO\s+'(?P<role>[a-z0-9_]+)'$",
        flags=re.IGNORECASE,
    )
    for statement in uncommented.split(";"):
        normalized = " ".join(statement.split())
        if not normalized:
            continue
        if not normalized.upper().startswith("GRANT "):
            assert re.fullmatch(
                r"CREATE ROLE IF NOT EXISTS\s+'[a-z0-9_]+'",
                normalized,
                flags=re.IGNORECASE,
            ), f"unexpected SQL statement: {normalized}"
            continue
        match = pattern.fullmatch(normalized)
        assert match is not None, f"unparseable GRANT: {normalized}"
        assert match.group("schema") == SCHEMA
        role = match.group("role")
        assert role in ROLES
        table = match.group("table")
        privileges = {
            item.strip().upper()
            for item in match.group("privileges").split(",")
        }
        assert not privileges.intersection(FORBIDDEN_PRIVILEGES)
        assert table not in parsed[role], f"duplicate table GRANT: {role}.{table}"
        parsed[role][table] = privileges
    return {role: dict(tables) for role, tables in parsed.items()}


def _role_grants() -> dict[str, dict[str, set[str]]]:
    assert ROLE_SQL.exists(), ROLE_SQL
    return _parse_grants(ROLE_SQL.read_text(encoding="utf-8"))


def _init_tables() -> set[str]:
    content = INIT_SQL.read_text(encoding="utf-8")
    return set(
        re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+([a-z0-9_]+)",
            content,
            flags=re.IGNORECASE,
        )
    )


def test_grant_parser_ignores_comments_to_prevent_false_positive() -> None:
    sql = """
    -- GRANT SELECT ON `weinsight_prod`.`comment_only` TO 'weinsight_web_role';
    /* GRANT UPDATE ON `weinsight_prod`.`also_comment` TO 'weinsight_web_role'; */
    GRANT SELECT ON `weinsight_prod`.`real_table` TO 'weinsight_web_role';
    """

    grants = _parse_grants(sql)

    assert grants == {
        "weinsight_web_role": {"real_table": {"SELECT"}},
    }


def test_grant_parser_rejects_non_role_or_grant_statement() -> None:
    with pytest.raises(AssertionError, match="unexpected SQL statement"):
        _parse_grants("UPDATE forbidden_table SET value = 1;")


def test_role_template_creates_only_three_roles_without_secrets_or_high_privilege() -> None:
    sql = ROLE_SQL.read_text(encoding="utf-8")
    uncommented = _strip_sql_comments(sql)
    upper = uncommented.upper()

    for marker in ("-- web role", "-- collector role", "-- pipeline role"):
        assert marker in sql
    assert set(
        re.findall(
            r"CREATE ROLE IF NOT EXISTS\s+'([a-z0-9_]+)'",
            uncommented,
            flags=re.IGNORECASE,
        )
    ) == ROLES
    for forbidden in (
        "CREATE USER",
        "IDENTIFIED",
        "PASSWORD",
        "GRANT OPTION",
        "ALL PRIVILEGES",
        "REVOKE",
        "DROP ",
        "@'",
    ):
        assert forbidden not in upper
    assert not re.search(r"`[a-z0-9_]+`\.\*", uncommented, re.IGNORECASE)
    assert not re.search(r"\b(SUPER|FILE|PROCESS)\b", upper)
    assert "BEGIN PRIVATE KEY" not in upper


def test_web_role_has_control_plane_crud_and_safe_read_policy() -> None:
    web = _role_grants()["weinsight_web_role"]

    assert web["weinsight_admin_user"] == {"SELECT", "INSERT", "UPDATE"}
    assert web["weinsight_admin_session"] == {"SELECT", "INSERT", "UPDATE"}
    assert web["wechat_group_config"] == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert web["wechat_public_account_config"] == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    assert web["wechat_collection_job"] == {"SELECT", "INSERT", "UPDATE"}
    assert web["wechat_collection_job_target"] == {"SELECT", "INSERT"}
    assert web["wechat_report_generation_request"] == {"SELECT", "INSERT"}
    assert web["wechat_collection_job_event"] == {"SELECT", "INSERT"}

    read_only = {
        "wechat_collection_job_run",
        "wechat_collection_job_target_run",
        "wechat_worker_heartbeat",
        "wechat_client_health_check",
        "wechat_group_collect_log",
        "wechat_article_collect_log",
        "wechat_group_msg_clean",
        "wechat_group_msg_analysis",
        "wechat_article_clean",
        "wechat_article_analysis",
        "wechat_article_egg_price_item",
        "wechat_group_daily_report",
        "wechat_article_daily_report",
        "wechat_group_process_task",
        "wechat_article_process_task",
    }
    for table in read_only:
        assert web[table] == {"SELECT"}

    for forbidden_table in (
        "wechat_group_msg_raw",
        "wechat_article_raw",
        "wechat_ui_lock",
        "wechat_group_collect_cursor",
        "wechat_article_route_cache",
        "wechat_article_collect_progress",
    ):
        assert forbidden_table not in web


def test_collector_role_is_limited_to_collection_runtime_policy() -> None:
    collector = _role_grants()["weinsight_collector_role"]

    for table in ("wechat_group_config", "wechat_collection_job_target"):
        assert collector[table] == {"SELECT"}
    assert collector["wechat_public_account_config"] == {"SELECT", "UPDATE"}
    assert collector["wechat_collection_job"] == {"SELECT", "UPDATE"}
    for table in (
        "wechat_collection_job_run",
        "wechat_collection_job_target_run",
        "wechat_worker_heartbeat",
        "wechat_group_collect_cursor",
        "wechat_article_route_cache",
        "wechat_article_collect_progress",
    ):
        assert collector[table] == {"SELECT", "INSERT", "UPDATE"}
    assert collector["wechat_client_health_check"] == {"SELECT", "INSERT"}
    assert collector["wechat_group_msg_raw"] == {"INSERT"}
    assert collector["wechat_article_raw"] == {"SELECT", "INSERT"}
    for table in ("wechat_group_collect_log", "wechat_article_collect_log"):
        assert collector[table] == {"INSERT"}
    for table in ("wechat_group_process_task", "wechat_article_process_task"):
        assert collector[table] == {"INSERT"}
    assert collector["wechat_ui_lock"] == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    assert collector["wechat_collection_job_event"] == {"INSERT"}

    for forbidden_table in (
        "weinsight_admin_user",
        "weinsight_admin_session",
        "wechat_report_generation_request",
        "wechat_group_daily_report",
        "wechat_article_daily_report",
        "wechat_group_msg_clean",
        "wechat_group_msg_analysis",
        "wechat_article_clean",
        "wechat_article_analysis",
        "wechat_article_egg_price_item",
    ):
        assert forbidden_table not in collector


def test_pipeline_role_cannot_access_admin_ui_lock_or_job_runs() -> None:
    pipeline = _role_grants()["weinsight_pipeline_role"]

    assert pipeline["wechat_group_msg_raw"] == {"SELECT"}
    assert pipeline["wechat_article_raw"] == {"SELECT"}
    for table in ("wechat_group_process_task", "wechat_article_process_task"):
        assert pipeline[table] == {"SELECT", "INSERT", "UPDATE"}
    for table in (
        "wechat_group_msg_clean",
        "wechat_group_msg_analysis",
        "wechat_article_clean",
        "wechat_article_analysis",
        "wechat_group_daily_report",
        "wechat_article_daily_report",
        "wechat_report_generation_request",
    ):
        assert pipeline[table] == {"SELECT", "INSERT", "UPDATE"}
    assert pipeline["wechat_article_egg_price_item"] == {"INSERT", "DELETE"}
    assert pipeline["wechat_worker_heartbeat"] == {"INSERT", "UPDATE"}
    assert pipeline["wechat_collection_job_event"] == {"INSERT"}

    for forbidden_table in (
        "weinsight_admin_user",
        "weinsight_admin_session",
        "wechat_ui_lock",
        "wechat_collection_job",
        "wechat_collection_job_target",
        "wechat_collection_job_run",
        "wechat_collection_job_target_run",
        "wechat_client_health_check",
    ):
        assert forbidden_table not in pipeline


def test_every_init_table_has_an_explicit_role_policy() -> None:
    grants = _role_grants()
    granted_tables = {
        table
        for role_tables in grants.values()
        for table in role_tables
    }

    assert granted_tables == _init_tables()
    assert all(table in _init_tables() for tables in grants.values() for table in tables)


def test_deployment_guide_covers_secure_order_and_independent_accounts() -> None:
    content = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")

    required = (
        "微信 PC 4.1.8.107",
        "TLS_CERT_PATH",
        "TLS_KEY_PATH",
        "icacls",
        'icacls $TLS_CERT_PATH /grant:r "${RUN_AS_USER}:(R)"',
        "Get-Acl",
        "IDENTIFIED BY RANDOM PASSWORD",
        "mysql --user <DBA_USER> --password",
        "GRANT 'weinsight_web_role'",
        "GRANT 'weinsight_collector_role'",
        "GRANT 'weinsight_pipeline_role'",
        "SET DEFAULT ROLE",
        "SHOW GRANTS",
        "WEINSIGHT_WEB_MYSQL_PASSWORD",
        "WEINSIGHT_COLLECTOR_MYSQL_PASSWORD",
        "WEINSIGHT_PIPELINE_MYSQL_PASSWORD",
        "<ADMIN_LAN_CIDR>",
        "-LocalPort 8848",
        "WeInsight-Group-Scheduler",
        "WeInsight Group Scheduler",
        "register_admin_stack.ps1",
        "-LogonType Interactive",
        "check_admin_stack.ps1",
        "00:10",
        "final",
        "首次登录不强制改密",
        "剩余风险",
        "本机截图路径",
        "只能在采集机本机打开",
        "生产最小权限模式禁止名单改名",
        "停用旧配置并新建替代配置",
    )
    for marker in required:
        assert marker in content


def test_deployment_guide_has_four_non_destructive_rollback_paths() -> None:
    content = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")

    for heading in (
        "### 回滚一：Web 只读查询",
        "### 回滚二：暂停 article 单链路",
        "### 回滚三：暂停全部托管采集",
        "### 回滚四：恢复旧手动 CLI",
    ):
        assert heading in content
    assert "数据库迁移不回退删除数据" in content
    assert "DROP TABLE" not in content.upper()
    assert "TRUNCATE TABLE" not in content.upper()
    assert "DELETE FROM" not in content.upper()

    managed_section = content.split("### 回滚三：暂停全部托管采集", 1)[1]
    managed_section = managed_section.split("### 回滚四：", 1)[0]
    assert managed_section.index("请求停止全部") < managed_section.index(
        'Stop-ScheduledTask -TaskName "WeInsight-Collector-Worker"'
    )
    assert managed_section.index("UI lock 已释放") < managed_section.index(
        'Stop-ScheduledTask -TaskName "WeInsight-Collector-Worker"'
    )


def test_deployment_guide_does_not_invent_summary_lifecycle() -> None:
    content = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")

    assert "汇总日报状态为 final" not in content
    assert "群和文章两类子日报均为 final" in content
    assert "compensation all 请求成功" in content


def test_deployment_guide_contains_no_embedded_secret_or_unsafe_network_example() -> None:
    content = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")

    assert "admin123456" not in content
    assert "BEGIN PRIVATE KEY" not in content
    assert "MYSQL_PWD" not in content
    assert not re.search(r"IDENTIFIED BY\s+'[^']+'", content, re.IGNORECASE)
    assert not re.search(r"(?:^|\s)-p[^\s<]", content)
    assert "0.0.0.0/0" not in content
    assert "-RemoteAddress Any" not in content
    assert "<ADMIN_LAN_CIDR>" in content
