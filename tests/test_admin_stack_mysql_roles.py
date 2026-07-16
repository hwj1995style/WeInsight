from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROLE_SQL = ROOT / "sql" / "operations" / "grant_admin_stack_roles.sql"
UI_LOCK_DIAGNOSTIC_SQL = (
    ROOT / "sql" / "operations" / "check_wechat_ui_lock.sql"
)
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
    expected = {
        "weinsight_admin_user": {"SELECT", "INSERT", "UPDATE"},
        "weinsight_admin_session": {"SELECT", "INSERT", "UPDATE"},
        "wechat_group_config": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "wechat_public_account_config": {
            "SELECT", "INSERT", "UPDATE", "DELETE"
        },
        "wechat_collection_job": {"SELECT", "INSERT", "UPDATE"},
        "wechat_collection_job_target": {"SELECT", "INSERT"},
        "wechat_report_generation_request": {"SELECT", "INSERT"},
        "wechat_collection_job_event": {"SELECT", "INSERT"},
        "wechat_werss_authorization_state": {"SELECT", "INSERT", "UPDATE"},
        "wechat_werss_authorization_settings": {"SELECT", "INSERT", "UPDATE"},
        **{
            table: {"SELECT"}
            for table in (
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
            )
        },
    }

    assert web == expected


def test_collector_role_is_limited_to_collection_runtime_policy() -> None:
    collector = _role_grants()["weinsight_collector_role"]
    expected = {
        "wechat_group_config": {"SELECT"},
        "wechat_public_account_config": {"SELECT", "UPDATE"},
        "wechat_collection_job": {"SELECT", "INSERT", "UPDATE"},
        "wechat_collection_job_target": {"SELECT", "INSERT"},
        "wechat_system_job_coordination": {"SELECT"},
        **{
            table: {"SELECT", "INSERT", "UPDATE"}
            for table in (
                "wechat_collection_job_run",
                "wechat_collection_job_target_run",
                "wechat_worker_heartbeat",
                "wechat_group_collect_cursor",
            )
        },
        "wechat_client_health_check": {"SELECT", "INSERT"},
        "wechat_group_msg_raw": {"INSERT"},
        "wechat_article_raw": {"SELECT", "INSERT"},
        "wechat_group_collect_log": {"INSERT"},
        "wechat_article_collect_log": {"INSERT"},
        "wechat_group_process_task": {"INSERT"},
        "wechat_article_process_task": {"INSERT"},
        "wechat_ui_lock": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "wechat_collection_job_event": {"INSERT"},
    }

    assert collector == expected


def test_pipeline_role_cannot_access_admin_ui_lock_or_job_runs() -> None:
    pipeline = _role_grants()["weinsight_pipeline_role"]
    expected = {
        "wechat_group_msg_raw": {"SELECT"},
        "wechat_article_raw": {"SELECT"},
        **{
            table: {"SELECT", "INSERT", "UPDATE"}
            for table in (
                "wechat_group_process_task",
                "wechat_article_process_task",
                "wechat_group_msg_clean",
                "wechat_group_msg_analysis",
                "wechat_article_clean",
                "wechat_article_analysis",
                "wechat_group_daily_report",
                "wechat_article_daily_report",
                "wechat_report_generation_request",
            )
        },
        "wechat_article_egg_price_item": {"INSERT", "DELETE"},
        "wechat_worker_heartbeat": {"INSERT", "UPDATE"},
        "wechat_collection_job_event": {"INSERT"},
        "wechat_werss_authorization_state": {"SELECT", "INSERT", "UPDATE"},
        "wechat_werss_authorization_notice": {"SELECT", "INSERT", "UPDATE"},
        "wechat_werss_authorization_settings": {"SELECT"},
    }

    assert pipeline == expected


def test_every_init_table_has_an_explicit_role_policy() -> None:
    grants = _role_grants()
    granted_tables = {
        table
        for role_tables in grants.values()
        for table in role_tables
    }

    assert granted_tables == _init_tables()
    assert all(table in _init_tables() for tables in grants.values() for table in tables)


def test_ui_lock_diagnostic_is_single_read_only_lease_query() -> None:
    assert UI_LOCK_DIAGNOSTIC_SQL.exists(), UI_LOCK_DIAGNOSTIC_SQL
    sql = _strip_sql_comments(
        UI_LOCK_DIAGNOSTIC_SQL.read_text(encoding="utf-8")
    ).strip()
    statements = [item.strip() for item in sql.split(";") if item.strip()]

    assert len(statements) == 1
    statement = statements[0]
    assert re.match(r"^SELECT\s+", statement, re.IGNORECASE)
    assert re.search(
        r"FROM\s+`weinsight_prod`\.`wechat_ui_lock`",
        statement,
        re.IGNORECASE,
    )
    assert "expire_time" in statement
    assert "CURRENT_TIMESTAMP" in statement.upper()
    assert "lease_until" in statement
    assert "free_no_row" in statement
    assert "free_expired" in statement
    assert "held" in statement
    assert not re.search(
        r"\b(INSERT|UPDATE|DELETE|REPLACE|ALTER|DROP|TRUNCATE|CREATE)\b",
        statement,
        re.IGNORECASE,
    )
    assert "FOR UPDATE" not in statement.upper()


def test_deployment_gates_use_dba_or_collector_ui_lock_diagnostic() -> None:
    content = DEPLOYMENT_GUIDE.read_text(encoding="utf-8")
    acceptance = content.split("## 8. 启动与验收", 1)[1].split(
        "## 9. 回滚路径", 1
    )[0]
    rollback = content.split("## 9. 回滚路径", 1)[1]
    managed = rollback.split("### 回滚三：暂停全部托管采集", 1)[1]
    managed = managed.split("### 回滚四：恢复旧手动 CLI", 1)[0]
    manual_cli = rollback.split("### 回滚四：恢复旧手动 CLI", 1)[1]

    for marker in (
        "sql\\operations\\check_wechat_ui_lock.sql",
        "<COLLECTOR_DB_USER>",
        "--password",
        "free_no_row",
        "free_expired",
        "held",
        "数据库返回的 CURRENT_TIMESTAMP",
        "不得使用 Web 账号",
    ):
        assert marker in content
    assert "UI lock 同时持有数为 0" not in acceptance
    assert "七键检查不查询 `wechat_ui_lock`" in acceptance
    assert managed.index("check_wechat_ui_lock.sql") < managed.index(
        'Stop-ScheduledTask -TaskName "WeInsight-Collector-Worker"'
    )
    assert "check_wechat_ui_lock.sql" in manual_cli
    recovery = managed.split("恢复前", 1)[1]
    assert recovery.index("check_admin_stack.ps1") < recovery.index(
        "check_wechat_ui_lock.sql"
    )


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


def test_collector_can_maintain_only_system_job_tables_without_delete() -> None:
    sql = ROLE_SQL.read_text(encoding="utf-8")
    assert "GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_collection_job` TO 'weinsight_collector_role'" in sql
    assert "GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_collection_job_target` TO 'weinsight_collector_role'" in sql
    assert "GRANT SELECT ON `weinsight_prod`.`wechat_system_job_coordination` TO 'weinsight_collector_role'" in sql
    managed_lines = [
        line for line in sql.splitlines()
        if "weinsight_collector_role" in line
        and any(table in line for table in (
            "wechat_collection_job`",
            "wechat_collection_job_target`",
            "wechat_system_job_coordination`",
        ))
    ]
    assert all("DELETE" not in line for line in managed_lines)
