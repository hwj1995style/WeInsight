-- Production schema template: weinsight_prod.
-- The DBA must review and safely replace every explicit schema identifier
-- before deployment when the approved production schema has a different name.

CREATE ROLE IF NOT EXISTS 'weinsight_web_role';
CREATE ROLE IF NOT EXISTS 'weinsight_collector_role';
CREATE ROLE IF NOT EXISTS 'weinsight_pipeline_role';

-- web role
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`weinsight_admin_user` TO 'weinsight_web_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`weinsight_admin_session` TO 'weinsight_web_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON `weinsight_prod`.`wechat_group_config` TO 'weinsight_web_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON `weinsight_prod`.`wechat_public_account_config` TO 'weinsight_web_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_collection_job` TO 'weinsight_web_role';
GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_collection_job_target` TO 'weinsight_web_role';
GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_report_generation_request` TO 'weinsight_web_role';
GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_collection_job_event` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_collection_job_run` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_collection_job_target_run` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_worker_heartbeat` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_client_health_check` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_group_collect_log` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_collect_log` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_group_msg_clean` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_group_msg_analysis` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_clean` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_analysis` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_egg_price_item` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_group_daily_report` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_daily_report` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_group_process_task` TO 'weinsight_web_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_process_task` TO 'weinsight_web_role';

-- collector role
GRANT SELECT ON `weinsight_prod`.`wechat_group_config` TO 'weinsight_collector_role';
GRANT SELECT, UPDATE ON `weinsight_prod`.`wechat_public_account_config` TO 'weinsight_collector_role';
GRANT SELECT, UPDATE ON `weinsight_prod`.`wechat_collection_job` TO 'weinsight_collector_role';
GRANT SELECT ON `weinsight_prod`.`wechat_collection_job_target` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_collection_job_run` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_collection_job_target_run` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_collection_job_event` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_worker_heartbeat` TO 'weinsight_collector_role';
GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_client_health_check` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_group_msg_raw` TO 'weinsight_collector_role';
GRANT SELECT, INSERT ON `weinsight_prod`.`wechat_article_raw` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_group_collect_cursor` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_route_cache` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_collect_progress` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_group_collect_log` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_article_collect_log` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_group_process_task` TO 'weinsight_collector_role';
GRANT INSERT ON `weinsight_prod`.`wechat_article_process_task` TO 'weinsight_collector_role';
GRANT SELECT, INSERT, UPDATE, DELETE ON `weinsight_prod`.`wechat_ui_lock` TO 'weinsight_collector_role';

-- pipeline role
GRANT SELECT ON `weinsight_prod`.`wechat_group_msg_raw` TO 'weinsight_pipeline_role';
GRANT SELECT ON `weinsight_prod`.`wechat_article_raw` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_group_process_task` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_process_task` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_group_msg_clean` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_group_msg_analysis` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_clean` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_analysis` TO 'weinsight_pipeline_role';
GRANT INSERT, DELETE ON `weinsight_prod`.`wechat_article_egg_price_item` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_group_daily_report` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_article_daily_report` TO 'weinsight_pipeline_role';
GRANT SELECT, INSERT, UPDATE ON `weinsight_prod`.`wechat_report_generation_request` TO 'weinsight_pipeline_role';
GRANT INSERT ON `weinsight_prod`.`wechat_collection_job_event` TO 'weinsight_pipeline_role';
GRANT INSERT, UPDATE ON `weinsight_prod`.`wechat_worker_heartbeat` TO 'weinsight_pipeline_role';
