-- Apply immediately after migration 20260712_002.
-- All nine sources collect raw; only the approved Hunan POC enters downstream.
INSERT INTO wechat_public_account_config (
    account_name, account_type, feed_url, source_type, enabled,
    downstream_clean_enabled, priority, poll_interval_minutes,
    request_timeout_seconds, daily_window_start, daily_window_end,
    max_articles_per_round, collect_today_only, dedup_key, remark
) VALUES
('河南金咕咕蛋品','subscription','http://127.0.0.1:8001/feed/MP_WXS_3906417437.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('江西九江褐壳蛋','subscription','http://127.0.0.1:8001/feed/MP_WXS_3945515712.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('成都鸡蛋价格','subscription','http://127.0.0.1:8001/feed/MP_WXS_3073527878.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('蓝天禽蛋联盟','subscription','http://127.0.0.1:8001/feed/MP_WXS_3286748951.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('贵阳鸡蛋价格','subscription','http://127.0.0.1:8001/feed/MP_WXS_3574743921.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('河北辛集城方蛋品','subscription','http://127.0.0.1:8001/feed/MP_WXS_3929327149.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('湖南三尖农牧公司','subscription','http://127.0.0.1:8001/feed/MP_WXS_3545051769.rss?limit=10','rss',1,1,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 湖南正文 POC'),
('河北馆陶鸡蛋报价','subscription','http://127.0.0.1:8001/feed/MP_WXS_3924217578.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集'),
('家美鲜鸡蛋 佳美鲜','subscription','http://127.0.0.1:8001/feed/MP_WXS_3632283328.rss?limit=10','rss',1,0,5,60,30,'07:30','19:30',5,1,'article_hash','WeRSS 九账号受控采集')
ON DUPLICATE KEY UPDATE
    account_name=VALUES(account_name), account_type=VALUES(account_type), feed_url=VALUES(feed_url),
    source_type=VALUES(source_type), enabled=VALUES(enabled),
    downstream_clean_enabled=VALUES(downstream_clean_enabled),
    update_time=CURRENT_TIMESTAMP;
