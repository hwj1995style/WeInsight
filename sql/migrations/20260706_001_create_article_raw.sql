-- Migration: create article raw table for public account/subscription POC.
-- Scope: existing databases created before fourth-stage article raw storage.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_article_raw (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    article_url TEXT NOT NULL COMMENT '文章链接',
    publish_time DATETIME NOT NULL COMMENT '文章发布时间',
    publish_date DATE NOT NULL COMMENT '文章发布日期',
    author VARCHAR(200) NULL COMMENT '作者',
    digest TEXT NULL COMMENT '摘要',
    collect_batch_id VARCHAR(64) NULL COMMENT '采集批次',
    collect_time DATETIME NOT NULL COMMENT '采集时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_hash (article_hash),
    KEY idx_article_account_publish (account_name, publish_time),
    KEY idx_article_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
