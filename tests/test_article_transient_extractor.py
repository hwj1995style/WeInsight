from __future__ import annotations

import sys
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from app.domain.article_analysis import CleanArticleForAnalysis
from app.pipelines.article_transient_extractor import (
    PlaywrightArticleTransientExtractor,
    ProviderBackedArticleTransientExtractor,
    extract_transient_article_data,
)


def test_provider_backed_extractor_replaces_only_transient_body() -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-provider",
        account_name="福建闽融鸡蛋报价平台",
        title="报价",
        publish_time=datetime(2026, 7, 9, 8, 30),
        author=None,
        digest=None,
        content_length=10,
        article_url="https://mp.weixin.qq.com/s/provider",
    )
    provider = FakeContentProvider("1.红蛋价格：4.90元/筐装(稳)")

    result = ProviderBackedArticleTransientExtractor(provider).extract(article)

    assert result.transient_body_text == "1.红蛋价格：4.90元/筐装(稳)"
    assert result.transient_html_tables == []
    assert result.transient_ocr_tables == []
    assert provider.seen_sources[0].article_hash == article.article_hash
    assert provider.seen_sources[0].article_url == article.article_url


class FakeContentProvider:
    def __init__(self, body_text: str) -> None:
        self.body_text = body_text
        self.seen_sources = []

    def parse(self, source):
        from app.content.article_content import ArticleContent

        self.seen_sources.append(source)
        return ArticleContent(
            body_text=self.body_text,
            title=source.title,
            publish_time=source.publish_time,
            author=source.author,
            digest=source.digest,
            source="werss",
        )


def test_extract_transient_article_data_reads_js_content_tables_and_context() -> None:
    html_payload = {
        "body_text": "\n".join(
            [
                "建议参考价360枚/箱",
                "通货装车价（含包装）",
                "净重",
                "价差",
                "昨日价",
                "今日价",
                "涨跌",
            ]
        ),
        "tables": [
            {
                "source_table_index": 0,
                "title": "通货装车价（含包装）",
                "context": {"quote_basis": "360枚/箱"},
                "headers": ["净重", "价差", "昨日价", "今日价", "涨跌"],
                "rows": [["45", "标价", "215", "220", "5"]],
            }
        ],
        "large_images": [{"source_image_index": 0, "width": 1080, "height": 607}],
    }

    result = extract_transient_article_data(html_payload)

    assert result.body_text.startswith("建议参考价360枚/箱")
    assert result.html_tables == [
        {
            "source_media_type": "dom_table",
            "source_table_index": 0,
            "title": "通货装车价（含包装）",
            "context": {"quote_basis": "360枚/箱"},
            "headers": ["净重", "价差", "昨日价", "今日价", "涨跌"],
            "rows": [["45", "标价", "215", "220", "5"]],
        }
    ]
    assert result.ocr_tables == [
        {
            "source_media_type": "image_quote_not_supported_v1",
            "source_image_index": 0,
            "width": 1080,
            "height": 607,
            "note": "image_quote_not_supported_v1",
        }
    ]


def test_extract_transient_article_data_promotes_late_header_rows() -> None:
    html_payload = {
        "body_text": "",
        "tables": [
            {
                "source_table_index": 0,
                "title": "",
                "context": {},
                "headers": [],
                "rows": [
                    ["扫码关注公众号\n360枚/箱\n（此报价不含运费和包装费）"],
                    ["河北馆陶鸡蛋报价"],
                    ["净重", "昨日价", "今日价", "涨跌"],
                    ["精品菜花黄蛋托（粉蛋）"],
                    ["45斤", "192元", "192元", "0"],
                ],
            }
        ],
        "large_images": [],
    }

    result = extract_transient_article_data(html_payload)

    assert result.html_tables[0]["title"] == "河北馆陶鸡蛋报价"
    assert result.html_tables[0]["context"] == {
        "quote_basis": "360枚/箱",
        "package_policy": "不含运费和包装费",
    }
    assert result.html_tables[0]["headers"] == ["净重", "昨日价", "今日价", "涨跌"]
    assert result.html_tables[0]["rows"] == [
        ["精品菜花黄蛋托（粉蛋）"],
        ["45斤", "192元", "192元", "0"],
    ]


