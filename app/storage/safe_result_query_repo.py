from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.admin_results import (
    ArticleDetailFilter,
    ArticleDetailRow,
    EggPriceDetailRow,
    GroupDetailFilter,
    GroupDetailRow,
    PagedResult,
    PriceDetailFilter,
)
from app.domain.price_matrix import PriceMatrixSourceRow


logger = logging.getLogger(__name__)


class MysqlSafeResultQueryRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def latest_price_quote_date(
        self, account_names: tuple[str, ...]
    ) -> date | None:
        placeholders, params = self._account_params(account_names)
        sql = f"""
            SELECT MAX(p.quote_date) AS quote_date
            FROM wechat_article_egg_price_item AS p
            WHERE p.account_name IN ({placeholders})
              AND p.include_in_egg_price = 1
        """
        with self.engine.begin() as connection:
            return connection.execute(text(sql), params).scalar_one()

    def list_price_matrix_rows(
        self, quote_date: date, account_names: tuple[str, ...]
    ) -> list[PriceMatrixSourceRow]:
        placeholders, account_params = self._account_params(account_names)
        sql = f"""
            SELECT
                p.id AS row_id,
                p.article_hash AS article_hash,
                p.account_name AS account_name,
                p.quote_date AS quote_date,
                p.publish_time AS publish_time,
                p.analyze_time AS analyze_time,
                p.region AS region,
                p.market_name AS market_name,
                p.product_name AS product_name,
                p.product_family AS product_family,
                p.include_in_egg_price AS include_in_egg_price,
                p.spec_text AS spec_text,
                p.weight_low AS weight_low,
                p.weight_high AS weight_high,
                p.price_low AS price_low,
                p.price_high AS price_high,
                p.price_unit_text AS price_unit_text
            FROM wechat_article_egg_price_item AS p
            WHERE p.quote_date = :quote_date
              AND p.account_name IN ({placeholders})
              AND p.include_in_egg_price = 1
              AND p.product_family = :product_family
            ORDER BY p.account_name, p.publish_time DESC, p.article_hash, p.id
        """
        params = {
            "quote_date": quote_date,
            "product_family": "chicken_egg",
            **account_params,
        }
        with self.engine.begin() as connection:
            rows = connection.execute(text(sql), params).mappings().all()
        return [self._matrix_from_row(row) for row in rows]

    @staticmethod
    def _account_params(
        account_names: tuple[str, ...]
    ) -> tuple[str, dict[str, object]]:
        if not account_names:
            raise ValueError("account_names must not be empty")
        params = {f"account_{index}": name for index, name in enumerate(account_names)}
        return ", ".join(f":{name}" for name in params), params

    def list_group_details(
        self, filters: GroupDetailFilter, page: int, page_size: int
    ) -> PagedResult[GroupDetailRow]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if filters.group_name is not None:
            clauses.append("c.group_name = :group_name")
            params["group_name"] = filters.group_name
        if filters.start_at is not None:
            clauses.append("a.msg_time_inferred >= :start_at")
            params["start_at"] = filters.start_at
        if filters.end_at is not None:
            clauses.append("a.msg_time_inferred < :end_at")
            params["end_at"] = filters.end_at
        if filters.intent_type is not None:
            clauses.append("a.intent_type = :intent_type")
            params["intent_type"] = filters.intent_type

        from_sql = """
            FROM wechat_group_msg_clean AS c
            INNER JOIN wechat_group_msg_analysis AS a
                ON a.msg_hash = c.msg_hash
        """
        return self._query_page(
            count_sql=f"SELECT COUNT(*) AS total_count {from_sql} {self._where(clauses)}",
            data_sql=f"""
                SELECT
                    a.id AS row_id,
                    c.msg_hash AS msg_hash,
                    c.group_name AS group_name,
                    c.sender_display AS sender_display,
                    a.msg_time_inferred AS msg_time_inferred,
                    c.clean_content AS clean_content,
                    a.intent_type AS intent_type,
                    a.region_hits AS region_hits,
                    a.category_hits AS category_hits,
                    a.keyword_hits AS keyword_hits,
                    a.opportunity_score AS opportunity_score,
                    a.has_contact AS has_contact
                {from_sql}
                {self._where(clauses)}
                ORDER BY a.msg_time_inferred DESC, a.id DESC
                LIMIT :limit OFFSET :offset
            """,
            params=params,
            page=page,
            page_size=page_size,
            mapper=self._group_from_row,
        )

    def list_article_details(
        self, filters: ArticleDetailFilter, page: int, page_size: int
    ) -> PagedResult[ArticleDetailRow]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if filters.account_name is not None:
            clauses.append("a.account_name = :account_name")
            params["account_name"] = filters.account_name
        if filters.publish_date is not None:
            clauses.append("a.publish_date = :publish_date")
            params["publish_date"] = filters.publish_date
        if filters.quote_date is not None:
            clauses.append("a.quote_date = :quote_date")
            params["quote_date"] = filters.quote_date

        from_sql = "FROM wechat_article_analysis AS a"
        return self._query_page(
            count_sql=f"SELECT COUNT(*) AS total_count {from_sql} {self._where(clauses)}",
            data_sql=f"""
                SELECT
                    a.id AS row_id,
                    a.article_hash AS article_hash,
                    a.account_name AS account_name,
                    a.title AS title,
                    a.publish_time AS publish_time,
                    a.quote_date AS quote_date,
                    a.collect_time AS collect_time,
                    a.summary_text AS summary_text,
                    a.topic_tags_json AS topic_tags_json,
                    a.content_length AS content_length,
                    a.analysis_version AS analysis_version
                {from_sql}
                {self._where(clauses)}
                ORDER BY a.publish_time DESC, a.id DESC
                LIMIT :limit OFFSET :offset
            """,
            params=params,
            page=page,
            page_size=page_size,
            mapper=self._article_from_row,
        )

    def list_price_details(
        self, filters: PriceDetailFilter, page: int, page_size: int
    ) -> PagedResult[EggPriceDetailRow]:
        clauses: list[str] = []
        params: dict[str, object] = {}
        if filters.account_name is not None:
            clauses.append("p.account_name = :account_name")
            params["account_name"] = filters.account_name
        if filters.quote_date is not None:
            clauses.append("p.quote_date = :quote_date")
            params["quote_date"] = filters.quote_date
        if filters.region is not None:
            clauses.append("p.region = :region")
            params["region"] = filters.region
        if filters.product_family is not None:
            clauses.append("p.product_family = :product_family")
            params["product_family"] = filters.product_family

        from_sql = "FROM wechat_article_egg_price_item AS p"
        return self._query_page(
            count_sql=f"SELECT COUNT(*) AS total_count {from_sql} {self._where(clauses)}",
            data_sql=f"""
                SELECT
                    p.id AS row_id,
                    p.account_name AS account_name,
                    p.quote_date AS quote_date,
                    p.region AS region,
                    p.market_name AS market_name,
                    p.product_family AS product_family,
                    p.product_name AS product_name,
                    p.spec_text AS spec_text,
                    p.price_text AS price_text,
                    p.price_low AS price_low,
                    p.price_high AS price_high,
                    p.price_unit_text AS price_unit_text,
                    p.standard_price_low AS standard_price_low,
                    p.standard_price_high AS standard_price_high,
                    p.standard_price_unit AS standard_price_unit,
                    p.change_text AS change_text,
                    p.change_value AS change_value,
                    p.trend AS trend,
                    p.conversion_method AS conversion_method,
                    p.conversion_confidence AS conversion_confidence
                {from_sql}
                {self._where(clauses)}
                ORDER BY p.quote_date DESC, p.id DESC
                LIMIT :limit OFFSET :offset
            """,
            params=params,
            page=page,
            page_size=page_size,
            mapper=self._price_from_row,
        )

    def _query_page(
        self,
        *,
        count_sql: str,
        data_sql: str,
        params: dict[str, object],
        page: int,
        page_size: int,
        mapper,
    ):
        data_params = {
            **params,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        with self.engine.begin() as connection:
            total = connection.execute(text(count_sql), params).scalar_one()
            rows = connection.execute(text(data_sql), data_params).mappings().all()
        return PagedResult(
            items=[mapper(row) for row in rows],
            page=page,
            page_size=page_size,
            total_count=int(total or 0),
        )

    @staticmethod
    def _where(clauses: list[str]) -> str:
        if not clauses:
            return ""
        return "WHERE " + " AND ".join(clauses)

    @staticmethod
    def _group_from_row(row: Mapping[str, Any]) -> GroupDetailRow:
        row_id = row.get("row_id")
        return GroupDetailRow(
            msg_hash=str(row.get("msg_hash") or ""),
            group_name=str(row.get("group_name") or ""),
            sender_display=_optional_string(row.get("sender_display")),
            msg_time_inferred=row.get("msg_time_inferred"),
            clean_content=str(row.get("clean_content") or ""),
            intent_type=str(row.get("intent_type") or ""),
            region_hits=_safe_string_tuple(
                row.get("region_hits"), field_name="region_hits", row_id=row_id
            ),
            category_hits=_safe_string_tuple(
                row.get("category_hits"), field_name="category_hits", row_id=row_id
            ),
            keyword_hits=_safe_string_tuple(
                row.get("keyword_hits"), field_name="keyword_hits", row_id=row_id
            ),
            opportunity_score=int(row.get("opportunity_score") or 0),
            has_contact=bool(row.get("has_contact") or False),
        )

    @staticmethod
    def _article_from_row(row: Mapping[str, Any]) -> ArticleDetailRow:
        return ArticleDetailRow(
            article_hash=str(row.get("article_hash") or ""),
            account_name=str(row.get("account_name") or ""),
            title=str(row.get("title") or ""),
            publish_time=row.get("publish_time"),
            quote_date=row.get("quote_date"),
            collect_time=row.get("collect_time"),
            summary_text=str(row.get("summary_text") or ""),
            topic_tags=_safe_string_tuple(
                row.get("topic_tags_json"),
                field_name="topic_tags_json",
                row_id=row.get("row_id"),
            ),
            content_length=int(row.get("content_length") or 0),
            analysis_version=str(row.get("analysis_version") or ""),
        )

    @staticmethod
    def _price_from_row(row: Mapping[str, Any]) -> EggPriceDetailRow:
        return EggPriceDetailRow(
            account_name=str(row.get("account_name") or ""),
            quote_date=row.get("quote_date"),
            region=_optional_string(row.get("region")),
            market_name=_optional_string(row.get("market_name")),
            product_name=_optional_string(row.get("product_name")),
            product_family=str(row.get("product_family") or ""),
            spec_text=_optional_string(row.get("spec_text")),
            price_text=_optional_string(row.get("price_text")),
            price_low=_optional_decimal(row.get("price_low")),
            price_high=_optional_decimal(row.get("price_high")),
            price_unit_text=_optional_string(row.get("price_unit_text")),
            standard_price_low=_optional_decimal(row.get("standard_price_low")),
            standard_price_high=_optional_decimal(row.get("standard_price_high")),
            standard_price_unit=str(row.get("standard_price_unit") or ""),
            change_text=_optional_string(row.get("change_text")),
            change_value=_optional_decimal(row.get("change_value")),
            trend=str(row.get("trend") or "unknown"),
            conversion_method=str(row.get("conversion_method") or "unconverted"),
            conversion_confidence=_optional_decimal(
                row.get("conversion_confidence")
            )
            or Decimal("0"),
        )

    @staticmethod
    def _matrix_from_row(row: Mapping[str, Any]) -> PriceMatrixSourceRow:
        return PriceMatrixSourceRow(
            row_id=int(row.get("row_id") or 0),
            article_hash=str(row.get("article_hash") or ""),
            account_name=str(row.get("account_name") or ""),
            quote_date=row.get("quote_date"),
            publish_time=row.get("publish_time"),
            analyze_time=row.get("analyze_time"),
            region=_optional_string(row.get("region")),
            market_name=_optional_string(row.get("market_name")),
            product_name=_optional_string(row.get("product_name")),
            product_family=str(row.get("product_family") or ""),
            include_in_egg_price=bool(row.get("include_in_egg_price")),
            spec_text=_optional_string(row.get("spec_text")),
            weight_low=_optional_decimal(row.get("weight_low")),
            weight_high=_optional_decimal(row.get("weight_high")),
            price_low=_optional_decimal(row.get("price_low")),
            price_high=_optional_decimal(row.get("price_high")),
            price_unit_text=_optional_string(row.get("price_unit_text")),
        )


def _safe_string_tuple(
    value: Any, *, field_name: str, row_id: object
) -> tuple[str, ...]:
    if value is None:
        return ()
    try:
        parsed = json.loads(value)
        if not isinstance(parsed, list) or not all(
            isinstance(item, str) for item in parsed
        ):
            raise ValueError("expected JSON array containing only strings")
        return tuple(parsed)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            "invalid JSON array field=%s row_id=%s error_type=%s",
            field_name,
            row_id,
            type(exc).__name__,
        )
        return ()


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
