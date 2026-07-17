from __future__ import annotations

from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from app.domain.article_downstream import ArticleBackfillCommand, ArticleBackfillSummary


_NORMALIZED_NAME_SQL = "REPLACE(REPLACE(REPLACE(TRIM(config.account_name), ' ', ''), '　', ''), CHAR(9), '')"


class MysqlArticleDownstreamRepo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def set_processing_enabled(self, source_id: int, enabled: bool) -> bool:
        statement = text(
            f"""
            UPDATE wechat_public_account_config AS config
            SET downstream_clean_enabled = :processing_enabled,
                update_time = CURRENT_TIMESTAMP
            WHERE config.id = :source_id
              AND config.werss_source_id IS NOT NULL
              AND config.upstream_status IN ('active', 'disabled')
              AND {_NORMALIZED_NAME_SQL} <> '一箱蛋'
            """
        )
        with self.engine.begin() as connection:
            result = connection.execute(
                statement,
                {"source_id": source_id, "processing_enabled": 1 if enabled else 0},
            )
        return result.rowcount > 0

    def enqueue_backfill(
        self, command: ArticleBackfillCommand, now: datetime
    ) -> ArticleBackfillSummary:
        if command.scope == "single":
            scope_clause = "config.id = :source_id"
        elif command.scope == "selected":
            scope_clause = "config.id IN :source_ids"
        else:
            scope_clause = "config.downstream_clean_enabled = 1"
        params = {"start_date": command.start_date, "end_date": command.end_date}
        if command.scope == "single":
            params["source_id"] = command.source_id
        elif command.scope == "selected":
            params["source_ids"] = command.source_ids

        select_statement = text(
            f"""
            SELECT raw.article_hash,
                   clean.article_hash IS NOT NULL AS has_clean,
                   analysis.article_hash IS NOT NULL AS has_analysis,
                   clean_task.status AS clean_status,
                   analyze_task.status AS analyze_status
            FROM wechat_public_account_config AS config
            JOIN wechat_article_raw AS raw ON raw.account_name = config.account_name
            LEFT JOIN wechat_article_clean AS clean ON clean.article_hash = raw.article_hash
            LEFT JOIN wechat_article_analysis AS analysis ON analysis.article_hash = raw.article_hash
            LEFT JOIN wechat_article_process_task AS clean_task
              ON clean_task.task_type = 'clean_article'
             AND clean_task.ref_type = 'article'
             AND clean_task.ref_id = raw.article_hash
            LEFT JOIN wechat_article_process_task AS analyze_task
              ON analyze_task.task_type = 'analyze_article'
             AND analyze_task.ref_type = 'article'
             AND analyze_task.ref_id = raw.article_hash
            WHERE {scope_clause}
              AND config.werss_source_id IS NOT NULL
              AND config.upstream_status IN ('active', 'disabled')
              AND {_NORMALIZED_NAME_SQL} <> '一箱蛋'
              AND raw.publish_date BETWEEN :start_date AND :end_date
            ORDER BY raw.article_hash
            FOR UPDATE
            """
        )
        if command.scope == "selected":
            select_statement = select_statement.bindparams(
                bindparam("source_ids", expanding=True)
            )

        created_clean = recovered_clean = created_analyze = recovered_analyze = 0
        existing_skipped = running_skipped = out_of_scope = 0
        writes: list[tuple[str, str]] = []
        with self.engine.begin() as connection:
            rows = connection.execute(select_statement, params).mappings().all()
            for row in rows:
                has_clean = bool(row["has_clean"])
                has_analysis = bool(row["has_analysis"])
                clean_status = row["clean_status"]
                analyze_status = row["analyze_status"]
                article_hash = str(row["article_hash"])

                if command.mode == "force_analyze":
                    if not has_clean:
                        out_of_scope += 1
                    elif analyze_status in {"pending", "running"}:
                        running_skipped += 1
                    else:
                        writes.append(("analyze_article", article_hash))
                        if analyze_status is None:
                            created_analyze += 1
                        else:
                            recovered_analyze += 1
                    continue

                if has_analysis:
                    existing_skipped += 1
                elif not has_clean:
                    if clean_status in {"pending", "running"}:
                        running_skipped += 1
                    else:
                        writes.append(("clean_article", article_hash))
                        if clean_status is None:
                            created_clean += 1
                        else:
                            recovered_clean += 1
                elif analyze_status in {"pending", "running"}:
                    running_skipped += 1
                else:
                    writes.append(("analyze_article", article_hash))
                    if analyze_status is None:
                        created_analyze += 1
                    else:
                        recovered_analyze += 1

            for task_type, article_hash in writes:
                connection.execute(
                    _UPSERT_TASK_SQL,
                    {"task_type": task_type, "ref_id": article_hash, "next_run_time": now},
                )

        return ArticleBackfillSummary(
            len(rows), created_clean, recovered_clean, created_analyze,
            recovered_analyze, existing_skipped, running_skipped, out_of_scope,
        )


_UPSERT_TASK_SQL = text(
    """
    INSERT INTO wechat_article_process_task (
        task_type, ref_type, ref_id, status, retry_count, next_run_time, error_msg
    ) VALUES (
        :task_type, 'article', :ref_id, 'pending', 0, :next_run_time, NULL
    )
    ON DUPLICATE KEY UPDATE
        retry_count = IF(status IN ('pending', 'running'), retry_count, 0),
        next_run_time = IF(status IN ('pending', 'running'), next_run_time, VALUES(next_run_time)),
        error_msg = IF(status IN ('pending', 'running'), error_msg, NULL),
        update_time = IF(status IN ('pending', 'running'), update_time, CURRENT_TIMESTAMP),
        status = IF(status IN ('pending', 'running'), status, 'pending')
    """
)
