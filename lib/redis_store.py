import json
import logging
from datetime import datetime, timezone
from typing import Optional

from upstash_redis import Redis

from lib import config
from lib.models import Pool

logger = logging.getLogger("trendzbr.redis_store")


class RedisStore:
    """Manages all state in Upstash Redis, replacing the SQLite Database class.

    State is consolidated into a single Redis hash (trendzbr:state) to minimize
    command count. Each cycle does ~20-30 Redis commands total.
    """

    STATE_KEY = "trendzbr:state"
    CLOSING_PREFIX = "trendzbr:closing"
    COOLDOWN_PREFIX = "trendzbr:cooldown"
    INIT_KEY = "trendzbr:init"
    ERROR_KEY = "trendzbr:last_error"

    def __init__(self):
        self.redis = Redis(
            url=config.UPSTASH_REDIS_REST_URL,
            token=config.UPSTASH_REDIS_REST_TOKEN,
        )
        # In-memory cache loaded at cycle start
        self._pools: dict = {}
        self._markets: dict = {}
        self._snapshots: dict = {}
        self._known_pool_ids: set = set()
        self._known_market_ids: set = set()
        self._meta: dict = {}
        self._is_first_run: bool = False

    def load_state(self):
        """Load all state from Redis in a single HGETALL command."""
        raw = self.redis.hgetall(self.STATE_KEY)  # 1 Redis command

        if not raw:
            # Empty state — check if this is truly first run
            self._is_first_run = not self.redis.exists(self.INIT_KEY)  # 1 command
            logger.info("No state found in Redis (first run: %s)", self._is_first_run)
            return

        self._pools = json.loads(raw.get("pools", "{}"))
        self._markets = json.loads(raw.get("markets", "{}"))
        self._snapshots = json.loads(raw.get("snapshots", "{}"))
        self._known_pool_ids = set(json.loads(raw.get("known_pool_ids", "[]")))
        self._known_market_ids = set(json.loads(raw.get("known_market_ids", "[]")))
        self._meta = json.loads(raw.get("meta", "{}"))
        self._is_first_run = False

    def save_state(self, pools: list[Pool]):
        """Save all state to Redis after a cycle completes."""
        now = datetime.now(timezone.utc).isoformat()

        # Update pools and markets from current data
        for pool in pools:
            self._pools[pool.pool_id] = {
                "title": pool.title,
                "category": pool.category,
                "end_date": pool.end_date,
                "volume": pool.volume,
                "status": pool.status,
                "url": pool.url,
            }
            self._known_pool_ids.add(pool.pool_id)
            for opt in pool.options:
                mid = str(opt.market_id)
                self._markets[mid] = {"name": opt.name, "pool_id": pool.pool_id}
                self._known_market_ids.add(mid)
                # Update snapshot for this market (only keep latest)
                self._snapshots[mid] = {
                    "yes_pct": opt.yes_pct,
                    "no_pct": opt.no_pct,
                    "yes_multiplier": opt.yes_multiplier,
                    "no_multiplier": opt.no_multiplier,
                    "ts": now,
                }

        # Update metadata
        self._meta["last_cycle_ts"] = now
        self._meta["cycle_count"] = self._meta.get("cycle_count", 0) + 1

        # Write all state in a single HSET call with multiple fields — 1 Redis command
        self.redis.hset(
            self.STATE_KEY,
            values={
                "pools": json.dumps(self._pools),
                "markets": json.dumps(self._markets),
                "snapshots": json.dumps(self._snapshots),
                "known_pool_ids": json.dumps(sorted(self._known_pool_ids)),
                "known_market_ids": json.dumps(sorted(self._known_market_ids)),
                "meta": json.dumps(self._meta),
            },
        )

        # Mark as initialized on first run
        if self._is_first_run:
            self.redis.set(self.INIT_KEY, "1")

    # -- Query methods (use in-memory cache, zero Redis commands) --

    def get_known_pool_ids(self) -> set[str]:
        return self._known_pool_ids

    def get_known_market_ids(self) -> set[str]:
        """Returns set of market IDs as strings."""
        return self._known_market_ids

    def get_latest_snapshot(self, market_id: int) -> Optional[dict]:
        """Get latest snapshot from in-memory cache. Returns dict with yes_pct, no_pct, etc."""
        mid = str(market_id)
        return self._snapshots.get(mid)

    def is_first_run(self) -> bool:
        return self._is_first_run

    # -- Dedup methods (individual Redis commands with TTL) --

    def has_closing_alert_been_sent(self, pool_id: str, window: str) -> bool:
        key = f"{self.CLOSING_PREFIX}:{pool_id}:{window}"
        return bool(self.redis.exists(key))  # 1 command

    def record_closing_alert(self, pool_id: str, window: str):
        key = f"{self.CLOSING_PREFIX}:{pool_id}:{window}"
        self.redis.set(key, "1", ex=86400)  # TTL 24 hours, 1 command

    def is_odds_on_cooldown(self, market_id: int) -> bool:
        key = f"{self.COOLDOWN_PREFIX}:{market_id}"
        return bool(self.redis.exists(key))  # 1 command

    def record_odds_cooldown(self, market_id: int):
        key = f"{self.COOLDOWN_PREFIX}:{market_id}"
        ttl = config.ODDS_CHANGE_COOLDOWN_MINUTES * 60
        self.redis.set(key, "1", ex=ttl)  # 1 command

    # -- Error cooldown --

    def can_send_error_alert(self) -> bool:
        return not bool(self.redis.exists(self.ERROR_KEY))

    def record_error_alert(self):
        self.redis.set(self.ERROR_KEY, "1", ex=600)  # 10 min cooldown
