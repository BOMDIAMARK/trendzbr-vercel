"""
Telegram sender specialized for the social media group bot.
Sends new Instagram/Twitter posts as messages with link previews.
"""
import logging
import time
from typing import Optional

import requests

from lib import config

logger = logging.getLogger("trendzbr.social_sender")

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"


class SocialSender:
    """Send social media post notifications to the Telegram group.

    Uses a separate bot token and chat ID from the market monitor bot.
    Sends links with preview enabled so Telegram auto-embeds the content.
    """

    def __init__(self):
        self.token = config.SOCIAL_BOT_TOKEN
        self.chat_id = config.SOCIAL_CHAT_ID
        self.api_base = TELEGRAM_API_BASE.format(token=self.token)

    def send_message(
        self,
        text: str,
        parse_mode: Optional[str] = "HTML",
        disable_preview: bool = False,
    ) -> bool:
        """Send a text message to the group."""
        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
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

    def send_instagram_post(self, post: dict) -> bool:
        """Send an Instagram post notification to the group.

        Sends just the link so Telegram can generate a rich preview.
        """
        username = post.get("username", "")
        url = post.get("url", "")
        caption = post.get("caption", "")

        if not url:
            logger.warning("Instagram post has no URL, skipping")
            return False

        # Build message — keep it simple so Telegram preview works
        lines = [
            f"\U0001F4F8 <b>Nova publicacao no Instagram</b>",
            f"",
            f"\U0001F464 @{username}",
        ]

        # Add a snippet of the caption if available
        if caption:
            snippet = caption[:150]
            if len(caption) > 150:
                snippet += "..."
            lines.append(f"")
            lines.append(f"\U0001F4DD {snippet}")

        lines.append(f"")
        lines.append(f"\U0001F517 {url}")

        message = "\n".join(lines)

        success = self.send_message(message, parse_mode="HTML", disable_preview=False)
        if success:
            logger.info("Sent Instagram post: %s", url)
        return success

    def send_tweet(self, tweet: dict) -> bool:
        """Send a tweet notification to the group.

        Note: This is a fallback. Primary Twitter forwarding is via Twitgram Bot.
        """
        username = tweet.get("username", "")
        url = tweet.get("url", "")
        text = tweet.get("text", "")

        if not url:
            logger.warning("Tweet has no URL, skipping")
            return False

        lines = [
            f"\U0001F426 <b>Novo tweet</b>",
            f"",
            f"\U0001F464 @{username}",
        ]

        if text:
            snippet = text[:200]
            if len(text) > 200:
                snippet += "..."
            lines.append(f"")
            lines.append(f"\U0001F4AC {snippet}")

        lines.append(f"")
        lines.append(f"\U0001F517 {url}")

        message = "\n".join(lines)

        success = self.send_message(message, parse_mode="HTML", disable_preview=False)
        if success:
            logger.info("Sent tweet: %s", url)
        return success

    def send_new_posts_batch(
        self,
        instagram_posts: list[dict],
        tweets: list[dict],
    ) -> int:
        """Send all new posts with rate limiting. Returns total sent count."""
        sent = 0
        max_per_cycle = config.SOCIAL_MAX_MESSAGES_PER_CYCLE

        # Send Instagram posts first
        for post in instagram_posts:
            if sent >= max_per_cycle:
                break
            if self.send_instagram_post(post):
                sent += 1
            time.sleep(1.0)  # Rate limit

        # Then tweets (if not using Twitgram)
        for tweet in tweets:
            if sent >= max_per_cycle:
                break
            if self.send_tweet(tweet):
                sent += 1
            time.sleep(1.0)

        if (len(instagram_posts) + len(tweets)) > max_per_cycle:
            skipped = (len(instagram_posts) + len(tweets)) - max_per_cycle
            self.send_message(
                f"\u26A0\uFE0F {skipped} publicacoes adicionais foram suprimidas neste ciclo.",
                disable_preview=True,
            )

        return sent

    def send_error_alert(self, error_msg: str):
        """Send error notification."""
        self.send_message(
            f"\u26A0\uFE0F Erro no Social Monitor:\n{error_msg[:500]}",
            disable_preview=True,
        )
