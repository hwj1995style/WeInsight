from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "windows" / "start_admin_test_stack.ps1"
E2E = ROOT / "tests" / "e2e" / "test_admin_smoke.py"
CONFTEST = ROOT / "tests" / "e2e" / "conftest.py"


def test_test_stack_fails_closed_before_starting_processes() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    first_start = content.index("$process = Start-Process")
    for gate in ("app.env=dev", "collector_mode=fake", "Web host must be loopback", "MySQL must be loopback", "Production-like database name rejected"):
        assert content.index(gate) < first_start
    assert "-WindowStyle Hidden" in content
    for module in ("app.web", "app.workers.collector_main", "app.workers.pipeline_main"):
        assert module in content
    assert "Stop-Process -Name" not in content
    assert "start_time_utc" in content
    assert "runtime\\test\\admin_stack" in content


def test_e2e_is_opt_in_loopback_only_and_covers_main_flow() -> None:
    conftest = CONFTEST.read_text(encoding="utf-8")
    smoke = E2E.read_text(encoding="utf-8")
    for marker in ("WEINSIGHT_ADMIN_E2E", "127.0.0.1", "localhost", "::1", "pytest.skip"):
        assert marker in conftest
    for marker in ("admin123456", "E2E-", "/sources/groups/new", "/jobs/new", "停止任务", "/reports", "临时版", "390"):
        assert marker in smoke
    assert "pageerror" in smoke and "console" in smoke
