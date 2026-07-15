from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.content.article_content import ContentFetchError
from app.domain.article_analysis import AnalyzedArticle, CleanArticleForAnalysis, analyze_clean_article


@dataclass(frozen=True)
class ArticleAnalysisResult:
    read_count: int
    success_count: int
    failed_count: int


@dataclass(frozen=True)
class ArticleTransientExtraction:
    body_text: str | None = None
    html_tables: list[dict] | None = None
    ocr_tables: list[dict] | None = None


class ArticleAnalysisRepo(Protocol):
    def list_pending_analyze_articles(self, limit: int) -> list[CleanArticleForAnalysis]:
        ...

    def upsert_article_analysis_with_price_items(self, analysis: AnalyzedArticle) -> None:
        ...

    def create_daily_report_task(self, report_date: date) -> None:
        ...

    def mark_analyze_task_success(self, article_hash: str) -> None:
        ...

    def mark_analyze_task_failed(self, article_hash: str, error_msg: str) -> None:
        ...


class ArticleTransientExtractor(Protocol):
    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        ...


class NoopArticleTransientExtractor:
    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        return article


class ArticleAnalysisService:
    def __init__(
        self,
        *,
        repo: ArticleAnalysisRepo,
        extractor: ArticleTransientExtractor | None = None,
        price_items_preview_limit: int = 20,
        egg_price_extraction_enabled: bool = True,
    ) -> None:
        self.repo = repo
        self.extractor = extractor or NoopArticleTransientExtractor()
        self.price_items_preview_limit = price_items_preview_limit
        self.egg_price_extraction_enabled = egg_price_extraction_enabled

    def analyze_once(self, limit: int, analyze_time: datetime) -> ArticleAnalysisResult:
        articles = self.repo.list_pending_analyze_articles(limit)
        success_count = 0
        failed_count = 0

        for article in articles:
            try:
                article_with_transient_data = (
                    self.extractor.extract(article)
                    if self.egg_price_extraction_enabled
                    else article
                )
                analysis = analyze_clean_article(
                    article_with_transient_data,
                    analyze_time=analyze_time,
                    price_items_preview_limit=self.price_items_preview_limit,
                    egg_price_extraction_enabled=self.egg_price_extraction_enabled,
                )
                self.repo.upsert_article_analysis_with_price_items(analysis)
                report_date = analysis.quote_date or analysis.publish_date
                if report_date is not None:
                    self.repo.create_daily_report_task(report_date)
                self.repo.mark_analyze_task_success(article.article_hash)
                success_count += 1
            except Exception as exc:
                error_summary = exc.code if isinstance(exc, ContentFetchError) else type(exc).__name__
                self.repo.mark_analyze_task_failed(article.article_hash, error_summary)
                failed_count += 1

        return ArticleAnalysisResult(
            read_count=len(articles),
            success_count=success_count,
            failed_count=failed_count,
        )
