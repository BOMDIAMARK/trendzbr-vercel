"""
TrendzBR Market Monitor — Vercel Serverless Function
Triggered by QStash every 5 minutes via POST request.
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


def verify_qstash_signature(headers: dict, body: bytes) -> bool:
    """Verify that the request comes from QStash."""
    if not config.QSTASH_CURRENT_SIGNING_KEY:
        logger.warning("QStash signing keys not configured, skipping verification")
        return True  # Allow in development / manual testing

    signature = headers.get("Upstash-Signature") or headers.get("upstash-signature", "")
    if not signature:
        # Check if this is a Vercel cron invocation (daily fallback)
        if headers.get("x-vercel-cron"):
            logger.info("Request from Vercel cron (daily fallback)")
            return True
        logger.warning("No QStash signature found in headers")
        return False

    try:
        from qstash import Receiver
        receiver = Receiver(
            current_signing_key=config.QSTASH_CURRENT_SIGNING_KEY,
            next_signing_key=config.QSTASH_NEXT_SIGNING_KEY,
        )
        receiver.verify(
            body=body.decode("utf-8") if body else "",
            signature=signature,
            url=None,  # Skip URL verification
        )
        return True
    except Exception as e:
        logger.error("QStash signature verification failed: %s", e)
        return False


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

    def do_POST(self):
        """Handle POST from QStash scheduled trigger."""
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""

        # Verify QStash signature
        header_dict = {k: v for k, v in self.headers.items()}
        if not verify_qstash_signature(header_dict, body):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid signature"}).encode())
            return

        # Run monitoring cycle
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

    def do_GET(self):
        """Respond to GET with a simple status (Vercel cron or manual check)."""
        # If this is a Vercel cron trigger, run the cycle
        if self.headers.get("x-vercel-cron"):
            return self.do_POST()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "TrendzBR Monitor",
            "note": "Use POST (via QStash) to trigger a monitoring cycle",
        }).encode())

    def log_message(self, format, *args):
        """Override to use Python logging instead of stderr."""
        logger.debug(format, *args)
