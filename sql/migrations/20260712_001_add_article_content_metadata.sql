DROP PROCEDURE IF EXISTS migrate_20260712_001;
DELIMITER $$
CREATE PROCEDURE migrate_20260712_001()
BEGIN
 IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_raw' AND COLUMN_NAME='content_locator') THEN ALTER TABLE wechat_article_raw ADD COLUMN content_locator VARCHAR(200) NULL; END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_raw' AND COLUMN_NAME='content_locator_type') THEN ALTER TABLE wechat_article_raw ADD COLUMN content_locator_type VARCHAR(30) NULL; END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_clean' AND COLUMN_NAME='content_source') THEN ALTER TABLE wechat_article_clean ADD COLUMN content_source VARCHAR(20) NULL; END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_clean' AND COLUMN_NAME='content_hash') THEN ALTER TABLE wechat_article_clean ADD COLUMN content_hash CHAR(64) NULL; END IF;
 IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='wechat_article_clean' AND COLUMN_NAME='content_fetch_status') THEN ALTER TABLE wechat_article_clean ADD COLUMN content_fetch_status VARCHAR(30) NULL; END IF;
END$$
DELIMITER ;
CALL migrate_20260712_001();
DROP PROCEDURE IF EXISTS migrate_20260712_001;
