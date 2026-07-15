-- Migration: create administrator authentication and session tables.
-- Scope: existing databases created before the admin web application.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and preserves existing data.

CREATE TABLE IF NOT EXISTS weinsight_admin_user (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '管理员主键',
    username VARCHAR(100) NOT NULL COMMENT '管理员登录名',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Argon2id密码哈希',
    enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
    password_changed_at DATETIME NULL COMMENT '最近主动改密时间，空表示仍为初始化密码',
    failed_login_count INT NOT NULL DEFAULT 0 COMMENT '连续登录失败次数',
    locked_until DATETIME NULL COMMENT '登录锁定截止时间',
    last_login_at DATETIME NULL COMMENT '最近成功登录时间',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_admin_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS weinsight_admin_session (
    id CHAR(36) PRIMARY KEY COMMENT '会话UUID',
    user_id BIGINT NOT NULL COMMENT '管理员主键',
    token_hash CHAR(64) NOT NULL COMMENT 'Session令牌SHA-256',
    csrf_token_hash CHAR(64) NOT NULL COMMENT 'CSRF令牌SHA-256',
    expires_at DATETIME NOT NULL COMMENT '绝对过期时间',
    idle_expires_at DATETIME NOT NULL COMMENT '空闲过期时间',
    last_seen_at DATETIME NOT NULL COMMENT '最近访问时间',
    revoked_at DATETIME NULL COMMENT '注销时间',
    client_ip VARCHAR(64) NULL COMMENT '登录客户端IP',
    user_agent_hash CHAR(64) NULL COMMENT 'User-Agent SHA-256',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_admin_session_token (token_hash),
    KEY idx_admin_session_user (user_id, revoked_at),
    KEY idx_admin_session_expiry (expires_at, idle_expires_at),
    CONSTRAINT fk_admin_session_user FOREIGN KEY (user_id)
        REFERENCES weinsight_admin_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
