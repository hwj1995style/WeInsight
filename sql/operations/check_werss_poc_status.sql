-- Read-only WeRSS POC status snapshot. Override the session variable before
-- running this file when the observation window starts earlier than 24 hours.
SET @poc_start = COALESCE(@poc_start, NOW() - INTERVAL 24 HOUR);

SELECT
    @poc_start AS poc_start,
    COUNT(*) AS enabled_target_count,
    SUM(feed_url LIKE '%?limit=10') AS bounded_feed_target_count,
    SUM(downstream_clean_enabled = 1) AS downstream_allowlisted_count
FROM wechat_public_account_config
WHERE enabled = 1;

SELECT
    job.id AS job_id,
    job.job_name,
    job.status AS job_status,
    job.next_run_at,
    run.id AS latest_run_id,
    run.status AS latest_run_status,
    run.target_total_count,
    run.target_success_count,
    run.target_failed_count,
    run.start_time,
    run.end_time
FROM wechat_collection_job AS job
LEFT JOIN wechat_collection_job_run AS run
  ON run.id = (
      SELECT MAX(candidate.id)
      FROM wechat_collection_job_run AS candidate
      WHERE candidate.job_id = job.id
  )
WHERE job.pipeline_type = 'article'
  AND job.status IN ('scheduled', 'active', 'stop_requested')
ORDER BY job.id DESC;

SELECT
    COUNT(*) AS failed_collect_count,
    MAX(start_time) AS latest_failed_collect_time
FROM wechat_article_collect_log
WHERE start_time >= @poc_start
  AND status = 'failed';

SELECT COUNT(*) AS article_ui_lock_count
FROM wechat_ui_lock
WHERE owner_pipeline = 'article';

SELECT COUNT(*) AS non_allowlisted_downstream_task_count
FROM wechat_article_process_task AS task
INNER JOIN wechat_article_raw AS raw_article
        ON raw_article.article_hash = task.ref_id
INNER JOIN wechat_public_account_config AS source_config
        ON source_config.account_name = raw_article.account_name
WHERE task.create_time >= @poc_start
  AND task.task_type IN ('clean_article', 'analyze_article')
  AND source_config.downstream_clean_enabled = 0;

SELECT
    worker_type,
    process_id,
    status,
    last_heartbeat_at,
    last_error_summary
FROM wechat_worker_heartbeat
WHERE last_heartbeat_at >= @poc_start
ORDER BY last_heartbeat_at DESC;

SELECT COUNT(*) AS article_task_backlog_count
FROM wechat_article_process_task
WHERE status IN ('pending', 'running', 'failed');

SELECT COUNT(*) AS group_task_backlog_count
FROM wechat_group_process_task
WHERE status IN ('pending', 'running', 'failed');
