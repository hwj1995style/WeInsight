-- RSS collection observability. IF NOT EXISTS makes retries safe.
ALTER TABLE wechat_article_collect_log
    ADD COLUMN IF NOT EXISTS feed_item_count INT NOT NULL DEFAULT 0 COMMENT 'Feed 返回条目数' AFTER screenshot_path,
    ADD COLUMN IF NOT EXISTS duplicate_count INT NOT NULL DEFAULT 0 COMMENT '重复文章数' AFTER feed_item_count,
    ADD COLUMN IF NOT EXISTS invalid_count INT NOT NULL DEFAULT 0 COMMENT '无效 Feed 条目数' AFTER duplicate_count,
    ADD COLUMN IF NOT EXISTS http_status INT NULL COMMENT 'Feed HTTP 响应状态码' AFTER invalid_count,
    ADD COLUMN IF NOT EXISTS elapsed_ms INT NOT NULL DEFAULT 0 COMMENT 'Feed 请求耗时毫秒' AFTER http_status;
