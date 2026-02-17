import os

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Polling (used by QStash, kept for reference)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL", "300"))

# Alert thresholds
ODDS_CHANGE_THRESHOLD_PP = float(os.environ.get("ODDS_CHANGE_THRESHOLD", "10.0"))
ODDS_CHANGE_COOLDOWN_MINUTES = int(os.environ.get("ODDS_COOLDOWN", "30"))

# Closing soon alert windows (hours before close)
CLOSING_WINDOWS_HOURS = [24, 6, 1]

# Rate limits per cycle
MAX_TELEGRAM_MESSAGES_PER_CYCLE = 20
TELEGRAM_SEND_DELAY_SECONDS = 1.0

# URLs
TRENDZBR_HOME_URL = "https://www.trendzbr.com/"
TRENDZBR_MARKET_URL = "https://www.trendzbr.com/market/{market_id}?question={slug}"
TRIADFI_API_BASE = "https://beta.triadfi.co/api"
TRIADFI_ORDERBOOK_URL = TRIADFI_API_BASE + "/market/{market_id}/orderbook"
TRIADFI_ACTIVITY_URL = TRIADFI_API_BASE + "/market/{market_id}/activity"
CATEGORIES_URL = "https://www.trendzbr.com/api/market/categories/total?authority=91rdKje7oqxRCSMWzHYPe8tj7esVjbs9Ege2p4Z6e16V"

# Upstash Redis
UPSTASH_REDIS_REST_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")

# Logging
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Request settings
REQUEST_TIMEOUT = 30
USER_AGENT = "TrendzBR-AlertBot/2.0"
