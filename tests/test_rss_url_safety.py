import pytest

from app.rss.url_safety import FeedUrlBlocked, validate_feed_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/feed",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/feed",
    ],
)
def test_validate_feed_url_blocks_unsafe_targets(url):
    with pytest.raises(FeedUrlBlocked):
        validate_feed_url(url, resolver=lambda _: ["93.184.216.34"])


def test_validate_feed_url_blocks_private_dns_answer():
    with pytest.raises(FeedUrlBlocked) as exc:
        validate_feed_url("https://feed.example/rss", resolver=lambda _: ["10.0.0.8"])
    assert exc.value.code == "feed_url_blocked"


def test_validate_feed_url_normalizes_public_url():
    result = validate_feed_url(
        " HTTPS://feed.example?format=rss#section ",
        resolver=lambda _: ["93.184.216.34"],
    )
    assert result == "https://feed.example/?format=rss"


@pytest.mark.parametrize(
    "url",
    ["https://user:secret@feed.example/rss", "https://feed.example:8080/rss"],
)
def test_validate_feed_url_blocks_credentials_and_unapproved_ports(url):
    with pytest.raises(FeedUrlBlocked) as exc:
        validate_feed_url(url, resolver=lambda _: ["93.184.216.34"])
    assert exc.value.code == "feed_url_blocked"


def test_validate_feed_url_allows_only_exact_configured_endpoint():
    result = validate_feed_url(
        "http://127.0.0.1:8001/feed",
        resolver=lambda _: ["127.0.0.1"],
        allowed_endpoint=("127.0.0.1", 8001),
    )
    assert result == "http://127.0.0.1:8001/feed"

    for target in ("http://127.0.0.1/feed", "http://127.0.0.2:8001/feed"):
        with pytest.raises(FeedUrlBlocked):
            validate_feed_url(
                target,
                resolver=lambda _: ["127.0.0.1"],
                allowed_endpoint=("127.0.0.1", 8001),
            )


def test_redirect_validation_does_not_inherit_endpoint_exception():
    with pytest.raises(FeedUrlBlocked):
        validate_feed_url(
            "http://127.0.0.1:8001/private",
            resolver=lambda _: ["127.0.0.1"],
        )
