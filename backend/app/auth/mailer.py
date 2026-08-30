"""Small Resend adapter used by the authentication service.

The adapter deliberately sends only a one-time code and never includes
assessment answers, scores, or safety information in an email.
"""

from __future__ import annotations

import json
import os
from urllib import error, request

from backend.app.config import load_local_env


class MailDeliveryError(RuntimeError):
    """Raised when the configured mail provider cannot accept a message."""


class ResendMailer:
    endpoint = "https://api.resend.com/emails"

    def __init__(self, *, api_key: str | None = None, from_email: str | None = None, app_url: str | None = None) -> None:
        load_local_env()
        self.api_key = (api_key if api_key is not None else os.getenv("RESEND_API_KEY", "")).strip()
        self.from_email = (from_email if from_email is not None else os.getenv("AUTH_FROM_EMAIL", "auth@qiuzheng.xyz")).strip()
        self.app_url = (app_url if app_url is not None else os.getenv("AUTH_APP_URL", "https://qiuzheng.xyz")).strip().rstrip("/")

    def _send(self, *, email: str, subject: str, html: str) -> None:
        if not self.api_key:
            raise MailDeliveryError("Email delivery is not configured")
        payload = json.dumps({"from": self.from_email, "to": [email], "subject": subject, "html": html}).encode("utf-8")
        req = request.Request(
            self.endpoint,
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=12) as response:
                if response.status >= 300:
                    raise MailDeliveryError("Email delivery failed")
        except (error.URLError, error.HTTPError, TimeoutError) as exc:
            raise MailDeliveryError("Email delivery failed") from exc

    def send_verification_code(self, email: str, code: str) -> None:
        self._send(
            email=email,
            subject="验证你的求证账号",
            html=(
                "<div style='font-family:system-ui,sans-serif;line-height:1.7;color:#292834'>"
                "<p>你好，</p><p>这是你的求证邮箱验证码：</p>"
                f"<p style='font-size:30px;letter-spacing:8px;font-weight:700'>{code}</p>"
                "<p>验证码 10 分钟内有效，只能使用一次。如果不是你本人操作，可以忽略这封邮件。</p>"
                "</div>"
            ),
        )

    def send_password_reset_code(self, email: str, code: str) -> None:
        self._send(
            email=email,
            subject="重置你的求证账号密码",
            html=(
                "<div style='font-family:system-ui,sans-serif;line-height:1.7;color:#292834'>"
                "<p>这是你的密码重置验证码：</p>"
                f"<p style='font-size:30px;letter-spacing:8px;font-weight:700'>{code}</p>"
                "<p>验证码 10 分钟内有效，只能使用一次。如果不是你本人操作，可以忽略这封邮件。</p>"
                "</div>"
            ),
        )
