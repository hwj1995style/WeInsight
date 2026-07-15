from __future__ import annotations

import sys
import importlib
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace

from app.content.article_content import ArticleContent, ContentFetchError
from app.domain.article_parsing import ArticleParseSource, ParsedArticleContent
from app.pipelines.article_parse_service import (
    ArticleParseService,
    PlaywrightArticleParser,
    extract_body_text_from_html,
    extract_article_metadata_from_html,
)


def test_body_extraction_prefers_wechat_article_selector_and_canonicalizes_digit_spans() -> None:
    html = "<body>navigation<div id='js_content'><span>12</span> <span>34</span></div>footer</body>"
    assert extract_body_text_from_html(html) == "12 34"


def test_body_selector_stops_after_void_elements_and_container_end() -> None:
    html = "<body><div id='js_content'>正文<br><img src='x'><hr></div>页脚</body>"
    assert extract_body_text_from_html(html) == "正文"


class FakeArticleParseRepo:
    def __init__(self, sources: list[ArticleParseSource]) -> None:
        self.sources = sources
        self.clean_articles = []
        self.analyze_tasks: list[str] = []
        self.successes: list[str] = []
        self.failures: list[tuple[str, str]] = []

    def list_pending_parse_articles(self, limit: int) -> list[ArticleParseSource]:
        return self.sources[:limit]

    def upsert_clean_article(self, article) -> None:
        self.clean_articles.append(article)

    def create_analyze_task(self, article_hash: str) -> None:
        self.analyze_tasks.append(article_hash)

    def mark_clean_task_success(self, article_hash: str) -> None:
        self.successes.append(article_hash)

    def mark_clean_task_failed(self, article_hash: str, error_msg: str) -> None:
        self.failures.append((article_hash, error_msg))


class FakeArticleBrowserParser:
    def __init__(self, parsed_by_url: dict[str, ParsedArticleContent]) -> None:
        self.parsed_by_url = parsed_by_url
        self.urls: list[str] = []
        self.fail_with: Exception | None = None

    def parse(self, article_url: str) -> ParsedArticleContent:
        self.urls.append(article_url)
        if self.fail_with is not None:
            raise self.fail_with
        return self.parsed_by_url[article_url]


def test_article_parse_service_parses_pending_articles_without_ui_lock() -> None:
    source = ArticleParseSource(
        article_hash="article-hash-1",
        account_name="行业观察",
        title="raw title",
        article_url="https://mp.weixin.qq.com/s/abc",
        publish_time=datetime(2026, 7, 6, 8, 0),
        author=None,
        digest=None,
    )
    parsed = ParsedArticleContent(
        title="解析标题",
        publish_time=datetime(2026, 7, 6, 8, 30),
        author="作者",
        digest="摘要",
        content_length=88,
    )
    repo = FakeArticleParseRepo([source])
    parser = FakeArticleBrowserParser({source.article_url: parsed})
    service = ArticleParseService(repo=repo, parser=parser)

    result = service.parse_once(limit=10, parse_time=datetime(2026, 7, 6, 9, 0))

    assert result.read_count == 1
    assert result.success_count == 1
    assert result.failed_count == 0
    assert parser.urls == [source.article_url]
    assert not hasattr(service, "lock_repo")
    assert repo.clean_articles[0].article_hash == "article-hash-1"
    assert repo.clean_articles[0].account_name == "行业观察"
    assert repo.clean_articles[0].title == "解析标题"
    assert repo.clean_articles[0].publish_time == datetime(2026, 7, 6, 8, 30)
    assert repo.clean_articles[0].author == "作者"
    assert repo.clean_articles[0].digest == "摘要"
    assert repo.clean_articles[0].content_length == 88
    assert repo.clean_articles[0].parse_time == datetime(2026, 7, 6, 9, 0)
    assert repo.analyze_tasks == ["article-hash-1"]
    assert repo.successes == ["article-hash-1"]
    assert repo.failures == []


def test_article_parse_service_marks_only_article_task_failed_on_parse_error() -> None:
    source = ArticleParseSource(
        article_hash="article-hash-2",
        account_name="行业观察",
        title="raw title",
        article_url="https://mp.weixin.qq.com/s/error",
        publish_time=datetime(2026, 7, 6, 8, 0),
        author=None,
        digest=None,
    )
    repo = FakeArticleParseRepo([source])
    parser = FakeArticleBrowserParser({})
    parser.fail_with = RuntimeError("parse failed")
    service = ArticleParseService(repo=repo, parser=parser)

    result = service.parse_once(limit=10, parse_time=datetime(2026, 7, 6, 9, 0))

    assert result.read_count == 1
    assert result.success_count == 0
    assert result.failed_count == 1
    assert repo.clean_articles == []
    assert repo.analyze_tasks == []
    assert repo.successes == []
    assert repo.failures == [("article-hash-2", "RuntimeError")]


