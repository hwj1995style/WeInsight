-- Add the stable WeRSS source identity and the latest observed upstream state.
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260713_001$$
CREATE PROCEDURE migrate_20260713_001()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND COLUMN_NAME = 'werss_source_id'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD COLUMN werss_source_id VARCHAR(200) NULL
            COMMENT 'WeRSS 来源稳定标识，历史记录允许为空' AFTER source_type;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND COLUMN_NAME = 'upstream_status'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD COLUMN upstream_status VARCHAR(20) NOT NULL DEFAULT 'unknown'
            COMMENT 'WeRSS 上游状态，由应用校验允许值' AFTER werss_source_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND COLUMN_NAME = 'upstream_last_seen_at'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD COLUMN upstream_last_seen_at DATETIME NULL
            COMMENT '最近一次在 WeRSS 来源目录中出现的时间' AFTER upstream_status;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND COLUMN_NAME = 'upstream_missing_at'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD COLUMN upstream_missing_at DATETIME NULL
            COMMENT '首次确认 WeRSS 来源目录缺失的时间' AFTER upstream_last_seen_at;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND INDEX_NAME = 'uk_public_account_werss_source_id'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD UNIQUE KEY uk_public_account_werss_source_id (werss_source_id);
    END IF;
END$$
CALL migrate_20260713_001()$$
DROP PROCEDURE IF EXISTS migrate_20260713_001$$
DELIMITER ;
