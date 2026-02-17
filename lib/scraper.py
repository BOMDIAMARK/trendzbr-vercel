import json
import logging
import re
import time
from datetime import datetime, timezone

import requests

from lib import config
from lib.models import MarketOption, Pool

logger = logging.getLogger("trendzbr.scraper")


class TrendzBRScraper:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
        })

    def fetch_all_pools(self) -> list[Pool]:
        """Fetch all markets from the TrendzBR homepage by extracting RSC flight data."""
        try:
            resp = self.session.get(config.TRENDZBR_HOME_URL, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            html = resp.text
            return self._parse_flight_data(html)
        except requests.RequestException as e:
            logger.error(f"Failed to fetch homepage: {e}")
            return []

    def _parse_flight_data(self, html: str) -> list[Pool]:
        """Extract initialMarkets from Next.js RSC flight data embedded in HTML."""
        pools = []

        escaped_marker = '\\"initialMarkets\\":'
        plain_marker = '"initialMarkets":'

        idx = html.find(escaped_marker)
        is_escaped = idx >= 0
        if idx < 0:
            idx = html.find(plain_marker)
        if idx < 0:
            logger.warning("initialMarkets not found in HTML, trying fallback")
            return self._parse_html_fallback(html)

        if is_escaped:
            chunk_start = idx
            chunk = html[chunk_start:]
            chunk = chunk.replace('\\"', '"').replace('\\\\', '\\')
            marker = '"initialMarkets":'
            arr_start = chunk.find(marker) + len(marker)
        else:
            chunk = html[idx:]
            arr_start = len(plain_marker)

        json_str = self._extract_json_array(chunk, arr_start)
        if not json_str:
            logger.warning("Could not extract initialMarkets JSON array")
            return self._parse_html_fallback(html)

        try:
            raw_markets = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse initialMarkets JSON: {e}")
            return self._parse_html_fallback(html)

        for raw in raw_markets:
            pool = self._raw_to_pool(raw)
            if pool:
                pools.append(pool)

        logger.info(f"Parsed {len(pools)} pools from flight data")
        return pools

    def _extract_json_array(self, text: str, start: int) -> str | None:
        """Extract a JSON array starting at position start in text."""
        if start >= len(text) or text[start] != '[':
            return None
        depth = 0
        in_string = False
        escape_next = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        return None

    def _raw_to_pool(self, raw: dict) -> Pool | None:
        """Convert a raw market dict from the API into a Pool object."""
        try:
            pool_id = str(raw.get("id", ""))
            title = raw.get("question", "")
            category = raw.get("category", {}).get("name", "") if raw.get("category") else ""

            sub_markets = raw.get("markets", [])
            options = []

            for sm in sub_markets:
                sm_id = int(sm.get("id", 0))
                sm_question = sm.get("question", "")
                hype_price = float(sm.get("hypePrice", 0.5))
                flop_price = float(sm.get("flopPrice", 0.5))

                yes_pct = round(hype_price * 100, 2)
                no_pct = round(flop_price * 100, 2)
                yes_mult = round(1.0 / hype_price, 2) if hype_price > 0.01 else 0.0
                no_mult = round(1.0 / flop_price, 2) if flop_price > 0.01 else 0.0

                options.append(MarketOption(
                    market_id=sm_id,
                    name=sm_question,
                    yes_multiplier=yes_mult,
                    no_multiplier=no_mult,
                    yes_pct=yes_pct,
                    no_pct=no_pct,
                ))

            end_date = None
            if sub_markets:
                market_end_ts = sub_markets[0].get("marketEnd")
                if market_end_ts:
                    end_date = datetime.fromtimestamp(market_end_ts, tz=timezone.utc).isoformat()

            from lib.utils import title_to_slug
            slug = title_to_slug(title)
            first_market_id = sub_markets[0]["id"] if sub_markets else pool_id
            url = config.TRENDZBR_MARKET_URL.format(market_id=first_market_id, slug=slug)

            volume = None
            if sub_markets:
                total = sum(float(sm.get("totalVolume", 0)) for sm in sub_markets)
                if total > 0:
                    volume = f"R${total:,.2f}"

            return Pool(
                pool_id=pool_id,
                title=title,
                category=category,
                end_date=end_date,
                volume=volume,
                status="Official" if raw.get("category", {}).get("authority") else "",
                options=options,
                url=url,
            )
        except Exception as e:
            logger.error(f"Failed to parse pool {raw.get('id', '?')}: {e}")
            return None

    def _parse_html_fallback(self, html: str) -> list[Pool]:
        """Fallback: parse market data from HTML structure when flight data is unavailable."""
        logger.info("Using HTML fallback parser")
        pools = []
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text()
            logger.warning(f"HTML fallback: extracted {len(text)} chars of text, but structured parsing not available")
        except ImportError:
            logger.warning("BeautifulSoup not available for fallback parsing")
        return pools

    def fetch_orderbook(self, market_id: int) -> dict | None:
        """Fetch orderbook data from TriadFi API for a specific market."""
        url = config.TRIADFI_ORDERBOOK_URL.format(market_id=market_id)
        try:
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch orderbook for market {market_id}: {e}")
            return None

    def fetch_activity(self, market_id: int) -> list[dict]:
        """Fetch recent activity/trades for a market."""
        url = config.TRIADFI_ACTIVITY_URL.format(market_id=market_id)
        try:
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []
        except requests.RequestException as e:
            logger.error(f"Failed to fetch activity for market {market_id}: {e}")
            return []

    def orderbook_to_probability(self, orderbook: dict) -> tuple[float, float]:
        """Convert TriadFi orderbook to Yes/No probabilities (percentages)."""
        try:
            hype_bids = orderbook.get("hype", {}).get("bid", [])
            flop_bids = orderbook.get("flop", {}).get("bid", [])
            yes_prob = 50.0
            no_prob = 50.0
            if hype_bids:
                best_hype = max(hype_bids, key=lambda x: int(x.get("price", 0)))
                yes_prob = int(best_hype["price"]) / 1_000_000 * 100
            if flop_bids:
                best_flop = max(flop_bids, key=lambda x: int(x.get("price", 0)))
                no_prob = int(best_flop["price"]) / 1_000_000 * 100
            return round(yes_prob, 2), round(no_prob, 2)
        except Exception as e:
            logger.error(f"Failed to parse orderbook probabilities: {e}")
            return 50.0, 50.0
