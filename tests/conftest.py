from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def default_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEINSIGHT_MYSQL_PASSWORD", "weinsight_dev")
    monkeypatch.setenv("WEINSIGHT_ENV", "test")
