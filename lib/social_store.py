"""
Redis store for social media monitoring.
Tracks seen post IDs to detect new publications.
Uses separate Redis keys from the TrendzBR market monitor.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from upstash_redis import Redis

from lib import config

logger = logging.getLogger("trendzbr.social_store")


class SocialStore:
    """Manages state for social media monitoring in Upstash Redis.

    Redis key design:
    - social:seen:instagram  -> SET of seen Instagram post IDs/shortcodes
    - social:seen:twitter    -> SET of seen tweet IDs
    - social:meta            -> HASH with last_cycle_ts, cycle_count
    - social:init            -> Flag for first run
    - social:error           -> Error cooldown (TTL 10min)
    """

    SEEN_IG_KEY = "social:seen:instagram"
    SEEN_TW_KEY = "social:seen:twitter"
    META_KEY = "social:meta"
    INIT_KEY = "social:init"
    ERROR_KEY = "social:error"

    def __init__(self):
        self.redis = Redis(
            url=config.UPSTASH_REDIS_REST_URL,
            token=config.UPSTASH_REDIS_REST_TOKEN,
        )
        self._is_first_run = False

    def check_first_run(self) -> bool:
        """Check if this is the first run (no state exists yet)."""
        self._is_first_run = not bool(self.redis.exists(self.INIT_KEY))
        return self._is_first_run

    def is_first_run(self) -> bool:
        return self._is_first_run

    def mark_initialized(self):
        """Mark system as initialized after first run."""
        self.redis.set(self.INIT_KEY, "1")
        self._is_first_run = False

    # -- Instagram --

    def get_seen_instagram_ids(self) -> set[str]:
        """Get all previously seen Instagram post IDs."""
        members = self.redis.smembers(self.SEEN_IG_KEY)
        return set(members) if members else set()

    def add_seen_instagram_ids(self, post_ids: list[str]):
        """Mark Instagram post IDs as seen."""
        if not post_ids:
            return
        self.redis.sadd(self.SEEN_IG_KEY, *post_ids)

    def is_instagram_post_seen(self, post_id: str) -> bool:
        """Check if an Instagram post has been seen before."""
        return bool(self.redis.sismember(self.SEEN_IG_KEY, post_id))

    # -- Twitter --

    def get_seen_twitter_ids(self) -> set[str]:
        """Get all previously seen tweet IDs."""
        members = self.redis.smembers(self.SEEN_TW_KEY)
        return set(members) if members else set()

    def add_seen_twitter_ids(self, tweet_ids: list[str]):
        """Mark tweet IDs as seen."""
        if not tweet_ids:
            return
        self.redis.sadd(self.SEEN_TW_KEY, *tweet_ids)

    def is_tweet_seen(self, tweet_id: str) -> bool:
        """Check if a tweet has been seen before."""
        return bool(self.redis.sismember(self.SEEN_TW_KEY, tweet_id))

    # -- Metadata --

    def update_meta(self):
        """Update cycle metadata."""
        now = datetime.now(timezone.utc).isoformat()
        raw = self.redis.hgetall(self.META_KEY)
        meta = {}
        if raw:
            meta = raw
        cycle_count = int(meta.get("cycle_count", 0)) + 1
        self.redis.hset(
            self.META_KEY,
            values={
                "last_cycle_ts": now,
                "cycle_count": str(cycle_count),
            },
        )

    def get_meta(self) -> dict:
        """Get cycle metadata."""
        raw = self.redis.hgetall(self.META_KEY)
        return raw if raw else {}

    # -- Error cooldown --

    def can_send_error_alert(self) -> bool:
        return not bool(self.redis.exists(self.ERROR_KEY))

    def record_error_alert(self):
        self.redis.set(self.ERROR_KEY, "1", ex=600)  # 10 min cooldown

    # -- Cleanup (keep sets from growing too large) --

    def trim_seen_ids(self, max_size: int = 500):
        """Keep the seen ID sets from growing indefinitely.
        Removes oldest entries when set exceeds max_size.
        Note: Redis SETs are unordered, so we just trim randomly.
        For our use case this is fine - we only need recent IDs.
        """
        for key in [self.SEEN_IG_KEY, self.SEEN_TW_KEY]:
            size = self.redis.scard(key)
            if size and size > max_size:
                # Remove excess members (random, since sets are unordered)
                excess = size - max_size
                for _ in range(excess):
                    self.redis.spop(key)
                logger.info("Trimmed %d entries from %s", excess, key)
