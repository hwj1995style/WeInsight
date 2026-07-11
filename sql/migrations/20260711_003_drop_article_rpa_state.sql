-- DESTRUCTIVE MIGRATION: execute only after a database backup is complete and
-- the single-public-account RSS collector has passed its continuous 24-hour POC gate.
-- Operators must backfill verified real feed URLs before rerunning this migration.
-- Never invent or derive an unknown feed URL automatically.
SET @invalid_feed_url_count := (
    SELECT COUNT(*) FROM wechat_article_account_config
    WHERE feed_url IS NULL OR TRIM(feed_url) = ''
);
SET @feed_url_gate_sql := IF(
    @invalid_feed_url_count > 0,
    "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Abort: backfill real feed_url values before rerunning 20260711_003'",
    'DO 0'
);
PREPARE feed_url_gate FROM @feed_url_gate_sql;
EXECUTE feed_url_gate;
DEALLOCATE PREPARE feed_url_gate;

ALTER TABLE wechat_article_account_config
    MODIFY COLUMN feed_url VARCHAR(2048) NOT NULL COMMENT 'RSS feed URL';

DROP TABLE IF EXISTS wechat_article_route_cache;
DROP TABLE IF EXISTS wechat_article_collect_progress;
