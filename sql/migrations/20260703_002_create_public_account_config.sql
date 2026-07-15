-- Migration: create public account configuration table for article POC.
-- Scope: existing databases created before fourth-stage article account config.
-- Safety: CREATE TABLE IF NOT EXISTS is idempotent and does not touch group tables.

CREATE TABLE IF NOT EXISTS wechat_public_account_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    account_type VARCHAR(50) NOT NULL DEFAULT 'subscription' COMMENT 'official/subscription',
    enabled TINYINT DEFAULT 1 COMMENT '是否启用',
    priority INT DEFAULT 5 COMMENT '优先级，数字越小优先级越高',
    poll_interval_minutes INT DEFAULT 60 COMMENT '账号级轮询间隔，默认每小时一次',
    daily_window_start TIME NOT NULL DEFAULT '07:30:00' COMMENT '每日采集窗口开始',
    daily_window_end TIME NOT NULL DEFAULT '19:30:00' COMMENT '每日采集窗口结束',
    max_articles_per_round INT DEFAULT 5 COMMENT '每轮最多采集文章数',
    collect_today_only TINYINT DEFAULT 1 COMMENT '是否只采集当天发布文章',
    dedup_key VARCHAR(50) DEFAULT 'article_hash' COMMENT '去重键',
    last_success_collect_time DATETIME NULL COMMENT '最近成功采集时间',
    remark VARCHAR(500) NULL COMMENT '备注',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_public_account_name (account_name),
    KEY idx_public_account_due (enabled, priority, last_success_collect_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
