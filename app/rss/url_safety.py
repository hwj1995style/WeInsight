"""Validation boundary for URLs fetched by the RSS client."""

from __future__ import annotations

import socket
from collections.abc import Callable, Sequence
from ipaddress import ip_address
from urllib.parse import urlsplit, urlunsplit


class FeedUrlBlocked(ValueError):
    """Raised when a feed URL is unsafe to fetch."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def resolve_host(host: str) -> Sequence[str]:
    """Resolve all addresses for a host without initiating a connection."""
    return tuple({item[4][0] for item in socket.getaddrinfo(host, None)})


def _is_forbidden(address: str) -> bool:
    value = ip_address(address)
    return any(
        (
            value.is_private,
            value.is_loopback,
            value.is_link_local,
            value.is_multicast,
            value.is_reserved,
            value.is_unspecified,
        )
    )


def validate_feed_url(
    url: str,
    *,
    resolver: Callable[[str], Sequence[str]] = resolve_host,
    allowed_endpoint: tuple[str, int] | None = None,
) -> str:
    """Return a normalized fetchable HTTP(S) URL or fail closed."""
    try:
        parsed = urlsplit(url.strip())
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
    except (AttributeError, TypeError, ValueError):
        raise FeedUrlBlocked("feed_url_blocked") from None

    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise FeedUrlBlocked("feed_url_blocked")

    host = hostname.lower()
    exact_exception = allowed_endpoint is not None and (
        allowed_endpoint[0].lower(), allowed_endpoint[1]
    ) == (host, port)
    if port not in {80, 443} and not exact_exception:
        raise FeedUrlBlocked("feed_url_blocked")

    if not exact_exception:
        try:
            literal_addresses = [host] if _is_ip_address(host) else []
            addresses = literal_addresses or list(resolver(host))
            if not addresses or any(_is_forbidden(address) for address in addresses):
                raise FeedUrlBlocked("feed_url_blocked")
        except FeedUrlBlocked:
            raise
        except (OSError, ValueError):
            raise FeedUrlBlocked("feed_url_blocked") from None

    return urlunsplit((scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _is_ip_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True
