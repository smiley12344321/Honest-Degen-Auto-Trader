import json
import pytest
from pathlib import Path
from src.trader import Trader
from src.sheet_reader import PickRecord
from src.kalshi_client import KalshiClient


class DummyNotifier:
    def __init__(self):
        self.placed_calls = []
        self.skipped_calls = []

    def notify_trade_placed(self, *args, **kwargs):
        self.placed_calls.append((args, kwargs))
        return True

    def notify_trade_skipped_price(self, *args, **kwargs):
        self.skipped_calls.append((args, kwargs))
        return True

    def notify_trade_skipped_unmapped(self, *args, **kwargs):
        self.skipped_calls.append((args, kwargs))
        return True

    def notify_error(self, *args, **kwargs):
        return True


class TestTrader:

    def test_trader_deduplication_and_state(self, tmp_path):
        state_file = tmp_path / "test_placed_trades.json"
        notifier = DummyNotifier()
        client = KalshiClient()
        
        trader = Trader(kalshi_client=client, notifier=notifier, state_file=state_file)
        
        # Test run with dry_run and mock events
        mock_events = [
            {
                "event_ticker": "KXMLBGAME-26AUG28-MIA-WSH",
                "title": "Miami vs Washington",
                "markets": [
                    {
                        "ticker": "KXMLBGAME-26AUG28-MIA-WSH-MIA",
                        "title": "Miami wins",
                        "yes_ask": 55
                    }
                ]
            }
        ]
        summary = trader.run_cycle(dry_run=True, live_events=mock_events)
        assert isinstance(summary, dict)
        assert "placed" in summary
        assert "skipped" in summary
        
        # Verify state file was created and is valid JSON
        assert state_file.exists()
        with open(state_file, "r") as f:
            state_data = json.load(f)
        assert "trades" in state_data
        assert "last_updated" in state_data
