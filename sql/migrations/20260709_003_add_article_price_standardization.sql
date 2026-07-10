-- Migration: add first-version standardized egg price fields.
-- Scope: article egg price detail rows only.
-- Safety: columns and indexes are added only when missing; group tables are not touched.

SET @schema_name = DATABASE();

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN standard_price_low DECIMAL(10,4) NULL COMMENT ''统一口径价格下限'' AFTER price_unit_text',
        'SELECT ''skip standard_price_low'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'standard_price_low'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN standard_price_high DECIMAL(10,4) NULL COMMENT ''统一口径价格上限'' AFTER standard_price_low',
        'SELECT ''skip standard_price_high'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'standard_price_high'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN standard_price_unit VARCHAR(50) DEFAULT ''yuan_per_jin'' COMMENT ''统一口径价格单位'' AFTER standard_price_high',
        'SELECT ''skip standard_price_unit'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'standard_price_unit'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_basis_weight_low DECIMAL(10,3) NULL COMMENT ''换算分母重量下限'' AFTER standard_price_unit',
        'SELECT ''skip conversion_basis_weight_low'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_basis_weight_low'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_basis_weight_high DECIMAL(10,3) NULL COMMENT ''换算分母重量上限'' AFTER conversion_basis_weight_low',
        'SELECT ''skip conversion_basis_weight_high'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_basis_weight_high'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_basis_weight_unit VARCHAR(20) NULL COMMENT ''换算分母重量单位'' AFTER conversion_basis_weight_high',
        'SELECT ''skip conversion_basis_weight_unit'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_basis_weight_unit'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_method VARCHAR(50) DEFAULT ''unconverted'' COMMENT ''规格换算方法'' AFTER conversion_basis_weight_unit',
        'SELECT ''skip conversion_method'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_method'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_confidence DECIMAL(5,4) DEFAULT 0 COMMENT ''规格换算置信度'' AFTER conversion_method',
        'SELECT ''skip conversion_confidence'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_confidence'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN conversion_notes_json TEXT NULL COMMENT ''规格换算备注JSON'' AFTER conversion_confidence',
        'SELECT ''skip conversion_notes_json'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'conversion_notes_json'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD COLUMN include_in_standard_price TINYINT DEFAULT 0 COMMENT ''是否纳入统一鸡蛋价格主口径'' AFTER conversion_notes_json',
        'SELECT ''skip include_in_standard_price'''
    )
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND COLUMN_NAME = 'include_in_standard_price'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @ddl = (
    SELECT IF(
        COUNT(*) = 0,
        'ALTER TABLE wechat_article_egg_price_item ADD INDEX idx_article_price_standard_quote_date (include_in_standard_price, quote_date)',
        'SELECT ''skip idx_article_price_standard_quote_date'''
    )
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'wechat_article_egg_price_item'
      AND INDEX_NAME = 'idx_article_price_standard_quote_date'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
