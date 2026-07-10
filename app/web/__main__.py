from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from app.core.config import load_config
from app.web.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="weinsight-web")
    parser.add_argument("--config", default="config/config.dev.yaml")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    app = create_app(config)
    app.state.auth_service.ensure_bootstrap_admin()
    uvicorn.run(app, host=config.web.host, port=config.web.port)


if __name__ == "__main__":
    main()
