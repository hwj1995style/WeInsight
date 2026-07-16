from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import AuthorizationEmailConfig
from app.domain.werss_authorization import WeRSSAuthorizationSnapshot


class SmtpAuthorizationMailer:
    def __init__(self, config: AuthorizationEmailConfig, password: str | None) -> None:
        self.config = config
        self.password = password

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def send(self, snapshot: WeRSSAuthorizationSnapshot, notice_type: str) -> None:
        if not self.config.enabled:
            return
        if not self.password:
            raise RuntimeError("smtp_password_missing")
        message = EmailMessage()
        if notice_type == "test":
            subject = "公众号授权提醒测试邮件"
        else:
            subject = "公众号授权已过期" if notice_type == "expired" else "公众号授权即将到期"
        message["Subject"] = f"[WeInsight] {subject}"
        message["From"] = self.config.from_address
        message["To"] = ", ".join(self.config.recipients)
        expires = snapshot.expires_at.strftime("%Y-%m-%d %H:%M:%S") if snapshot.expires_at else "未知"
        message.set_content(
            f"公众号：{snapshot.account_name or '未知'}\n"
            f"到期时间：{expires}\n"
            "处理入口：/sources/articles#authorization-management\n"
        )
        if self.config.security == "ssl":
            connection = smtplib.SMTP_SSL(
                self.config.host,
                self.config.port,
                timeout=10,
                context=ssl.create_default_context(),
            )
        else:
            connection = smtplib.SMTP(self.config.host, self.config.port, timeout=10)
        with connection:
            if self.config.security == "starttls":
                connection.starttls(context=ssl.create_default_context())
            if self.config.username:
                connection.login(self.config.username, self.password)
            connection.send_message(message)
