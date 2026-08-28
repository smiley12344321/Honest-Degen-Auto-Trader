import pytest
from src.market_matcher import MarketMatcher, MatchResult
from src.sheet_reader import PickRecord
from src.kalshi_client import KalshiClient


@pytest.fixture
def matcher():
    client = KalshiClient()
    return MarketMatcher(client)


@pytest.fixture
def mock_events():
    return [
        {
            "event_ticker": "KXMLBGAME-24AUG24-TBR-DET",
            "title": "Tampa Bay Rays vs Detroit Tigers",
            "category": "sports",
            "markets": [
                {
                    "ticker": "KXMLBGAME-24AUG24-TBR-DET-TBR",
                    "title": "Tampa Bay Rays to win",
                    "yes_ask": 57,
                    "last_price": 56
                },
                {
                    "ticker": "KXMLBGAME-24AUG24-TBR-DET-DET",
                    "title": "Detroit Tigers to win",
                    "yes_ask": 44,
                    "last_price": 44
                }
            ]
        },
        {
            "event_ticker": "KXNRFI-24AUG24-PHI-SEA",
            "title": "Philadelphia Phillies at Seattle Mariners First Inning",
            "category": "sports",
            "markets": [
                {
                    "ticker": "KXNRFI-24AUG24-PHI-SEA-SCORELESS",
                    "title": "Will 1st inning be scoreless (NRFI)?",
                    "yes_ask": 60,
                    "last_price": 60
                }
            ]
        }
    ]


class TestMarketMatcher:

    def test_normalize_team(self, matcher):
        assert matcher.normalize_team("MLB", "D-backs") == "ARI"
        assert matcher.normalize_team("MLB", "Rays") == "TBR"
        assert matcher.normalize_team("MLB", "TB Rays") == "TBR"
        assert matcher.normalize_team("WNBA", "Dallas Wings") == "DAL"
        assert matcher.normalize_team("NHL", "Canadiens") == "MTL"

    def test_extract_teams_from_play(self, matcher):
        assert matcher.extract_teams_from_play("Rays ML", "MLB") == ["Rays"]
        assert matcher.extract_teams_from_play("Phillies/Mariners NRFI", "MLB") == ["Phillies", "Mariners"]
        assert matcher.extract_teams_from_play("Angels vs Rangers", "MLB") == ["Angels", "Rangers"]

    def test_match_moneyline(self, matcher, mock_events):
        pick = PickRecord(
            day="112", date="8/24/2026", sport="MLB", play="Rays ML",
            market="Moneyline", odds_raw="-130", odds_numeric=-130.0,
            implied_cents=57, grade="B+", units=1.5, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="test1"
        )
        res = matcher.match_pick(pick, live_events=mock_events)
        assert res.matched is True
        assert res.ticker == "KXMLBGAME-24AUG24-TBR-DET-TBR"
        assert res.side == "yes"

    def test_match_nrfi(self, matcher, mock_events):
        pick = PickRecord(
            day="112", date="8/24/2026", sport="MLB", play="Phillies/Mariners NRFI",
            market="NRFI", odds_raw="-148", odds_numeric=-148.0,
            implied_cents=60, grade="A", units=2.5, risk_dollars_sheet=None,
            result="", notes="", trade_id="test2"
        )
        res = matcher.match_pick(pick, live_events=mock_events)
        assert res.matched is True
        assert res.ticker == "KXNRFI-24AUG24-PHI-SEA-SCORELESS"
        assert res.side == "yes"

    def test_skip_parlays(self, matcher):
        pick = PickRecord(
            day="111", date="8/23/2026", sport="Tennis", play="10-Leg Royal Sweep",
            market="Parlay", odds_raw="1514", odds_numeric=1514.0,
            implied_cents=6, grade="A", units=0.5, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="test3"
        )
        res = matcher.match_pick(pick, live_events=[])
        assert res.matched is False
        assert res.unsupported is True
        assert "Parlay" in res.reason
