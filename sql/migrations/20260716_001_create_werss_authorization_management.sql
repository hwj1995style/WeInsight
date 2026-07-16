-- WeRSS authorization state and deduplicated notification delivery records.
-- Safety: CREATE TABLE IF NOT EXISTS preserves existing data.

CREATE TABLE IF NOT EXISTS wechat_werss_authorization_state (
    singleton_id TINYINT UNSIGNED NOT NULL COMMENT '单例主键，固定为1',
    status VARCHAR(20) NOT NULL COMMENT '授权状态',
    account_name VARCHAR(200) NULL COMMENT '已授权公众号名称',
    expires_at DATETIME NULL COMMENT '授权到期时间',
    last_checked_at DATETIME NOT NULL COMMENT '最近检查时间',
    last_successful_check_at DATETIME NULL COMMENT '最近成功检查时间',
    last_error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    authorization_version CHAR(64) NULL COMMENT '授权周期摘要',
    updated_at DATETIME NOT NULL COMMENT '更新时间',
    PRIMARY KEY (singleton_id),
    KEY idx_werss_auth_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WeRSS授权状态单例';

CREATE TABLE IF NOT EXISTS wechat_werss_authorization_notice (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '通知记录主键',
    authorization_version CHAR(64) NOT NULL COMMENT '授权周期摘要',
    notice_type VARCHAR(30) NOT NULL COMMENT '通知类型',
    status VARCHAR(20) NOT NULL COMMENT '投递状态',
    attempt_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '投递尝试次数',
    next_attempt_at DATETIME NULL COMMENT '下次投递时间',
    sent_at DATETIME NULL COMMENT '成功发送时间',
    last_error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    recipient_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '收件人数',
    create_time DATETIME NOT NULL COMMENT '创建时间',
    update_time DATETIME NOT NULL COMMENT '更新时间',
    PRIMARY KEY (id),
    UNIQUE KEY uk_werss_auth_notice_version_type (authorization_version, notice_type),
    KEY idx_werss_auth_notice_due (status, next_attempt_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WeRSS授权邮件通知';

CREATE TABLE IF NOT EXISTS wechat_werss_authorization_settings (
    singleton_id TINYINT UNSIGNED NOT NULL COMMENT '单例主键，固定为1',
    werss_username VARCHAR(100) NOT NULL COMMENT 'WeRSS管理用户名',
    werss_password_encrypted BLOB NULL COMMENT 'DPAPI加密的WeRSS管理密码',
    smtp_enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否启用SMTP提醒',
    smtp_host VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'SMTP服务器',
    smtp_port INT UNSIGNED NOT NULL DEFAULT 587 COMMENT 'SMTP端口',
    smtp_username VARCHAR(255) NOT NULL DEFAULT '' COMMENT 'SMTP用户名',
    smtp_password_encrypted BLOB NULL COMMENT 'DPAPI加密的SMTP密码',
    smtp_security VARCHAR(20) NOT NULL DEFAULT 'starttls' COMMENT 'SMTP加密方式',
    from_address VARCHAR(320) NOT NULL DEFAULT '' COMMENT '发件邮箱',
    recipients_json TEXT NOT NULL COMMENT '规范化收件人JSON',
    updated_at DATETIME NOT NULL COMMENT '更新时间',
    PRIMARY KEY (singleton_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='WeRSS授权与邮件提醒设置';
