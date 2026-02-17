from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MarketOption:
    """A single option within a pool (e.g., one BBB contestant)."""
    market_id: int
    name: str
    yes_multiplier: float = 0.0
    no_multiplier: float = 0.0
    yes_pct: float = 50.0
    no_pct: float = 50.0


@dataclass
class Pool:
    """A prediction market pool (may contain multiple options/sub-markets)."""
    pool_id: str
    title: str
    category: str = ""
    end_date: Optional[str] = None
    volume: Optional[str] = None
    status: str = ""
    options: list[MarketOption] = field(default_factory=list)
    url: str = ""


@dataclass
class Alert:
    """An alert to send via Telegram."""
    alert_type: str  # "new_market", "odds_change", "closing_soon"
    pool_id: str
    pool_title: str
    category: str
    message: str
    url: str
    priority: str = "medium"  # "high", "medium", "low"
