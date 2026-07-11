-- Two-stage RSS migration: feed_url remains nullable for legacy rows until backfill.
ALTER TABLE wechat_public_account_config
    ADD COLUMN feed_url TEXT NULL COMMENT '标准 RSS 或 Atom 订阅地址' AFTER account_type,
    ADD COLUMN source_type VARCHAR(20) NOT NULL DEFAULT 'rss' COMMENT '文章来源类型，首期固定 rss' AFTER feed_url,
    ADD COLUMN request_timeout_seconds INT NOT NULL DEFAULT 30 COMMENT 'Feed 单次请求超时秒数' AFTER poll_interval_minutes,
    ADD COLUMN last_feed_etag VARCHAR(500) NULL COMMENT 'Feed 最近成功响应 ETag' AFTER last_success_collect_time,
    ADD COLUMN last_feed_modified VARCHAR(100) NULL COMMENT 'Feed 最近成功响应 Last-Modified' AFTER last_feed_etag,
    ADD COLUMN last_error_code VARCHAR(100) NULL COMMENT '最近一次 Feed 结构化错误码' AFTER last_feed_modified,
    ADD UNIQUE KEY uk_public_account_feed_url (feed_url(255));
