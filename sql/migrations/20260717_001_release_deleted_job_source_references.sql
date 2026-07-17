-- Allow the application to detach source references held by soft-deleted jobs.
-- Source foreign keys remain RESTRICT; historical targets and snapshots stay intact.

DELIMITER $$
DROP PROCEDURE IF EXISTS migrate_20260717_001$$
CREATE PROCEDURE migrate_20260717_001()
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job_target'
          AND CONSTRAINT_NAME = 'ck_job_target_exactly_one'
          AND CONSTRAINT_TYPE = 'CHECK'
    ) THEN
        ALTER TABLE wechat_collection_job_target
            DROP CHECK ck_job_target_exactly_one;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'wechat_collection_job_target'
          AND CONSTRAINT_NAME = 'ck_job_target_at_most_one'
          AND CONSTRAINT_TYPE = 'CHECK'
    ) THEN
        ALTER TABLE wechat_collection_job_target
            ADD CONSTRAINT ck_job_target_at_most_one
            CHECK (group_config_id IS NULL OR article_config_id IS NULL);
    END IF;

END$$
CALL migrate_20260717_001()$$
DROP PROCEDURE IF EXISTS migrate_20260717_001$$
DELIMITER ;
