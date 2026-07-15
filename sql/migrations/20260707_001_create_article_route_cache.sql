-- Migration: create article route cache for public account history article link extraction.
-- Scope: article pipeline only.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_article_route_cache (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    route_type VARCHAR(50) NOT NULL COMMENT '取链入口类型',
    entry_label VARCHAR(100) NULL COMMENT '入口标签，如历史消息、全部消息、蛋价资讯',
    entry_index INT NULL COMMENT '入口序号，用于同名或无文本入口兜底',
    link_extract_type VARCHAR(50) NOT NULL COMMENT '链接提取方式',
    cache_status VARCHAR(50) NOT NULL DEFAULT 'active' COMMENT 'active/invalid/probing/failed',
    last_success_at DATETIME NULL COMMENT '最近一次按该路由成功取到文章详情链接的时间',
    last_failure_at DATETIME NULL COMMENT '最近一次按该路由失败的时间',
    failure_count INT NOT NULL DEFAULT 0 COMMENT '连续失败次数',
    last_error_code VARCHAR(100) NULL COMMENT '最近失败错误码',
    last_error_msg VARCHAR(500) NULL COMMENT '最近失败摘要，不包含文章链接或正文',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_route_account (account_name),
    KEY idx_article_route_status (cache_status, failure_count),
    KEY idx_article_route_success (last_success_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
