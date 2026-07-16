from __future__ import annotations

import os
from datetime import datetime

import pytest

from app.core.config import AuthorizationEmailConfig, WeRSSAuthorizationConfig
from app.domain.werss_authorization import AuthorizationSettingsCommand
from app.security.windows_dpapi import WindowsDpapiSecretCipher
from app.services.authorization_settings_service import AuthorizationSettingsService


NOW = datetime(2026, 7, 16, 18, 30, 0)


class Repo:
    def __init__(self):
        self.settings = None

    def get_settings(self):
        return self.settings

    def upsert_settings(self, settings):
        self.settings = settings


class Cipher:
    def encrypt(self, value):
        return f"encrypted:{value[::-1]}".encode()

    def decrypt(self, value):
        return value.decode().split(":", 1)[1][::-1]


def _service(repo=None, env=None):
    return AuthorizationSettingsService(
        repo or Repo(),
        Cipher(),
        WeRSSAuthorizationConfig(enabled=True),
        AuthorizationEmailConfig(),
        environ_getter=(env or {}).get,
    )


def test_settings_encrypt_passwords_and_never_return_them_publicly() -> None:
    repo = Repo()
    service = _service(repo)
    public = service.save(AuthorizationSettingsCommand(
        werss_username="controller",
        werss_password="werss-secret",
        smtp_enabled=True,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="notifier@example.com",
        smtp_password="smtp-secret",
        smtp_security="starttls",
        from_address="notifier@example.com",
        recipients=("Owner@Example.com", "owner@example.com"),
    ), NOW)

    assert repo.settings.werss_password_encrypted != b"werss-secret"
    assert repo.settings.smtp_password_encrypted != b"smtp-secret"
    assert public.werss_password_configured is True
    assert public.smtp_password_configured is True
    assert public.recipients == ("owner@example.com",)
    assert not hasattr(public, "werss_password")
    assert not hasattr(public, "smtp_password")
    assert service.management_credentials() == ("controller", "werss-secret")


def test_blank_passwords_preserve_existing_encrypted_values() -> None:
    repo = Repo()
    service = _service(repo)
    command = AuthorizationSettingsCommand(
        "controller", "first-secret", False, "", 587, "", "", "starttls", "", ()
    )
    service.save(command, NOW)
    encrypted = repo.settings.werss_password_encrypted

    service.save(AuthorizationSettingsCommand(
        "controller-2", "", False, "", 587, "", "", "starttls", "", ()
    ), NOW)

    assert repo.settings.werss_password_encrypted == encrypted
    assert service.management_credentials() == ("controller-2", "first-secret")


def test_environment_secret_is_used_only_when_database_secret_is_missing() -> None:
    service = _service(env={"WERSS_AUTH_ADMIN_PASSWORD": "fallback-secret"})
    assert service.public_settings().werss_password_configured is True
    assert service.management_credentials()[1] == "fallback-secret"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_windows_dpapi_round_trip_is_not_plaintext() -> None:
    cipher = WindowsDpapiSecretCipher()
    encrypted = cipher.encrypt("本机专用-secret")
    assert b"secret" not in encrypted
    assert cipher.decrypt(encrypted) == "本机专用-secret"
