from datetime import datetime

from app.core.config import AuthorizationEmailConfig
from app.domain.werss_authorization import WeRSSAuthorizationSnapshot
from app.integrations.smtp_mailer import SmtpAuthorizationMailer


def test_smtp_mailer_sends_only_safe_authorization_fields(monkeypatch) -> None:
    observed = {}

    class Connection:
        def __init__(self, host, port, timeout):
            observed["connection"] = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self, context):
            observed["tls"] = True

        def login(self, username, password):
            observed["login"] = (username, password)

        def send_message(self, message):
            observed["message"] = message

    monkeypatch.setattr("smtplib.SMTP", Connection)
    config = AuthorizationEmailConfig(
        enabled=True,
        host="smtp.example.com",
        port=587,
        username="notifier@example.com",
        password_env="SMTP_PASSWORD",
        security="starttls",
        from_address="notifier@example.com",
        recipients=("owner@example.com",),
    )
    snapshot = WeRSSAuthorizationSnapshot(
        "expiring", "测试公众号", datetime(2026, 7, 17, 15, 26, 20),
        datetime(2026, 7, 16, 18, 0, 0), datetime(2026, 7, 16, 18, 0, 0),
        None, "version",
    )

    SmtpAuthorizationMailer(config, "smtp-secret").send(snapshot, "expiring_24h")

    message = observed["message"]
    assert message["To"] == "owner@example.com"
    assert "测试公众号" in message.get_content()
    assert "2026-07-17 15:26:20" in message.get_content()
    assert "Token" not in message.get_content()
    assert "Cookie" not in message.get_content()
    assert observed["login"] == ("notifier@example.com", "smtp-secret")
