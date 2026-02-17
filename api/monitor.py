"""
TrendzBR Market Monitor — Vercel Serverless Function
Triggered by Vercel Cron every 5 minutes via GET request.
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
from lib.scraper import TrendzBRScraper
from lib.detector import AlertDetector
from lib.redis_store import RedisStore
from lib.telegram_sender import TelegramSender

logger = setup_logging()


def run_cycle() -> dict:
    """Execute a single monitoring cycle. Returns summary dict."""
    cycle_start = time.time()

    store = RedisStore()
    store.load_state()

    scraper = TrendzBRScraper()
    detector = AlertDetector(store)
    sender = TelegramSender()

    # Step 1: Fetch pools
    pools = scraper.fetch_all_pools()
    if not pools:
        logger.warning("No pools returned from scraper")
        return {
            "status": "warning",
            "message": "No pools found",
            "elapsed": round(time.time() - cycle_start, 2),
        }

    total_options = sum(len(p.options) for p in pools)
    logger.info("Found %d pools with %d total options", len(pools), total_options)

    # Step 2: Detect alerts (skip on first run to avoid spam)
    alerts = []
    if store.is_first_run():
        logger.info("First run detected — saving initial state without sending alerts")
    else:
        alerts.extend(detector.check_new_markets(pools))
        alerts.extend(detector.check_odds_changes(pools))
        alerts.extend(detector.check_closing_soon(pools))

    # Step 3: Send alerts via Telegram
    sent_count = 0
    if alerts:
        sent_count = sender.send_alerts_batch(alerts)

    # Step 4: Save state to Redis
    store.save_state(pools)

    elapsed = round(time.time() - cycle_start, 2)
    summary = {
        "status": "ok",
        "pools": len(pools),
        "options": total_options,
        "alerts_detected": len(alerts),
        "alerts_sent": sent_count,
        "first_run": store.is_first_run(),
        "elapsed": elapsed,
    }
    logger.info("Cycle complete: %s", json.dumps(summary))
    return summary


class handler(BaseHTTPRequestHandler):
    """Vercel serverless function handler."""

    def do_GET(self):
        """Handle GET from Vercel Cron or manual check."""
        # If this is a Vercel cron trigger, run the cycle
        if self.headers.get("x-vercel-cron"):
            return self._run_and_respond()

        # Otherwise return info
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "TrendzBR Monitor",
            "note": "Triggered automatically by Vercel Cron every 5 minutes",
        }).encode())

    def do_POST(self):
        """Handle POST for manual triggers."""
        # Read body (discard — no QStash verification needed)
        content_len = int(self.headers.get("Content-Length", 0))
        if content_len > 0:
            self.rfile.read(content_len)

        self._run_and_respond()

    def _run_and_respond(self):
        """Run monitoring cycle and send response."""
        try:
            result = run_cycle()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:
            logger.error("Cycle failed: %s", e, exc_info=True)
            # Try to send error via Telegram (with cooldown)
            try:
                store = RedisStore()
                if store.can_send_error_alert():
                    sender = TelegramSender()
                    sender.send_error_alert(str(e))
                    store.record_error_alert()
            except Exception:
                pass

            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr."""
        logger.debug(format, *args)
