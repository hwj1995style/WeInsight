-- DESTRUCTIVE MIGRATION: execute only after a database backup is complete and
-- the single-public-account RSS collector has passed its continuous 24-hour POC gate.
-- Operators must backfill verified real feed URLs before rerunning this migration.
-- Never invent or derive an unknown feed URL automatically.
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260711_003_feed_url_gate$$
CREATE PROCEDURE migrate_20260711_003_feed_url_gate()
BEGIN
    IF EXISTS (
        SELECT 1 FROM wechat_public_account_config
        WHERE enabled = 1
          AND (feed_url IS NULL OR TRIM(feed_url) = '')
    ) THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Abort: backfill real feed_url values before rerunning 20260711_003';
    END IF;
END$$
CALL migrate_20260711_003_feed_url_gate()$$
DROP PROCEDURE migrate_20260711_003_feed_url_gate$$
DELIMITER ;

-- Upgrade databases where _001 was applied before full-URL hash uniqueness was introduced.
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260711_003_feed_hash$$
CREATE PROCEDURE migrate_20260711_003_feed_hash()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='feed_url_hash') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN feed_url_hash BINARY(32) GENERATED ALWAYS AS (UNHEX(SHA2(feed_url, 256))) STORED COMMENT 'Feed URL 完整 SHA-256' AFTER feed_url;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND INDEX_NAME='uk_public_account_feed_url') THEN
        ALTER TABLE wechat_public_account_config DROP INDEX uk_public_account_feed_url;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND INDEX_NAME='uk_public_account_feed_url_hash') THEN
        ALTER TABLE wechat_public_account_config ADD UNIQUE KEY uk_public_account_feed_url_hash (feed_url_hash);
    END IF;
END$$
DELIMITER ;
CALL migrate_20260711_003_feed_hash();
DROP PROCEDURE migrate_20260711_003_feed_hash;

ALTER TABLE wechat_public_account_config
    MODIFY COLUMN feed_url VARCHAR(2048) NULL COMMENT 'RSS feed URL；禁用的历史来源可为空';

DROP TABLE IF EXISTS wechat_article_route_cache;
DROP TABLE IF EXISTS wechat_article_collect_progress;
