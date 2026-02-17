"""
Social Media Monitor — Vercel Serverless Function
Monitors Instagram (@trendz.bra) for new posts and sends them to a Telegram group.
Twitter (@trendz_br) is handled by the Twitgram Bot separately.

Triggered by Vercel Cron every 10 minutes via GET request.
"""
import json
import logging
import os
import sys
import time
from http.server import BaseHTTPRequestHandler

# Add project root to path so lib/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config
from lib.utils import setup_logging
from lib.social_scraper import InstagramScraper
from lib.social_store import SocialStore
from lib.social_sender import SocialSender

logger = setup_logging()


def run_social_cycle() -> dict:
    """Execute a single social media monitoring cycle."""
    cycle_start = time.time()

    store = SocialStore()
    is_first = store.check_first_run()

    scraper = InstagramScraper()
    sender = SocialSender()

    new_ig_posts = []
    new_tweets = []  # Reserved for future use if Twitgram is insufficient
    errors = []

    # --- Instagram Monitoring ---
    for username in config.INSTAGRAM_PROFILES:
        try:
            posts = scraper.fetch_latest_posts(username, max_posts=5)
            if not posts:
                logger.warning("No posts returned for Instagram @%s", username)
                continue

            for post in posts:
                post_id = post.get("shortcode") or post.get("id", "")
                if not post_id:
                    continue

                if not store.is_instagram_post_seen(post_id):
                    if not is_first:
                        # Only notify if not first run (avoid spamming old posts)
                        new_ig_posts.append(post)
                    # Mark as seen regardless (so we don't alert again)
                    store.add_seen_instagram_ids([post_id])

        except Exception as e:
            logger.error("Error monitoring Instagram @%s: %s", username, e)
            errors.append(f"IG @{username}: {e}")

    # --- Twitter Monitoring (disabled — Twitgram handles this) ---
    # Uncomment below if you want Apify-based Twitter monitoring too:
    #
    # from lib.social_scraper import TwitterScraper
    # tw_scraper = TwitterScraper()
    # for username in config.TWITTER_PROFILES:
    #     try:
    #         tweets = tw_scraper.fetch_latest_tweets(username, max_tweets=5)
    #         for tweet in tweets:
    #             tweet_id = str(tweet.get("id", ""))
    #             if tweet_id and not store.is_tweet_seen(tweet_id):
    #                 if not is_first:
    #                     new_tweets.append(tweet)
    #                 store.add_seen_twitter_ids([tweet_id])
    #     except Exception as e:
    #         logger.error("Error monitoring Twitter @%s: %s", username, e)

    # --- Send notifications ---
    sent_count = 0
    if new_ig_posts or new_tweets:
        sent_count = sender.send_new_posts_batch(new_ig_posts, new_tweets)

    # --- Update state ---
    if is_first:
        store.mark_initialized()
        logger.info("First run — saved baseline of seen posts without sending alerts")

    store.update_meta()

    # Periodically trim seen IDs to prevent unbounded growth
    store.trim_seen_ids(max_size=500)

    elapsed = round(time.time() - cycle_start, 2)
    summary = {
        "status": "ok",
        "instagram_new": len(new_ig_posts),
        "twitter_new": len(new_tweets),
        "sent": sent_count,
        "first_run": is_first,
        "errors": errors if errors else None,
        "elapsed": elapsed,
    }
    logger.info("Social cycle complete: %s", json.dumps(summary))
    return summary


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler for social media monitoring."""

    def do_GET(self):
        """Handle GET from Vercel Cron or manual check."""
        if self.headers.get("x-vercel-cron"):
            return self._run_and_respond()

        # Info response for manual access
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "TrendzBR Social Monitor",
            "monitors": {
                "instagram": config.INSTAGRAM_PROFILES,
                "twitter": "Handled by Twitgram Bot",
            },
            "note": "Triggered automatically by Vercel Cron every 10 minutes",
        }).encode())

    def do_POST(self):
        """Handle POST for manual triggers."""
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            self.rfile.read(content_len)
        self._run_and_respond()

    def _run_and_respond(self):
        """Run social monitoring cycle and send response."""
        try:
            result = run_social_cycle()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            logger.error("Social cycle failed: %s", e, exc_info=True)
            try:
                store = SocialStore()
                if store.can_send_error_alert():
                    sender = SocialSender()
                    sender.send_error_alert(str(e))
                    store.record_error_alert()
            except Exception:
                pass

            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        logger.debug(format, *args)
