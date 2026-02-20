"""
TrendzBR Market Monitor — Continuous Worker
Runs on Railway 24/7. Executes monitoring cycle every 5 minutes.
Also handles the social media monitor every 10 minutes.
"""
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone

from lib import config
from lib.utils import setup_logging
from lib.scraper import TrendzBRScraper
from lib.detector import AlertDetector
from lib.redis_store import RedisStore
from lib.telegram_sender import TelegramSender

logger = setup_logging()

MARKET_INTERVAL = 300   # 5 minutes
SOCIAL_INTERVAL = 600   # 10 minutes


def run_market_cycle() -> dict:
    """Execute a single market monitoring cycle."""
    cycle_start = time.time()

    store = RedisStore()
    store.load_state()

    scraper = TrendzBRScraper()
    detector = AlertDetector(store)
    sender = TelegramSender()

    pools = scraper.fetch_all_pools()
    if not pools:
        logger.warning("No pools returned from scraper")
        return {"status": "warning", "message": "No pools found"}

    total_options = sum(len(p.options) for p in pools)
    logger.info("Found %d pools with %d total options", len(pools), total_options)

    alerts = []
    if store.is_first_run():
        logger.info("First run — saving initial state without sending alerts")
    else:
        alerts.extend(detector.check_new_markets(pools))
        alerts.extend(detector.check_odds_changes(pools))
        alerts.extend(detector.check_closing_soon(pools))

    sent_count = 0
    if alerts:
        sent_count = sender.send_alerts_batch(alerts)

    store.save_state(pools)

    elapsed = round(time.time() - cycle_start, 2)
    return {
        "status": "ok",
        "pools": len(pools),
        "options": total_options,
        "alerts_detected": len(alerts),
        "alerts_sent": sent_count,
        "first_run": store.is_first_run(),
        "elapsed": elapsed,
    }


def run_social_cycle() -> dict:
    """Execute a single social media monitoring cycle."""
    from lib.social_scraper import InstagramScraper, TwitterScraper
    from lib.social_store import SocialStore
    from lib.social_sender import SocialSender

    cycle_start = time.time()
    store = SocialStore()
    is_first = store.check_first_run()

    ig_scraper = InstagramScraper()
    tw_scraper = TwitterScraper()
    sender = SocialSender()

    errors = []
    new_ig_posts = []
    new_tweets = []

    # Instagram
    for username in config.INSTAGRAM_PROFILES:
        try:
            posts = ig_scraper.fetch_latest_posts(username, max_posts=5)
            for post in posts:
                post_id = post.get("id") or post.get("shortcode", "")
                if not post_id:
                    continue
                if not store.is_instagram_post_seen(post_id):
                    store.add_seen_instagram_ids([post_id])
                    if not is_first:
                        new_ig_posts.append(post)
        except Exception as e:
            errors.append(f"IG @{username}: {e}")
            logger.error("Instagram error for @%s: %s", username, e)

    # Twitter
    for username in config.TWITTER_PROFILES:
        try:
            tweets = tw_scraper.fetch_latest_tweets(username, max_tweets=5)
            for tweet in tweets:
                tweet_id = tweet.get("id", "")
                if not tweet_id:
                    continue
                if not store.is_tweet_seen(tweet_id):
                    store.add_seen_twitter_ids([tweet_id])
                    if not is_first:
                        new_tweets.append(tweet)
        except Exception as e:
            errors.append(f"TW @{username}: {e}")
            logger.error("Twitter error for @%s: %s", username, e)

    # Send new posts
    sent = 0
    if new_ig_posts or new_tweets:
        sent = sender.send_new_posts_batch(new_ig_posts, new_tweets)

    if is_first:
        store.mark_initialized()

    store.update_meta()

    elapsed = round(time.time() - cycle_start, 2)
    return {
        "status": "ok",
        "instagram_new": len(new_ig_posts),
        "twitter_new": len(new_tweets),
        "sent": sent,
        "first_run": is_first,
        "errors": errors if errors else None,
        "elapsed": elapsed,
    }


def main():
    """Main loop — runs forever."""
    logger.info("=" * 50)
    logger.info("TrendzBR Worker starting...")
    logger.info("Market interval: %ds | Social interval: %ds", MARKET_INTERVAL, SOCIAL_INTERVAL)
    logger.info("=" * 50)

    last_market_run = 0
    last_social_run = 0

    # Send startup notification
    try:
        sender = TelegramSender()
        sender.send_message("🟢 TrendzBR Worker iniciado!\nMonitoramento ativo 24/7.")
    except Exception:
        pass

    while True:
        now = time.time()

        # Market monitor cycle
        if now - last_market_run >= MARKET_INTERVAL:
            try:
                logger.info("--- Market cycle starting ---")
                result = run_market_cycle()
                logger.info("Market cycle: %s", json.dumps(result))
                last_market_run = now
            except Exception as e:
                logger.error("Market cycle FAILED: %s", e)
                logger.error(traceback.format_exc())
                last_market_run = now  # Don't retry immediately
                try:
                    store = RedisStore()
                    if store.can_send_error_alert():
                        sender = TelegramSender()
                        sender.send_error_alert(f"Market cycle error: {str(e)[:300]}")
                        store.record_error_alert()
                except Exception:
                    pass

        # Social monitor cycle
        if now - last_social_run >= SOCIAL_INTERVAL:
            try:
                logger.info("--- Social cycle starting ---")
                result = run_social_cycle()
                logger.info("Social cycle: %s", json.dumps(result))
                last_social_run = now
            except Exception as e:
                logger.error("Social cycle FAILED: %s", e)
                logger.error(traceback.format_exc())
                last_social_run = now
                try:
                    from lib.social_store import SocialStore
                    store = SocialStore()
                    if store.can_send_error_alert():
                        from lib.social_sender import SocialSender
                        sender = SocialSender()
                        sender.send_error_alert(f"Social cycle error: {str(e)[:300]}")
                        store.record_error_alert()
                except Exception:
                    pass

        # Sleep 30 seconds between checks
        time.sleep(30)


if __name__ == "__main__":
    main()
