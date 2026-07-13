CREATE TABLE IF NOT EXISTS wechat_group_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    enabled TINYINT DEFAULT 1 COMMENT '是否启用',
    priority INT DEFAULT 5 COMMENT '优先级，数字越小优先级越高',
    poll_interval_seconds INT DEFAULT 60 COMMENT '轮询间隔',
    backtrack_pages INT DEFAULT 10 COMMENT '普通回溯屏数',
    extra_backtrack_pages INT DEFAULT 30 COMMENT '找不到锚点时额外回溯屏数',
    is_core_group TINYINT DEFAULT 0 COMMENT '是否核心群',
    remark VARCHAR(500) NULL COMMENT '备注',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_name (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_msg_raw (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    msg_hash VARCHAR(64) NOT NULL COMMENT '消息唯一hash',
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    sender_name VARCHAR(200) NULL COMMENT '发送人',
    msg_time_display VARCHAR(100) NULL COMMENT '微信界面显示时间',
    msg_time_inferred DATETIME NULL COMMENT '推断消息时间',
    msg_type VARCHAR(50) NULL COMMENT '消息类型',
    msg_content TEXT NULL COMMENT '消息内容',
    raw_content TEXT NULL COMMENT '原始内容',
    collect_time DATETIME NOT NULL COMMENT '采集时间',
    collect_batch_id VARCHAR(64) NULL COMMENT '采集批次',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_msg_hash (msg_hash),
    KEY idx_group_time (group_name, msg_time_inferred),
    KEY idx_collect_time (collect_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_msg_clean (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    msg_hash VARCHAR(64) NOT NULL COMMENT '消息唯一hash，与raw表一致',
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    sender_hash VARCHAR(64) NULL COMMENT '发送人脱敏hash',
    sender_display VARCHAR(200) NULL COMMENT '发送人脱敏展示名',
    msg_time_display VARCHAR(100) NULL COMMENT '微信界面显示时间',
    msg_time_inferred DATETIME NULL COMMENT '推断消息时间',
    msg_type VARCHAR(50) NULL COMMENT '消息类型',
    clean_content TEXT NULL COMMENT '脱敏后的消息内容',
    content_length INT DEFAULT 0 COMMENT '脱敏后内容长度',
    is_empty TINYINT DEFAULT 0 COMMENT '是否空消息或无业务内容',
    has_phone TINYINT DEFAULT 0 COMMENT '原文是否包含手机号',
    has_wechat_id TINYINT DEFAULT 0 COMMENT '原文是否包含微信号',
    clean_version VARCHAR(20) DEFAULT 'v1' COMMENT '清洗规则版本',
    source_collect_batch_id VARCHAR(64) NULL COMMENT '来源采集批次',
    clean_time DATETIME NOT NULL COMMENT '清洗时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_clean_msg_hash (msg_hash),
    KEY idx_clean_group_time (group_name, msg_time_inferred),
    KEY idx_clean_time (clean_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_msg_analysis (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    msg_hash VARCHAR(64) NOT NULL COMMENT '消息唯一hash，与clean表一致',
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    sender_hash VARCHAR(64) NULL COMMENT '发送人脱敏hash',
    msg_time_display VARCHAR(100) NULL COMMENT '微信界面显示时间',
    msg_time_inferred DATETIME NULL COMMENT '推断消息时间',
    activity_date DATE NOT NULL COMMENT '归属分析日期',
    activity_hour INT NOT NULL COMMENT '归属小时，0-23',
    intent_type VARCHAR(50) NOT NULL COMMENT '意向类型：demand/supply/neutral/empty',
    keyword_hits TEXT NULL COMMENT '命中的规则关键词，JSON数组',
    region_hits TEXT NULL COMMENT '命中的地区词，JSON数组',
    category_hits TEXT NULL COMMENT '命中的品类词，JSON数组',
    opportunity_hits TEXT NULL COMMENT '命中的商机词，JSON数组',
    opportunity_score INT DEFAULT 0 COMMENT '可疑商机评分',
    has_contact TINYINT DEFAULT 0 COMMENT '是否包含联系方式标记',
    content_length INT DEFAULT 0 COMMENT '脱敏后内容长度',
    analysis_version VARCHAR(20) DEFAULT 'v1' COMMENT '分析规则版本',
    analyze_time DATETIME NOT NULL COMMENT '分析时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_analysis_msg_hash (msg_hash),
    KEY idx_group_analysis_date (activity_date, group_name),
    KEY idx_group_analysis_intent (group_name, intent_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_daily_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    report_date DATE NOT NULL COMMENT '日报日期',
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    title VARCHAR(300) NOT NULL COMMENT '日报标题',
    markdown_body MEDIUMTEXT NOT NULL COMMENT 'Markdown日报草稿',
    message_count INT DEFAULT 0 COMMENT '分析消息数',
    sender_count INT DEFAULT 0 COMMENT '活跃发送人数',
    demand_count INT DEFAULT 0 COMMENT '需求消息数',
    supply_count INT DEFAULT 0 COMMENT '供应消息数',
    contact_count INT DEFAULT 0 COMMENT '包含联系方式标记的消息数',
    peak_hour INT NULL COMMENT '消息高峰小时',
    top_keywords TEXT NULL COMMENT '高频关键词，JSON数组',
    report_version VARCHAR(20) DEFAULT 'v1' COMMENT '日报模板版本',
    generate_time DATETIME NOT NULL COMMENT '生成时间',
    report_status VARCHAR(20) NOT NULL DEFAULT 'final' COMMENT 'provisional/final',
    data_cutoff_time DATETIME NULL COMMENT '统计数据截止时间',
    generation_trigger VARCHAR(20) NOT NULL DEFAULT 'legacy' COMMENT 'manual/automatic/compensation/legacy',
    last_generated_by VARCHAR(100) NOT NULL DEFAULT 'system' COMMENT 'admin/system',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_daily_report (report_date, group_name),
    KEY idx_group_daily_report_group (group_name, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_collect_cursor (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    group_name VARCHAR(200) NOT NULL COMMENT '微信群名称',
    last_msg_hash VARCHAR(64) NULL COMMENT '最近成功采集消息hash',
    last_msg_time_display VARCHAR(100) NULL COMMENT '最近消息显示时间',
    last_msg_content_preview VARCHAR(500) NULL COMMENT '最近消息内容预览',
    last_sender_name VARCHAR(200) NULL COMMENT '最近发送人',
    last_success_collect_time DATETIME NULL COMMENT '最近成功采集时间',
    last_collect_batch_id VARCHAR(64) NULL COMMENT '最近成功批次',
    last_anchor_found TINYINT DEFAULT 1 COMMENT '最近一次是否找到锚点',
    possible_lost TINYINT DEFAULT 0 COMMENT '是否可能漏采',
    consecutive_fail_count INT DEFAULT 0 COMMENT '连续失败次数',
    error_msg TEXT NULL COMMENT '最近失败原因',
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_cursor (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_process_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_type VARCHAR(50) NOT NULL COMMENT 'clean_group_msg/analyze_group_msg/group_daily_report',
    ref_type VARCHAR(50) NOT NULL COMMENT 'msg/date',
    ref_id VARCHAR(100) NOT NULL COMMENT '消息hash或日期',
    status VARCHAR(50) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/failed/skipped',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '重试次数',
    next_run_time DATETIME NULL COMMENT '下次执行时间',
    error_msg TEXT NULL COMMENT '失败原因',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_group_task_ref (task_type, ref_type, ref_id),
    KEY idx_group_status_next_run (status, next_run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_public_account_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    account_type VARCHAR(50) NOT NULL DEFAULT 'subscription' COMMENT 'official/subscription',
    feed_url TEXT NULL COMMENT '标准 RSS 或 Atom 订阅地址',
    feed_url_hash BINARY(32) GENERATED ALWAYS AS (UNHEX(SHA2(feed_url, 256))) STORED COMMENT 'Feed URL 完整 SHA-256',
    source_type VARCHAR(20) NOT NULL DEFAULT 'rss' COMMENT '文章来源类型，首期固定 rss',
    werss_source_id VARCHAR(200) NULL COMMENT 'WeRSS 来源稳定标识，历史记录允许为空',
    upstream_status VARCHAR(20) NOT NULL DEFAULT 'unknown' COMMENT 'WeRSS 上游状态，由应用校验允许值',
    upstream_last_seen_at DATETIME NULL COMMENT '最近一次在 WeRSS 来源目录中出现的时间',
    upstream_missing_at DATETIME NULL COMMENT '首次确认 WeRSS 来源目录缺失的时间',
    enabled TINYINT DEFAULT 1 COMMENT '是否启用',
    downstream_clean_enabled TINYINT NOT NULL DEFAULT 0 COMMENT '是否允许进入文章清洗分析下游，默认拒绝',
    priority INT DEFAULT 5 COMMENT '优先级，数字越小优先级越高',
    poll_interval_minutes INT DEFAULT 60 COMMENT '账号级轮询间隔，默认每小时一次',
    request_timeout_seconds INT NOT NULL DEFAULT 30 COMMENT 'Feed 单次请求超时秒数',
    daily_window_start TIME NOT NULL DEFAULT '07:30:00' COMMENT '每日采集窗口开始',
    daily_window_end TIME NOT NULL DEFAULT '19:30:00' COMMENT '每日采集窗口结束',
    max_articles_per_round INT DEFAULT 5 COMMENT '每轮最多采集文章数',
    collect_today_only TINYINT DEFAULT 1 COMMENT '是否只采集当天发布文章',
    dedup_key VARCHAR(50) DEFAULT 'article_hash' COMMENT '去重键',
    last_success_collect_time DATETIME NULL COMMENT '最近成功采集时间',
    last_feed_etag VARCHAR(500) NULL COMMENT 'Feed 最近成功响应 ETag',
    last_feed_modified VARCHAR(100) NULL COMMENT 'Feed 最近成功响应 Last-Modified',
    last_error_code VARCHAR(100) NULL COMMENT '最近一次 Feed 结构化错误码',
    remark VARCHAR(500) NULL COMMENT '备注',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_public_account_name (account_name),
    UNIQUE KEY uk_public_account_feed_url_hash (feed_url_hash),
    UNIQUE KEY uk_public_account_werss_source_id (werss_source_id),
    KEY idx_public_account_due (enabled, priority, last_success_collect_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_raw (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    article_url TEXT NOT NULL COMMENT '文章链接',
    content_locator VARCHAR(200) NULL COMMENT '受控正文定位标识',
    content_locator_type VARCHAR(30) NULL COMMENT '正文定位标识类型',
    publish_time DATETIME NOT NULL COMMENT '文章发布时间',
    publish_date DATE NOT NULL COMMENT '文章发布日期',
    author VARCHAR(200) NULL COMMENT '作者',
    digest TEXT NULL COMMENT '摘要',
    collect_batch_id VARCHAR(64) NULL COMMENT '采集批次',
    collect_time DATETIME NOT NULL COMMENT '采集时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_hash (article_hash),
    KEY idx_article_account_publish (account_name, publish_time),
    KEY idx_article_publish_date (publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_clean (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与raw表一致',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    article_url TEXT NOT NULL COMMENT '文章链接',
    publish_time DATETIME NULL COMMENT '文章发布时间',
    author VARCHAR(200) NULL COMMENT '作者',
    digest TEXT NULL COMMENT '摘要',
    content_length INT DEFAULT 0 COMMENT '正文长度',
    content_source VARCHAR(20) NULL COMMENT '正文获取来源',
    content_hash CHAR(64) NULL COMMENT '净化正文SHA-256',
    content_fetch_status VARCHAR(30) NULL COMMENT '正文获取状态',
    parse_time DATETIME NOT NULL COMMENT '解析时间',
    parse_version VARCHAR(20) DEFAULT 'v1' COMMENT '解析规则版本',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_clean_article_hash (article_hash),
    KEY idx_article_clean_account_publish (account_name, publish_time),
    KEY idx_article_clean_parse_time (parse_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_analysis (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与clean表一致',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    publish_time DATETIME NULL COMMENT '文章发布时间',
    publish_date DATE NULL COMMENT '文章发布日期',
    collect_time DATETIME NULL COMMENT '文章采集时间',
    quote_date DATE NULL COMMENT '报价业务日期',
    quote_date_source VARCHAR(50) DEFAULT 'unknown' COMMENT '报价日期来源',
    quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '报价日期置信度',
    author VARCHAR(200) NULL COMMENT '作者',
    summary_text TEXT NULL COMMENT '规则摘要',
    topic_tags_json TEXT NULL COMMENT '主题标签JSON',
    keyword_hits_json TEXT NULL COMMENT '关键词命中JSON',
    extracted_tables_json TEXT NULL COMMENT '提取表格JSON',
    price_items_json TEXT NULL COMMENT '价格项JSON',
    content_length INT DEFAULT 0 COMMENT '正文长度',
    analysis_version VARCHAR(20) DEFAULT 'v1' COMMENT '分析规则版本',
    analyze_time DATETIME NOT NULL COMMENT '分析时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_analysis_hash (article_hash),
    KEY idx_article_analysis_account_date (account_name, publish_date),
    KEY idx_article_analysis_quote_date (account_name, quote_date),
    KEY idx_article_analysis_time (analyze_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_egg_price_item (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    article_hash VARCHAR(64) NOT NULL COMMENT '文章唯一hash，与article_analysis一致',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(500) NOT NULL COMMENT '文章标题',
    publish_time DATETIME NULL COMMENT '文章发布时间',
    publish_date DATE NULL COMMENT '文章发布日期',
    collect_time DATETIME NULL COMMENT '文章采集时间',
    quote_date DATE NULL COMMENT '报价业务日期',
    quote_date_source VARCHAR(50) DEFAULT 'unknown' COMMENT '报价日期来源',
    quote_date_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '报价日期置信度',
    item_index INT NOT NULL COMMENT '同一文章内报价明细序号',
    source_media_type VARCHAR(50) NOT NULL COMMENT '来源类型：dom_table/text_line/text_block',
    source_table_index INT NULL COMMENT 'DOM表格序号',
    source_row_index INT NULL COMMENT '来源行序号',
    source_table_title VARCHAR(300) NULL COMMENT '表格或段落标题',
    source_context_json TEXT NULL COMMENT '表格级或段落级上下文摘要，不保存全文',
    source_confidence DECIMAL(5,4) NULL COMMENT '规则解析置信度',
    product_family VARCHAR(50) NOT NULL COMMENT '产品族：chicken_egg/duck_egg/quail_egg/preserved_egg/salted_egg/other_egg',
    product_name VARCHAR(100) NULL COMMENT '原文产品名，如洋鸡蛋、红蛋、绿壳蛋、鸭蛋',
    include_in_egg_price TINYINT DEFAULT 0 COMMENT '是否纳入鸡蛋报价主口径',
    region VARCHAR(100) NULL COMMENT '地区',
    market_name VARCHAR(200) NULL COMMENT '市场、机构或报价主体',
    quote_basis VARCHAR(100) NULL COMMENT '报价基准，如30斤、27.5斤、360枚/箱',
    trade_scene VARCHAR(100) NULL COMMENT '交易场景，如到户、接货、装车、批发、收购',
    package_policy VARCHAR(100) NULL COMMENT '包装或运费规则，如含包装、不含包装',
    spec_text VARCHAR(200) NULL COMMENT '规格原文，如大码、45斤、52斤以上',
    weight_text VARCHAR(100) NULL COMMENT '重量原文',
    weight_low DECIMAL(10,3) NULL COMMENT '重量下限',
    weight_high DECIMAL(10,3) NULL COMMENT '重量上限',
    weight_unit VARCHAR(20) NULL COMMENT '重量单位',
    price_text VARCHAR(100) NULL COMMENT '价格原文',
    price_low DECIMAL(10,3) NULL COMMENT '价格下限',
    price_high DECIMAL(10,3) NULL COMMENT '价格上限',
    price_unit_text VARCHAR(50) NULL COMMENT '价格单位原文',
    standard_price_low DECIMAL(10,4) NULL COMMENT '统一口径价格下限',
    standard_price_high DECIMAL(10,4) NULL COMMENT '统一口径价格上限',
    standard_price_unit VARCHAR(50) DEFAULT 'yuan_per_jin' COMMENT '统一口径价格单位',
    conversion_basis_weight_low DECIMAL(10,3) NULL COMMENT '换算分母重量下限',
    conversion_basis_weight_high DECIMAL(10,3) NULL COMMENT '换算分母重量上限',
    conversion_basis_weight_unit VARCHAR(20) NULL COMMENT '换算分母重量单位',
    conversion_method VARCHAR(50) DEFAULT 'unconverted' COMMENT '规格换算方法',
    conversion_confidence DECIMAL(5,4) DEFAULT 0 COMMENT '规格换算置信度',
    conversion_notes_json TEXT NULL COMMENT '规格换算备注JSON',
    include_in_standard_price TINYINT DEFAULT 0 COMMENT '是否纳入统一鸡蛋价格主口径',
    yesterday_price_text VARCHAR(100) NULL COMMENT '昨日价原文',
    yesterday_price_low DECIMAL(10,3) NULL COMMENT '昨日价下限',
    yesterday_price_high DECIMAL(10,3) NULL COMMENT '昨日价上限',
    change_text VARCHAR(100) NULL COMMENT '涨跌原文',
    change_value DECIMAL(10,3) NULL COMMENT '涨跌数值',
    trend VARCHAR(20) DEFAULT 'unknown' COMMENT '趋势：up/down/flat/unknown',
    raw_headers_json TEXT NULL COMMENT '来源表头JSON',
    raw_row_json TEXT NULL COMMENT '来源行JSON',
    row_note VARCHAR(500) NULL COMMENT '行级备注，如以质论价、双色、32以下顺减',
    parse_notes_json TEXT NULL COMMENT '解析备注JSON',
    analysis_version VARCHAR(20) DEFAULT 'egg_price_v1' COMMENT '蛋价解析版本',
    analyze_time DATETIME NOT NULL COMMENT '分析时间',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_price_item (article_hash, item_index),
    KEY idx_article_price_account_date (account_name, publish_date),
    KEY idx_article_price_quote_date (account_name, quote_date),
    KEY idx_article_price_product_date (product_family, publish_date),
    KEY idx_article_price_product_quote_date (product_family, quote_date),
    KEY idx_article_price_standard_quote_date (include_in_standard_price, quote_date),
    KEY idx_article_price_region_date (region, publish_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_daily_report (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    report_date DATE NOT NULL COMMENT '日报日期',
    account_name VARCHAR(200) NOT NULL COMMENT '公众号或订阅号名称',
    title VARCHAR(300) NOT NULL COMMENT '日报标题',
    markdown_body MEDIUMTEXT NOT NULL COMMENT 'Markdown日报草稿',
    article_count INT DEFAULT 0 COMMENT '文章数',
    avg_content_length INT DEFAULT 0 COMMENT '平均正文长度',
    top_tags_json TEXT NULL COMMENT '主题标签TOP JSON',
    top_keywords_json TEXT NULL COMMENT '关键词TOP JSON',
    report_version VARCHAR(20) DEFAULT 'v1' COMMENT '日报模板版本',
    generate_time DATETIME NOT NULL COMMENT '生成时间',
    report_status VARCHAR(20) NOT NULL DEFAULT 'final' COMMENT 'provisional/final',
    data_cutoff_time DATETIME NULL COMMENT '统计数据截止时间',
    generation_trigger VARCHAR(20) NOT NULL DEFAULT 'legacy' COMMENT 'manual/automatic/compensation/legacy',
    last_generated_by VARCHAR(100) NOT NULL DEFAULT 'system' COMMENT 'admin/system',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_daily_report (report_date, account_name),
    KEY idx_article_daily_report_date (report_date),
    KEY idx_article_daily_report_generate_time (generate_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_report_generation_request (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '日报生成请求主键',
    idempotency_key VARCHAR(100) NOT NULL COMMENT '请求幂等键',
    report_type VARCHAR(20) NOT NULL COMMENT 'group/article/summary/all',
    report_date DATE NOT NULL COMMENT '日报业务日期',
    source_name VARCHAR(200) NULL COMMENT '可选群名或公众号名称',
    generation_trigger VARCHAR(20) NOT NULL COMMENT 'manual/automatic/compensation',
    data_cutoff_time DATETIME NOT NULL COMMENT '统计数据截止时间',
    requested_by VARCHAR(100) NOT NULL COMMENT 'admin/system',
    status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/partial_success/failed',
    worker_id VARCHAR(100) NULL COMMENT '领取请求的Worker',
    lease_expires_at DATETIME NULL COMMENT '运行租约截止时间',
    error_summary TEXT NULL COMMENT '安全失败摘要',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    start_time DATETIME NULL COMMENT '开始时间',
    end_time DATETIME NULL COMMENT '结束时间',
    UNIQUE KEY uk_report_request_idempotency (idempotency_key),
    KEY idx_report_request_pending (status, create_time),
    KEY idx_report_request_date (report_date, report_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_process_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    task_type VARCHAR(50) NOT NULL COMMENT 'clean_article/analyze_article/article_daily_report',
    ref_type VARCHAR(50) NOT NULL COMMENT 'article/date',
    ref_id VARCHAR(100) NOT NULL COMMENT '文章hash或日期',
    status VARCHAR(50) NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/failed/skipped',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '重试次数',
    next_run_time DATETIME NULL COMMENT '下次执行时间',
    error_msg TEXT NULL COMMENT '失败原因',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_article_task_ref (task_type, ref_type, ref_id),
    KEY idx_article_status_next_run (status, next_run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_group_collect_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    batch_id VARCHAR(64) NOT NULL,
    source_name VARCHAR(200) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NULL,
    scan_pages INT DEFAULT 0,
    read_count INT DEFAULT 0,
    insert_count INT DEFAULT 0,
    duplicate_count INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_code VARCHAR(100) NULL,
    error_msg TEXT NULL,
    screenshot_path VARCHAR(500) NULL,
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_group_log_source_time (source_name, start_time),
    KEY idx_group_log_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_article_collect_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    batch_id VARCHAR(64) NOT NULL,
    account_name VARCHAR(200) NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NULL,
    link_count INT DEFAULT 0,
    insert_count INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    stage VARCHAR(50) NULL,
    error_code VARCHAR(100) NULL,
    error_msg TEXT NULL,
    screenshot_path VARCHAR(500) NULL,
    feed_item_count INT NOT NULL DEFAULT 0 COMMENT 'Feed 返回条目数',
    duplicate_count INT NOT NULL DEFAULT 0 COMMENT '重复文章数',
    invalid_count INT NOT NULL DEFAULT 0 COMMENT '无效 Feed 条目数',
    http_status INT NULL COMMENT 'Feed HTTP 响应状态码',
    elapsed_ms INT NOT NULL DEFAULT 0 COMMENT 'Feed 请求耗时毫秒',
    create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    KEY idx_article_log_account_time (account_name, start_time),
    KEY idx_article_log_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_ui_lock (
    lock_name VARCHAR(100) PRIMARY KEY,
    owner_pipeline VARCHAR(50) NOT NULL,
    owner_task_id VARCHAR(100) NOT NULL,
    acquire_time DATETIME NOT NULL,
    heartbeat_time DATETIME NOT NULL,
    expire_time DATETIME NOT NULL,
    lease_seconds INT NOT NULL,
    wait_seconds DECIMAL(10,3) DEFAULT 0,
    stale_recovered_by VARCHAR(100) NULL,
    update_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS weinsight_admin_user (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '管理员主键',
    username VARCHAR(100) NOT NULL COMMENT '管理员登录名',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Argon2id密码哈希',
    enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
    password_changed_at DATETIME NULL COMMENT '最近主动改密时间，空表示仍为初始化密码',
    failed_login_count INT NOT NULL DEFAULT 0 COMMENT '连续登录失败次数',
    locked_until DATETIME NULL COMMENT '登录锁定截止时间',
    last_login_at DATETIME NULL COMMENT '最近成功登录时间',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_admin_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS weinsight_admin_session (
    id CHAR(36) PRIMARY KEY COMMENT '会话UUID',
    user_id BIGINT NOT NULL COMMENT '管理员主键',
    token_hash CHAR(64) NOT NULL COMMENT 'Session令牌SHA-256',
    csrf_token_hash CHAR(64) NOT NULL COMMENT 'CSRF令牌SHA-256',
    expires_at DATETIME NOT NULL COMMENT '绝对过期时间',
    idle_expires_at DATETIME NOT NULL COMMENT '空闲过期时间',
    last_seen_at DATETIME NOT NULL COMMENT '最近访问时间',
    revoked_at DATETIME NULL COMMENT '注销时间',
    client_ip VARCHAR(64) NULL COMMENT '登录客户端IP',
    user_agent_hash CHAR(64) NULL COMMENT 'User-Agent SHA-256',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_admin_session_token (token_hash),
    KEY idx_admin_session_user (user_id, revoked_at),
    KEY idx_admin_session_expiry (expires_at, idle_expires_at),
    CONSTRAINT fk_admin_session_user FOREIGN KEY (user_id)
        REFERENCES weinsight_admin_user(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Migration: create the collection control-plane schema.
-- Scope: jobs, runs, events, worker heartbeats, and WeChat health checks.
-- Safety: additive and idempotent; source configuration rows remain protected by RESTRICT.

CREATE TABLE IF NOT EXISTS wechat_collection_job (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '采集任务主键',
    job_name VARCHAR(200) NOT NULL COMMENT '采集任务名称',
    pipeline_type VARCHAR(20) NOT NULL COMMENT 'group/article',
    effective_start_at DATETIME NOT NULL COMMENT '任务整体开始时间',
    effective_end_at DATETIME NOT NULL COMMENT '任务整体结束时间',
    daily_window_start TIME NOT NULL COMMENT '每日运行窗口开始',
    daily_window_end TIME NOT NULL COMMENT '每日运行窗口结束',
    interval_seconds INT NOT NULL COMMENT '任务执行间隔秒数',
    status VARCHAR(30) NOT NULL COMMENT 'scheduled/active/stop_requested/stopped/completed/deleted',
    next_run_at DATETIME NULL COMMENT '下次计划运行时间',
    stop_requested_at DATETIME NULL COMMENT '停止请求时间',
    stop_requested_by VARCHAR(100) NULL COMMENT '停止请求管理员',
    deleted_at DATETIME NULL COMMENT '软删除时间',
    deleted_by VARCHAR(100) NULL COMMENT '软删除管理员',
    version INT NOT NULL DEFAULT 1 COMMENT '乐观锁版本',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT ck_collection_job_pipeline CHECK (pipeline_type IN ('group', 'article')),
    KEY idx_collection_job_due (status, next_run_at),
    KEY idx_collection_job_window (effective_start_at, effective_end_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_target (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务目标主键',
    job_id BIGINT NOT NULL COMMENT '采集任务主键',
    group_config_id BIGINT NULL COMMENT '微信群配置主键',
    article_config_id BIGINT NULL COMMENT '公众号配置主键',
    target_name_snapshot VARCHAR(200) NOT NULL COMMENT '目标名称快照',
    priority_snapshot INT NOT NULL COMMENT '优先级快照',
    config_snapshot_json TEXT NOT NULL COMMENT '配置快照JSON',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_group_target (job_id, group_config_id),
    UNIQUE KEY uk_job_article_target (job_id, article_config_id),
    CONSTRAINT ck_job_target_exactly_one CHECK (
        (group_config_id IS NOT NULL AND article_config_id IS NULL)
        OR (group_config_id IS NULL AND article_config_id IS NOT NULL)
    ),
    CONSTRAINT fk_job_target_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT,
    CONSTRAINT fk_job_target_group FOREIGN KEY (group_config_id)
        REFERENCES wechat_group_config(id) ON DELETE RESTRICT,
    CONSTRAINT fk_job_target_article FOREIGN KEY (article_config_id)
        REFERENCES wechat_public_account_config(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_run (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务运行实例主键',
    job_id BIGINT NOT NULL COMMENT '采集任务主键',
    scheduled_at DATETIME NOT NULL COMMENT '本次计划执行时间',
    status VARCHAR(30) NOT NULL COMMENT 'queued/running/success/partial_success/failed/cancelled/aborted',
    worker_id VARCHAR(100) NULL COMMENT '执行Worker标识',
    lease_expires_at DATETIME NULL COMMENT '运行租约过期时间',
    start_time DATETIME NULL COMMENT '实际开始时间',
    end_time DATETIME NULL COMMENT '实际结束时间',
    target_total_count INT NOT NULL DEFAULT 0 COMMENT '目标总数',
    target_success_count INT NOT NULL DEFAULT 0 COMMENT '成功目标数',
    target_failed_count INT NOT NULL DEFAULT 0 COMMENT '失败目标数',
    error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    error_summary VARCHAR(1000) NULL COMMENT '脱敏错误摘要',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_job_schedule (job_id, scheduled_at),
    KEY idx_collection_run_status_lease (status, lease_expires_at),
    KEY idx_collection_run_worker (worker_id, status),
    CONSTRAINT fk_collection_run_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_target_run (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '任务目标运行主键',
    run_id BIGINT NOT NULL COMMENT '任务运行实例主键',
    job_target_id BIGINT NOT NULL COMMENT '任务目标主键',
    batch_id VARCHAR(64) NULL COMMENT '业务采集批次标识',
    status VARCHAR(30) NOT NULL COMMENT 'queued/running/success/failed/skipped/cancelled',
    stage VARCHAR(50) NULL COMMENT '当前处理阶段',
    read_count INT NOT NULL DEFAULT 0 COMMENT '读取数量',
    insert_count INT NOT NULL DEFAULT 0 COMMENT '新增数量',
    duplicate_count INT NOT NULL DEFAULT 0 COMMENT '重复数量',
    skipped_count INT NOT NULL DEFAULT 0 COMMENT '跳过数量',
    error_code VARCHAR(100) NULL COMMENT '脱敏错误码',
    error_summary VARCHAR(1000) NULL COMMENT '脱敏错误摘要',
    screenshot_path VARCHAR(1000) NULL COMMENT '采集机本地故障截图绝对路径',
    start_time DATETIME NULL COMMENT '实际开始时间',
    end_time DATETIME NULL COMMENT '实际结束时间',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_target_run (run_id, job_target_id),
    KEY idx_target_run_status_stage (status, stage),
    KEY idx_target_run_batch (batch_id),
    CONSTRAINT fk_target_run_run FOREIGN KEY (run_id)
        REFERENCES wechat_collection_job_run(id) ON DELETE RESTRICT,
    CONSTRAINT fk_target_run_target FOREIGN KEY (job_target_id)
        REFERENCES wechat_collection_job_target(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_collection_job_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '结构化运行事件主键',
    job_id BIGINT NULL COMMENT '采集任务主键',
    run_id BIGINT NULL COMMENT '任务运行实例主键',
    target_run_id BIGINT NULL COMMENT '目标运行主键',
    worker_id VARCHAR(100) NULL COMMENT '上报Worker标识',
    level VARCHAR(20) NOT NULL COMMENT 'debug/info/warning/error',
    event_type VARCHAR(100) NOT NULL COMMENT '结构化事件类型',
    stage VARCHAR(50) NULL COMMENT '事件所属阶段',
    message VARCHAR(1000) NOT NULL COMMENT '脱敏事件消息',
    metrics_json TEXT NULL COMMENT '结构化指标JSON',
    actor_type VARCHAR(20) NOT NULL COMMENT 'admin/system/worker',
    actor_name VARCHAR(100) NULL COMMENT '操作者名称',
    create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_collection_event_run (run_id, id),
    KEY idx_collection_event_job_time (job_id, create_time),
    KEY idx_collection_event_worker_time (worker_id, create_time),
    CONSTRAINT fk_collection_event_job FOREIGN KEY (job_id)
        REFERENCES wechat_collection_job(id) ON DELETE RESTRICT,
    CONSTRAINT fk_collection_event_run FOREIGN KEY (run_id)
        REFERENCES wechat_collection_job_run(id) ON DELETE RESTRICT,
    CONSTRAINT fk_collection_event_target_run FOREIGN KEY (target_run_id)
        REFERENCES wechat_collection_job_target_run(id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_worker_heartbeat (
    worker_id VARCHAR(100) NOT NULL COMMENT 'Worker唯一标识',
    worker_type VARCHAR(30) NOT NULL COMMENT 'collector/pipeline',
    hostname VARCHAR(255) NOT NULL COMMENT '采集主机名',
    process_id INT NOT NULL COMMENT 'Worker进程ID',
    version VARCHAR(100) NULL COMMENT 'Worker版本',
    status VARCHAR(30) NOT NULL COMMENT 'starting/running/degraded/stopping/stopped',
    last_heartbeat_at DATETIME NOT NULL COMMENT '最近心跳时间',
    start_time DATETIME NOT NULL COMMENT 'Worker启动时间',
    last_error_summary VARCHAR(1000) NULL COMMENT '最近脱敏错误摘要',
    PRIMARY KEY (worker_id),
    KEY idx_worker_heartbeat_type_status (worker_type, status),
    KEY idx_worker_heartbeat_time (last_heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS wechat_client_health_check (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '微信客户端健康检查主键',
    worker_id VARCHAR(100) NULL COMMENT '执行探测的Worker标识',
    hostname VARCHAR(255) NOT NULL COMMENT '微信客户端所在主机名',
    status VARCHAR(50) NOT NULL COMMENT 'ok/not_running/not_logged_in/version_mismatch/window_unavailable/rpa_unavailable',
    detected_version VARCHAR(100) NULL COMMENT '探测到的微信版本',
    consecutive_failure_count INT NOT NULL DEFAULT 0 COMMENT '连续失败次数',
    message VARCHAR(1000) NULL COMMENT '脱敏健康消息',
    checked_at DATETIME NOT NULL COMMENT '检查时间',
    KEY idx_client_health_checked (checked_at),
    KEY idx_client_health_status (status, checked_at),
    KEY idx_client_health_worker (worker_id, checked_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
