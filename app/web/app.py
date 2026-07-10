from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import Config
from app.security.passwords import PasswordHasher
from app.services.auth_service import AuthService
from app.storage.admin_auth_repo import MysqlAdminAuthRepo
from app.storage.db import create_mysql_engine
from app.web.middleware import AdminSessionMiddleware
from app.web.routes import auth


WEB_DIR = Path(__file__).resolve().parent


def create_app(config: Config, auth_service: AuthService | None = None) -> FastAPI:
    app = FastAPI(title="WeInsight Admin", docs_url=None, redoc_url=None)
    app.state.config = config
    app.state.auth_service = auth_service or _build_auth_service(config)
    app.add_middleware(AdminSessionMiddleware)
    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )
    app.include_router(auth.router)
    return app


def _build_auth_service(config: Config) -> AuthService:
    engine = create_mysql_engine(config.mysql)
    return AuthService(
        MysqlAdminAuthRepo(engine),
        PasswordHasher(),
        config.auth,
    )
