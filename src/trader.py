import datetime
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from config.settings import (
    PLACED_TRADES_FILE,
    UNIT_SIZE_DOLLARS,
    PRICE_SLIPPAGE_TOLERANCE_CENTS,
    ALLOW_FRACTIONAL_CONTRACTS,
    KALSHI_ENV
)
from src.sheet_reader import get_active_picks, PickRecord
from src.odds_converter import calculate_sizing, is_price_acceptable
from src.kalshi_client import KalshiClient
from src.market_matcher import MarketMatcher
from src.notifier import DiscordNotifier


class Trader:
    """
    Core orchestrator that runs the end-to-end trading loop:
    Reads sheet -> Matches Kalshi market -> Checks price threshold -> Executes order -> Updates ledger & alerts Discord.
    """

    def __init__(
        self,
        kalshi_client: Optional[KalshiClient] = None,
        notifier: Optional[DiscordNotifier] = None,
        state_file: Path = PLACED_TRADES_FILE,
        unit_size_dollars: Optional[float] = None,
        slippage_tolerance_cents: Optional[int] = None,
        allow_fractional: Optional[bool] = None
    ):
        self.client = kalshi_client or KalshiClient()
        self.matcher = MarketMatcher(self.client)
        self.notifier = notifier or DiscordNotifier()
        self.state_file = Path(state_file)
        self.unit_size_dollars = unit_size_dollars if unit_size_dollars is not None else UNIT_SIZE_DOLLARS
        self.slippage_tolerance_cents = slippage_tolerance_cents if slippage_tolerance_cents is not None else PRICE_SLIPPAGE_TOLERANCE_CENTS
        self.allow_fractional = allow_fractional if allow_fractional is not None else ALLOW_FRACTIONAL_CONTRACTS
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_file.exists():
            return {"version": "1.0", "last_updated": None, "trades": {}}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Trader] Warning: Could not read state file: {e}")
            return {"version": "1.0", "last_updated": None, "trades": {}}

    def _save_state(self) -> None:
        self.state["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"[Trader] Error writing state file: {e}")

    def run_cycle(
        self,
        picks: Optional[List[PickRecord]] = None,
        live_events: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
        unit_size_dollars: Optional[float] = None
    ) -> Dict[str, int]:
        """
        Executes one full run cycle.
        """
        effective_unit_size = unit_size_dollars if unit_size_dollars is not None else self.unit_size_dollars
        placed_count = 0
        skipped_count = 0
        error_count = 0

        print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting Auto Picker run cycle...")
        
        if picks is None:
            try:
                active_picks = get_active_picks()
            except Exception as e:
                err_msg = f"Failed to fetch active picks from Google Sheet: {e}"
                print(f"[Trader] {err_msg}")
                self.notifier.notify_error("Sheet Reader Failure", err_msg)
                return {"placed": 0, "skipped": 0, "errors": 1}
        else:
            active_picks = picks

        print(f"[Trader] Found {len(active_picks)} active picks to evaluate.")

        # Fetch open Kalshi events if not passed
        if live_events is None:
            try:
                live_events = self.client.get_events(status="open")
            except Exception as e:
                print(f"[Trader] Notice: Could not fetch Kalshi events (offline or API issue): {e}")
                live_events = []

        for pick in active_picks:
            # 1. Deduplication check
            if pick.trade_id in self.state.get("trades", {}):
                print(f"[Trader] Skipping already placed trade: {pick.play} (ID: {pick.trade_id})")
                continue

            print(f"\n[Trader] Processing pick: [{pick.sport}] {pick.play} ({pick.market}) @ {pick.odds_raw}")

            # 2. Market matching
            match = self.matcher.match_pick(pick, live_events=live_events)
            if not match.matched:
                print(f"[Trader] Match skipped: {match.reason}")
                if match.unsupported:
                    self.notifier.notify_trade_skipped_unmapped(pick, match.reason or "Unsupported market format")
                skipped_count += 1
                continue

            # 3. Price & Slippage Evaluation
            ticker = match.ticker
            ask_cents = self.client.get_best_ask_cents(ticker, side=match.side)
            
            # If no live orderbook price returned, fallback to target cents from sheet odds
            if ask_cents is None:
                ask_cents = pick.implied_cents or 50
                print(f"[Trader] No live ask depth found; using sheet target price {ask_cents}¢.")

            if pick.odds_numeric is not None:
                is_acceptable, target_cents, max_buy_cents, delta = is_price_acceptable(
                    sheet_odds=pick.odds_numeric,
                    kalshi_ask_cents=ask_cents,
                    slippage_tolerance_cents=self.slippage_tolerance_cents
                )
                if not is_acceptable:
                    print(
                        f"[Trader] Price rejected for {pick.play}: Ask is {ask_cents}¢ "
                        f"(Target: {target_cents}¢, Max Allowed: {max_buy_cents}¢, Delta: +{delta}¢)"
                    )
                    self.notifier.notify_trade_skipped_price(pick, target_cents, ask_cents, max_buy_cents)
                    skipped_count += 1
                    continue
            else:
                target_cents = ask_cents

            # 4. Sizing calculation (configurable base unit, fractional or whole contract count)
            sizing = calculate_sizing(
                units=pick.units,
                unit_size_dollars=effective_unit_size,
                price_cents=ask_cents,
                allow_fractional=self.allow_fractional
            )

            # 5. Order execution
            try:
                order_result = self.client.create_order(
                    ticker=ticker,
                    side=match.side,
                    count_fp=sizing["count_fp"],
                    price_cents=ask_cents,
                    dry_run=dry_run
                )
                
                order_id = order_result.get("order_id") or order_result.get("client_order_id")
                
                # 6. Record to state ledger
                self.state["trades"][pick.trade_id] = {
                    "trade_id": pick.trade_id,
                    "date_placed": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "play": pick.play,
                    "sport": pick.sport,
                    "market": pick.market,
                    "sheet_odds": pick.odds_raw,
                    "units": pick.units,
                    "kalshi_ticker": ticker,
                    "kalshi_side": match.side,
                    "price_cents": ask_cents,
                    "count_fp": sizing["count_fp"],
                    "actual_risk_dollars": sizing["actual_risk_dollars"],
                    "order_id": order_id,
                    "simulated": order_result.get("simulated", False)
                }
                self._save_state()

                # 7. Alert Discord
                self.notifier.notify_trade_placed(
                    pick=pick,
                    kalshi_ticker=ticker,
                    kalshi_price_cents=ask_cents,
                    count_fp=sizing["count_fp"],
                    total_risk_dollars=sizing["actual_risk_dollars"],
                    mode="simulated" if dry_run or not self.client.is_authenticated else KALSHI_ENV
                )
                placed_count += 1
                print(f"[Trader] ✅ Successfully placed trade: {pick.play} ({sizing['count_fp']} contracts @ {ask_cents}¢)")

            except Exception as e:
                err_msg = f"Order placement failed for {pick.play} on ticker {ticker}: {e}"
                print(f"[Trader] ❌ {err_msg}")
                self.notifier.notify_error("Order Placement Error", err_msg)
                error_count += 1

        self._save_state()
        print(f"\n[Trader] Cycle complete: {placed_count} placed, {skipped_count} skipped, {error_count} errors.")
        return {"placed": placed_count, "skipped": skipped_count, "errors": error_count}
