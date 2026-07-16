-- 旧 article_daily_report 任务已由 wechat_report_generation_request 替代。
-- 保留历史任务行用于审计，只把不可消费的非终态统一收敛为成功。
UPDATE wechat_article_process_task
SET status = 'success',
    next_run_time = NULL,
    error_msg = NULL,
    update_time = CURRENT_TIMESTAMP
WHERE task_type = 'article_daily_report'
  AND status IN ('pending', 'running', 'failed');
