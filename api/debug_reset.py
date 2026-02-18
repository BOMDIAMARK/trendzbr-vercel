"""Temporary debug endpoint to remove a post ID from seen set."""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        from upstash_redis import Redis
        redis = Redis(
            url=config.UPSTASH_REDIS_REST_URL,
            token=config.UPSTASH_REDIS_REST_TOKEN,
        )

        # Remove specific post from seen
        removed = redis.srem("social:seen:instagram", "DU4JYcgidaQ")
        remaining = redis.smembers("social:seen:instagram")

        result = {
            "removed_DU4JYcgidaQ": removed,
            "remaining_ids": list(remaining) if remaining else [],
            "remaining_count": len(remaining) if remaining else 0,
        }

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result, indent=2).encode())

    def log_message(self, format, *args):
        pass
