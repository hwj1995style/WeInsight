from __future__ import annotations

import hashlib
from pathlib import Path


VENDOR_DIR = Path("app/web/static/vendor")
EXPECTED_SHA256 = {
    "htmx.min.js": "e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447",
    "echarts.min.js": "bf4a223524e40b77c304bec67e1222cf551f14880cf42c69dc046558e11c07b1",
}


def test_vendor_scripts_are_real_fixed_release_assets() -> None:
    htmx = VENDOR_DIR / "htmx.min.js"
    echarts = VENDOR_DIR / "echarts.min.js"

    assert htmx.stat().st_size > 40_000
    assert echarts.stat().st_size > 900_000
    assert 'version:"2.0.4"' in htmx.read_text(encoding="utf-8")
    assert "Apache License" in echarts.read_text(encoding="utf-8")[:1_000]
    assert "5.6.0" in echarts.read_text(encoding="utf-8")
    for filename, expected in EXPECTED_SHA256.items():
        assert hashlib.sha256((VENDOR_DIR / filename).read_bytes()).hexdigest() == expected


def test_readme_records_vendor_versions_hashes_sources_and_licenses() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    for filename in EXPECTED_SHA256:
        payload = (VENDOR_DIR / filename).read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        assert digest in readme
    assert "HTMX 2.0.4" in readme
    assert "BSD 2-Clause" in readme
    assert "Apache License 2.0" in readme
    assert "ECharts 5.6.0" in readme
    assert "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js" in readme
    assert "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.min.js" in readme
