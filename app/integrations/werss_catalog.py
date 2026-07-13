from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


_CATALOG_PATH = "/api/v1/wx/mps"
_PAGE_LIMIT = 100
_MAX_SOURCES = 1000
_MAX_RESPONSE_BYTES = 1_048_576
_READ_CHUNK_BYTES = 65_536
_VALID_ERROR_CODES = frozenset(
    {
        "werss_catalog_auth_failed",
        "werss_catalog_timeout",
        "werss_catalog_unavailable",
        "werss_catalog_invalid",
        "werss_catalog_incomplete",
    }
)


@dataclass(frozen=True)
class WeRSSCatalogItem:
    source_id: str
    name: str
    enabled: bool


class WeRSSCatalogError(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in _VALID_ERROR_CODES:
            raise ValueError("invalid WeRSS catalog error code")
        super().__init__(code)
        self.code = code


class WeRSSCatalogClient:
    def __init__(
        self,
        base_url: str,
        access_key: str,
        secret_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self._base_url = base_url
        self._authorization = f"AK-SK {access_key}:{secret_key}"
        self._transport = transport
        self._timeout = timeout_seconds

    def fetch_all(self) -> tuple[WeRSSCatalogItem, ...]:
        items: list[WeRSSCatalogItem] = []
        seen_ids: set[str] = set()
        expected_total: int | None = None
        offset = 0

        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                while expected_total is None or len(items) < expected_total:
                    payload = self._request_page(client, offset)
                    page_items, total = self._validate_page(payload, offset, expected_total)
                    if total > _MAX_SOURCES:
                        raise WeRSSCatalogError("werss_catalog_invalid")
                    expected_total = total

                    if not page_items and len(items) < total:
                        raise WeRSSCatalogError("werss_catalog_incomplete")
                    for raw_item in page_items:
                        item = self._convert_item(raw_item)
                        if item.source_id in seen_ids:
                            raise WeRSSCatalogError("werss_catalog_invalid")
                        seen_ids.add(item.source_id)
                        items.append(item)
                        if len(items) > total or len(items) > _MAX_SOURCES:
                            raise WeRSSCatalogError("werss_catalog_incomplete")
                    offset += len(page_items)
        except WeRSSCatalogError:
            raise
        except httpx.TimeoutException:
            raise WeRSSCatalogError("werss_catalog_timeout") from None
        except httpx.HTTPError:
            raise WeRSSCatalogError("werss_catalog_unavailable") from None
        except (TypeError, ValueError, KeyError):
            raise WeRSSCatalogError("werss_catalog_invalid") from None

        if expected_total is None or len(items) != expected_total:
            raise WeRSSCatalogError("werss_catalog_incomplete")
        return tuple(items)

    def _request_page(self, client: httpx.Client, offset: int) -> Any:
        url = f"{self._base_url}{_CATALOG_PATH}"
        with client.stream(
            "GET",
            url,
            params={"limit": _PAGE_LIMIT, "offset": offset},
            headers={"Authorization": self._authorization},
        ) as response:
            if response.status_code in {401, 403}:
                raise WeRSSCatalogError("werss_catalog_auth_failed")
            if response.is_redirect or response.status_code >= 400:
                raise WeRSSCatalogError("werss_catalog_unavailable")

            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=_READ_CHUNK_BYTES):
                remaining = _MAX_RESPONSE_BYTES - len(body)
                if len(chunk) > remaining:
                    raise WeRSSCatalogError("werss_catalog_invalid")
                body.extend(chunk)
        try:
            return httpx.Response(200, content=bytes(body)).json()
        except ValueError:
            raise WeRSSCatalogError("werss_catalog_invalid") from None

    @staticmethod
    def _validate_page(
        payload: Any,
        offset: int,
        expected_total: int | None,
    ) -> tuple[list[Any], int]:
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise WeRSSCatalogError("werss_catalog_invalid")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise WeRSSCatalogError("werss_catalog_invalid")
        raw_items = data.get("list")
        total = data.get("total")
        page = data.get("page")
        page_limit = page.get("limit") if isinstance(page, dict) else None
        page_offset = page.get("offset") if isinstance(page, dict) else None
        page_total = page.get("total") if isinstance(page, dict) else None
        if (
            not isinstance(raw_items, list)
            or len(raw_items) > _PAGE_LIMIT
            or not WeRSSCatalogClient._is_exact_int(total)
            or total < 0
            or not isinstance(page, dict)
            or not WeRSSCatalogClient._is_exact_int(page_limit)
            or page_limit != _PAGE_LIMIT
            or not WeRSSCatalogClient._is_exact_int(page_offset)
            or page_offset != offset
            or not WeRSSCatalogClient._is_exact_int(page_total)
            or page_total != total
        ):
            raise WeRSSCatalogError("werss_catalog_invalid")
        if expected_total is not None and total != expected_total:
            raise WeRSSCatalogError("werss_catalog_incomplete")
        return raw_items, total

    @staticmethod
    def _is_exact_int(value: Any) -> bool:
        return type(value) is int

    @staticmethod
    def _convert_item(raw_item: Any) -> WeRSSCatalogItem:
        if not isinstance(raw_item, dict):
            raise WeRSSCatalogError("werss_catalog_invalid")
        source_id = raw_item.get("id")
        name = raw_item.get("mp_name")
        status = raw_item.get("status")
        if (
            not isinstance(source_id, str)
            or not source_id.strip()
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(status, int)
            or isinstance(status, bool)
            or status not in {0, 1}
        ):
            raise WeRSSCatalogError("werss_catalog_invalid")
        return WeRSSCatalogItem(source_id, name, status == 1)
