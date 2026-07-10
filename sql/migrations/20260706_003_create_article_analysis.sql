-- Migration: create article analysis table for rule-based article post-processing.
-- Scope: existing databases created before sixth-stage article analysis.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_article_analysis (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与clean表一致',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    publish_time DATETIME NULL COMMENT '文章发布时间',
    publish_date DATE NULL COMMENT '文章发布日期',
    author VARCHAR(200) NULL COMMENT '作者',
    summary_text TEXT NULL COMMENT '规则摘要',
    topic_tags_json TEXT NULL COMMENT '主题标签JSON',
    keyword_hits_json TEXT NULL COMMENT '关键词命中JSON',
    extracted_tables_json TEXT NULL COMMENT '提取表格JSON',
    price_items_json TEXT NULL COMMENT '价格项JSON',
    content_length INT DEFAULT 0 COMMENT '正文长度',
    analysis_version VARCHAR(20) DEFAULT 'v1' COMMENT '分析规则版本',
    analyze_time DATETIME NOT NULL COMMENT '分析时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_analysis_hash (article_hash),
    KEY idx_article_analysis_account_date (account_name, publish_date),
    KEY idx_article_analysis_time (analyze_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
