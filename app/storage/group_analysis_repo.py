from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.domain.group_analysis import AnalyzedGroupMessage, DailyReportDraft, DailyReportStats
from app.domain.group_cleaning import CleanGroupMessage


class MysqlGroupAnalysisRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_pending_analyze_clean_messages(self, limit: int) -> list[CleanGroupMessage]:
        statement = text(
            """
            SELECT
                clean.msg_hash,
                clean.group_name,
                clean.sender_hash,
                clean.sender_display,
                clean.msg_time_display,
                clean.msg_time_inferred,
                clean.msg_type,
                clean.clean_content,
                clean.content_length,
                clean.is_empty,
                clean.has_phone,
                clean.has_wechat_id,
                clean.clean_version,
                clean.source_collect_batch_id,
                clean.clean_time
            FROM wechat_group_process_task task
            JOIN wechat_group_msg_clean clean
              ON clean.msg_hash = task.ref_id
            WHERE task.task_type = 'analyze_group_msg'
              AND task.ref_type = 'msg'
              AND task.status = 'pending'
              AND (task.next_run_time IS NULL OR task.next_run_time <= CURRENT_TIMESTAMP)
            ORDER BY task.create_time ASC, task.id ASC
            LIMIT :limit
            """
        )
        with self.engine.begin() as connection:
            rows = connection.execute(statement, {"limit": limit}).mappings().all()

        return [
            CleanGroupMessage(
                msg_hash=str(row["msg_hash"]),
                group_name=str(row["group_name"]),
                sender_hash=row["sender_hash"],
                sender_display=str(row["sender_display"] or ""),
                msg_time_display=str(row["msg_time_display"] or ""),
                msg_time_inferred=row["msg_time_inferred"],
                msg_type=str(row["msg_type"] or "text"),
                clean_content=str(row["clean_content"] or ""),
                content_length=int(row["content_length"] or 0),
                is_empty=bool(row["is_empty"]),
                has_phone=bool(row["has_phone"]),
                has_wechat_id=bool(row["has_wechat_id"]),
                clean_version=str(row["clean_version"] or "v1"),
                source_collect_batch_id=str(row["source_collect_batch_id"] or ""),
                clean_time=row["clean_time"],
            )
            for row in rows
        ]

    def upsert_message_analysis(self, analysis: AnalyzedGroupMessage) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_msg_analysis (
                msg_hash,
                group_name,
                sender_hash,
                msg_time_display,
                msg_time_inferred,
                activity_date,
                activity_hour,
                intent_type,
                keyword_hits,
                region_hits,
                category_hits,
                opportunity_hits,
                opportunity_score,
                has_contact,
                content_length,
                analysis_version,
                analyze_time
            ) VALUES (
                :msg_hash,
                :group_name,
                :sender_hash,
                :msg_time_display,
                :msg_time_inferred,
                :activity_date,
                :activity_hour,
                :intent_type,
                :keyword_hits,
                :region_hits,
                :category_hits,
                :opportunity_hits,
                :opportunity_score,
                :has_contact,
                :content_length,
                :analysis_version,
                :analyze_time
            )
            ON DUPLICATE KEY UPDATE
                group_name = VALUES(group_name),
                sender_hash = VALUES(sender_hash),
                msg_time_display = VALUES(msg_time_display),
                msg_time_inferred = VALUES(msg_time_inferred),
                activity_date = VALUES(activity_date),
                activity_hour = VALUES(activity_hour),
                intent_type = VALUES(intent_type),
                keyword_hits = VALUES(keyword_hits),
                region_hits = VALUES(region_hits),
                category_hits = VALUES(category_hits),
                opportunity_hits = VALUES(opportunity_hits),
                opportunity_score = VALUES(opportunity_score),
                has_contact = VALUES(has_contact),
                content_length = VALUES(content_length),
                analysis_version = VALUES(analysis_version),
                analyze_time = VALUES(analyze_time),
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "msg_hash": analysis.msg_hash,
            "group_name": analysis.group_name,
            "sender_hash": analysis.sender_hash,
            "msg_time_display": analysis.msg_time_display,
            "msg_time_inferred": analysis.msg_time_inferred,
            "activity_date": analysis.activity_date,
            "activity_hour": analysis.activity_hour,
            "intent_type": analysis.intent_type,
            "keyword_hits": json.dumps(analysis.keyword_hits, ensure_ascii=False),
            "region_hits": json.dumps(analysis.region_hits, ensure_ascii=False),
            "category_hits": json.dumps(analysis.category_hits, ensure_ascii=False),
            "opportunity_hits": json.dumps(analysis.opportunity_hits, ensure_ascii=False),
            "opportunity_score": analysis.opportunity_score,
            "has_contact": 1 if analysis.has_contact else 0,
            "content_length": analysis.content_length,
            "analysis_version": analysis.analysis_version,
            "analyze_time": analysis.analyze_time,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def create_daily_report_task(self, report_date: date) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_process_task (
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
                {"task_type": "group_daily_report", "ref_id": report_date.isoformat()},
            )

    def mark_daily_report_task_success(self, report_date: date) -> None:
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'group_daily_report'
              AND ref_type = 'date'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": report_date.isoformat()})

    def mark_analyze_task_success(self, msg_hash: str) -> None:
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = 'success',
                error_msg = NULL,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'analyze_group_msg'
              AND ref_type = 'msg'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": msg_hash})

    def mark_analyze_task_failed(self, msg_hash: str, error_msg: str) -> None:
        statement = text(
            """
            UPDATE wechat_group_process_task
            SET status = CASE WHEN retry_count + 1 >= 3 THEN 'failed' ELSE 'pending' END,
                retry_count = retry_count + 1,
                next_run_time = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL 60 SECOND),
                error_msg = :error_msg,
                update_time = CURRENT_TIMESTAMP
            WHERE task_type = 'analyze_group_msg'
              AND ref_type = 'msg'
              AND ref_id = :ref_id
            """
        )
        with self.engine.begin() as connection:
            connection.execute(statement, {"ref_id": msg_hash, "error_msg": error_msg})

    def list_daily_report_stats(self, report_date: date, group_name: str | None) -> list[DailyReportStats]:
        group_filter = "AND group_name = :group_name" if group_name else ""
        statement = text(
            f"""
            SELECT
                group_name,
                sender_hash,
                activity_hour,
                intent_type,
                keyword_hits,
                region_hits,
                category_hits,
                opportunity_hits,
                opportunity_score,
                has_contact
            FROM wechat_group_msg_analysis
            WHERE activity_date = :report_date
              {group_filter}
            ORDER BY group_name ASC, activity_hour ASC, msg_hash ASC
            """
        )
        params = {"report_date": report_date, "group_name": group_name}
        with self.engine.begin() as connection:
            rows = connection.execute(statement, params).mappings().all()

        return self._stats_from_rows(report_date, rows)

    def upsert_daily_report(self, report: DailyReportDraft) -> None:
        statement = text(
            """
            INSERT INTO wechat_group_daily_report (
                report_date,
                group_name,
                title,
                markdown_body,
                message_count,
                sender_count,
                demand_count,
                supply_count,
                contact_count,
                peak_hour,
                top_keywords,
                report_version,
                generate_time
            ) VALUES (
                :report_date,
                :group_name,
                :title,
                :markdown_body,
                :message_count,
                :sender_count,
                :demand_count,
                :supply_count,
                :contact_count,
                :peak_hour,
                :top_keywords,
                :report_version,
                :generate_time
            )
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                markdown_body = VALUES(markdown_body),
                message_count = VALUES(message_count),
                sender_count = VALUES(sender_count),
                demand_count = VALUES(demand_count),
                supply_count = VALUES(supply_count),
                contact_count = VALUES(contact_count),
                peak_hour = VALUES(peak_hour),
                top_keywords = VALUES(top_keywords),
                report_version = VALUES(report_version),
                generate_time = VALUES(generate_time),
                update_time = CURRENT_TIMESTAMP
            """
        )
        params = {
            "report_date": report.report_date,
            "group_name": report.group_name,
            "title": report.title,
            "markdown_body": report.markdown_body,
            "message_count": report.message_count,
            "sender_count": report.sender_count,
            "demand_count": report.demand_count,
            "supply_count": report.supply_count,
            "contact_count": report.contact_count,
            "peak_hour": report.peak_hour,
            "top_keywords": report.top_keywords_json(),
            "report_version": report.report_version,
            "generate_time": report.generate_time,
        }
        with self.engine.begin() as connection:
            connection.execute(statement, params)

    def _stats_from_rows(self, report_date: date, rows) -> list[DailyReportStats]:
        grouped: dict[str, list] = defaultdict(list)
        for row in rows:
            grouped[str(row["group_name"])].append(row)

        stats: list[DailyReportStats] = []
        for group_name, group_rows in grouped.items():
            sender_hashes = {row["sender_hash"] for row in group_rows if row["sender_hash"]}
            hour_counts = Counter(int(row["activity_hour"]) for row in group_rows)
            keyword_counts: Counter[str] = Counter()
            region_counts: Counter[str] = Counter()
            category_counts: Counter[str] = Counter()
            opportunity_counts: Counter[str] = Counter()
            for row in group_rows:
                keyword_counts.update(_load_keyword_hits(row["keyword_hits"]))
                region_counts.update(_load_keyword_hits(row["region_hits"]))
                category_counts.update(_load_keyword_hits(row["category_hits"]))
                opportunity_counts.update(_load_keyword_hits(row["opportunity_hits"]))

            peak_hour = None
            if hour_counts:
                peak_hour = sorted(hour_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

            stats.append(
                DailyReportStats(
                    report_date=report_date,
                    group_name=group_name,
                    message_count=len(group_rows),
                    sender_count=len(sender_hashes),
                    demand_count=sum(1 for row in group_rows if row["intent_type"] == "demand"),
                    supply_count=sum(1 for row in group_rows if row["intent_type"] == "supply"),
                    contact_count=sum(1 for row in group_rows if bool(row["has_contact"])),
                    opportunity_count=sum(1 for row in group_rows if int(row["opportunity_score"] or 0) >= 3),
                    peak_hour=peak_hour,
                    top_keywords=keyword_counts.most_common(10),
                    top_regions=region_counts.most_common(10),
                    top_categories=category_counts.most_common(10),
                    top_opportunity_keywords=opportunity_counts.most_common(10),
                )
            )
        return stats


def _load_keyword_hits(value) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if str(item)]
