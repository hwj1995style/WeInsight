-- Persistent account-level downstream allowlist. Safe default is deny.
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260712_002$$
CREATE PROCEDURE migrate_20260712_002()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_public_account_config'
          AND COLUMN_NAME = 'downstream_clean_enabled'
    ) THEN
        ALTER TABLE wechat_public_account_config
            ADD COLUMN downstream_clean_enabled TINYINT NOT NULL DEFAULT 0
            COMMENT '是否允许进入文章清洗分析下游，默认拒绝' AFTER enabled;
    END IF;
END$$
CALL migrate_20260712_002()$$
DROP PROCEDURE IF EXISTS migrate_20260712_002$$
DELIMITER ;
