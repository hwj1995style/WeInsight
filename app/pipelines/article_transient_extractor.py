from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from app.domain.article_analysis import CleanArticleForAnalysis
from app.pipelines.article_parse_service import resolve_playwright_browser_executable_path


_MAX_TABLES = 20
_MAX_ROWS_PER_TABLE = 80
_MAX_CELLS_PER_ROW = 24
_MAX_TEXT_CHARS = 120_000
_MAX_CELL_CHARS = 500
_MAX_TITLE_CHARS = 300


@dataclass(frozen=True)
class ArticleTransientData:
    body_text: str
    html_tables: list[dict[str, Any]]
    ocr_tables: list[dict[str, Any]]


class PlaywrightArticleTransientExtractor:
    def __init__(
        self,
        *,
        timeout_ms: int = 30000,
        headless: bool = True,
        browser_executable_path: str | None = None,
        image_quote_note_enabled: bool = True,
    ) -> None:
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.browser_executable_path = browser_executable_path
        self.image_quote_note_enabled = image_quote_note_enabled

    def extract(self, article: CleanArticleForAnalysis) -> CleanArticleForAnalysis:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": self.headless}
            executable_path = resolve_playwright_browser_executable_path(
                self.browser_executable_path
            )
            if executable_path is not None:
                launch_options["executable_path"] = executable_path

            browser = playwright.chromium.launch(**launch_options)
            try:
                page = browser.new_page(viewport={"width": 1365, "height": 900})
                page.goto(
                    article.article_url,
                    wait_until="domcontentloaded",
                    timeout=self.timeout_ms,
                )
                page.wait_for_timeout(1200)
                payload = page.evaluate(_PAGE_EXTRACTION_SCRIPT)
            finally:
                browser.close()

        transient = extract_transient_article_data(
            payload,
            image_quote_note_enabled=self.image_quote_note_enabled,
        )
        return replace(
            article,
            transient_body_text=transient.body_text,
            transient_html_tables=transient.html_tables,
            transient_ocr_tables=transient.ocr_tables,
        )


def extract_transient_article_data(
    payload: dict[str, Any],
    *,
    image_quote_note_enabled: bool = True,
) -> ArticleTransientData:
    html_tables = [
        _normalize_dom_table(table)
        for table in _iter_dicts(payload.get("tables"))[:_MAX_TABLES]
    ]

    ocr_tables: list[dict[str, Any]] = []
    if image_quote_note_enabled:
        for image in _iter_dicts(payload.get("large_images")):
            ocr_tables.append(
                {
                    "source_media_type": "image_quote_not_supported_v1",
                    "source_image_index": _to_int(image.get("source_image_index")),
                    "width": _to_int(image.get("width")),
                    "height": _to_int(image.get("height")),
                    "note": "image_quote_not_supported_v1",
                }
            )

    return ArticleTransientData(
        body_text=_text(payload.get("body_text"), max_chars=_MAX_TEXT_CHARS),
        html_tables=html_tables,
        ocr_tables=ocr_tables,
    )


def _normalize_dom_table(table: dict[str, Any]) -> dict[str, Any]:
    rows = [
        _normalize_row(row)
        for row in _iter_rows(table.get("rows"))[:_MAX_ROWS_PER_TABLE]
    ]
    headers = _normalize_row(table.get("headers"))
    context = _normalize_context(table.get("context"))
    title = _text(table.get("title"), max_chars=_MAX_TITLE_CHARS)
    if headers and not _row_looks_like_header(headers):
        rows = [headers, *rows]
        headers = []
    if not headers:
        header_index = _find_header_row_index(rows)
        if header_index is not None:
            pre_header_rows = rows[:header_index]
            headers = rows[header_index]
            rows = rows[header_index + 1 :]
            context = _merge_table_context(context, pre_header_rows)
            promoted_title = _first_title_text(pre_header_rows)
            if promoted_title and _should_replace_table_title(title):
                title = promoted_title
    return {
        "source_media_type": "dom_table",
        "source_table_index": _to_int(table.get("source_table_index")),
        "title": title,
        "context": context,
        "headers": headers,
        "rows": [row for row in rows if row],
    }


def _find_header_row_index(rows: list[list[str]]) -> int | None:
    for index, row in enumerate(rows[:8]):
        if _row_looks_like_header(row):
            return index
    return None


def _row_looks_like_header(row: list[str]) -> bool:
    joined = "".join(row)
    header_hits = sum(
        1
        for word in (
            "净重",
            "毛重",
            "昨日价",
            "今日价",
            "涨跌",
            "涨/落",
            "涨落",
            "规格",
            "含包装价",
            "单价",
            "价格",
        )
        if word in joined
    )
    return len(row) >= 2 and header_hits >= 2


def _merge_table_context(context: dict[str, str], rows: list[list[str]]) -> dict[str, str]:
    merged = dict(context)
    text = "\n".join(" ".join(row) for row in rows)
    box_match = re.search(r"\d+\s*枚\s*/\s*箱", text)
    if box_match and "quote_basis" not in merged:
        merged["quote_basis"] = re.sub(r"\s+", "", box_match.group(0))
    if "不含运费和包装费" in text:
        merged["package_policy"] = "不含运费和包装费"
    elif "含包装" in text:
        merged["package_policy"] = "含包装"
    return merged


