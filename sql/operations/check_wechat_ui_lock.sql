-- Read-only production diagnostic for the Collector/DBA account.
-- The approved production schema is fixed to weinsight_prod.

SELECT
    CURRENT_TIMESTAMP AS database_time,
    MAX(expire_time) AS lease_until,
    MAX(owner_pipeline) AS owner_pipeline,
    MAX(owner_task_id) AS owner_task_id,
    CASE
        WHEN COUNT(*) = 0 THEN 'free_no_row'
        WHEN MAX(expire_time) <= CURRENT_TIMESTAMP THEN 'free_expired'
        ELSE 'held'
    END AS ui_lock_state
FROM `weinsight_prod`.`wechat_ui_lock`
WHERE lock_name = 'wechat_ui';
