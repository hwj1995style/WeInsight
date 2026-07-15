-- Migration: create the collection control-plane schema.
-- Scope: jobs, runs, events, worker heartbeats, and WeChat health checks.
-- Safety: additive and idempotent; source configuration rows remain protected by RESTRICT.

CREATE TABLE IF NOT EXISTS wechat_collection_job (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '采集任务主键',
    managed_key VARCHAR(100) NULL COMMENT '系统管理任务唯一身份，人工任务为空',
    job_name VARCHAR(200) NOT NULL COMMENT '采集任务名称',
    pipeline_type VARCHAR(20) NOT NULL COMMENT 'group/article',
    effective_start_at DATETIME NOT NULL COMMENT '任务整体开始时间',
    effective_end_at DATETIME NOT NULL COMMENT '任务整体结束时间',
    daily_window_start TIME NOT NULL COMMENT '每日运行窗口开始',
    daily_window_end TIME NOT NULL COMMENT '每日运行窗口结束',
    interval_seconds INT NOT NULL COMMENT '任务执行间隔秒数',
    status VARCHAR(30) NOT NULL COMMENT 'scheduled/active/stop_requested/stopped/completed/deleted',
    next_run_at DATETIME NULL COMMENT '下次计划运行时间',
    stop_requested_at DATETIME NULL COMMENT '停止请求时间',
    stop_requested_by VARCHAR(100) NULL COMMENT '停止请求管理员',
    deleted_at DATETIME NULL COMMENT '软删除时间',
    deleted_by VARCHAR(100) NULL COMMENT '软删除管理员',
    version INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_collection_job_pipeline CHECK (pipeline_type IN ('group', 'article')),
    UNIQUE KEY uk_collection_job_managed_key (managed_key),
    KEY idx_collection_job_due (status, next_run_at),
    KEY idx_collection_job_window (effective_start_at, effective_end_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS wechat_collection_job_target (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务目标主键',
    job_id BIGINT NOT NULL COMMENT '采集任务主键',
    group_config_id BIGINT NULL COMMENT '微信群配置主键',
    article_config_id BIGINT NULL COMMENT '公众号配置主键',
    target_name_snapshot VARCHAR(200) NOT NULL COMMENT '目标名称快照',
    priority_snapshot INT NOT NULL COMMENT '优先级快照',
    config_snapshot_json TEXT NOT NULL COMMENT '配置快照JSON',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_group_target (job_id, group_config_id),
    UNIQUE KEY uk_job_article_target (job_id, article_config_id),
    CONSTRAINT ck_job_target_exactly_one CHECK (
        (group_config_id IS NOT NULL AND article_config_id IS NULL)
        OR (group_config_id IS NULL AND article_config_id IS NOT NULL)
    ),
    CONSTRAINT fk_job_target_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT,
    CONSTRAINT fk_job_target_group FOREIGN KEY (group_config_id)
        REFERENCES wechat_group_config(id) ON DELETE RESTRICT,
    CONSTRAINT fk_job_target_article FOREIGN KEY (article_config_id)
        REFERENCES wechat_public_account_config(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_run (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务运行实例主键',
    job_id BIGINT NOT NULL COMMENT '采集任务主键',
    scheduled_at DATETIME NOT NULL COMMENT '本次计划执行时间',
    status VARCHAR(30) NOT NULL COMMENT 'queued/running/success/partial_success/failed/cancelled/aborted',
    worker_id VARCHAR(100) NULL COMMENT '执行Worker标识',
    lease_expires_at DATETIME NULL COMMENT '运行租约过期时间',
    start_time DATETIME NULL COMMENT '实际开始时间',
    end_time DATETIME NULL COMMENT '实际结束时间',
    target_total_count INT NOT NULL DEFAULT 0 COMMENT '目标总数',
    target_success_count INT NOT NULL DEFAULT 0 COMMENT '成功目标数',
    target_failed_count INT NOT NULL DEFAULT 0 COMMENT '失败目标数',
    error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    error_summary VARCHAR(1000) NULL COMMENT '脱敏错误摘要',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_schedule (job_id, scheduled_at),
    KEY idx_collection_run_status_lease (status, lease_expires_at),
    KEY idx_collection_run_worker (worker_id, status),
    CONSTRAINT fk_collection_run_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_target_run (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务目标运行主键',
    run_id BIGINT NOT NULL COMMENT '任务运行实例主键',
    job_target_id BIGINT NOT NULL COMMENT '任务目标主键',
    batch_id VARCHAR(64) NULL COMMENT '业务采集批次标识',
    status VARCHAR(30) NOT NULL COMMENT 'queued/running/success/failed/skipped/cancelled',
    stage VARCHAR(50) NULL COMMENT '当前处理阶段',
    read_count INT NOT NULL DEFAULT 0 COMMENT '读取数量',
    insert_count INT NOT NULL DEFAULT 0 COMMENT '新增数量',
    duplicate_count INT NOT NULL DEFAULT 0 COMMENT '重复数量',
    skipped_count INT NOT NULL DEFAULT 0 COMMENT '跳过数量',
    error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    error_summary VARCHAR(1000) NULL COMMENT '脱敏错误摘要',
    screenshot_path VARCHAR(1000) NULL COMMENT '采集机本地故障截图绝对路径',
    start_time DATETIME NULL COMMENT '实际开始时间',
    end_time DATETIME NULL COMMENT '实际结束时间',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_target_run (run_id, job_target_id),
    KEY idx_target_run_status_stage (status, stage),
    KEY idx_target_run_batch (batch_id),
    CONSTRAINT fk_target_run_run FOREIGN KEY (run_id)
        REFERENCES wechat_collection_job_run(id) ON DELETE RESTRICT,
    CONSTRAINT fk_target_run_target FOREIGN KEY (job_target_id)
        REFERENCES wechat_collection_job_target(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '结构化运行事件主键',
    job_id BIGINT NULL COMMENT '采集任务主键',
    run_id BIGINT NULL COMMENT '任务运行实例主键',
    target_run_id BIGINT NULL COMMENT '目标运行主键',
    worker_id VARCHAR(100) NULL COMMENT '上报Worker标识',
    level VARCHAR(20) NOT NULL COMMENT 'debug/info/warning/error',
    event_type VARCHAR(100) NOT NULL COMMENT '结构化事件类型',
    stage VARCHAR(50) NULL COMMENT '事件所属阶段',
    message VARCHAR(1000) NOT NULL COMMENT '脱敏事件消息',
    metrics_json TEXT NULL COMMENT '结构化指标JSON',
    actor_type VARCHAR(20) NOT NULL COMMENT 'admin/system/worker',
    actor_name VARCHAR(100) NULL COMMENT '操作者名称',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_collection_event_run (run_id, id),
    KEY idx_collection_event_job_time (job_id, create_time),
    KEY idx_collection_event_worker_time (worker_id, create_time),
    CONSTRAINT fk_collection_event_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT,
    CONSTRAINT fk_collection_event_run FOREIGN KEY (run_id)
        REFERENCES wechat_collection_job_run(id) ON DELETE RESTRICT,
    CONSTRAINT fk_collection_event_target_run FOREIGN KEY (target_run_id)
        REFERENCES wechat_collection_job_target_run(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_worker_heartbeat (
    worker_id VARCHAR(100) NOT NULL COMMENT 'Worker唯一标识',
    worker_type VARCHAR(30) NOT NULL COMMENT 'collector/pipeline',
    hostname VARCHAR(255) NOT NULL COMMENT '采集主机名',
    process_id INT NOT NULL COMMENT 'Worker进程ID',
    version VARCHAR(100) NULL COMMENT 'Worker版本',
    status VARCHAR(30) NOT NULL COMMENT 'starting/running/degraded/stopping/stopped',
    last_heartbeat_at DATETIME NOT NULL COMMENT '最近心跳时间',
    start_time DATETIME NOT NULL COMMENT 'Worker启动时间',
    last_error_summary VARCHAR(1000) NULL COMMENT '最近脱敏错误摘要',
    PRIMARY KEY (worker_id),
    KEY idx_worker_heartbeat_type_status (worker_type, status),
    KEY idx_worker_heartbeat_time (last_heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_client_health_check (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '微信客户端健康检查主键',
    worker_id VARCHAR(100) NULL COMMENT '执行探测的Worker标识',
    hostname VARCHAR(255) NOT NULL COMMENT '微信客户端所在主机名',
    status VARCHAR(50) NOT NULL COMMENT 'ok/not_running/not_logged_in/version_mismatch/window_unavailable/rpa_unavailable',
    detected_version VARCHAR(100) NULL COMMENT '探测到的微信版本',
    consecutive_failure_count INT NOT NULL DEFAULT 0 COMMENT '连续失败次数',
    message VARCHAR(1000) NULL COMMENT '脱敏健康消息',
    checked_at DATETIME NOT NULL COMMENT '检查时间',
    KEY idx_client_health_checked (checked_at),
    KEY idx_client_health_status (status, checked_at),
    KEY idx_client_health_worker (worker_id, checked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
