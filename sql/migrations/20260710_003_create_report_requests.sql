-- Migration: create the asynchronous report generation request table.
-- Safety: additive and idempotent; existing report data is not modified.

CREATE TABLE IF NOT EXISTS wechat_report_generation_request (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '日报生成请求主键',
    idempotency_key VARCHAR(100) NOT NULL COMMENT '请求幂等键',
    report_type VARCHAR(20) NOT NULL COMMENT 'group/article/summary/all',
    report_date DATE NOT NULL COMMENT '日报业务日期',
    source_name VARCHAR(200) NULL COMMENT '可选群名或公众号名称',
    generation_trigger VARCHAR(20) NOT NULL COMMENT 'manual/automatic/compensation',
    data_cutoff_time DATETIME NOT NULL COMMENT '统计数据截止时间',
    requested_by VARCHAR(100) NOT NULL COMMENT 'admin/system',
    status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/partial_success/failed',
    worker_id VARCHAR(100) NULL COMMENT '领取请求的Worker',
    lease_expires_at DATETIME NULL COMMENT '运行租约截止时间',
    error_summary TEXT NULL COMMENT '安全失败摘要',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    start_time DATETIME NULL COMMENT '开始时间',
    end_time DATETIME NULL COMMENT '结束时间',
    UNIQUE KEY uk_report_request_idempotency (idempotency_key),
    KEY idx_report_request_pending (status, create_time),
    KEY idx_report_request_date (report_date, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
