from __future__ import annotations

import hashlib


def _sha256_join(parts: list[str | None]) -> str:
    normalized = "\u241f".join("" if part is None else str(part).strip() for part in parts)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def group_msg_hash(
    *,
    group_name: str,
    sender_name: str | None,
    msg_time_display: str | None,
    msg_content: str | None,
    msg_type: str | None,
) -> str:
    return _sha256_join([group_name, sender_name, msg_time_display, msg_content, msg_type])


def article_hash(
    *,
    account_name: str,
    title: str | None,
    publish_time: str | None,
    url: str | None,
) -> str:
    return _sha256_join([account_name, title, publish_time, url])
