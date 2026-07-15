-- Migration: add lifecycle metadata to both daily report tables.
-- Safety: each column is added only when missing in the selected database.
-- Historical rows only receive data_cutoff_time from their generate_time.

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_daily_report ADD COLUMN report_status VARCHAR(20) NOT NULL DEFAULT ''final'' COMMENT ''provisional/final'' AFTER generate_time',
        'SELECT ''skip group report_status'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_group_daily_report'
      AND COLUMN_NAME = 'report_status'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_daily_report ADD COLUMN data_cutoff_time DATETIME NULL COMMENT ''统计数据截止时间'' AFTER report_status',
        'SELECT ''skip group data_cutoff_time'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_group_daily_report'
      AND COLUMN_NAME = 'data_cutoff_time'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_daily_report ADD COLUMN generation_trigger VARCHAR(20) NOT NULL DEFAULT ''legacy'' COMMENT ''manual/automatic/compensation/legacy'' AFTER data_cutoff_time',
        'SELECT ''skip group generation_trigger'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_group_daily_report'
      AND COLUMN_NAME = 'generation_trigger'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_daily_report ADD COLUMN last_generated_by VARCHAR(100) NOT NULL DEFAULT ''system'' COMMENT ''admin/system'' AFTER generation_trigger',
        'SELECT ''skip group last_generated_by'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_group_daily_report'
      AND COLUMN_NAME = 'last_generated_by'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_daily_report ADD COLUMN report_status VARCHAR(20) NOT NULL DEFAULT ''final'' COMMENT ''provisional/final'' AFTER generate_time',
        'SELECT ''skip article report_status'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_article_daily_report'
      AND COLUMN_NAME = 'report_status'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_daily_report ADD COLUMN data_cutoff_time DATETIME NULL COMMENT ''统计数据截止时间'' AFTER report_status',
        'SELECT ''skip article data_cutoff_time'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_article_daily_report'
      AND COLUMN_NAME = 'data_cutoff_time'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_daily_report ADD COLUMN generation_trigger VARCHAR(20) NOT NULL DEFAULT ''legacy'' COMMENT ''manual/automatic/compensation/legacy'' AFTER data_cutoff_time',
        'SELECT ''skip article generation_trigger'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_article_daily_report'
      AND COLUMN_NAME = 'generation_trigger'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

SET @report_lifecycle_ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_daily_report ADD COLUMN last_generated_by VARCHAR(100) NOT NULL DEFAULT ''system'' COMMENT ''admin/system'' AFTER generation_trigger',
        'SELECT ''skip article last_generated_by'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'wechat_article_daily_report'
      AND COLUMN_NAME = 'last_generated_by'
);
PREPARE report_lifecycle_stmt FROM @report_lifecycle_ddl;
EXECUTE report_lifecycle_stmt;
DEALLOCATE PREPARE report_lifecycle_stmt;

UPDATE wechat_group_daily_report
SET data_cutoff_time = generate_time
WHERE data_cutoff_time IS NULL;

UPDATE wechat_article_daily_report
SET data_cutoff_time = generate_time
WHERE data_cutoff_time IS NULL;
