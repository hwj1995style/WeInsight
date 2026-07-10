from __future__ import annotations

from pathlib import Path


def read_init_sql() -> str:
    return Path("sql/init.sql").read_text(encoding="utf-8")
