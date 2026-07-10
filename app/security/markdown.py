from __future__ import annotations

import bleach
from markdown_it import MarkdownIt
from markupsafe import Markup


ALLOWED_TAGS = frozenset(
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
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)

_MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable(
    "table"
)


def render_safe_markdown(markdown_text: str) -> Markup:
    """Render report Markdown without preserving HTML, links, or attributes."""
    if not isinstance(markdown_text, str):
        raise TypeError("markdown_text must be a string")
    text_without_html = bleach.clean(
        markdown_text,
        tags=(),
        attributes={},
        protocols=(),
        strip=True,
        strip_comments=True,
    )
    rendered = _MARKDOWN.render(text_without_html)
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={},
        protocols=(),
        strip=True,
        strip_comments=True,
    )
    return Markup(cleaned)
