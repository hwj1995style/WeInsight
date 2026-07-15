from __future__ import annotations

from markupsafe import Markup

import pytest

from app.security.markdown import ALLOWED_TAGS, render_safe_markdown


def test_markdown_renderer_removes_raw_html_scripts_and_attributes() -> None:
    rendered = render_safe_markdown(
        "# 日报\n<script>alert(1)</script>"
        '<img src="x" onerror="alert(2)">'
        '<p style="color:red">正文</p><iframe src="bad"></iframe>'
    )

    assert isinstance(rendered, Markup)
    assert "<h1>日报</h1>" in rendered
    assert "正文" in rendered
    for forbidden in (
        "<script",
        "script&gt;",
        "alert(1)",
        "alert(2)",
        "onerror",
        "style=",
        "<iframe",
        "<img",
    ):
        assert forbidden not in rendered.lower()


def test_markdown_renderer_strips_links_and_does_not_autolink_urls() -> None:
    rendered = render_safe_markdown(
        "[不应保留链接](https://example.test/private)\n\n"
        "https://example.test/raw"
    )

    assert "不应保留链接" in rendered
    assert "https://example.test/raw" in rendered
    assert "<a" not in rendered.lower()
    assert "href" not in rendered.lower()


def test_markdown_renderer_allows_tables_without_any_attributes() -> None:
    rendered = render_safe_markdown(
        "| 对象 | 数量 |\n| --- | ---: |\n| 核心群 | 3 |"
    )

    assert "<table>" in rendered
    assert "<thead>" in rendered
    assert "<tbody>" in rendered
    assert "<th>对象</th>" in rendered
    assert "<td>核心群</td>" in rendered
    assert "=" not in rendered


def test_markdown_renderer_uses_the_fixed_attribute_free_allowlist() -> None:
    assert ALLOWED_TAGS == frozenset(
        {
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "p",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "code",
            "pre",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "blockquote",
        }
    )


def test_markdown_renderer_removes_nested_malformed_html_and_comments() -> None:
    rendered = render_safe_markdown(
        "<!-- secret -->"
        "<style>body{background:url(https://secret.test)}</style>"
        "<iframe srcdoc='<script>alert(3)</script>'>private body</iframe>"
        "<div><svg><script>alert(4)</script></svg><b>保留文字</div>"
    )

    assert "保留文字" in rendered
    for forbidden in (
        "secret",
        "background",
        "private body",
        "alert",
        "iframe",
        "script",
        "style",
        "svg",
        "srcdoc",
        "<!--",
    ):
        assert forbidden not in rendered.lower()


def test_markdown_renderer_never_emits_link_image_or_protocol_attributes() -> None:
    rendered = render_safe_markdown(
        "[javascript](javascript:alert(1))\n\n"
        "![data](data:text/html;base64,PHNjcmlwdD4=)\n\n"
        '<a href="javascript:alert(2)">raw</a>'
    )

    for forbidden in ("<a", "<img", "href", "src=", "javascript:", "data:"):
        assert forbidden not in rendered.lower()


@pytest.mark.parametrize("value", [None, 1, b"# report", []])
def test_markdown_renderer_rejects_non_string_input(value) -> None:
    with pytest.raises(TypeError, match="string"):
        render_safe_markdown(value)
