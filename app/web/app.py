from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import Config
from app.security.passwords import PasswordHasher
from app.services.auth_service import AuthService
from app.services.source_management_service import SourceManagementService
from app.storage.admin_auth_repo import MysqlAdminAuthRepo
from app.storage.article_config_repo import MysqlArticleAccountConfigRepo
from app.storage.db import create_mysql_engine
from app.storage.group_repo import MysqlGroupConfigRepo
from app.storage.source_reference_repo import MysqlSourceReferenceRepo
from app.web.middleware import AdminSessionMiddleware
from app.web.routes import auth, sources
from app.web.routes.auth import LoginAttemptLimiter, MAX_CONCURRENT_LOGIN_HASHES


WEB_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.login_hash_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LOGIN_HASHES)
    try:
        yield
    finally:
        app.state.login_hash_semaphore = None


def create_app(
    config: Config,
    auth_service: AuthService | None = None,
    source_service: SourceManagementService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="WeInsight Admin",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.config = config
    engine = None
    if auth_service is None or source_service is None:
        engine = create_mysql_engine(config.mysql)
    app.state.auth_service = auth_service or _build_auth_service(config, engine)
    app.state.source_service = source_service or _build_source_service(engine)
    app.state.login_attempt_limiter = LoginAttemptLimiter(
        config.auth.login_failure_limit,
        config.auth.login_lock_minutes,
    )
    app.add_middleware(AdminSessionMiddleware)
    app.mount(
        "/static",
        StaticFiles(directory=str(WEB_DIR / "static")),
        name="static",
    )
    app.include_router(auth.router)
    app.include_router(sources.router)
    return app


def _build_auth_service(config: Config, engine) -> AuthService:
    return AuthService(
        MysqlAdminAuthRepo(engine),
        PasswordHasher(),
        config.auth,
    )


def _build_source_service(engine) -> SourceManagementService:
    return SourceManagementService(
        MysqlGroupConfigRepo(engine),
        MysqlArticleAccountConfigRepo(engine),
        MysqlSourceReferenceRepo(engine),
    )