def test_extract_transient_article_data_repairs_title_misclassified_as_headers() -> None:
    html_payload = {
        "body_text": "",
        "tables": [
            {
                "source_table_index": 0,
                "title": "（特别提醒：报价仅供参考。）",
                "context": {},
                "headers": ["7月8日贵阳鸡蛋价格参考仅供参考"],
                "rows": [
                    ["规格", "毛重", "含包装价", "涨"],
                    ["大码", "52斤以上", "228—233", "↑5"],
                    ["中码", "48斤以上", "220—225", "↑5"],
                ],
            }
        ],
        "large_images": [],
    }

    result = extract_transient_article_data(html_payload)

    assert result.html_tables[0]["title"] == "7月8日贵阳鸡蛋价格参考仅供参考"
    assert result.html_tables[0]["headers"] == ["规格", "毛重", "含包装价", "涨"]
    assert result.html_tables[0]["rows"] == [
        ["大码", "52斤以上", "228—233", "↑5"],
        ["中码", "48斤以上", "220—225", "↑5"],
    ]


def test_playwright_transient_extractor_reopens_article_and_replaces_transient_fields(
    monkeypatch,
) -> None:
    article = CleanArticleForAnalysis(
        article_hash="hash-1",
        account_name="家美鲜鸡蛋 佳美鲜",
        title="报价",
        publish_time=datetime(2026, 7, 9, 9, 0),
        author=None,
        digest=None,
        content_length=100,
        article_url="https://mp.weixin.qq.com/s/test",
    )
    payload = {
        "body_text": "建议参考价360枚/箱\n通货装车价（含包装）",
        "tables": [
            {
                "source_table_index": 0,
                "title": "通货装车价（含包装）",
                "context": {"quote_basis": "360枚/箱"},
                "headers": ["净重", "今日价"],
                "rows": [["45", "220"]],
            }
        ],
        "large_images": [{"source_image_index": 0, "width": 1080, "height": 607}],
    }
    events: list[tuple[str, Any]] = []
    sync_playwright = _build_fake_sync_playwright(payload, events)
    monkeypatch.setitem(
        sys.modules,
        "playwright",
        SimpleNamespace(sync_api=SimpleNamespace(sync_playwright=sync_playwright)),
    )
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=sync_playwright),
    )
    monkeypatch.setattr(
        "app.pipelines.article_transient_extractor.resolve_playwright_browser_executable_path",
        lambda configured_path: "C:/Chrome/chrome.exe",
    )

    extractor = PlaywrightArticleTransientExtractor(
        timeout_ms=12345,
        headless=False,
        browser_executable_path="auto",
    )

    result = extractor.extract(article)

    assert result.transient_body_text == "建议参考价360枚/箱\n通货装车价（含包装）"
    assert result.transient_html_tables == [
        {
            "source_media_type": "dom_table",
            "source_table_index": 0,
            "title": "通货装车价（含包装）",
            "context": {"quote_basis": "360枚/箱"},
            "headers": ["净重", "今日价"],
            "rows": [["45", "220"]],
        }
    ]
    assert result.transient_ocr_tables == [
        {
            "source_media_type": "image_quote_not_supported_v1",
            "source_image_index": 0,
            "width": 1080,
            "height": 607,
            "note": "image_quote_not_supported_v1",
        }
    ]
    assert events == [
        ("launch", {"headless": False, "executable_path": "C:/Chrome/chrome.exe"}),
        ("new_page", {"viewport": {"width": 1365, "height": 900}}),
        (
            "goto",
            {
                "url": "https://mp.weixin.qq.com/s/test",
                "wait_until": "domcontentloaded",
                "timeout": 12345,
            },
        ),
        ("wait_for_timeout", 1200),
        ("evaluate", "script"),
        ("close", None),
    ]


def _build_fake_sync_playwright(payload: dict[str, Any], events: list[tuple[str, Any]]):
    class FakePage:
        def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
            events.append(
                (
                    "goto",
                    {
                        "url": url,
                        "wait_until": wait_until,
                        "timeout": timeout,
                    },
                )
            )

        def wait_for_timeout(self, timeout_ms: int) -> None:
            events.append(("wait_for_timeout", timeout_ms))

        def evaluate(self, script: str) -> dict[str, Any]:
            assert "#js_content" in script
            assert "large_images" in script
            events.append(("evaluate", "script"))
            return payload

    class FakeBrowser:
        def new_page(self, **kwargs) -> FakePage:
            events.append(("new_page", kwargs))
            return FakePage()

        def close(self) -> None:
            events.append(("close", None))

    class FakeChromium:
        def launch(self, **kwargs) -> FakeBrowser:
            events.append(("launch", kwargs))
            return FakeBrowser()

    class FakePlaywrightContext:
        def __enter__(self):
            return SimpleNamespace(chromium=FakeChromium())

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    return FakePlaywrightContext
