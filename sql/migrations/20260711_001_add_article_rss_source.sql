-- Retry-safe two-stage RSS migration. feed_url remains nullable until verified backfill.
DELIMITER $$
CREATE PROCEDURE migrate_20260711_001()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='feed_url') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN feed_url TEXT NULL COMMENT '标准 RSS 或 Atom 订阅地址' AFTER account_type;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='source_type') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'rss' COMMENT '文章来源类型，首期固定 rss' AFTER feed_url;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='request_timeout_seconds') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN request_timeout_seconds INT NOT NULL DEFAULT 30 COMMENT 'Feed 单次请求超时秒数' AFTER poll_interval_minutes;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='last_feed_etag') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN last_feed_etag VARCHAR(500) NULL COMMENT 'Feed 最近成功响应 ETag' AFTER last_success_collect_time;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='last_feed_modified') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN last_feed_modified VARCHAR(100) NULL COMMENT 'Feed 最近成功响应 Last-Modified' AFTER last_feed_etag;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_public_account_config' AND COLUMN_NAME='last_error_code') THEN
        ALTER TABLE wechat_public_account_config ADD COLUMN last_error_code VARCHAR(100) NULL COMMENT '最近一次 Feed 结构化错误码' AFTER last_feed_modified;
    END IF;
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
CALL migrate_20260711_001();
DROP PROCEDURE migrate_20260711_001;
