from __future__ import annotations

from markupsafe import Markup

from app.security.markdown import render_safe_markdown


def test_markdown_renderer_removes_raw_html_scripts_and_attributes() -> None:
    rendered = render_safe_markdown(
        "# 日报\n<script>alert(1)</script>"
        '<img src="x" onerror="alert(2)">'
        '<p style="color:red">正文</p><iframe src="bad"></iframe>'
    )

    assert isinstance(rendered, Markup)
    assert "<h1>日报</h1>" in rendered
    assert "正文" in rendered
    for forbidden in ("<script", "script&gt;", "onerror", "style=", "<iframe", "<img"):
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

