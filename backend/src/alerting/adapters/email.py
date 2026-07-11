"""AlertPort adapter that sends email over SMTP.

Uses stdlib `smtplib` (no new dependency) wrapped in `asyncio.to_thread`,
the same sync-to-async offload `journal/adapters/repository.py` uses for its
SQLAlchemy calls. Never raises — see `telegram.py`'s module docstring.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from src.alerting.domain.models import AlertMessage

logger = logging.getLogger(__name__)


class EmailAlertAdapter:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_address: str,
        to_address: str,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._to_address = to_address

    async def send(self, message: AlertMessage) -> None:
        try:
            await asyncio.to_thread(self._send_sync, message)
        except Exception:
            logger.exception("email alert failed: %s", message.title)

    def _send_sync(self, message: AlertMessage) -> None:
        email = EmailMessage()
        email["Subject"] = f"[trading-bot] {message.title}"
        email["From"] = self._from_address
        email["To"] = self._to_address
        email.set_content(message.body)
        with smtplib.SMTP(self._smtp_host, self._smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if self._username:
                smtp.login(self._username, self._password)
            smtp.send_message(email)
