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
        assert matcher.normalize_team("MLB", "D-backs") == "AZ"
        assert matcher.normalize_team("MLB", "Rays") == "TB"
        assert matcher.normalize_team("MLB", "TB Rays") == "TB"
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

    def test_extract_parlay_legs(self, matcher):
        legs1 = matcher.extract_parlay_legs("Gauff +3.5 / Tiafoe +4.5")
        assert len(legs1) == 2
        assert legs1[0] == "Gauff +3.5"
        assert legs1[1] == "Tiafoe +4.5"

        legs2 = matcher.extract_parlay_legs("Brunold ML / Gulin ML")
        assert len(legs2) == 2
        assert legs2[0] == "Brunold ML"
        assert legs2[1] == "Gulin ML"

    def test_match_parlays_multi_leg(self, matcher):
        # Mock events containing both legs
        mock_tennis_events = [
            {
                "event_ticker": "KXTENNIS-24AUG24-BRUNOLD",
                "title": "Brunold vs Opponent",
                "category": "sports",
                "markets": [
                    {
                        "ticker": "KXTENNIS-24AUG24-BRUNOLD-WIN",
                        "title": "Brunold to win",
                        "yes_ask": 55
                    }
                ]
            },
            {
                "event_ticker": "KXTENNIS-24AUG24-GULIN",
                "title": "Gulin vs Opponent",
                "category": "sports",
                "markets": [
                    {
                        "ticker": "KXTENNIS-24AUG24-GULIN-WIN",
                        "title": "Gulin to win",
                        "yes_ask": 58
                    }
                ]
            }
        ]

        pick = PickRecord(
            day="112", date="8/24/2026", sport="Tennis", play="Brunold ML / Gulin ML",
            market="Parlay", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=2.5, risk_dollars_sheet=None,
            result="pending", notes="Brunold clay & Gulin clay", trade_id="test_parlay"
        )
        res = matcher.match_pick(pick, live_events=mock_tennis_events)
        assert res.matched is True
        assert res.is_combo is True
        assert len(res.combo_legs) == 2
        assert res.combo_legs[0]["market_ticker"] == "KXTENNIS-24AUG24-BRUNOLD-WIN"
        assert res.combo_legs[1]["market_ticker"] == "KXTENNIS-24AUG24-GULIN-WIN"

    def test_safe_side_totals_proximity(self, matcher):
        mock_totals_events = [
            {
                "event_ticker": "KXWNBATOTAL-26AUG28TORLV",
                "title": "Toronto vs Las Vegas: Point Total",
                "category": "sports",
                "markets": [
                    {"ticker": "KXWNBATOTAL-26AUG28TORLV-175", "title": "Over 175.5 points scored", "yes_ask": 50},
                    {"ticker": "KXWNBATOTAL-26AUG28TORLV-178", "title": "Over 178.5 points scored", "yes_ask": 40},
                ]
            }
        ]

        # Under 177: should pick 178.5 (safer side) rather than 175.5
        pick_under = PickRecord(
            day="116", date="8/28/2026", sport="WNBA", play="Toronto Tempo/Las Vegas Aces Under 177",
            market="Game Total", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="B+", units=1.5, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="test_under"
        )
        res_under = matcher.match_pick(pick_under, live_events=mock_totals_events)
        assert res_under.matched is True
        assert res_under.ticker == "KXWNBATOTAL-26AUG28TORLV-178"
        assert res_under.side == "no"
