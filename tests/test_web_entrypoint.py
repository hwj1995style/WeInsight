from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _fresh_entrypoint():
    sys.modules.pop("app.web.__main__", None)
    return importlib.import_module("app.web.__main__")


def test_web_entrypoint_import_has_no_runtime_side_effects_or_rpa_imports(
) -> None:
    script = """
import builtins
import json
import sys

imported = []
real_import = builtins.__import__

def tracked_import(name, *args, **kwargs):
    imported.append(name)
    return real_import(name, *args, **kwargs)

builtins.__import__ = tracked_import
import app.web.__main__ as entrypoint
forbidden = [
    name for name in imported
    if name == "app.main"
    or name.startswith(("app.rpa", "app.worker", "app.workers"))
]
print(json.dumps({
    "callable": callable(entrypoint.main),
    "forbidden": forbidden,
    "rpa_loaded": "app.rpa.desktop_probe" in sys.modules,
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    observed = json.loads(result.stdout)

    assert observed == {
        "callable": True,
        "forbidden": [],
        "rpa_loaded": False,
    }


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
        web=SimpleNamespace(
            host="127.0.0.8",
            port=8765,
            secure_cookie=False,
            tls_certfile=None,
            tls_keyfile=None,
        ),
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

    def fake_uvicorn_run(
        received_app,
        *,
        host: str,
        port: int,
        ssl_certfile: str | None,
        ssl_keyfile: str | None,
    ) -> None:
        calls.append(
            (
                "uvicorn.run",
                received_app,
                host,
                port,
                ssl_certfile,
                ssl_keyfile,
            )
        )

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
        (
            "uvicorn.run",
            app,
            config.web.host,
            config.web.port,
            None,
            None,
        ),
    ]


def test_web_entrypoint_passes_tls_paths_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint = _fresh_entrypoint()
    config = SimpleNamespace(
        web=SimpleNamespace(
            host="10.20.30.40",
            port=8848,
            secure_cookie=True,
            tls_certfile="C:/certs/weinsight.crt",
            tls_keyfile="C:/certs/weinsight.key",
        ),
    )
    app = SimpleNamespace(
        state=SimpleNamespace(
            auth_service=SimpleNamespace(ensure_bootstrap_admin=lambda: None),
        ),
    )
    uvicorn_calls: list[tuple[object, dict[str, object]]] = []

    monkeypatch.setattr(entrypoint, "load_config", lambda path: config)
    monkeypatch.setattr(entrypoint, "create_app", lambda received: app)
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        lambda received, **kwargs: uvicorn_calls.append((received, kwargs)),
    )
    monkeypatch.setattr(sys, "argv", ["weinsight-web"])

    entrypoint.main()

    assert uvicorn_calls == [
        (
            app,
            {
                "host": "10.20.30.40",
                "port": 8848,
                "ssl_certfile": "C:/certs/weinsight.crt",
                "ssl_keyfile": "C:/certs/weinsight.key",
            },
        )
    ]


def test_web_entrypoint_rejects_secure_cookie_without_tls_before_app_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entrypoint = _fresh_entrypoint()
    private_key_marker = "PRIVATE_KEY_CONTENT_MUST_NOT_LEAK"
    config = SimpleNamespace(
        web=SimpleNamespace(
            host="10.20.30.40",
            port=8848,
            secure_cookie=True,
            tls_certfile=None,
            tls_keyfile=private_key_marker,
        ),
    )
    actions: list[str] = []

    monkeypatch.setattr(entrypoint, "load_config", lambda path: config)
    monkeypatch.setattr(
        entrypoint,
        "create_app",
        lambda received: actions.append("create_app"),
    )
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        lambda *args, **kwargs: actions.append("uvicorn.run"),
    )
    monkeypatch.setattr(sys, "argv", ["weinsight-web"])

    with pytest.raises(RuntimeError) as exc_info:
        entrypoint.main()

    assert str(exc_info.value) == "secure_cookie requires TLS certificate and key"
    assert private_key_marker not in str(exc_info.value)
    assert actions == []
