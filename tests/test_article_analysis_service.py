from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime

from app.domain.article_analysis import CleanArticleForAnalysis, analyze_clean_article
from app.pipelines.article_analysis_service import (
    ArticleAnalysisService,
    ArticleTransientExtraction,
)
from app.content.article_content import ArticleContent
from app.pipelines.article_transient_extractor import ProviderBackedArticleTransientExtractor


def test_analyze_clean_article_builds_summary_and_tags_from_transient_body() -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-1",
        account_name="行业观察",
        title="深圳供应链价格观察",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author="作者A",
        digest="深圳企业关注报价和供需变化。",
        content_length=1200,
        transient_body_text="深圳供应链企业反馈报价波动，湖北客户关注供需变化。",
        transient_html_tables=[
            {
                "source_media_type": "dom_table",
                "title": "贵阳鸡蛋价格参考",
                "headers": ["净重", "昨日价", "今日价", "涨跌"],
                "rows": [
                    ["45斤", "182元", "187元", "+5"],
                ],
            }
        ],
        transient_ocr_tables=[
            {
                "source_media_type": "image_ocr",
                "title": "河北馆陶鸡蛋报价",
                "headers": ["净重", "昨日价", "今日价", "涨跌"],
                "rows": [
                    ["45斤", "182元", "187元", "+5"],
                ],
                "ocr_confidence": 0.91,
            }
        ],
    )

    result = analyze_clean_article(article, analyze_time=datetime(2026, 7, 6, 9, 0))

    assert result.article_hash == "hash-1"
    assert result.publish_date.isoformat() == "2026-07-06"
    assert result.summary_text == "深圳企业关注报价和供需变化。"
    assert result.topic_tags == ["深圳", "湖北", "供应链", "报价", "供需"]
    assert "article_url" not in result.summary_text
    assert not hasattr(result, "transient_body_text")
    assert result.extracted_tables[0]["source_media_type"] == "dom_table"
    assert result.extracted_tables[0]["row_count"] == 1
    assert result.extracted_tables[0]["parsed_item_count"] == 1
    assert result.price_items[0]["product_family"] == "chicken_egg"
    assert result.price_items[0]["price_text"] == "187元"
    assert len(result.egg_price_items) == 1


def test_analyze_clean_article_builds_bounded_egg_price_preview() -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-price",
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 9, 8, 30),
        author=None,
        digest=None,
        content_length=100,
        transient_body_text="1.红蛋价格：4.90元/筐装(稳)\n2.粉蛋价格：5.00元/筐装(稳)",
    )

    result = analyze_clean_article(
        article,
        analyze_time=datetime(2026, 7, 9, 10, 0),
        price_items_preview_limit=1,
    )

    payload = json.loads(result.price_items_json())
    assert payload["version"] == "egg_price_v1"
    assert payload["total_item_count"] == 2
    assert payload["preview_limit"] == 1
    assert payload["truncated"] is True
    assert payload["items"][0]["product_name"] == "红蛋"
    assert len(result.egg_price_items) == 2


def test_analyze_clean_article_resolves_quote_date_separately_from_publish_date() -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-fujian",
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 8, 21, 59),
        collect_time=datetime(2026, 7, 9, 8, 3),
        author=None,
        digest=None,
        content_length=100,
        transient_body_text="1.红蛋价格：4.90元/筐装(稳)",
    )

    result = analyze_clean_article(article, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.publish_date == date(2026, 7, 8)
    assert result.collect_time == datetime(2026, 7, 9, 8, 3)
    assert result.quote_date == date(2026, 7, 9)
    assert result.quote_date_source == "title"
    assert result.quote_date_confidence == 1.0
    assert result.egg_price_items[0].quote_date == date(2026, 7, 9)


def test_analyze_clean_article_keeps_image_quote_not_supported_note() -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-image-note",
        account_name="家美鲜鸡蛋 佳美鲜",
        title="报价",
        publish_time=datetime(2026, 7, 9, 8, 30),
        author=None,
        digest=None,
        content_length=100,
        transient_ocr_tables=[
            {
                "source_media_type": "image_quote_not_supported_v1",
                "source_image_index": 0,
                "width": 1080,
                "height": 607,
                "note": "image_quote_not_supported_v1",
            }
        ],
    )

    result = analyze_clean_article(article, analyze_time=datetime(2026, 7, 9, 10, 0))

    payload = json.loads(result.extracted_tables_json())
    assert payload["notes"] == [
        {
            "source_media_type": "image_quote_not_supported_v1",
            "source_image_index": 0,
            "width": 1080,
            "height": 607,
            "note": "image_quote_not_supported_v1",
        }
    ]
    assert "raw" not in result.extracted_tables_json()
    assert "https://mp.weixin.qq.com" not in result.extracted_tables_json()


