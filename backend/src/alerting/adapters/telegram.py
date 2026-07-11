"""AlertPort adapter that posts to the Telegram Bot API.

Never raises — a broken alert channel must not break the trading flow that
triggered it (fills, circuit breakers, ...); failures are logged and
swallowed, same tolerance as `journal`'s "one failing subscriber must never
break the others" event-bus rule.
"""

from __future__ import annotations

import logging

import httpx

from src.alerting.domain.models import AlertMessage

logger = logging.getLogger(__name__)


class TelegramAlertAdapter:
    def __init__(self, client: httpx.AsyncClient, bot_token: str, chat_id: str) -> None:
        self._client = client
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send(self, message: AlertMessage) -> None:
        text = f"*{message.title}*\n{message.body}"
        try:
            response = await self._client.post(
                f"/bot{self._bot_token}/sendMessage",
                json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
            )
            response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("telegram alert failed: %s", message.title)
