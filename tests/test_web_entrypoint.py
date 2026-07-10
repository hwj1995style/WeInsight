from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _fresh_entrypoint():
    sys.modules.pop("app.web.__main__", None)
    return importlib.import_module("app.web.__main__")


def test_web_entrypoint_import_has_no_runtime_side_effects_or_rpa_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imported: list[str] = []
    actions: list[str] = []
    real_import = builtins.__import__

    def tracked_import(name, *args, **kwargs):
        imported.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", tracked_import)
    sys.modules.pop("app.web.app", None)
    from app.web.app import create_app

    assert callable(create_app)

    config_module = importlib.import_module("app.core.config")
    web_app_module = importlib.import_module("app.web.app")
    uvicorn_module = importlib.import_module("uvicorn")
    monkeypatch.setattr(
        config_module,
        "load_config",
        lambda path: actions.append("load_config"),
    )
    monkeypatch.setattr(
        web_app_module,
        "create_app",
        lambda config: actions.append("create_app"),
    )
    monkeypatch.setattr(
        uvicorn_module,
        "run",
        lambda *args, **kwargs: actions.append("uvicorn.run"),
    )

    entrypoint = _fresh_entrypoint()

    assert callable(entrypoint.main)
    assert actions == []
    assert not any(
        name == "app.main"
        or name.startswith(("app.rpa", "app.worker", "app.workers"))
        for name in imported
    )


@pytest.mark.parametrize(
    ("argv", "expected_config_path"),
    [
        (["weinsight-web"], Path("config/config.dev.yaml")),
        (
            ["weinsight-web", "--config", "config/custom.yaml"],
            Path("config/custom.yaml"),
        ),
    ],
)
def test_web_entrypoint_runs_startup_in_order_with_configured_bind_address(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    expected_config_path: Path,
) -> None:
    entrypoint = _fresh_entrypoint()
    calls: list[tuple[object, ...]] = []
    config = SimpleNamespace(
        web=SimpleNamespace(host="127.0.0.8", port=8765),
    )

    class BootstrapAuthService:
        def ensure_bootstrap_admin(self) -> None:
            raise AssertionError("test must replace bootstrap initialization")

    auth_service = BootstrapAuthService()
    app = SimpleNamespace(
        state=SimpleNamespace(auth_service=auth_service),
    )

    def fake_load_config(path: Path):
        calls.append(("load_config", path))
        return config

    def fake_create_app(received_config):
        calls.append(("create_app", received_config))
        return app

    def fake_ensure_bootstrap_admin() -> None:
        calls.append(("ensure_bootstrap_admin",))

    def fake_uvicorn_run(received_app, *, host: str, port: int) -> None:
        calls.append(("uvicorn.run", received_app, host, port))

    monkeypatch.setattr(entrypoint, "load_config", fake_load_config)
    monkeypatch.setattr(entrypoint, "create_app", fake_create_app)
    monkeypatch.setattr(
        auth_service,
        "ensure_bootstrap_admin",
        fake_ensure_bootstrap_admin,
    )
    monkeypatch.setattr(entrypoint.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(sys, "argv", argv)

    entrypoint.main()

    assert calls == [
        ("load_config", expected_config_path),
        ("create_app", config),
        ("ensure_bootstrap_admin",),
        ("uvicorn.run", app, config.web.host, config.web.port),
    ]
