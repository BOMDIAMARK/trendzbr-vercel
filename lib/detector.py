import logging
from datetime import datetime, timezone

from lib import config
from lib.redis_store import RedisStore
from lib.models import Alert, Pool
from lib.utils import format_time_remaining

logger = logging.getLogger("trendzbr.detector")


class AlertDetector:
    def __init__(self, store: RedisStore):
        self.store = store

    def check_new_markets(self, current_pools: list[Pool]) -> list[Alert]:
        """Detect new pools and new options within existing pools."""
        alerts = []
        known_pool_ids = self.store.get_known_pool_ids()
        known_market_ids = self.store.get_known_market_ids()

        for pool in current_pools:
            if pool.pool_id not in known_pool_ids:
                # New pool detected
                options_text = ""
                for opt in pool.options[:5]:
                    options_text += f"  - {opt.name}: Sim {opt.yes_pct:.0f}% ({opt.yes_multiplier:.2f}x) / Nao {opt.no_pct:.0f}% ({opt.no_multiplier:.2f}x)\n"
                if len(pool.options) > 5:
                    options_text += f"  ... e mais {len(pool.options) - 5} opcoes\n"

                end_info = ""
                if pool.end_date:
                    try:
                        end_dt = datetime.fromisoformat(pool.end_date)
                        remaining = format_time_remaining(end_dt)
                        end_info = f"\n{_emoji('calendar')} Encerramento em: {remaining}"
                    except ValueError:
                        end_info = f"\n{_emoji('calendar')} Encerramento: {pool.end_date}"

                msg = (
                    f"{_emoji('new')} NOVO MERCADO\n\n"
                    f"{_emoji('chart')} {pool.title}\n"
                    f"{_emoji('folder')} Categoria: {pool.category}"
                    f"{end_info}\n\n"
                    f"Opcoes:\n{options_text}\n"
                    f"{_emoji('link')} {pool.url}"
                )

                alerts.append(Alert(
                    alert_type="new_market",
                    pool_id=pool.pool_id,
                    pool_title=pool.title,
                    category=pool.category,
                    message=msg,
                    url=pool.url,
                    priority="medium",
                ))
                logger.info(f"New pool detected: {pool.pool_id} - {pool.title}")
            else:
                # Check for new options in existing pool
                for opt in pool.options:
                    if str(opt.market_id) not in known_market_ids:
                        msg = (
                            f"{_emoji('new')} NOVA OPCAO EM MERCADO\n\n"
                            f"{_emoji('chart')} {pool.title}\n"
                            f"{_emoji('person')} {opt.name}\n"
                            f"Sim {opt.yes_pct:.0f}% ({opt.yes_multiplier:.2f}x) / "
                            f"Nao {opt.no_pct:.0f}% ({opt.no_multiplier:.2f}x)\n\n"
                            f"{_emoji('link')} {pool.url}"
                        )
                        alerts.append(Alert(
                            alert_type="new_market",
                            pool_id=pool.pool_id,
                            pool_title=pool.title,
                            category=pool.category,
                            message=msg,
                            url=pool.url,
                            priority="low",
                        ))
                        logger.info(f"New option detected: {opt.market_id} - {opt.name} in pool {pool.pool_id}")

        return alerts

    def check_odds_changes(self, current_pools: list[Pool]) -> list[Alert]:
        """Detect significant odds changes compared to last snapshot."""
        alerts = []

        for pool in current_pools:
            for opt in pool.options:
                prev = self.store.get_latest_snapshot(opt.market_id)
                if not prev:
                    continue

                prev_yes = prev["yes_pct"]
                curr_yes = opt.yes_pct
                change_pp = curr_yes - prev_yes

                if abs(change_pp) < config.ODDS_CHANGE_THRESHOLD_PP:
                    continue

                # Check cooldown via Redis TTL key
                if self.store.is_odds_on_cooldown(opt.market_id):
                    continue

                # Record cooldown
                self.store.record_odds_cooldown(opt.market_id)

                direction = _emoji("up") if change_pp > 0 else _emoji("down")
                priority = "high" if abs(change_pp) >= 20 else "medium"

                msg = (
                    f"{_emoji('chart_up')} MUDANCA DE ODDS\n\n"
                    f"{_emoji('chart')} {pool.title}\n"
                    f"{_emoji('person')} {opt.name}\n\n"
                    f"Antes: Sim {prev_yes:.0f}% ({prev['yes_multiplier']:.2f}x) / "
                    f"Nao {prev['no_pct']:.0f}% ({prev['no_multiplier']:.2f}x)\n"
                    f"Agora: Sim {opt.yes_pct:.0f}% ({opt.yes_multiplier:.2f}x) / "
                    f"Nao {opt.no_pct:.0f}% ({opt.no_multiplier:.2f}x)\n"
                    f"Variacao: {direction} {change_pp:+.1f}pp\n\n"
                    f"{_emoji('link')} {pool.url}"
                )

                alerts.append(Alert(
                    alert_type="odds_change",
                    pool_id=pool.pool_id,
                    pool_title=pool.title,
                    category=pool.category,
                    message=msg,
                    url=pool.url,
                    priority=priority,
                ))
                logger.info(
                    f"Odds change detected: {opt.name} in {pool.title} "
                    f"({prev_yes:.1f}% -> {curr_yes:.1f}%, {change_pp:+.1f}pp)"
                )

        return alerts

    def check_closing_soon(self, current_pools: list[Pool]) -> list[Alert]:
        """Detect markets that are about to close."""
        alerts = []
        now = datetime.now(timezone.utc)

        for pool in current_pools:
            if not pool.end_date:
                continue

            try:
                end_dt = datetime.fromisoformat(pool.end_date)
            except ValueError:
                continue

            time_left = end_dt - now
            if time_left.total_seconds() <= 0:
                continue

            hours_left = time_left.total_seconds() / 3600

            for window_hours in config.CLOSING_WINDOWS_HOURS:
                if hours_left > window_hours:
                    continue

                window_key = f"{window_hours}h"
                if self.store.has_closing_alert_been_sent(pool.pool_id, window_key):
                    continue

                if window_hours <= 1:
                    priority = "high"
                elif window_hours <= 6:
                    priority = "medium"
                else:
                    priority = "low"

                remaining = format_time_remaining(end_dt)

                status_lines = ""
                sorted_opts = sorted(pool.options, key=lambda o: o.yes_pct, reverse=True)
                for opt in sorted_opts[:5]:
                    status_lines += f"  - {opt.name}: {opt.yes_pct:.0f}% (Sim {opt.yes_multiplier:.2f}x)\n"

                msg = (
                    f"{_emoji('clock')} MERCADO FECHANDO EM BREVE\n\n"
                    f"{_emoji('chart')} {pool.title}\n"
                    f"{_emoji('folder')} Categoria: {pool.category}\n"
                    f"{_emoji('hourglass')} Fecha em: ~{remaining}\n\n"
                    f"Situacao atual:\n{status_lines}\n"
                    f"{_emoji('link')} {pool.url}"
                )

                alerts.append(Alert(
                    alert_type="closing_soon",
                    pool_id=pool.pool_id,
                    pool_title=pool.title,
                    category=pool.category,
                    message=msg,
                    url=pool.url,
                    priority=priority,
                ))

                # Record that we sent this window alert
                self.store.record_closing_alert(pool.pool_id, window_key)
                logger.info(
                    f"Closing soon alert: {pool.title} closes in ~{remaining} "
                    f"(window: {window_key})"
                )
                break  # Only alert for the most urgent window

        return alerts


def _emoji(name: str) -> str:
    """Return emoji by name for Telegram messages."""
    emojis = {
        "new": "\U0001F195",       # 🆕
        "chart": "\U0001F4CA",     # 📊
        "chart_up": "\U0001F4C8",  # 📈
        "folder": "\U0001F4C1",    # 📁
        "calendar": "\U0001F4C5",  # 📅
        "clock": "\u23F0",         # ⏰
        "hourglass": "\u23F3",     # ⏳
        "link": "\U0001F517",      # 🔗
        "person": "\U0001F464",    # 👤
        "up": "\u2B06\uFE0F",     # ⬆️
        "down": "\u2B07\uFE0F",   # ⬇️
        "green": "\U0001F7E2",     # 🟢
        "red": "\U0001F534",       # 🔴
        "warning": "\u26A0\uFE0F", # ⚠️
    }
    return emojis.get(name, "")