def test_legacy_parser_failure_never_persists_sensitive_exception_message() -> None:
    source = ArticleParseSource("h", "account", "raw", "https://example.test/private", None, None, None)
    repo = FakeArticleParseRepo([source])
    parser = FakeArticleBrowserParser({})
    parser.fail_with = RuntimeError("https://example.test/private 正文 secret")

    ArticleParseService(repo=repo, parser=parser).parse_once(1, datetime(2026, 7, 6, 9))

    assert repo.failures == [("h", "RuntimeError")]


def test_provider_content_is_hashed_but_never_persisted() -> None:
    source = ArticleParseSource("h", "account", "raw", "https://example.test/a", None, None, None)
    repo = FakeArticleParseRepo([source])

    class Provider:
        def parse(self, value):
            assert value is source
            return ArticleContent("  第一段\n 第二段  ", "title", None, None, None, "werss")

    service = ArticleParseService(repo=repo, provider=Provider())
    service.parse_once(1, datetime(2026, 7, 6, 9))

    clean = repo.clean_articles[0]
    assert clean.content_length == len("第一段 第二段")
    assert clean.content_hash == "568cbfa03f03d65971ee141436c39f855c455918730824343eeb506af9dbb7de"
    assert clean.content_source == "werss"
    assert "正文" not in repr(clean)
    assert not hasattr(clean, "body_text")


def test_provider_failure_records_only_safe_code() -> None:
    source = ArticleParseSource("h", "account", "raw", "https://example.test/secret", None, None, None)
    repo = FakeArticleParseRepo([source])

    class Provider:
        def parse(self, value):
            raise ContentFetchError("werss_http_error", True)

    ArticleParseService(repo=repo, provider=Provider()).parse_once(1, datetime(2026, 7, 6, 9))

    assert repo.failures == [("h", "werss_http_error")]


def test_extract_article_metadata_from_html_keeps_only_metadata_and_body_length() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="解析标题">
        <meta name="author" content="作者">
        <meta name="description" content="摘要">
        <meta property="article:published_time" content="2026-07-06 08:30">
      </head>
      <body>
        <div id="js_content">第一段正文<script>ignore()</script>第二段正文</div>
      </body>
    </html>
    """

    parsed = extract_article_metadata_from_html(html)

    assert parsed.title == "解析标题"
    assert parsed.publish_time == datetime(2026, 7, 6, 8, 30)
    assert parsed.author == "作者"
    assert parsed.digest == "摘要"
    assert parsed.content_length == len("第一段正文 第二段正文")


def test_extract_article_metadata_from_html_uses_visible_wechat_publish_time() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="2026年07月09日｜福建闽融平台">
      </head>
      <body>
        <h1 id="activity-name">2026年07月09日｜福建闽融平台</h1>
        <em id="publish_time">2026年7月8日 21:59</em>
        <span id="js_name">福建闽融鸡蛋报价平台</span>
        <div id="js_content">1.红蛋价格：4.90元/筐装(稳)</div>
      </body>
    </html>
    """

    parsed = extract_article_metadata_from_html(html)

    assert parsed.title == "2026年07月09日｜福建闽融平台"
    assert parsed.publish_time == datetime(2026, 7, 8, 21, 59)


def test_playwright_article_parser_uses_configured_browser_executable_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    executable_path = tmp_path / "chrome.exe"
    executable_path.write_text("", encoding="utf-8")
    launch_kwargs = {}

    class FakeBrowser:
        def new_page(self):
            return SimpleNamespace(
                goto=lambda *args, **kwargs: None,
                content=lambda: "<html><head><title>ok</title></head><body>正文</body></html>",
            )

        def close(self):
            return None

    class FakeChromium:
        def launch(self, **kwargs):
            launch_kwargs.update(kwargs)
            return FakeBrowser()

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=FakeChromium())

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: FakePlaywrightContext()),
    )

    parser = PlaywrightArticleParser(browser_executable_path=str(executable_path))
    parsed = parser.parse("https://mp.weixin.qq.com/s/abc")

    assert parsed.title == "ok"
    assert launch_kwargs["headless"] is True
    assert launch_kwargs["executable_path"] == str(executable_path)


def test_resolve_playwright_browser_executable_path_auto_uses_existing_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = importlib.import_module("app.pipelines.article_parse_service")
    resolve_playwright_browser_executable_path = getattr(
        module,
        "resolve_playwright_browser_executable_path",
    )
    cache_root = tmp_path / "ms-playwright"
    old_chrome = cache_root / "chromium-1129" / "chrome-win" / "chrome.exe"
    new_chrome = cache_root / "chromium-1223" / "chrome-win64" / "chrome.exe"
    old_chrome.parent.mkdir(parents=True)
    new_chrome.parent.mkdir(parents=True)
    old_chrome.write_text("", encoding="utf-8")
    new_chrome.write_text("", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert resolve_playwright_browser_executable_path("auto") == str(new_chrome)