def _first_title_text(rows: list[list[str]]) -> str:
    for row in reversed(rows):
        if len(row) == 1:
            value = row[0]
            if value and not re.search(r"\d+\s*枚\s*/\s*箱|扫码|报价不含|不含运费", value):
                return _text(value, max_chars=_MAX_TITLE_CHARS)
    return ""


def _should_replace_table_title(title: str) -> bool:
    if not title:
        return True
    return "特别提醒" in title or "报价仅供参考" in title


def _iter_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _iter_rows(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_context(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        _text(key, max_chars=_MAX_CELL_CHARS): _text(val, max_chars=_MAX_CELL_CHARS)
        for key, val in value.items()
        if _text(key, max_chars=_MAX_CELL_CHARS)
    }


def _normalize_row(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        _text(cell, max_chars=_MAX_CELL_CHARS)
        for cell in value[:_MAX_CELLS_PER_ROW]
        if _text(cell, max_chars=_MAX_CELL_CHARS)
    ]


def _text(value: Any, *, max_chars: int) -> str:
    return str(value or "").strip()[:max_chars]


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_PAGE_EXTRACTION_SCRIPT = r"""
() => {
  const MAX_TABLES = 20;
  const MAX_ROWS_PER_TABLE = 80;
  const MAX_CELLS_PER_ROW = 24;
  const MAX_BODY_CHARS = 120000;
  const MAX_CELL_CHARS = 500;
  const MAX_TITLE_CHARS = 300;
  const root =
    document.querySelector('#js_content') ||
    document.querySelector('.rich_media_content') ||
    document.body;

  const cleanText = (value, maxChars = MAX_CELL_CHARS) =>
    String(value || '')
      .replace(/\u00a0/g, ' ')
      .replace(/[ \t\r\f\v]+/g, ' ')
      .replace(/\n{3,}/g, '\n\n')
      .trim()
      .slice(0, maxChars);

  const elementText = (element, maxChars = MAX_CELL_CHARS) =>
    cleanText(element ? element.innerText || element.textContent || '' : '', maxChars);

  const directCells = (row) =>
    Array.from(row.children)
      .filter((child) => /^(TD|TH)$/i.test(child.tagName || ''))
      .map((cell) => elementText(cell))
      .filter(Boolean)
      .slice(0, MAX_CELLS_PER_ROW);

  const rowLooksLikeHeader = (row) => {
    const joined = row.join('');
    const tokens = ['净重', '价差', '昨日', '今日', '涨跌', '涨/落', '涨落', '规格', '毛重', '含包装价', '单价', '价格', '装车', '到户'];
    const hits = tokens.filter((token) => joined.includes(token)).length;
    return row.length >= 2 && hits >= 2;
  };

  const nearbyTexts = (table) => {
    const texts = [];
    let node = table;
    for (let depth = 0; depth < 4 && node; depth += 1) {
      let prev = node.previousElementSibling;
      let hops = 0;
      while (prev && hops < 4) {
        const text = elementText(prev, MAX_TITLE_CHARS);
        if (text) {
          texts.push(text);
        }
        prev = prev.previousElementSibling;
        hops += 1;
      }
      node = node.parentElement;
    }
    return texts;
  };

  const inferTitle = (table, nearby) => {
    const caption = table.querySelector('caption');
    const captionText = elementText(caption, MAX_TITLE_CHARS);
    if (captionText) {
      return captionText;
    }
    return nearby.find((text) => text && !/^\d+$/.test(text)) || '';
  };

  const quoteBasisFrom = (text) => {
    const match = text.match(/\d+\s*枚\s*\/\s*箱/);
    return match ? match[0].replace(/\s+/g, '') : '';
  };

  const tables = Array.from(root.querySelectorAll('table'))
    .slice(0, MAX_TABLES)
    .map((table, idx) => {
      const domRows = Array.from(table.querySelectorAll('tr'));
      const rawRows = domRows
        .map((row) => directCells(row))
        .filter((row) => row.length > 0);
      let headers = [];
      let dataRows = rawRows;
      if (rawRows.length > 0 && rowLooksLikeHeader(rawRows[0])) {
        headers = rawRows[0];
        dataRows = rawRows.slice(1);
      }

      const nearby = nearbyTexts(table);
      const tableText = elementText(table, MAX_BODY_CHARS);
      const contextText = [tableText, ...nearby].join('\n');
      const quoteBasis = quoteBasisFrom(contextText);
      return {
        source_table_index: idx,
        title: inferTitle(table, nearby),
        context: quoteBasis ? { quote_basis: quoteBasis } : {},
        headers,
        rows: dataRows.slice(0, MAX_ROWS_PER_TABLE),
      };
    });

  const large_images = Array.from(root.querySelectorAll('img'))
    .map((img, idx) => ({
      source_image_index: idx,
      width: Number(img.naturalWidth || img.width || img.getAttribute('width') || 0),
      height: Number(img.naturalHeight || img.height || img.getAttribute('height') || 0),
    }))
    .filter((img) => img.width >= 600 || img.height >= 600);

  return {
    body_text: elementText(root, MAX_BODY_CHARS),
    tables,
    large_images,
  };
}
"""
