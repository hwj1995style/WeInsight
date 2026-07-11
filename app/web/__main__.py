from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.core.config import load_config
from app.web.app import create_app


def _validate_secure_tls(config) -> None:
    if not config.web.secure_cookie:
        return
    if not all(
        isinstance(path, str) and bool(path.strip())
        for path in (config.web.tls_certfile, config.web.tls_keyfile)
    ):
        raise RuntimeError("secure_cookie requires TLS certificate and key")


def main() -> None:
    parser = argparse.ArgumentParser(prog="weinsight-web")
    parser.add_argument("--config", default="config/config.dev.yaml")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    _validate_secure_tls(config)
    app = create_app(config)
    app.state.auth_service.ensure_bootstrap_admin()
    uvicorn.run(
        app,
        host=config.web.host,
        port=config.web.port,
        ssl_certfile=config.web.tls_certfile,
        ssl_keyfile=config.web.tls_keyfile,
    )


if __name__ == "__main__":
    main()
