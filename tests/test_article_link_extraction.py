from __future__ import annotations

from app.rpa.article_link_extraction import (
    extract_article_detail_urls,
    read_article_url_from_clipboard_copy,
)


def test_extract_article_detail_urls_prefers_s_path_over_profile_ext() -> None:
    values = [
        "https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=abc",
        "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz&chksm=1",
    ]

    assert extract_article_detail_urls(values, max_articles=3) == [
        "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz&chksm=1"
    ]


def test_extract_article_detail_urls_deduplicates_and_limits() -> None:
    url1 = "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=one"
    url2 = "https://mp.weixin.qq.com/s?__biz=abc&mid=2&idx=1&sn=two"

    assert extract_article_detail_urls([url1, url1, url2], max_articles=1) == [url1]


def test_extract_article_detail_urls_accepts_tokenized_s_path() -> None:
    url = "https://mp.weixin.qq.com/s/AbCdEf_123-xyz"

    assert extract_article_detail_urls([url], max_articles=1) == [url]


def test_clipboard_copy_restores_original_clipboard_after_success() -> None:
    clipboard = {"value": "original"}

    def paste() -> str:
        return clipboard["value"]

    def copy(value: str) -> None:
        clipboard["value"] = value

    def copy_action() -> None:
        clipboard["value"] = "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"

    result = read_article_url_from_clipboard_copy(copy_action, paste, copy)

    assert result == "https://mp.weixin.qq.com/s?__biz=abc&mid=1&idx=1&sn=xyz"
    assert clipboard["value"] == "original"


def test_clipboard_copy_restores_original_clipboard_after_failure() -> None:
    clipboard = {"value": "original"}

    def paste() -> str:
        return clipboard["value"]

    def copy(value: str) -> None:
        clipboard["value"] = value

    def copy_action() -> None:
        clipboard["value"] = "not a wechat article url"

    result = read_article_url_from_clipboard_copy(copy_action, paste=paste, copy=copy)

    assert result is None
    assert clipboard["value"] == "original"
