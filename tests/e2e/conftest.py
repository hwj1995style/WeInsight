import os
from urllib.parse import urlparse

import pytest


@pytest.fixture(scope="session")
def admin_base_url() -> str:
    if os.getenv("WEINSIGHT_ADMIN_E2E") != "1":
        pytest.skip("set WEINSIGHT_ADMIN_E2E=1 to run the isolated Fake browser E2E")
    value = os.getenv("WEINSIGHT_ADMIN_BASE_URL", "").rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("WEINSIGHT_ADMIN_BASE_URL must use a loopback host")
    return value
