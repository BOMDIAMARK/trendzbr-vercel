"""
Telegram Bot Commands Webhook — POST /api/bot_commands
Handles commands sent to @trendzbr_alerts_bot in private chat.

Commands:
  /mercados   — List all active markets with status
  /paredao    — Show BBB Paredão details
  /fechando   — Show markets closing within 24h
  /verificar  — Force a monitoring cycle now
  /status     — Show bot and monitor status
  /help       — Show available commands
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import config
from lib.utils import setup_logging, format_time_remaining

logger = setup_logging()

# Only respond to this user (owner)
# Accept from env var OR hardcoded owner ID
OWNER_CHAT_ID = config.TELEGRAM_CHAT_ID or "8572258485"


def send_reply(chat_id, text, parse_mode="HTML"):
    """Send a reply message via Telegram API."""
    import requests
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error("Failed to send reply: %s", e)
        return False


def cmd_mercados(chat_id):
    """List all active markets."""
    from lib.scraper import TrendzBRScraper
    scraper = TrendzBRScraper()
    pools = scraper.fetch_all_pools()

    if not pools:
        send_reply(chat_id, "⚠️ Nenhum mercado encontrado.")
        return

    now = datetime.now(timezone.utc)
    lines = [f"📊 <b>Mercados Ativos ({len(pools)})</b>\n"]

    for pool in pools:
        # Time remaining
        time_info = ""
        if pool.end_date:
            try:
                end_dt = datetime.fromisoformat(pool.end_date)
                remaining = format_time_remaining(end_dt)
                hours_left = (end_dt - now).total_seconds() / 3600
                if hours_left <= 0:
                    time_info = "❌ Encerrado"
                elif hours_left <= 6:
                    time_info = f"🔴 {remaining}"
                elif hours_left <= 24:
                    time_info = f"🟡 {remaining}"
                else:
                    time_info = f"🟢 {remaining}"
            except ValueError:
                time_info = "?"

        # Top option
        top_opt = ""
        if pool.options:
            best = max(pool.options, key=lambda o: o.yes_pct)
            top_opt = f" | Top: {best.name[:18]} {best.yes_pct:.0f}%"

        title_short = pool.title[:45]
        lines.append(f"• <b>{title_short}</b>")
        lines.append(f"  ⏳ {time_info}{top_opt}")
        lines.append("")

    send_reply(chat_id, "\n".join(lines))


def cmd_paredao(chat_id):
    """Show Paredão-related markets in detail."""
    from lib.scraper import TrendzBRScraper
    scraper = TrendzBRScraper()
    pools = scraper.fetch_all_pools()

    paredao_pools = [p for p in pools if "pared" in p.title.lower()]

    if not paredao_pools:
        send_reply(chat_id, "ℹ️ Nenhum mercado de Paredão encontrado no momento.")
        return

    now = datetime.now(timezone.utc)

    for pool in paredao_pools:
        lines = [f"📊 <b>{pool.title}</b>\n"]

        if pool.end_date:
            try:
                end_dt = datetime.fromisoformat(pool.end_date)
                remaining = format_time_remaining(end_dt)
                hours_left = (end_dt - now).total_seconds() / 3600
                if hours_left <= 6:
                    emoji = "🔴"
                elif hours_left <= 24:
                    emoji = "🟡"
                else:
                    emoji = "🟢"
                lines.append(f"{emoji} Fecha em: <b>{remaining}</b>")
            except ValueError:
                pass

        if pool.category:
            lines.append(f"📁 {pool.category}")
        if pool.volume:
            lines.append(f"💰 Volume: {pool.volume}")

        lines.append("")
        lines.append("<b>Opções:</b>")

        sorted_opts = sorted(pool.options, key=lambda o: o.yes_pct, reverse=True)
        for i, opt in enumerate(sorted_opts):
            medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f" {i+1}."
            lines.append(
                f"{medal} {opt.name}\n"
                f"   ✅ Sim: {opt.yes_pct:.0f}% ({opt.yes_multiplier:.2f}x) "
                f"| ❌ Não: {opt.no_pct:.0f}% ({opt.no_multiplier:.2f}x)"
            )

        lines.append(f"\n🔗 {pool.url}")
        send_reply(chat_id, "\n".join(lines))


def cmd_fechando(chat_id):
    """Show markets closing within 24h."""
    from lib.scraper import TrendzBRScraper
    scraper = TrendzBRScraper()
    pools = scraper.fetch_all_pools()

    now = datetime.now(timezone.utc)
    closing = []

    for pool in pools:
        if not pool.end_date:
            continue
        try:
            end_dt = datetime.fromisoformat(pool.end_date)
            hours_left = (end_dt - now).total_seconds() / 3600
            if 0 < hours_left <= 24:
                closing.append((pool, hours_left, end_dt))
        except ValueError:
            continue

    if not closing:
        send_reply(chat_id, "✅ Nenhum mercado fecha nas próximas 24h.")
        return

    closing.sort(key=lambda x: x[1])
    lines = [f"⏰ <b>Mercados Fechando em 24h ({len(closing)})</b>\n"]

    for pool, hours_left, end_dt in closing:
        remaining = format_time_remaining(end_dt)
        emoji = "🔴" if hours_left <= 6 else "🟡"

        lines.append(f"{emoji} <b>{pool.title[:50]}</b>")
        lines.append(f"   ⏳ Fecha em: {remaining}")

        if pool.options:
            best = max(pool.options, key=lambda o: o.yes_pct)
            lines.append(f"   🏆 Top: {best.name[:25]} ({best.yes_pct:.0f}%)")

        lines.append(f"   🔗 {pool.url}")
        lines.append("")

    send_reply(chat_id, "\n".join(lines))


def cmd_verificar(chat_id):
    """Force a monitoring cycle and report results."""
    send_reply(chat_id, "🔄 Executando verificação...")

    try:
        from lib.scraper import TrendzBRScraper
        from lib.detector import AlertDetector
        from lib.redis_store import RedisStore
        from lib.telegram_sender import TelegramSender

        store = RedisStore()
        store.load_state()
        scraper = TrendzBRScraper()
        detector = AlertDetector(store)
        sender = TelegramSender()

        pools = scraper.fetch_all_pools()
        if not pools:
            send_reply(chat_id, "⚠️ Nenhum mercado encontrado.")
            return

        alerts = []
        if not store.is_first_run():
            alerts.extend(detector.check_new_markets(pools))
            alerts.extend(detector.check_odds_changes(pools))
            alerts.extend(detector.check_closing_soon(pools))

        sent_count = 0
        if alerts:
            sent_count = sender.send_alerts_batch(alerts)

        store.save_state(pools)

        lines = [
            "✅ <b>Verificação concluída</b>\n",
            f"📊 Mercados: {len(pools)}",
            f"📢 Alertas detectados: {len(alerts)}",
            f"📤 Alertas enviados: {sent_count}",
        ]

        if not alerts:
            lines.append("\nℹ️ Nenhuma mudança significativa detectada.")

        send_reply(chat_id, "\n".join(lines))

    except Exception as e:
        send_reply(chat_id, f"❌ Erro na verificação: {str(e)[:200]}")


def cmd_status(chat_id):
    """Show system status."""
    try:
        from lib.redis_store import RedisStore
        from lib.social_store import SocialStore

        # Market monitor
        store = RedisStore()
        store.load_state()
        meta = store._meta

        lines = ["📡 <b>Status do Sistema</b>\n"]

        # Market monitor info
        last_cycle = meta.get("last_cycle_ts", "N/A")
        cycle_count = meta.get("cycle_count", 0)
        lines.append("<b>🔹 Market Monitor</b>")
        lines.append(f"   Último ciclo: {last_cycle[:19] if last_cycle != 'N/A' else 'N/A'}")
        lines.append(f"   Total de ciclos: {cycle_count}")
        lines.append(f"   Intervalo: a cada 5 min")
        lines.append("")

        # Social monitor info
        social_store = SocialStore()
        social_meta = social_store.get_meta()

        lines.append("<b>🔹 Social Monitor</b>")
        s_last = social_meta.get("last_cycle_ts", "N/A")
        s_count = social_meta.get("cycle_count", "0")
        lines.append(f"   Último ciclo: {s_last[:19] if s_last != 'N/A' else 'N/A'}")
        lines.append(f"   Total de ciclos: {s_count}")
        lines.append(f"   Instagram: {', '.join(config.INSTAGRAM_PROFILES)}")
        lines.append(f"   Twitter: {', '.join(config.TWITTER_PROFILES)}")
        lines.append(f"   Intervalo: a cada 10 min")
        lines.append("")

        # Config info
        lines.append("<b>🔹 Configuração</b>")
        lines.append(f"   Threshold odds: {config.ODDS_CHANGE_THRESHOLD_PP}pp")
        lines.append(f"   Cooldown odds: {config.ODDS_CHANGE_COOLDOWN_MINUTES}min")
        lines.append(f"   Janelas fechamento: {config.CLOSING_WINDOWS_HOURS}")

        send_reply(chat_id, "\n".join(lines))

    except Exception as e:
        send_reply(chat_id, f"❌ Erro ao obter status: {str(e)[:200]}")


def cmd_help(chat_id):
    """Show available commands."""
    text = (
        "🤖 <b>TrendzBR Alertas — Comandos</b>\n\n"
        "/mercados — Lista todos os mercados ativos\n"
        "/paredao — Detalhes dos mercados de Paredão\n"
        "/fechando — Mercados que fecham em 24h\n"
        "/verificar — Forçar verificação agora\n"
        "/status — Status do sistema\n"
        "/help — Mostrar esta ajuda"
    )
    send_reply(chat_id, text)


COMMANDS = {
    "/mercados": cmd_mercados,
    "/paredao": cmd_paredao,
    "/fechando": cmd_fechando,
    "/verificar": cmd_verificar,
    "/status": cmd_status,
    "/help": cmd_help,
    "/start": cmd_help,
}


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        """Handle Telegram webhook updates."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            update = json.loads(body)

            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = (message.get("text", "") or "").strip()

            # Only respond in private chat to the owner
            chat_type = message.get("chat", {}).get("type", "")
            if chat_type != "private":
                self._ok()
                return

            if not chat_id or chat_id != OWNER_CHAT_ID:
                logger.info("Ignoring message from non-owner chat_id=%s (owner=%s)", chat_id, OWNER_CHAT_ID)
                self._ok()
                return

            # Extract command (handle /command@botname format)
            cmd = text.split()[0].lower() if text else ""
            if "@" in cmd:
                cmd = cmd.split("@")[0]

            handler_fn = COMMANDS.get(cmd)
            if handler_fn:
                handler_fn(chat_id)
            elif text.startswith("/"):
                send_reply(chat_id, "❓ Comando desconhecido. Use /help para ver os comandos.")

        except Exception as e:
            logger.error("Webhook error: %s", e, exc_info=True)

        self._ok()

    def _ok(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, format, *args):
        pass
