-- DESTRUCTIVE MIGRATION: execute only after a database backup is complete and
-- the single-public-account RSS collector has passed its continuous 24-hour POC gate.
-- Abort unless this validation returns zero rows; backfill any remaining feed_url first.
SELECT account_name
FROM wechat_article_account_config
WHERE feed_url IS NULL OR TRIM(feed_url) = '';

-- Run this NOT NULL change only after an operator confirms the validation above is empty.
ALTER TABLE wechat_article_account_config
    MODIFY COLUMN feed_url VARCHAR(2048) NOT NULL COMMENT 'RSS feed URL';

DROP TABLE IF EXISTS wechat_article_route_cache;
DROP TABLE IF EXISTS wechat_article_collect_progress;
