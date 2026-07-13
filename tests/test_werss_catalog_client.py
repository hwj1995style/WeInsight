from __future__ import annotations

import logging

import httpx
import pytest

import app.integrations.werss_catalog as werss_catalog
from app.integrations.werss_catalog import (
    WeRSSCatalogClient,
    WeRSSCatalogError,
    WeRSSCatalogItem,
)


BASE_URL = "http://127.0.0.1:8001"
ACCESS_KEY = "WK-test-sensitive"
SECRET_KEY = "SK-test-sensitive"


def response(items, *, total=None, offset=0, limit=100, status_code=200):
    if total is None:
        total = len(items)
    return httpx.Response(
        status_code,
        json={
            "code": 0,
            "data": {
                "list": items,
                "total": total,
                "page": {"limit": limit, "offset": offset, "total": total},
            },
        },
    )


def client_for(handler) -> WeRSSCatalogClient:
    return WeRSSCatalogClient(
        BASE_URL,
        ACCESS_KEY,
        SECRET_KEY,
        transport=httpx.MockTransport(handler),
    )


def assert_error(client, code: str, caplog=None) -> None:
    with pytest.raises(WeRSSCatalogError) as caught:
        client.fetch_all()
    assert caught.value.code == code
    assert str(caught.value) == code
    exposed = str(caught.value) + (caplog.text if caplog is not None else "")
    assert ACCESS_KEY not in exposed
    assert SECRET_KEY not in exposed
    assert "response-secret-body" not in exposed


def test_fetches_all_pages_with_fixed_get_and_ak_sk_header() -> None:
    seen = []

    def handler(request):
        seen.append(request)
        offset = int(request.url.params["offset"])
        items = [
            {"id": f"MP{index}", "mp_name": f"公众号{index}", "status": index % 2}
            for index in range(offset, min(offset + 100, 101))
        ]
        return response(items, total=101, offset=offset)

    items = client_for(handler).fetch_all()

    assert len(items) == 101
    assert items[0] == WeRSSCatalogItem("MP0", "公众号0", False)
    assert items[-1] == WeRSSCatalogItem("MP100", "公众号100", False)
    assert [request.method for request in seen] == ["GET", "GET"]
    assert [request.url.path for request in seen] == ["/api/v1/wx/mps"] * 2
    assert [request.url.params["limit"] for request in seen] == ["100", "100"]
    assert [request.url.params["offset"] for request in seen] == ["0", "100"]
    assert all(request.headers["Authorization"] == f"AK-SK {ACCESS_KEY}:{SECRET_KEY}" for request in seen)


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failures_have_stable_safe_error(status_code, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    assert_error(
        client_for(lambda request: httpx.Response(status_code, text="response-secret-body")),
        "werss_catalog_auth_failed",
        caplog,
    )


def test_timeout_has_stable_safe_error(caplog) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request):
        raise httpx.ReadTimeout("response-secret-body", request=request)

    assert_error(client_for(handler), "werss_catalog_timeout", caplog)


@pytest.mark.parametrize("status_code", [302, 500, 503])
def test_redirects_and_server_failures_are_unavailable(status_code, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    headers = {"location": "https://other.example/api"} if status_code == 302 else {}
    assert_error(
        client_for(lambda request: httpx.Response(status_code, headers=headers, text="response-secret-body")),
        "werss_catalog_unavailable",
        caplog,
    )


def test_response_over_one_mib_is_invalid_and_safe(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    body = b'{"response-secret-body":"' + b"x" * 1_048_576 + b'"}'
    assert_error(
        client_for(lambda request: httpx.Response(200, content=body)),
        "werss_catalog_invalid",
        caplog,
    )


def test_oversized_stream_chunk_is_rejected_before_accumulator_retains_it(monkeypatch) -> None:
    retained_sizes = []

    class GuardedBuffer(bytearray):
        def extend(self, value) -> None:
            retained_sizes.append(len(value))
            if len(self) + len(value) > 1_048_576:
                raise AssertionError("oversized chunk was retained before validation")
            super().extend(value)

    monkeypatch.setattr(werss_catalog, "bytearray", GuardedBuffer, raising=False)
    oversized_chunk = b"x" * (1_048_576 + 1)

    assert_error(
        client_for(lambda request: httpx.Response(200, content=oversized_chunk)),
        "werss_catalog_invalid",
    )
    assert retained_sizes
    assert max(retained_sizes) <= 65_536
    assert sum(retained_sizes) <= 1_048_576


@pytest.mark.parametrize(
    "item",
    [
        {"id": "", "mp_name": "name", "status": 1},
        {"id": "   ", "mp_name": "name", "status": 1},
        {"id": "MP1", "mp_name": "", "status": 1},
        {"id": "MP1", "mp_name": "\t", "status": 1},
        {"id": "MP1", "mp_name": "name", "status": 2},
        {"id": 1, "mp_name": "name", "status": 1},
        {"id": "MP1", "mp_name": "name", "status": True},
        {"id": "MP1", "mp_name": "name", "status": 1.0},
    ],
)
def test_invalid_item_fields_fail_closed(item) -> None:
    assert_error(client_for(lambda request: response([item])), "werss_catalog_invalid")


def test_duplicate_ids_fail_closed() -> None:
    item = {"id": "MP1", "mp_name": "name", "status": 1}
    assert_error(client_for(lambda request: response([item, item])), "werss_catalog_invalid")


def test_more_than_one_thousand_sources_fail_closed() -> None:
    def handler(request):
        offset = int(request.url.params["offset"])
        items = [
            {"id": f"MP{index}", "mp_name": f"name{index}", "status": 1}
            for index in range(offset, min(offset + 100, 1001))
        ]
        return response(items, total=1001, offset=offset)

    assert_error(client_for(handler), "werss_catalog_invalid")


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 1, "data": {}},
        {"code": 0, "data": {"list": "not-a-list", "total": 0, "page": {}}},
        {"code": 0, "data": {"list": [], "total": 0, "page": {"limit": 99, "offset": 0, "total": 0}}},
    ],
)
def test_malformed_envelope_is_invalid(payload) -> None:
    assert_error(
        client_for(lambda request: httpx.Response(200, json=payload)),
        "werss_catalog_invalid",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit", 100.0),
        ("limit", True),
        ("offset", 0.0),
        ("offset", False),
        ("total", 1.0),
        ("total", True),
    ],
)
def test_page_metadata_requires_exact_non_boolean_integers(field, value) -> None:
    item = {"id": "MP1", "mp_name": "name", "status": 1}
    payload = {
        "code": 0,
        "data": {
            "list": [item],
            "total": 1,
            "page": {"limit": 100, "offset": 0, "total": 1, field: value},
        },
    }
    assert_error(
        client_for(lambda request: httpx.Response(200, json=payload)),
        "werss_catalog_invalid",
    )


@pytest.mark.parametrize("total", [1.0, True])
def test_top_level_total_requires_exact_non_boolean_integer(total) -> None:
    item = {"id": "MP1", "mp_name": "name", "status": 1}
    payload = {
        "code": 0,
        "data": {
            "list": [item],
            "total": total,
            "page": {"limit": 100, "offset": 0, "total": total},
        },
    }
    assert_error(
        client_for(lambda request: httpx.Response(200, json=payload)),
        "werss_catalog_invalid",
    )


def test_total_mismatch_is_incomplete() -> None:
    item = {"id": "MP1", "mp_name": "name", "status": 1}

    def handler(request):
        offset = int(request.url.params["offset"])
        return response([item] if offset == 0 else [], total=2, offset=offset)

    assert_error(
        client_for(handler),
        "werss_catalog_incomplete",
    )
