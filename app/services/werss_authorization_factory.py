from __future__ import annotations

import os

from sqlalchemy.engine import Engine

from app.core.config import Config
from app.integrations.dynamic_authorization_mailer import DynamicAuthorizationMailer
from app.integrations.werss_authorization import WeRSSAuthorizationClient
from app.security.windows_dpapi import WindowsDpapiSecretCipher
from app.services.authorization_settings_service import AuthorizationSettingsService
from app.services.werss_authorization_service import (
    DisabledWeRSSAuthorizationService,
    WeRSSAuthorizationService,
)
from app.storage.werss_authorization_repo import MysqlWeRSSAuthorizationRepo


def build_werss_authorization_service(config: Config, engine: Engine):
    settings = getattr(config, "werss_authorization", None)
    if settings is None:
        return DisabledWeRSSAuthorizationService()
    if not settings.enabled:
        return DisabledWeRSSAuthorizationService()
    article = config.pipelines.article
    repo = MysqlWeRSSAuthorizationRepo(engine)
    settings_service = AuthorizationSettingsService(
        repo,
        WindowsDpapiSecretCipher(),
        settings,
        config.authorization_email,
    )
    client = WeRSSAuthorizationClient(
        settings.base_url,
        article.werss_access_key,
        article.werss_secret_key,
        settings.management_username,
        os.getenv(settings.management_password_env),
    )
    mailer = DynamicAuthorizationMailer(settings_service)
    return WeRSSAuthorizationService(
        repo,
        client,
        warning_threshold_hours=settings.warning_threshold_hours,
        check_interval_seconds=settings.check_interval_seconds,
        mailer=mailer,
        recipient_count=len(config.authorization_email.recipients),
        settings_service=settings_service,
    )
