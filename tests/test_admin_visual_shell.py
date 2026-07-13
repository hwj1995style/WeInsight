from pathlib import Path


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
