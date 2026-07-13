from pathlib import Path
import subprocess

import pytest
from fastapi import FastAPI

from test_web_dashboard import (
    authenticated_client,
    config,
    dashboard_service,
    raw_client,
    FakeAuthService,
)
from test_web_runtime import FakeRuntimeMonitorService
from app.web.app import create_app


@pytest.fixture
def runtime_service():
    return FakeRuntimeMonitorService()


@pytest.fixture
def app(config, dashboard_service, runtime_service) -> FastAPI:
    return create_app(
        config,
        auth_service=FakeAuthService(),
        dashboard_service=dashboard_service,
        runtime_monitor_service=runtime_service,
    )


@pytest.mark.parametrize(
    "path",
    (
        "/dashboard", "/sources/groups", "/sources/articles", "/jobs",
        "/runs", "/events", "/workers", "/results/groups", "/reports",
    ),
)
def test_admin_pages_use_shared_direction_a_shell(authenticated_client, path):
    response = authenticated_client.get(path)

    assert response.status_code == 200
    for fragment in ('class="app-shell"', 'class="sidebar"', 'class="top-toolbar"'):
        assert fragment in response.text
    for unsafe_copy in ("security-warning", "默认密码", "admin123456"):
        assert unsafe_copy not in response.text


def test_login_does_not_advertise_default_credentials(raw_client):
    response = raw_client.get("/login")

    assert response.status_code == 200
    for unsafe_copy in ("默认账号", "默认密码", "修改默认密码", "admin123456"):
        assert unsafe_copy not in response.text


def test_account_and_editor_pages_use_shared_heading_and_actions():
    paths = (
        "app/web/templates/home.html",
        "app/web/templates/sources/group_form.html",
        "app/web/templates/sources/article_form.html",
        "app/web/templates/jobs/form.html",
    )
    for path in paths:
        text = Path(path).read_text("utf-8")
        assert 'class="page-heading' in text, path
        assert 'class="form-actions"' in text, path


def test_direction_a_tokens_and_components_are_declared():
    css = Path("app/web/static/app.css").read_text("utf-8")
    for token in (
        "--color-sidebar:", "--color-workspace:", "--color-surface:",
        "--color-sidebar-border:",
        "--color-accent:", "--color-success:", "--color-warning:",
        "--color-danger:", "--radius-panel:", "--shadow-panel:",
    ):
        assert token in css
    assert "linear-gradient" not in css
    assert "backdrop-filter" not in css


def test_direction_a_shared_components_and_control_sizes_are_declared():
    css = Path("app/web/static/app.css").read_text("utf-8")
    for selector in (
        ".content-panel {", ".kpi-card {", ".data-table {",
        ".filter-panel {", ".notice {", ".job-status {",
    ):
        assert selector in css
    assert "button, .button { min-height: 40px;" in css
    assert 'input:not([type="hidden"]) { width: 100%; min-height: 42px;' in css
    assert ".data-table th, .data-table td { height: 46px;" in css
    assert ".filter-panel button { min-height: 40px;" in css
    assert ".report-request-form button { min-height: 40px;" in css
    assert ".button.compact, button.compact { min-height: 40px;" in css


def test_base_template_contains_professional_sidebar_shell():
    text = Path("app/web/templates/base.html").read_text("utf-8")
    for fragment in (
        'class="app-shell"', 'class="sidebar"', 'id="sidebar-toggle"',
        'id="mobile-nav-toggle"', 'id="nav-backdrop"',
        'src="/static/app-shell.js"', 'aria-label="主要导航"',
    ):
        assert fragment in text


def test_app_shell_script_persists_and_closes_navigation():
    script = Path("app/web/static/app-shell.js").read_text("utf-8")
    assert "weinsight.sidebar.v1" in script
    assert "localStorage" in script
    assert "Escape" in script
    assert "aria-expanded" in script


def test_responsive_shell_css_has_desktop_tablet_and_mobile_boundaries():
    css = Path("app/web/static/app.css").read_text("utf-8")
    assert "@media (max-width: 980px)" in css
    assert "@media (max-width: 720px)" in css
    assert ".app-shell.nav-open .sidebar" in css
    assert ".table-scroll { overflow-x: auto;" in css
    assert "prefers-reduced-motion" in css


def test_e2e_proves_mobile_keyboard_console_and_navigation_contracts():
    test = Path("tests/e2e/test_admin_smoke.py").read_text("utf-8")
    for evidence in (
        'item.type in {"warning", "error"}',
        'document.activeElement.id',
        'get_by_role("link", name="总览")',
        'not_to_have_class(re.compile(r".*nav-open.*"))',
        'assert console == []',
    ):
        assert evidence in test


def test_storage_failures_do_not_disable_interactions_and_toggle_label():
    app_shell = Path("app/web/static/app-shell.js").resolve().as_posix()
    harness = f"""
const assert = require('node:assert/strict');
class Element {{
  constructor() {{ this.attrs = {{}}; this.listeners = {{}}; this.dataset = {{ sidebarState: 'expanded' }}; this.hidden = true; this.classList = {{ values: new Set(), add: x => this.classList.values.add(x), remove: x => this.classList.values.delete(x) }}; }}
  setAttribute(name, value) {{ this.attrs[name] = value; }}
  addEventListener(name, handler) {{ this.listeners[name] = handler; }}
  querySelectorAll() {{ return [link]; }}
}}
const shell = new Element(); const sidebar = new Element(); const desktop = new Element();
const mobile = new Element(); const backdrop = new Element(); const link = new Element();
const documentListeners = {{}};
global.document = {{
  querySelector: () => shell,
  getElementById: id => ({{ 'app-sidebar': sidebar, 'sidebar-toggle': desktop, 'mobile-nav-toggle': mobile, 'nav-backdrop': backdrop }})[id],
  addEventListener: (name, handler) => {{ documentListeners[name] = handler; }},
}};
global.localStorage = {{ getItem() {{ throw new Error('blocked'); }}, setItem() {{ throw new Error('blocked'); }} }};
require('{app_shell}');
assert.equal(shell.dataset.sidebarState, 'expanded');
assert.equal(desktop.attrs['aria-label'], '折叠侧栏');
desktop.listeners.click();
assert.equal(shell.dataset.sidebarState, 'collapsed');
assert.equal(desktop.attrs['aria-label'], '展开侧栏');
mobile.listeners.click();
assert.equal(mobile.attrs['aria-expanded'], 'true');
assert.equal(backdrop.hidden, false);
documentListeners.keydown({{ key: 'Escape' }});
assert.equal(mobile.attrs['aria-expanded'], 'false');
mobile.listeners.click(); link.listeners.click();
assert.equal(mobile.attrs['aria-expanded'], 'false');
"""
    subprocess.run(["node", "-e", harness], check=True, capture_output=True, text=True)
