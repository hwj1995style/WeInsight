from __future__ import annotations

import re
from html.parser import HTMLParser

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
_DROP_CONTENT_TAGS = frozenset(
    {"script", "style", "iframe", "object", "embed", "svg", "math", "template"}
)
_BLOCK_TAGS = frozenset(
    {"address", "article", "aside", "blockquote", "div", "footer", "header", "main", "nav", "p", "section"}
)
_DANGEROUS_PROTOCOL = re.compile(r"(?i)\b(?:javascript|data)\s*:")


def render_safe_markdown(markdown_text: str) -> Markup:
    """Render report Markdown without preserving HTML, links, or attributes."""
    if not isinstance(markdown_text, str):
        raise TypeError("markdown_text must be a string")
    text_without_html = _strip_raw_html(markdown_text)
    text_without_html = _DANGEROUS_PROTOCOL.sub("", text_without_html)
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


def _strip_raw_html(value: str) -> str:
    parser = _SafeTextExtractor()
    parser.feed(value)
    parser.close()
    return "".join(parser.parts)


class _SafeTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._blocked_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        normalized = tag.lower()
        if normalized in _DROP_CONTENT_TAGS:
            self._blocked_tags.append(normalized)
        elif not self._blocked_tags and normalized in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if self._blocked_tags:
            if normalized == self._blocked_tags[-1]:
                self._blocked_tags.pop()
            return
        if normalized in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._blocked_tags:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        return
