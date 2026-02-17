"""
Health check endpoint — GET /api/health
Returns Redis connectivity status, last cycle info for both monitors.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = {"service": "TrendzBR Platform", "status": "ok"}

        try:
            from upstash_redis import Redis
            redis = Redis(
                url=config.UPSTASH_REDIS_REST_URL,
                token=config.UPSTASH_REDIS_REST_TOKEN,
            )

            # Market monitor status
            market_meta_raw = redis.hget("trendzbr:state", "meta")
            if market_meta_raw:
                meta = json.loads(market_meta_raw)
                status["market_monitor"] = {
                    "last_cycle": meta.get("last_cycle_ts"),
                    "cycle_count": meta.get("cycle_count"),
                }
            else:
                status["market_monitor"] = {"note": "Not yet started"}

            # Social monitor status
            social_meta_raw = redis.hgetall("social:meta")
            if social_meta_raw:
                status["social_monitor"] = {
                    "last_cycle": social_meta_raw.get("last_cycle_ts"),
                    "cycle_count": int(social_meta_raw.get("cycle_count", 0)),
                    "instagram_profiles": config.INSTAGRAM_PROFILES,
                    "twitter_profiles": config.TWITTER_PROFILES,
                }
            else:
                status["social_monitor"] = {"note": "Not yet started"}

            status["redis"] = "connected"
        except Exception as e:
            status["status"] = "error"
            status["redis"] = "error"
            status["redis_error"] = str(e)

        code = 200 if status["status"] == "ok" else 503
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(status, indent=2).encode())

    def log_message(self, format, *args):
        pass
