-- Preserve historical job targets while allowing stopped jobs to change current targets.

DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260717_002$$
CREATE PROCEDURE migrate_20260717_002()
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job_target'
          AND COLUMN_NAME = 'is_active'
    ) THEN
        ALTER TABLE wechat_collection_job_target
            ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1
            COMMENT '是否为任务当前启用目标'
            AFTER config_snapshot_json;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job_target'
          AND INDEX_NAME = 'idx_job_target_active'
    ) THEN
        ALTER TABLE wechat_collection_job_target
            ADD KEY idx_job_target_active (job_id, is_active);
    END IF;
END$$
CALL migrate_20260717_002()$$
DROP PROCEDURE IF EXISTS migrate_20260717_002$$
DELIMITER ;
