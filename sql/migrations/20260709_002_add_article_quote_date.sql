-- Migration: add quote business date fields to article analysis and egg price items.
-- Scope: article-only quote extraction date semantics.
-- Safety: columns and indexes are added only when missing; group tables are not touched.

SET @schema_name = DATABASE();

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_analysis ADD COLUMN collect_time DATETIME NULL COMMENT ''文章采集时间'' AFTER publish_date',
        'SELECT ''skip article_analysis collect_time'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_analysis'
      AND COLUMN_NAME = 'collect_time'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_analysis ADD COLUMN quote_date DATE NULL COMMENT ''报价业务日期'' AFTER collect_time',
        'SELECT ''skip article_analysis quote_date'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_analysis'
      AND COLUMN_NAME = 'quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_analysis ADD COLUMN quote_date_source VARCHAR(50) DEFAULT ''unknown'' COMMENT ''报价日期来源'' AFTER quote_date',
        'SELECT ''skip article_analysis quote_date_source'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_analysis'
      AND COLUMN_NAME = 'quote_date_source'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_analysis ADD COLUMN quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT ''报价日期置信度'' AFTER quote_date_source',
        'SELECT ''skip article_analysis quote_date_confidence'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_analysis'
      AND COLUMN_NAME = 'quote_date_confidence'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_analysis ADD INDEX idx_article_analysis_quote_date (account_name, quote_date)',
        'SELECT ''skip idx_article_analysis_quote_date'''
    )
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_analysis'
      AND INDEX_NAME = 'idx_article_analysis_quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN collect_time DATETIME NULL COMMENT ''文章采集时间'' AFTER publish_date',
        'SELECT ''skip egg_price_item collect_time'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'collect_time'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN quote_date DATE NULL COMMENT ''报价业务日期'' AFTER collect_time',
        'SELECT ''skip egg_price_item quote_date'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN quote_date_source VARCHAR(50) DEFAULT ''unknown'' COMMENT ''报价日期来源'' AFTER quote_date',
        'SELECT ''skip egg_price_item quote_date_source'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'quote_date_source'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT ''报价日期置信度'' AFTER quote_date_source',
        'SELECT ''skip egg_price_item quote_date_confidence'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'quote_date_confidence'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD INDEX idx_article_price_quote_date (account_name, quote_date)',
        'SELECT ''skip idx_article_price_quote_date'''
    )
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND INDEX_NAME = 'idx_article_price_quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD INDEX idx_article_price_product_quote_date (product_family, quote_date)',
        'SELECT ''skip idx_article_price_product_quote_date'''
    )
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND INDEX_NAME = 'idx_article_price_product_quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE wechat_article_analysis analysis
JOIN wechat_article_raw raw
  ON raw.article_hash = analysis.article_hash
SET analysis.collect_time = raw.collect_time
WHERE analysis.collect_time IS NULL;

UPDATE wechat_article_analysis
SET quote_date = publish_date,
    quote_date_source = 'publish_date_fallback',
    quote_date_confidence = 0.6000
WHERE quote_date IS NULL
  AND publish_date IS NOT NULL;

UPDATE wechat_article_egg_price_item item
JOIN wechat_article_analysis analysis
  ON analysis.article_hash = item.article_hash
SET item.collect_time = analysis.collect_time,
    item.quote_date = analysis.quote_date,
    item.quote_date_source = analysis.quote_date_source,
    item.quote_date_confidence = analysis.quote_date_confidence
WHERE item.quote_date IS NULL;
