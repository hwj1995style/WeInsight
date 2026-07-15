-- Retry-safe RSS collection observability migration for MySQL 8.x.
DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260711_002$$
CREATE PROCEDURE migrate_20260711_002()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_collect_log' AND COLUMN_NAME='feed_item_count') THEN
        ALTER TABLE wechat_article_collect_log ADD COLUMN feed_item_count INT NOT NULL DEFAULT 0 COMMENT 'Feed 返回条目数' AFTER screenshot_path;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_collect_log' AND COLUMN_NAME='duplicate_count') THEN
        ALTER TABLE wechat_article_collect_log ADD COLUMN duplicate_count INT NOT NULL DEFAULT 0 COMMENT '重复文章数' AFTER feed_item_count;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_collect_log' AND COLUMN_NAME='invalid_count') THEN
        ALTER TABLE wechat_article_collect_log ADD COLUMN invalid_count INT NOT NULL DEFAULT 0 COMMENT '无效 Feed 条目数' AFTER duplicate_count;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_collect_log' AND COLUMN_NAME='http_status') THEN
        ALTER TABLE wechat_article_collect_log ADD COLUMN http_status INT NULL COMMENT 'Feed HTTP 响应状态码' AFTER invalid_count;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_collect_log' AND COLUMN_NAME='elapsed_ms') THEN
        ALTER TABLE wechat_article_collect_log ADD COLUMN elapsed_ms INT NOT NULL DEFAULT 0 COMMENT 'Feed 请求耗时毫秒' AFTER http_status;
    END IF;
END$$
DELIMITER ;
CALL migrate_20260711_002();
DROP PROCEDURE migrate_20260711_002;
