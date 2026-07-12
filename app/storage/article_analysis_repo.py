from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.article_analysis import AnalyzedArticle, CleanArticleForAnalysis


class MysqlArticleAnalysisRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_pending_analyze_articles(self, limit: int) -> list[CleanArticleForAnalysis]:
        statement = text(
            """
            SELECT
                clean.article_hash,
                clean.account_name,
                clean.title,
                clean.article_url,
                clean.publish_time,
                raw.collect_time,
                raw.content_locator,
                raw.content_locator_type,
                clean.author,
                clean.digest,
                clean.content_length
            FROM wechat_article_process_task task
            JOIN wechat_article_clean clean
              ON clean.article_hash = task.ref_id
            JOIN wechat_article_raw raw
              ON raw.article_hash = clean.article_hash
            WHERE task.task_type = 'analyze_article'
              AND task.ref_type = 'article'
              AND task.status = 'pending'
              AND (task.next_run_time IS NULL OR task.next_run_time <= CURRENT_TIMESTAMP)
            ORDER BY task.create_time ASC, task.id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings().all()

        return [
            CleanArticleForAnalysis(
                article_hash=str(row["article_hash"]),
                account_name=str(row["account_name"]),
                title=str(row["title"] or ""),
                publish_time=row["publish_time"],
                collect_time=row["collect_time"],
                author=row["author"],
                digest=row["digest"],
                content_length=int(row["content_length"] or 0),
                article_url=str(row["article_url"] or ""),
                content_locator=row["content_locator"],
                content_locator_type=row["content_locator_type"],
            )
            for row in rows
        ]

    def upsert_article_analysis_with_price_items(self, analysis: AnalyzedArticle) -> None:
        analysis_statement = text(
            """
            INSERT INTO wechat_article_analysis (
                article_hash,
                account_name,
                title,
                publish_time,
                publish_date,
                collect_time,
                quote_date,
                quote_date_source,
                quote_date_confidence,
                author,
                summary_text,
                topic_tags_json,
                keyword_hits_json,
                extracted_tables_json,
                price_items_json,
                content_length,
                analysis_version,
                analyze_time
            ) VALUES (
                :article_hash,
                :account_name,
                :title,
                :publish_time,
                :publish_date,
                :collect_time,
                :quote_date,
                :quote_date_source,
                :quote_date_confidence,
                :author,
                :summary_text,
                :topic_tags_json,
                :keyword_hits_json,
                :extracted_tables_json,
                :price_items_json,
                :content_length,
                :analysis_version,
                :analyze_time
            )
            ON DUPLICATE KEY UPDATE
                account_name = VALUES(account_name),
                title = VALUES(title),
                publish_time = VALUES(publish_time),
                publish_date = VALUES(publish_date),
                collect_time = VALUES(collect_time),
                quote_date = VALUES(quote_date),
                quote_date_source = VALUES(quote_date_source),
                quote_date_confidence = VALUES(quote_date_confidence),
                author = VALUES(author),
                summary_text = VALUES(summary_text),
                topic_tags_json = VALUES(topic_tags_json),
                keyword_hits_json = VALUES(keyword_hits_json),
                extracted_tables_json = VALUES(extracted_tables_json),
                price_items_json = VALUES(price_items_json),
                content_length = VALUES(content_length),
                analysis_version = VALUES(analysis_version),
                analyze_time = VALUES(analyze_time),
                update_time = CURRENT_TIMESTAMP
            """
        )
        delete_items_statement = text(
            """
            DELETE FROM wechat_article_egg_price_item
            WHERE article_hash = :article_hash
            """
        )
        insert_item_statement = text(
            """
            INSERT INTO wechat_article_egg_price_item (
                article_hash,
                account_name,
                title,
                publish_time,
                publish_date,
                collect_time,
                quote_date,
                quote_date_source,
                quote_date_confidence,
                item_index,
                source_media_type,
                source_table_index,
                source_row_index,
                source_table_title,
                source_context_json,
                source_confidence,
                product_family,
                product_name,
                include_in_egg_price,
                region,
                market_name,
                quote_basis,
                trade_scene,
                package_policy,
                spec_text,
                weight_text,
                weight_low,
                weight_high,
                weight_unit,
                price_text,
                price_low,
                price_high,
                price_unit_text,
                standard_price_low,
                standard_price_high,
                standard_price_unit,
                conversion_basis_weight_low,
                conversion_basis_weight_high,
                conversion_basis_weight_unit,
                conversion_method,
                conversion_confidence,
                conversion_notes_json,
                include_in_standard_price,
                yesterday_price_text,
                yesterday_price_low,
                yesterday_price_high,
                change_text,
                change_value,
                trend,
                raw_headers_json,
                raw_row_json,
                row_note,
                parse_notes_json,
                analysis_version,
                analyze_time
            ) VALUES (
                :article_hash,
                :account_name,
                :title,
                :publish_time,
                :publish_date,
                :collect_time,
                :quote_date,
                :quote_date_source,
                :quote_date_confidence,
                :item_index,
                :source_media_type,
                :source_table_index,
                :source_row_index,
                :source_table_title,
                :source_context_json,
                :source_confidence,
                :product_family,
                :product_name,
                :include_in_egg_price,
                :region,
                :market_name,
                :quote_basis,
                :trade_scene,
                :package_policy,
                :spec_text,
                :weight_text,
                :weight_low,
                :weight_high,
                :weight_unit,
                :price_text,
                :price_low,
                :price_high,
                :price_unit_text,
                :standard_price_low,
                :standard_price_high,
                :standard_price_unit,
                :conversion_basis_weight_low,
                :conversion_basis_weight_high,
                :conversion_basis_weight_unit,
                :conversion_method,
                :conversion_confidence,
                :conversion_notes_json,
                :include_in_standard_price,
                :yesterday_price_text,
                :yesterday_price_low,
                :yesterday_price_high,
                :change_text,
                :change_value,
                :trend,
                :raw_headers_json,
                :raw_row_json,
                :row_note,
                :parse_notes_json,
                :analysis_version,
                :analyze_time
            )
            """
        )
        analysis_params = self._analysis_params(analysis)
        item_params = [self._item_params(item) for item in analysis.egg_price_items]
        with self.engine.begin() as connection:
            connection.execute(analysis_statement, analysis_params)
            connection.execute(delete_items_statement, {"article_hash": analysis.article_hash})
            for params in item_params:
                connection.execute(insert_item_statement, params)

    def _analysis_params(self, analysis: AnalyzedArticle) -> dict:
        return {
            "article_hash": analysis.article_hash,
            "account_name": analysis.account_name,
            "title": analysis.title,
            "publish_time": analysis.publish_time,
            "publish_date": analysis.publish_date,
            "collect_time": analysis.collect_time,
            "quote_date": analysis.quote_date,
            "quote_date_source": analysis.quote_date_source,
            "quote_date_confidence": analysis.quote_date_confidence,
            "author": analysis.author,
            "summary_text": analysis.summary_text,
            "topic_tags_json": analysis.topic_tags_json(),
            "keyword_hits_json": analysis.keyword_hits_json(),
            "extracted_tables_json": analysis.extracted_tables_json(),
            "price_items_json": analysis.price_items_json(),
            "content_length": analysis.content_length,
            "analysis_version": analysis.analysis_version,
            "analyze_time": analysis.analyze_time,
        }

    def _item_params(self, item) -> dict:
        return {
            "article_hash": item.article_hash,
            "account_name": item.account_name,
            "title": item.title,
            "publish_time": item.publish_time,
            "publish_date": item.publish_date,
            "collect_time": item.collect_time,
            "quote_date": item.quote_date,
            "quote_date_source": item.quote_date_source,
            "quote_date_confidence": item.quote_date_confidence,
            "item_index": item.item_index,
            "source_media_type": item.source_media_type,
            "source_table_index": item.source_table_index,
            "source_row_index": item.source_row_index,
            "source_table_title": item.source_table_title,
            "source_context_json": json.dumps(item.source_context, ensure_ascii=False),
            "source_confidence": item.source_confidence,
            "product_family": item.product_family,
            "product_name": item.product_name,
            "include_in_egg_price": 1 if item.include_in_egg_price else 0,
            "region": item.region,
            "market_name": item.market_name,
            "quote_basis": item.quote_basis,
            "trade_scene": item.trade_scene,
            "package_policy": item.package_policy,
            "spec_text": item.spec_text,
            "weight_text": item.weight_text,
            "weight_low": item.weight_low,
            "weight_high": item.weight_high,
            "weight_unit": item.weight_unit,
            "price_text": item.price_text,
            "price_low": item.price_low,
            "price_high": item.price_high,
            "price_unit_text": item.price_unit_text,
            "standard_price_low": item.standard_price_low,
            "standard_price_high": item.standard_price_high,
            "standard_price_unit": item.standard_price_unit,
            "conversion_basis_weight_low": item.conversion_basis_weight_low,
            "conversion_basis_weight_high": item.conversion_basis_weight_high,
            "conversion_basis_weight_unit": item.conversion_basis_weight_unit,
            "conversion_method": item.conversion_method,
            "conversion_confidence": item.conversion_confidence,
            "conversion_notes_json": json.dumps(item.conversion_notes, ensure_ascii=False),
            "include_in_standard_price": 1 if item.include_in_standard_price else 0,
            "yesterday_price_text": item.yesterday_price_text,
            "yesterday_price_low": item.yesterday_price_low,
            "yesterday_price_high": item.yesterday_price_high,
            "change_text": item.change_text,
            "change_value": item.change_value,
            "trend": item.trend,
            "raw_headers_json": json.dumps(item.raw_headers, ensure_ascii=False),
            "raw_row_json": json.dumps(item.raw_row, ensure_ascii=False),
            "row_note": item.row_note,
            "parse_notes_json": json.dumps(item.parse_notes, ensure_ascii=False),
            "analysis_version": item.analysis_version,
            "analyze_time": item.analyze_time,
        }

    def create_daily_report_task(self, report_date: date) -> None:
        statement = text(
            """
            INSERT INTO wechat_article_process_task (
                task_type,
                ref_type,
                ref_id,
                status
            ) VALUES (
                :task_type,
                'date',
                :ref_id,
                'pending'
            )
            ON DUPLICATE KEY UPDATE
                status = 'pending',
                next_run_time = NULL,
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {"task_type": "article_daily_report", "ref_id": report_date.isoformat()},
            )

    def mark_analyze_task_success(self, article_hash: str) -> None:
        statement = text(
            """
            UPDATE wechat_article_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'analyze_article'
              AND ref_type = 'article'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": article_hash})

    def mark_analyze_task_failed(self, article_hash: str, error_msg: str) -> None:
        statement = text(
            """
            UPDATE wechat_article_process_task
            SET status = CASE WHEN retry_count + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                retry_count = retry_count + 1,
                next_run_time = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 60 SECOND),
                error_msg = :error_msg,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'analyze_article'
              AND ref_type = 'article'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": article_hash, "error_msg": error_msg})
