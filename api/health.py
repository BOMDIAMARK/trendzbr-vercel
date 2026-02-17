"""
Health check endpoint — GET /api/health
Returns Redis connectivity status and last cycle info.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status = {"service": "TrendzBR Monitor", "status": "ok"}

        try:
            from upstash_redis import Redis
            redis = Redis(
                url=config.UPSTASH_REDIS_REST_URL,
                token=config.UPSTASH_REDIS_REST_TOKEN,
            )
            meta_raw = redis.hget("trendzbr:state", "meta")
            if meta_raw:
                meta = json.loads(meta_raw)
                status["last_cycle"] = meta.get("last_cycle_ts")
                status["cycle_count"] = meta.get("cycle_count")
            else:
                status["note"] = "No state found (system may not have run yet)"
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
