-- Migration: add structured quality fields for group daily report v2.
-- Scope: existing databases created before Task 20.
-- Safety: each column is added only when it is missing.

SET @schema_name = DATABASE();

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_msg_analysis ADD COLUMN region_hits TEXT NULL COMMENT ''命中的地区词，JSON数组'' AFTER keyword_hits',
        'SELECT ''skip region_hits'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_group_msg_analysis'
      AND COLUMN_NAME = 'region_hits'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_msg_analysis ADD COLUMN category_hits TEXT NULL COMMENT ''命中的品类词，JSON数组'' AFTER region_hits',
        'SELECT ''skip category_hits'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_group_msg_analysis'
      AND COLUMN_NAME = 'category_hits'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_msg_analysis ADD COLUMN opportunity_hits TEXT NULL COMMENT ''命中的商机词，JSON数组'' AFTER category_hits',
        'SELECT ''skip opportunity_hits'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_group_msg_analysis'
      AND COLUMN_NAME = 'opportunity_hits'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_group_msg_analysis ADD COLUMN opportunity_score INT DEFAULT 0 COMMENT ''可疑商机评分'' AFTER opportunity_hits',
        'SELECT ''skip opportunity_score'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_group_msg_analysis'
      AND COLUMN_NAME = 'opportunity_score'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
