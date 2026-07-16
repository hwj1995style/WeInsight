from __future__ import annotations

from datetime import datetime

from app.domain.werss_authorization import WeRSSAuthorizationSnapshot
from app.integrations.smtp_mailer import SmtpAuthorizationMailer
from app.services.authorization_settings_service import AuthorizationSettingsService


class DynamicAuthorizationMailer:
    def __init__(self, settings_service: AuthorizationSettingsService) -> None:
        self.settings_service = settings_service

    @property
    def enabled(self) -> bool:
        config, _ = self.settings_service.email_credentials()
        return config.enabled

    @property
    def recipient_count(self) -> int:
        config, _ = self.settings_service.email_credentials()
        return len(config.recipients)

    def send(self, snapshot: WeRSSAuthorizationSnapshot, notice_type: str) -> None:
        config, password = self.settings_service.email_credentials()
        SmtpAuthorizationMailer(config, password).send(snapshot, notice_type)

    def send_test(self, now: datetime) -> None:
        config, password = self.settings_service.email_credentials()
        if not config.enabled:
            raise ValueError("email is not enabled")
        snapshot = WeRSSAuthorizationSnapshot(
            status="valid",
            account_name="WeInsight 测试",
            expires_at=None,
            last_checked_at=now,
            last_successful_check_at=now,
            last_error_code=None,
            authorization_version=None,
        )
        SmtpAuthorizationMailer(config, password).send(snapshot, "test")
