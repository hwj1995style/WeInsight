from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import datetime
from typing import Callable, Protocol

from app.core.config import AuthorizationEmailConfig, WeRSSAuthorizationConfig
from app.domain.werss_authorization import (
    AuthorizationManagementSettings,
    AuthorizationSettingsCommand,
    PublicAuthorizationSettings,
)


_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$")


class SettingsRepo(Protocol):
    def get_settings(self) -> AuthorizationManagementSettings | None: ...
    def upsert_settings(self, settings: AuthorizationManagementSettings) -> None: ...


class SecretCipher(Protocol):
    def encrypt(self, value: str) -> bytes: ...
    def decrypt(self, value: bytes) -> str: ...


class AuthorizationSettingsService:
    def __init__(
        self,
        repo: SettingsRepo,
        cipher: SecretCipher,
        authorization_defaults: WeRSSAuthorizationConfig,
        email_defaults: AuthorizationEmailConfig,
        *,
        environ_getter: Callable[[str], str | None] = os.getenv,
    ) -> None:
        self.repo = repo
        self.cipher = cipher
        self.authorization_defaults = authorization_defaults
        self.email_defaults = email_defaults
        self.environ_getter = environ_getter

    def public_settings(self) -> PublicAuthorizationSettings:
        settings = self._stored_or_defaults()
        return PublicAuthorizationSettings(
            werss_username=settings.werss_username,
            werss_password_configured=bool(
                settings.werss_password_encrypted
                or self.environ_getter(self.authorization_defaults.management_password_env)
            ),
            smtp_enabled=settings.smtp_enabled,
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_username=settings.smtp_username,
            smtp_password_configured=bool(
                settings.smtp_password_encrypted
                or self.environ_getter(self.email_defaults.password_env)
            ),
            smtp_security=settings.smtp_security,
            from_address=settings.from_address,
            recipients=settings.recipients,
            updated_at=settings.updated_at,
        )

    def save(self, command: AuthorizationSettingsCommand, now: datetime) -> PublicAuthorizationSettings:
        normalized = _validate_command(command)
        previous = self._stored_or_defaults()
        werss_secret = (
            self.cipher.encrypt(normalized.werss_password)
            if normalized.werss_password
            else previous.werss_password_encrypted
        )
        smtp_secret = (
            self.cipher.encrypt(normalized.smtp_password)
            if normalized.smtp_password
            else previous.smtp_password_encrypted
        )
        if normalized.smtp_enabled:
            if not smtp_secret and not self.environ_getter(self.email_defaults.password_env):
                raise ValueError("smtp password is required when email is enabled")
            if not normalized.smtp_host or not normalized.from_address or not normalized.recipients:
                raise ValueError("smtp host, from address and recipients are required")
        settings = AuthorizationManagementSettings(
            werss_username=normalized.werss_username,
            werss_password_encrypted=werss_secret,
            smtp_enabled=normalized.smtp_enabled,
            smtp_host=normalized.smtp_host,
            smtp_port=normalized.smtp_port,
            smtp_username=normalized.smtp_username,
            smtp_password_encrypted=smtp_secret,
            smtp_security=normalized.smtp_security,
            from_address=normalized.from_address,
            recipients=normalized.recipients,
            updated_at=now,
        )
        self.repo.upsert_settings(settings)
        return self.public_settings()

    def management_credentials(self) -> tuple[str, str | None]:
        settings = self._stored_or_defaults()
        password = (
            self.cipher.decrypt(settings.werss_password_encrypted)
            if settings.werss_password_encrypted
            else self.environ_getter(self.authorization_defaults.management_password_env)
        )
        return settings.werss_username, password

    def email_credentials(self) -> tuple[AuthorizationEmailConfig, str | None]:
        settings = self._stored_or_defaults()
        config = AuthorizationEmailConfig(
            enabled=settings.smtp_enabled,
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password_env=self.email_defaults.password_env,
            security=settings.smtp_security,
            from_address=settings.from_address,
            recipients=settings.recipients,
        )
        password = (
            self.cipher.decrypt(settings.smtp_password_encrypted)
            if settings.smtp_password_encrypted
            else self.environ_getter(self.email_defaults.password_env)
        )
        return config, password

    def _stored_or_defaults(self) -> AuthorizationManagementSettings:
        stored = self.repo.get_settings()
        if stored is not None:
            return stored
        return AuthorizationManagementSettings(
            werss_username=self.authorization_defaults.management_username,
            werss_password_encrypted=None,
            smtp_enabled=self.email_defaults.enabled,
            smtp_host=self.email_defaults.host,
            smtp_port=self.email_defaults.port,
            smtp_username=self.email_defaults.username,
            smtp_password_encrypted=None,
            smtp_security=self.email_defaults.security,
            from_address=self.email_defaults.from_address,
            recipients=self.email_defaults.recipients,
            updated_at=None,
        )


def _validate_command(command: AuthorizationSettingsCommand) -> AuthorizationSettingsCommand:
    if not isinstance(command, AuthorizationSettingsCommand):
        raise TypeError("command must be AuthorizationSettingsCommand")
    werss_username = _text(command.werss_username, "werss username", 100, required=True)
    werss_password = _secret(command.werss_password, "werss password")
    smtp_host = _text(command.smtp_host, "smtp host", 255)
    smtp_username = _text(command.smtp_username, "smtp username", 255)
    smtp_password = _secret(command.smtp_password, "smtp password")
    if type(command.smtp_enabled) is not bool:
        raise TypeError("smtp enabled must be boolean")
    from_address = _email(command.from_address, "from address", allow_empty=True)
    if command.smtp_security not in {"starttls", "ssl", "plain"}:
        raise ValueError("invalid smtp security")
    if type(command.smtp_port) is not int or not 1 <= command.smtp_port <= 65535:
        raise ValueError("invalid smtp port")
    recipients: list[str] = []
    for raw in command.recipients:
        address = _email(raw, "recipient", allow_empty=False).lower()
        if address not in recipients:
            recipients.append(address)
    if len(recipients) > 50:
        raise ValueError("too many recipients")
    return replace(
        command,
        werss_username=werss_username,
        werss_password=werss_password,
        smtp_host=smtp_host,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        from_address=from_address.lower(),
        recipients=tuple(recipients),
    )


def _text(value: object, field: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise ValueError(f"{field} is required")
    if len(result) > maximum or any(ord(char) < 32 for char in result):
        raise ValueError(f"invalid {field}")
    return result


def _secret(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be text")
    if len(value) > 1024 or any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {field}")
    return value


def _email(value: object, field: str, *, allow_empty: bool) -> str:
    result = _text(value, field, 320)
    if not result and allow_empty:
        return ""
    if not _EMAIL_PATTERN.fullmatch(result):
        raise ValueError(f"invalid {field}")
    return result
