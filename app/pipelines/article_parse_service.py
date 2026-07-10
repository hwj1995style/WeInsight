from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.domain.article_parsing import ArticleParseSource, CleanArticleRecord, ParsedArticleContent


@dataclass(frozen=True)
class ArticleParseResult:
    read_count: int
    success_count: int
    failed_count: int


class ArticleParseRepo(Protocol):
    def list_pending_parse_articles(self, limit: int) -> list[ArticleParseSource]:
        ...

    def upsert_clean_article(self, article: CleanArticleRecord) -> None:
        ...

    def create_analyze_task(self, article_hash: str) -> None:
        ...

    def mark_clean_task_success(self, article_hash: str) -> None:
        ...

    def mark_clean_task_failed(self, article_hash: str, error_msg: str) -> None:
        ...


class ArticleBrowserParser(Protocol):
    def parse(self, article_url: str) -> ParsedArticleContent:
        ...


class ArticleParseService:
    def __init__(self, *, repo: ArticleParseRepo, parser: ArticleBrowserParser) -> None:
        self.repo = repo
        self.parser = parser

    def parse_once(self, limit: int, parse_time: datetime) -> ArticleParseResult:
        sources = self.repo.list_pending_parse_articles(limit)
        success_count = 0
        failed_count = 0

        for source in sources:
            try:
                parsed = self.parser.parse(source.article_url)
                clean = CleanArticleRecord(
                    article_hash=source.article_hash,
                    account_name=source.account_name,
                    title=parsed.title or source.title,
                    article_url=source.article_url,
                    publish_time=parsed.publish_time or source.publish_time,
                    author=parsed.author or source.author,
                    digest=parsed.digest or source.digest,
                    content_length=parsed.content_length,
                    parse_time=parse_time,
                )
                self.repo.upsert_clean_article(clean)
                self.repo.create_analyze_task(source.article_hash)
                self.repo.mark_clean_task_success(source.article_hash)
                success_count += 1
            except Exception as exc:
                self.repo.mark_clean_task_failed(source.article_hash, str(exc))
                failed_count += 1

        return ArticleParseResult(
            read_count=len(sources),
            success_count=success_count,
            failed_count=failed_count,
        )


class PlaywrightArticleParser:
    def __init__(
        self,
        *,
        timeout_ms: int = 30000,
        headless: bool = True,
        browser_executable_path: str | None = None,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.browser_executable_path = browser_executable_path

    def parse(self, article_url: str) -> ParsedArticleContent:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch_options = {"headless": self.headless}
            executable_path = resolve_playwright_browser_executable_path(self.browser_executable_path)
            if executable_path is not None:
                launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_options)
            try:
                page = browser.new_page()
                page.goto(article_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                html = page.content()
            finally:
                browser.close()
        return extract_article_metadata_from_html(html)


def resolve_playwright_browser_executable_path(configured_path: str | None) -> str | None:
    value = (configured_path or "").strip()
    if not value:
        return None

    if value.lower() == "auto":
        return _find_existing_playwright_chromium() or _find_system_chrome()

    path = Path(os.path.expandvars(value)).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Configured browser executable was not found: {path}")
    return str(path)


def _find_existing_playwright_chromium() -> str | None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    cache_root = Path(local_app_data) / "ms-playwright"
    if not cache_root.exists():
        return None

    revisions = sorted(
        (
            (_playwright_chromium_revision(path), path)
            for path in cache_root.glob("chromium-*")
            if path.is_dir()
        ),
        reverse=True,
    )
    for _, revision_path in revisions:
        for relative_path in (
            Path("chrome-win64") / "chrome.exe",
            Path("chrome-win") / "chrome.exe",
        ):
            executable = revision_path / relative_path
            if executable.exists():
                return str(executable)
    return None


def _playwright_chromium_revision(path: Path) -> int:
    match = re.match(r"chromium-(\d+)$", path.name)
    return int(match.group(1)) if match else -1


def _find_system_chrome() -> str | None:
    candidates = [
        os.environ.get("CHROME"),
        os.environ.get("GOOGLE_CHROME_SHIM"),
        _env_path("PROGRAMFILES", "Google", "Chrome", "Application", "chrome.exe"),
        _env_path("PROGRAMFILES(X86)", "Google", "Chrome", "Application", "chrome.exe"),
        _env_path("LOCALAPPDATA", "Google", "Chrome", "Application", "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate))
    return None


def _env_path(name: str, *parts: str) -> str | None:
    root = os.environ.get(name)
    if not root:
        return None
    return str(Path(root, *parts))


def extract_article_metadata_from_html(html: str) -> ParsedArticleContent:
    parser = _ArticleHtmlMetadataParser()
    parser.feed(html)
    return ParsedArticleContent(
        title=_first_non_empty(
            parser.meta_values.get("og:title"),
            parser.meta_values.get("twitter:title"),
            _normalize_text(" ".join(parser.title_parts)),
        ),
        publish_time=_parse_datetime(
            _first_non_empty(
                parser.meta_values.get("article:published_time"),
                parser.meta_values.get("publish_time"),
                parser.meta_values.get("publishdate"),
                _normalize_text(" ".join(parser.visible_publish_time_parts)),
            )
        ),
        author=_first_non_empty(
            parser.meta_values.get("author"),
            parser.meta_values.get("article:author"),
        ),
        digest=_first_non_empty(
            parser.meta_values.get("description"),
            parser.meta_values.get("og:description"),
        ),
        content_length=len(_normalize_text(" ".join(parser.body_text_parts))),
    )


class _ArticleHtmlMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_values: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.body_text_parts: list[str] = []
        self.visible_publish_time_parts: list[str] = []
        self._in_title = False
        self._in_body = False
        self._skip_depth = 0
        self._visible_publish_time_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        attrs_map = {str(name).lower(): value for name, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
        elif tag == "body":
            self._in_body = True
        elif tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag == "meta":
            key = (attrs_map.get("property") or attrs_map.get("name") or "").lower()
            content = attrs_map.get("content")
            if key and content:
                self.meta_values[key] = str(content).strip()
        if attrs_map.get("id") == "publish_time":
            self._visible_publish_time_depth = 1
        elif self._visible_publish_time_depth > 0:
            self._visible_publish_time_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "body":
            self._in_body = False
        elif tag in {"script", "style"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._visible_publish_time_depth > 0:
            self._visible_publish_time_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_body and self._skip_depth == 0:
            self.body_text_parts.append(data)
        if self._visible_publish_time_depth > 0 and self._skip_depth == 0:
            self.visible_publish_time_parts.append(data)


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        normalized = _normalize_text(value or "")
        if normalized:
            return normalized
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None)
    except ValueError:
        pass

    text = (
        value.strip()
        .replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
    )
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
