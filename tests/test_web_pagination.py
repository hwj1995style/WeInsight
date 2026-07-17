from app.web.pagination import build_pagination


def test_pagination_supports_first_last_and_direct_page_jump() -> None:
    pagination = build_pagination(
        "/events",
        {"level": "error", "page_size": "50"},
        page=3,
        page_size=50,
        total_count=501,
    )

    assert pagination["total_pages"] == 11
    assert pagination["first_url"] == "/events?level=error&page=1&page_size=50"
    assert pagination["previous_url"] == "/events?level=error&page=2&page_size=50"
    assert pagination["next_url"] == "/events?level=error&page=4&page_size=50"
    assert pagination["last_url"] == "/events?level=error&page=11&page_size=50"
    assert pagination["action"] == "/events"
    assert pagination["query"] == {"level": "error", "page_size": "50"}


def test_pagination_keeps_requested_page_visible_with_legacy_count() -> None:
    pagination = build_pagination(
        "/jobs", {}, page=2, page_size=20, total_count=1
    )

    assert pagination["total_pages"] == 2
    assert pagination["first_url"] == "/jobs?page=1&page_size=20"
    assert pagination["last_url"] is None