def test_article_analysis_service_consumes_article_tasks_without_legacy_report_task() -> None:
    source = CleanArticleForAnalysis(
        article_hash="hash-1",
        account_name="行业观察",
        title="深圳供应链价格观察",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author="作者A",
        digest="深圳企业关注报价和供需变化。",
        content_length=1200,
        article_url="https://mp.weixin.qq.com/s/abc",
    )
    repo = FakeArticleAnalysisRepo([source])
    extractor = FakeTransientExtractor(
        ArticleTransientExtraction(
            body_text="湖北客户关注深圳供应链报价。",
            html_tables=[
                {
                    "source_media_type": "html_table",
                    "title": "贵阳鸡蛋价格参考",
                    "headers": ["规格", "毛重", "含包装价", "涨"],
                    "rows": [["大码", "52斤以上", "208-213", "+8"]],
                }
            ],
            ocr_tables=[],
        )
    )
    service = ArticleAnalysisService(repo=repo, extractor=extractor)

    result = service.analyze_once(limit=10, analyze_time=datetime(2026, 7, 6, 9, 0))

    assert result.read_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    assert extractor.seen_articles == [source]
    assert repo.analyses[0].article_hash == "hash-1"
    assert repo.analyses[0].topic_tags == ["深圳", "湖北", "供应链", "报价", "供需"]
    assert len(repo.analyses[0].egg_price_items) == 1
    assert repo.analyses[0].egg_price_items[0].price_text == "208-213"
    assert repo.daily_report_dates == []
    assert repo.successes == ["hash-1"]
    assert repo.failures == []
    assert not hasattr(repo.analyses[0], "transient_body_text")


