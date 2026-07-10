-- Migration: create article clean table for Playwright article parsing.
-- Scope: existing databases created before fourth-stage article parsing.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_article_clean (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与raw表一致',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    article_url TEXT NOT NULL COMMENT '文章链接',
    publish_time DATETIME NULL COMMENT '文章发布时间',
    author VARCHAR(200) NULL COMMENT '作者',
    digest TEXT NULL COMMENT '摘要',
    content_length INT DEFAULT 0 COMMENT '正文长度',
    parse_time DATETIME NOT NULL COMMENT '解析时间',
    parse_version VARCHAR(20) DEFAULT 'v1' COMMENT '解析规则版本',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_clean_article_hash (article_hash),
    KEY idx_article_clean_account_publish (account_name, publish_time),
    KEY idx_article_clean_parse_time (parse_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
