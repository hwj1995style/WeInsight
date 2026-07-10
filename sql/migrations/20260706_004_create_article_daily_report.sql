-- Migration: create article daily report table for rule-based article summaries.
-- Scope: existing databases created before sixth-stage article daily reports.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_article_daily_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    report_date DATE NOT NULL COMMENT '日报日期',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(300) NOT NULL COMMENT '日报标题',
    markdown_body MEDIUMTEXT NOT NULL COMMENT 'Markdown日报草稿',
    article_count INT DEFAULT 0 COMMENT '文章数',
    avg_content_length INT DEFAULT 0 COMMENT '平均正文长度',
    top_tags_json TEXT NULL COMMENT '主题标签TOP JSON',
    top_keywords_json TEXT NULL COMMENT '关键词TOP JSON',
    report_version VARCHAR(20) DEFAULT 'v1' COMMENT '日报模板版本',
    generate_time DATETIME NOT NULL COMMENT '生成时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_daily_report (report_date, account_name),
    KEY idx_article_daily_report_date (report_date),
    KEY idx_article_daily_report_generate_time (generate_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
