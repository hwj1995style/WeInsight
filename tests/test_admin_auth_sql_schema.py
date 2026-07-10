import re
from pathlib import Path

import pytest


ADMIN_USER_DEFINITIONS = (
    "id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '管理员主键'",
    "username VARCHAR(100) NOT NULL COMMENT '管理员登录名'",
    "password_hash VARCHAR(255) NOT NULL COMMENT 'Argon2id密码哈希'",
    "enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用'",
    "password_changed_at DATETIME NULL COMMENT '最近主动改密时间，空表示仍为初始化密码'",
    "failed_login_count INT NOT NULL DEFAULT 0 COMMENT '连续登录失败次数'",
    "locked_until DATETIME NULL COMMENT '登录锁定截止时间'",
    "last_login_at DATETIME NULL COMMENT '最近成功登录时间'",
    "create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
    "UNIQUE KEY uk_admin_username (username)",
)

ADMIN_SESSION_DEFINITIONS = (
    "id CHAR(36) PRIMARY KEY COMMENT '会话UUID'",
    "user_id BIGINT NOT NULL COMMENT '管理员主键'",
    "token_hash CHAR(64) NOT NULL COMMENT 'Session令牌SHA-256'",
    "csrf_token_hash CHAR(64) NOT NULL COMMENT 'CSRF令牌SHA-256'",
    "expires_at DATETIME NOT NULL COMMENT '绝对过期时间'",
    "idle_expires_at DATETIME NOT NULL COMMENT '空闲过期时间'",
    "last_seen_at DATETIME NOT NULL COMMENT '最近访问时间'",
    "revoked_at DATETIME NULL COMMENT '注销时间'",
    "client_ip VARCHAR(64) NULL COMMENT '登录客户端IP'",
    "user_agent_hash CHAR(64) NULL COMMENT 'User-Agent SHA-256'",
    "create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP",
    "UNIQUE KEY uk_admin_session_token (token_hash)",
    "KEY idx_admin_session_user (user_id, revoked_at)",
    "KEY idx_admin_session_expiry (expires_at, idle_expires_at)",
)

ADMIN_SESSION_FOREIGN_KEY = (
    "CONSTRAINT fk_admin_session_user FOREIGN KEY (user_id) "
    "REFERENCES weinsight_admin_user(id) ON DELETE CASCADE"
)

MUTATED_SCHEMA_FRAGMENTS = (
    "    token_hash CHAR(64) NOT NULL COMMENT 'Session令牌SHA-256',\n",
    "    expires_at DATETIME NOT NULL COMMENT '绝对过期时间',\n",
    "    UNIQUE KEY uk_admin_session_token (token_hash),\n",
    "    CONSTRAINT fk_admin_session_user FOREIGN KEY (user_id)\n"
    "        REFERENCES weinsight_admin_user(id) ON DELETE CASCADE\n",
)


def _table_body(sql: str, table_name: str) -> str:
    table_pattern = re.compile(
        rf"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+{re.escape(table_name)}\s*"
        rf"\((?P<body>[^;]*?)\)\s*ENGINE=InnoDB\s+DEFAULT\s+CHARSET=utf8mb4\s*;",
        re.DOTALL,
    )
    matches = list(table_pattern.finditer(sql))
    assert len(matches) == 1, f"expected one complete {table_name} InnoDB/utf8mb4 DDL"
    return matches[0].group("body")


def _assert_complete_definitions(
    table_body: str, expected_definitions: tuple[str, ...]
) -> None:
    actual_definitions = {line.strip().removesuffix(",") for line in table_body.splitlines()}
    for definition in expected_definitions:
        assert definition in actual_definitions, f"missing complete definition: {definition}"


def _assert_admin_auth_schema(sql: str) -> None:
    admin_user_body = _table_body(sql, "weinsight_admin_user")
    admin_session_body = _table_body(sql, "weinsight_admin_session")

    _assert_complete_definitions(admin_user_body, ADMIN_USER_DEFINITIONS)
    _assert_complete_definitions(admin_session_body, ADMIN_SESSION_DEFINITIONS)
    normalized_session_body = " ".join(admin_session_body.split())
    assert ADMIN_SESSION_FOREIGN_KEY in normalized_session_body

    prohibited_statements = (
        r"\bDROP\s+TABLE\b",
        r"\bTRUNCATE\s+TABLE\b",
        r"\bDELETE\s+FROM\b",
    )
    for prohibited_statement in prohibited_statements:
        assert re.search(prohibited_statement, sql, flags=re.IGNORECASE) is None


def _remove_fragment_once(sql: str, fragment: str) -> str:
    assert sql.count(fragment) == 1
    return sql.replace(fragment, "", 1)


def test_admin_auth_schema_exists_in_init_and_migration() -> None:
    init_sql = Path("sql/init.sql").read_text(encoding="utf-8")
    migration_sql = Path(
        "sql/migrations/20260710_001_create_admin_auth.sql"
    ).read_text(encoding="utf-8")

    for sql in (init_sql, migration_sql):
        _assert_admin_auth_schema(sql)

    for sql in (init_sql, migration_sql):
        for fragment in MUTATED_SCHEMA_FRAGMENTS:
            mutated_sql = _remove_fragment_once(sql, fragment)
            with pytest.raises(AssertionError):
                _assert_admin_auth_schema(mutated_sql)
