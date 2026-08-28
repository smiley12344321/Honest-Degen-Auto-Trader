import datetime
from typing import Optional, Dict, Any
import requests

from config.settings import DISCORD_WEBHOOK_URL, KALSHI_ENV
from src.sheet_reader import PickRecord


class DiscordNotifier:
    """
    Handles Discord webhook notifications for trade actions, skips, and errors.
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or DISCORD_WEBHOOK_URL

    def _post(self, payload: Dict[str, Any]) -> bool:
        if not self.webhook_url:
            return False
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            return resp.status_code in (200, 204)
        except Exception as e:
            print(f"[DiscordNotifier] Failed to send webhook: {e}")
            return False

    def notify_trade_placed(
        self,
        pick: PickRecord,
        kalshi_ticker: str,
        kalshi_price_cents: int,
        count_fp: str,
        total_risk_dollars: float,
        mode: Optional[str] = None
    ) -> bool:
        env_label = (mode or KALSHI_ENV).upper()
        color = 0x2ECC71  # Green
        
        embed = {
            "title": f"🎯 [{env_label}] Trade Placed: {pick.play}",
            "color": color,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fields": [
                {"name": "Sport / Market", "value": f"{pick.sport} • {pick.market}", "inline": True},
                {"name": "Sheet Odds / Target", "value": f"{pick.odds_raw} (~{pick.implied_cents}¢)", "inline": True},
                {"name": "Kalshi Fill Price", "value": f"{kalshi_price_cents}¢", "inline": True},
                {"name": "Units", "value": f"{pick.units}u (Grade: {pick.grade or 'N/A'})", "inline": True},
                {"name": "Contracts", "value": f"{count_fp} contracts", "inline": True},
                {"name": "Total Risk", "value": f"${total_risk_dollars:.2f}", "inline": True},
                {"name": "Kalshi Ticker", "value": f"`{kalshi_ticker}`", "inline": False},
                {"name": "Notes", "value": pick.notes[:300] if pick.notes else "None", "inline": False},
            ],
            "footer": {"text": "Honest Degen Auto Picker • GitHub Actions"}
        }
        return self._post({"embeds": [embed]})

    def notify_trade_skipped_price(
        self,
        pick: PickRecord,
        target_cents: int,
        kalshi_ask_cents: int,
        max_buy_cents: int
    ) -> bool:
        color = 0xF39C12  # Orange
        price_diff = kalshi_ask_cents - target_cents
        
        embed = {
            "title": f"⚠️ Price Slippage Exceeded: {pick.play}",
            "color": color,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "description": (
                f"Kalshi ask price ({kalshi_ask_cents}¢) exceeds acceptable threshold ({max_buy_cents}¢). "
                f"Slippage: +{price_diff}¢ above sheet fair value ({target_cents}¢)."
            ),
            "fields": [
                {"name": "Sport / Market", "value": f"{pick.sport} • {pick.market}", "inline": True},
                {"name": "Sheet Odds", "value": f"{pick.odds_raw}", "inline": True},
                {"name": "Units", "value": f"{pick.units}u", "inline": True},
            ],
            "footer": {"text": "Honest Degen Auto Picker • Skipped"}
        }
        return self._post({"embeds": [embed]})

    def notify_trade_skipped_unmapped(
        self,
        pick: PickRecord,
        reason: str
    ) -> bool:
        color = 0x95A5A6  # Grey
        
        embed = {
            "title": f"ℹ️ Market Skipped: {pick.play}",
            "color": color,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "description": f"Reason: {reason}",
            "fields": [
                {"name": "Sport / Market", "value": f"{pick.sport} • {pick.market}", "inline": True},
                {"name": "Sheet Odds", "value": f"{pick.odds_raw}", "inline": True},
            ],
            "footer": {"text": "Honest Degen Auto Picker • Skipped"}
        }
        return self._post({"embeds": [embed]})

    def notify_cycle_summary(
        self,
        placed_count: int,
        skipped_count: int,
        error_count: int,
        mode: Optional[str] = None
    ) -> bool:
        if placed_count == 0 and skipped_count == 0 and error_count == 0:
            return False  # Skip sending empty heartbeats unless desired
        
        env_label = (mode or KALSHI_ENV).upper()
        color = 0x3498DB  # Blue
        
        embed = {
            "title": f"📊 [{env_label}] Run Complete",
            "color": color,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "fields": [
                {"name": "Trades Placed", "value": str(placed_count), "inline": True},
                {"name": "Trades Skipped", "value": str(skipped_count), "inline": True},
                {"name": "Errors", "value": str(error_count), "inline": True},
            ],
            "footer": {"text": "Honest Degen Auto Picker"}
        }
        return self._post({"embeds": [embed]})

    def notify_error(self, title: str, message: str) -> bool:
        color = 0xE74C3C  # Red
        embed = {
            "title": f"🚨 Error: {title}",
            "color": color,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "description": message[:1500],
            "footer": {"text": "Honest Degen Auto Picker • Alert"}
        }
        return self._post({"embeds": [embed]})
