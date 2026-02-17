import logging
import re
import sys
from datetime import datetime, timezone

from dateutil import parser as dateparser

from lib import config


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("trendzbr")
    logger.setLevel(getattr(logging, config.LOG_LEVEL.upper(), logging.INFO))

    if not logger.handlers:
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    return logger


def parse_end_date(date_str: str) -> datetime | None:
    """Parse end date strings like 'Apr 21, 2026' or 'Feb 18, 09:00' or 'Dec 31, 09:00'."""
    if not date_str:
        return None
    try:
        dt = dateparser.parse(date_str)
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except (ValueError, OverflowError):
        pass
    return None


def title_to_slug(title: str) -> str:
    """Convert a market title to a URL slug."""
    slug = title.lower().strip()
    slug = re.sub(r'[àáâãä]', 'a', slug)
    slug = re.sub(r'[èéêë]', 'e', slug)
    slug = re.sub(r'[ìíîï]', 'i', slug)
    slug = re.sub(r'[òóôõö]', 'o', slug)
    slug = re.sub(r'[ùúûü]', 'u', slug)
    slug = re.sub(r'[ç]', 'c', slug)
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s]+', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


def format_time_remaining(dt: datetime) -> str:
    """Format remaining time as a human-readable string in Portuguese."""
    now = datetime.now(timezone.utc)
    delta = dt - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "ja encerrado"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes}min")

    return " ".join(parts) if parts else "< 1min"
