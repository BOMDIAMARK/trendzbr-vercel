import logging
import time
from typing import Optional

import requests

from lib import config
from lib.models import Alert

logger = logging.getLogger("trendzbr.telegram")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramSender:
    """Send messages to Telegram using direct HTTP API calls.

    Replaces the async python-telegram-bot library with simple synchronous
    requests — better suited for serverless environments.
    """

    def __init__(self, token: str = "", chat_id: str = ""):
        self.token = token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.api_base = TELEGRAM_API_BASE.format(token=self.token)

    def send_message(self, text: str, parse_mode: Optional[str] = None) -> bool:
        """Send a text message to the configured chat via HTTP POST."""
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error("Failed to send Telegram message: %s", e)
            return False

    def send_alert(self, alert: Alert) -> bool:
        """Send an individual alert message."""
        success = self.send_message(alert.message)
        if success:
            logger.info("Alert sent: [%s] %s", alert.alert_type, alert.pool_title)
        return success

    def send_alerts_batch(self, alerts: list[Alert]) -> int:
        """Send multiple alerts with rate limiting. Returns count of successfully sent."""
        sent = 0
        for alert in alerts[:config.MAX_TELEGRAM_MESSAGES_PER_CYCLE]:
            if self.send_alert(alert):
                sent += 1
            time.sleep(config.TELEGRAM_SEND_DELAY_SECONDS)

        if len(alerts) > config.MAX_TELEGRAM_MESSAGES_PER_CYCLE:
            skipped = len(alerts) - config.MAX_TELEGRAM_MESSAGES_PER_CYCLE
            self.send_message(
                f"\u26A0\uFE0F {skipped} alertas adicionais foram suprimidos neste ciclo."
            )
        return sent

    def send_error_alert(self, error_msg: str):
        """Send error notification."""
        self.send_message(
            f"\u26A0\uFE0F Erro no sistema de alertas:\n{error_msg[:500]}"
        )
