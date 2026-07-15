-- Add a database-enforced singleton identity and a fixed serialization row.
-- Additive and idempotent; historical jobs and runs are preserved.

DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260713_004$$
CREATE PROCEDURE migrate_20260713_004()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job'
          AND COLUMN_NAME = 'managed_key'
    ) THEN
        ALTER TABLE wechat_collection_job
            ADD COLUMN managed_key VARCHAR(100) NULL
            COMMENT '系统管理任务唯一身份，人工任务为空' AFTER id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job'
          AND INDEX_NAME = 'uk_collection_job_managed_key'
    ) THEN
        ALTER TABLE wechat_collection_job
            ADD UNIQUE KEY uk_collection_job_managed_key (managed_key);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM wechat_collection_job
        WHERE managed_key = 'article_global'
    ) THEN
        UPDATE wechat_collection_job
        SET managed_key = 'article_global'
        WHERE id = (
            SELECT id FROM (
                SELECT id
                FROM wechat_collection_job
                WHERE job_name = '公众号全局增量采集（系统）'
                  AND pipeline_type = 'article'
                ORDER BY id DESC
                LIMIT 1
            ) AS latest_system_job
        );
    END IF;

    UPDATE wechat_collection_job
    SET status = 'stop_requested', next_run_at = NULL
    WHERE job_name = '公众号全局增量采集（系统）'
      AND pipeline_type = 'article'
      AND managed_key IS NULL
      AND status IN ('scheduled', 'active');
END$$
CALL migrate_20260713_004()$$
DROP PROCEDURE IF EXISTS migrate_20260713_004$$
DELIMITER ;

CREATE TABLE IF NOT EXISTS wechat_system_job_coordination (
    coordination_key VARCHAR(100) PRIMARY KEY COMMENT '固定系统协调键',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO wechat_system_job_coordination (coordination_key)
VALUES ('article_global');