def test_article_analysis_service_extracts_quote_from_provider_body_without_persisting_body() -> None:
    body = "1.红蛋价格：4.90元/筐装(稳)"
    source = CleanArticleForAnalysis(
        article_hash="hash-provider-quote",
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 9, 8, 30),
        author=None,
        digest=None,
        content_length=len(body),
        article_url="https://mp.weixin.qq.com/s/provider-quote",
        content_locator="provider-quote-locator",
        content_locator_type="werss_article_view",
    )
    repo = FakeArticleAnalysisRepo([source])
    provider = QuoteContentProvider(body)
    service = ArticleAnalysisService(
        repo=repo,
        extractor=ProviderBackedArticleTransientExtractor(provider),
    )

    result = service.analyze_once(limit=1, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.success_count == 1
    assert provider.seen_sources[0].content_locator == "provider-quote-locator"
    assert repo.analyses[0].egg_price_items[0].price_text == "4.90元"
    assert not hasattr(repo.analyses[0], "transient_body_text")
    assert body not in repo.analyses[0].price_items_json()


def test_article_analysis_service_marks_article_task_failed_without_group_side_effects() -> None:
    source = CleanArticleForAnalysis(
        article_hash="hash-err",
        account_name="行业观察",
        title="解析失败文章",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author=None,
        digest=None,
        content_length=0,
        article_url="https://mp.weixin.qq.com/s/error",
    )
    repo = FakeArticleAnalysisRepo([source])
    service = ArticleAnalysisService(repo=repo, extractor=FailingTransientExtractor())

    result = service.analyze_once(limit=5, analyze_time=datetime(2026, 7, 6, 9, 0))

    assert result.read_count == 1
    assert result.success_count == 0
    assert result.failed_count == 1
    assert repo.analyses == []
    assert repo.daily_report_dates == []
    assert repo.successes == []
    assert repo.failures == [("hash-err", "RuntimeError")]


def test_article_analysis_service_redacts_provider_failure_and_leaves_task_retryable() -> None:
    secret_body = "内部正文报价 999 元"
    source = CleanArticleForAnalysis(
        article_hash="hash-provider-error",
        account_name="行业观察",
        title="解析失败文章",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author=None,
        digest=None,
        content_length=0,
        article_url="https://mp.weixin.qq.com/s/error",
    )
    repo = FakeArticleAnalysisRepo([source])
    service = ArticleAnalysisService(repo=repo, extractor=SensitiveFailingExtractor(secret_body))

    result = service.analyze_once(limit=1, analyze_time=datetime(2026, 7, 6, 9, 0))

    assert result.failed_count == 1
    assert repo.analyses == []
    assert repo.successes == []
    assert repo.failures == [("hash-provider-error", "RuntimeError")]
    assert secret_body not in repo.failures[0][1]


def test_article_analysis_service_can_disable_egg_price_extraction() -> None:
    source = CleanArticleForAnalysis(
        article_hash="hash-disabled",
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 9, 8, 30),
        author=None,
        digest=None,
        content_length=100,
        article_url="https://mp.weixin.qq.com/s/abc",
    )
    repo = FakeArticleAnalysisRepo([source])
    service = ArticleAnalysisService(
        repo=repo,
        extractor=FailingTransientExtractor(),
        egg_price_extraction_enabled=False,
    )

    result = service.analyze_once(limit=1, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.success_count == 1
    assert result.failed_count == 0
    assert repo.analyses[0].egg_price_items == []
    assert json.loads(repo.analyses[0].price_items_json())["total_item_count"] == 0
    assert repo.successes == ["hash-disabled"]


def test_article_analysis_service_creates_daily_report_task_by_quote_date() -> None:
    source = CleanArticleForAnalysis(
        article_hash="hash-fujian",
        account_name="福建闽融鸡蛋报价平台",
        title="2026年07月09日｜福建闽融平台",
        publish_time=datetime(2026, 7, 8, 21, 59),
        collect_time=datetime(2026, 7, 9, 8, 3),
        author=None,
        digest=None,
        content_length=100,
        article_url="https://mp.weixin.qq.com/s/fujian",
    )
    repo = FakeArticleAnalysisRepo([source])
    extractor = FakeTransientExtractor(
        ArticleTransientExtraction(
            body_text="1.红蛋价格：4.90元/筐装(稳)",
            html_tables=[],
            ocr_tables=[],
        )
    )
    service = ArticleAnalysisService(repo=repo, extractor=extractor)

    result = service.analyze_once(limit=1, analyze_time=datetime(2026, 7, 9, 10, 0))

    assert result.success_count == 1
    assert repo.analyses[0].publish_date == date(2026, 7, 8)
    assert repo.analyses[0].quote_date == date(2026, 7, 9)
    assert repo.daily_report_dates == []


class FakeArticleAnalysisRepo:
    def __init__(self, articles: list[CleanArticleForAnalysis]) -> None:
        self.articles = articles
        self.analyses = []
        self.daily_report_dates = []
        self.successes = []
        self.failures = []

    def list_pending_analyze_articles(self, limit: int) -> list[CleanArticleForAnalysis]:
        return self.articles[:limit]

    def upsert_article_analysis_with_price_items(self, analysis) -> None:
        self.analyses.append(analysis)

    def create_daily_report_task(self, report_date) -> None:
        self.daily_report_dates.append(report_date)

    def mark_analyze_task_success(self, article_hash: str) -> None:
        self.successes.append(article_hash)

    def mark_analyze_task_failed(self, article_hash: str, error_msg: str) -> None:
        self.failures.append((article_hash, error_msg))


class FakeTransientExtractor:
    def __init__(self, extraction: ArticleTransientExtraction) -> None:
        self.extraction = extraction
        self.seen_articles = []

    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        self.seen_articles.append(article)
        return replace(
            article,
            transient_body_text=self.extraction.body_text,
            transient_html_tables=self.extraction.html_tables,
            transient_ocr_tables=self.extraction.ocr_tables,
        )


class FailingTransientExtractor:
    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        raise RuntimeError("extract failed")


class SensitiveFailingExtractor:
    def __init__(self, secret_body: str) -> None:
        self.secret_body = secret_body

    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        raise RuntimeError(self.secret_body)


class QuoteContentProvider:
    def __init__(self, body: str) -> None:
        self.body = body
        self.seen_sources = []

    def parse(self, source):
        self.seen_sources.append(source)
        return ArticleContent(self.body, source.title, source.publish_time, source.author, source.digest, "werss")
