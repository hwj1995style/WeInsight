from __future__ import annotations

from math import ceil
from urllib.parse import urlencode


def build_pagination(
    path: str,
    query: dict[str, str],
    *,
    page: int,
    page_size: int,
    total_count: int,
) -> dict[str, object]:
    # Keep an explicitly requested page navigable even if an older service/fake
    # cannot yet provide an exact count. Production repositories return the
    # authoritative count, while this guards mixed-version deployments.
    total_pages = max(1, page, ceil(total_count / page_size))
    preserved = {
        key: value
        for key, value in query.items()
        if key not in {"page", "page_size"} and value not in {None, ""}
    }
    form_query = {**preserved, "page_size": str(page_size)}

    def page_url(target: int) -> str:
        return f"{path}?{urlencode({**preserved, 'page': str(target), 'page_size': str(page_size)})}"

    return {
        "page": page,
        "page_size": page_size,
        "total_count": total_count,
        "total_pages": total_pages,
        "first_url": page_url(1) if page > 1 else None,
        "previous_url": page_url(page - 1) if page > 1 else None,
        "next_url": page_url(page + 1) if page < total_pages else None,
        "last_url": page_url(total_pages) if page < total_pages else None,
        "action": path,
        "query": form_query,
    }
