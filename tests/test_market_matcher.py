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

    def test_match_cfb_team_total(self, matcher):
        mock_cfb_events = [
            {
                "event_ticker": "KXNCAAFTOTAL-26SEP07SMUFSU",
                "title": "SMU vs Florida St.: Total Points",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNCAAFTOTAL-26SEP07SMUFSU-33", "title": "Over 32.5 points scored", "yes_ask": 50},
                    {"ticker": "KXNCAAFTOTAL-26SEP07SMUFSU-55", "title": "Over 54.5 points scored", "yes_ask": 50},
                ]
            },
            {
                "event_ticker": "KXNCAAFTEAMTOTAL-26SEP07SMUFSU",
                "title": "SMU vs Florida St.: Team Total",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNCAAFTEAMTOTAL-26SEP07SMUFSU-FSU24", "title": "Florida St. scores over 23.5 points", "yes_ask": 70},
                    {"ticker": "KXNCAAFTEAMTOTAL-26SEP07SMUFSU-FSU28", "title": "Florida St. scores over 27.5 points", "yes_ask": 45},
                    {"ticker": "KXNCAAFTEAMTOTAL-26SEP07SMUFSU-SMU28", "title": "SMU scores over 27.5 points", "yes_ask": 50},
                ]
            }
        ]

        pick_tt = PickRecord(
            day="120", date="9/7/2026", sport="NCAAF", play="FSU Under 27.5",
            market="Team Total", odds_raw="-135", odds_numeric=-135.0,
            implied_cents=57, grade="A", units=2.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="test_tt"
        )
        res_tt = matcher.match_pick(pick_tt, live_events=mock_cfb_events)
        assert res_tt.matched is True
        assert res_tt.ticker == "KXNCAAFTEAMTOTAL-26SEP07SMUFSU-FSU28"
        assert res_tt.event_ticker == "KXNCAAFTEAMTOTAL-26SEP07SMUFSU"
        assert res_tt.side == "no"

    def test_strict_date_matching_rejects_mismatched_date(self):
        matcher = MarketMatcher(kalshi_client=None)
        mock_events = [
            {
                "event_ticker": "KXMLBGAME-26SEP101215TBATL",
                "title": "Tampa Bay vs Atlanta",
                "sub_title": "TB vs ATL (Sep 10)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXMLBGAME-26SEP101215TBATL-TB", "title": "Tampa Bay to win", "yes_ask": 55}
                ]
            }
        ]
        # Pick is for Sep 9, event is for Sep 10
        pick = PickRecord(
            day="120", date="9/9/2026", sport="MLB", play="Tampa Bay ML",
            market="Moneyline", odds_raw="-120", odds_numeric=-120.0,
            implied_cents=55, grade="A", units=1.5, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="tb_ml_test"
        )
        res = matcher.match_pick(pick, live_events=mock_events)
        assert res.matched is False
        assert "on 9/9/2026" in res.reason

    def test_nfl_patriots_spread_matching(self, matcher):
        mock_nfl_events = [
            {
                "event_ticker": "KXNFLSPREAD-26SEP09NESEA",
                "title": "New England vs Seattle: Spread",
                "sub_title": "NE vs SEA (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLSPREAD-26SEP09NESEA-SEA4", "title": "Seattle wins by over 3.5 points?", "yes_ask": 52},
                    {"ticker": "KXNFLSPREAD-26SEP09NESEA-NE4", "title": "New England wins by over 3.5 points?", "yes_ask": 48}
                ]
            },
            {
                "event_ticker": "KXNFLGAME-26SEP20PITNE",
                "title": "Pittsburgh vs New England",
                "sub_title": "PIT vs NE (Sep 20)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLGAME-26SEP20PITNE-NE", "title": "New England to win", "yes_ask": 50}
                ]
            }
        ]
        pick = PickRecord(
            day="120", date="9/9/2026", sport="NFL", play="Patriots +3.5",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=2.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="patriots_test"
        )
        res = matcher.match_pick(pick, live_events=mock_nfl_events)
        assert res.matched is True
        assert res.event_ticker == "KXNFLSPREAD-26SEP09NESEA"
        assert res.ticker == "KXNFLSPREAD-26SEP09NESEA-SEA4"
        assert res.side == "no"

    def test_nfl_comprehensive_suite(self, matcher):
        mock_events = [
            # Full Game Spread: KC vs BAL
            {
                "event_ticker": "KXNFLSPREAD-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: Spread",
                "sub_title": "KC vs BAL (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLSPREAD-26SEP09KCBAL-KC4", "title": "Kansas City wins by over 3.5 points?", "yes_ask": 51},
                    {"ticker": "KXNFLSPREAD-26SEP09KCBAL-BAL4", "title": "Baltimore wins by over 3.5 points?", "yes_ask": 49}
                ]
            },
            # Full Game Spread: SF vs NYJ
            {
                "event_ticker": "KXNFLSPREAD-26SEP09SFNYJ",
                "title": "San Francisco vs New York Jets: Spread",
                "sub_title": "SF vs NYJ (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLSPREAD-26SEP09SFNYJ-SF4", "title": "San Francisco wins by over 3.5 points?", "yes_ask": 54},
                    {"ticker": "KXNFLSPREAD-26SEP09SFNYJ-NYJ4", "title": "New York Jets wins by over 3.5 points?", "yes_ask": 46}
                ]
            },
            # Full Game Moneyline: DET vs LAR
            {
                "event_ticker": "KXNFLGAME-26SEP09DETLAR",
                "title": "Detroit vs Los Angeles Rams",
                "sub_title": "DET vs LAR (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLGAME-26SEP09DETLAR-DET", "title": "Detroit to win", "yes_ask": 65},
                    {"ticker": "KXNFLGAME-26SEP09DETLAR-LAR", "title": "Los Angeles Rams to win", "yes_ask": 35}
                ]
            },
            # Full Game Total: KC vs BAL
            {
                "event_ticker": "KXNFLTOTAL-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: Total Points",
                "sub_title": "KC vs BAL (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLTOTAL-26SEP09KCBAL-47", "title": "Total points over 46.5?", "yes_ask": 52}
                ]
            },
            # Team Total: KC
            {
                "event_ticker": "KXNFLTEAMTOTAL-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: Team Total",
                "sub_title": "KC vs BAL (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFLTEAMTOTAL-26SEP09KCBAL-KC25", "title": "Kansas City total points over 24.5", "yes_ask": 53}
                ]
            },
            # 1H Spread: KC vs BAL
            {
                "event_ticker": "KXNFL1HSPREAD-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: 1st Half Spread",
                "sub_title": "KC vs BAL 1H (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFL1HSPREAD-26SEP09KCBAL-KC2", "title": "Kansas City 1H spread by over 1.5 points?", "yes_ask": 50}
                ]
            },
            # 1H Moneyline: KC vs BAL
            {
                "event_ticker": "KXNFL1H-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: 1st Half Winner",
                "sub_title": "KC vs BAL 1H (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFL1H-26SEP09KCBAL-KC", "title": "Kansas City to win 1st Half", "yes_ask": 58}
                ]
            },
            # 1H Total: KC vs BAL
            {
                "event_ticker": "KXNFL1HTOTAL-26SEP09KCBAL",
                "title": "Kansas City vs Baltimore: 1st Half Total",
                "sub_title": "KC vs BAL 1H (Sep 9)",
                "category": "sports",
                "markets": [
                    {"ticker": "KXNFL1HTOTAL-26SEP09KCBAL-24", "title": "Total 1H points over 23.5?", "yes_ask": 50}
                ]
            }
        ]

        # 1. Favorite Spread: Chiefs -3.5 -> yes on KC4
        p_fav = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Chiefs -3.5",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_spread"
        )
        r_fav = matcher.match_pick(p_fav, live_events=mock_events)
        assert r_fav.matched is True
        assert r_fav.ticker == "KXNFLSPREAD-26SEP09KCBAL-KC4"
        assert r_fav.side == "yes"

        # 2. Numbered team name: 49ers -3.5 -> yes on SF4
        p_49ers = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="49ers -3.5",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="sf_spread"
        )
        r_49ers = matcher.match_pick(p_49ers, live_events=mock_events)
        assert r_49ers.matched is True
        assert r_49ers.ticker == "KXNFLSPREAD-26SEP09SFNYJ-SF4"
        assert r_49ers.side == "yes"

        # 3. Moneyline: Lions ML -> yes on DET
        p_ml = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Lions ML",
            market="Moneyline", odds_raw="-180", odds_numeric=-180.0,
            implied_cents=64, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="det_ml"
        )
        r_ml = matcher.match_pick(p_ml, live_events=mock_events)
        assert r_ml.matched is True
        assert r_ml.ticker == "KXNFLGAME-26SEP09DETLAR-DET"
        assert r_ml.side == "yes"

        # 4. Game Total: Ravens / Chiefs Over 46.5 -> yes on 47
        p_total = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Ravens / Chiefs Over 46.5",
            market="Game Total", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_bal_total"
        )
        r_total = matcher.match_pick(p_total, live_events=mock_events)
        assert r_total.matched is True
        assert r_total.ticker == "KXNFLTOTAL-26SEP09KCBAL-47"
        assert r_total.side == "yes"

        # 5. Team Total: Chiefs Over 24.5 TT -> yes on KC25 (strictly avoids full game total)
        p_tt = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Chiefs Over 24.5 TT",
            market="Team Total", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_tt"
        )
        r_tt = matcher.match_pick(p_tt, live_events=mock_events)
        assert r_tt.matched is True
        assert r_tt.ticker == "KXNFLTEAMTOTAL-26SEP09KCBAL-KC25"
        assert r_tt.side == "yes"

        # 6. 1H Spread: Chiefs 1H -1.5 -> yes on KC2 (strictly avoids full game spread)
        p_1h_spread = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Chiefs 1H -1.5",
            market="First Half Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_1h_spread"
        )
        r_1h_spread = matcher.match_pick(p_1h_spread, live_events=mock_events)
        assert r_1h_spread.matched is True
        assert r_1h_spread.ticker == "KXNFL1HSPREAD-26SEP09KCBAL-KC2"
        assert r_1h_spread.side == "yes"

        # 7. 1H Moneyline: Chiefs 1H ML -> yes on KC
        p_1h_ml = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Chiefs 1H ML",
            market="First Half Moneyline", odds_raw="-130", odds_numeric=-130.0,
            implied_cents=56, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_1h_ml"
        )
        r_1h_ml = matcher.match_pick(p_1h_ml, live_events=mock_events)
        assert r_1h_ml.matched is True
        assert r_1h_ml.ticker == "KXNFL1H-26SEP09KCBAL-KC"
        assert r_1h_ml.side == "yes"

        # 8. 1H Total: Ravens / Chiefs 1H Over 23.5 -> yes on 24
        p_1h_total = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Ravens / Chiefs 1H Over 23.5",
            market="First Half Total", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kc_1h_total"
        )
        r_1h_total = matcher.match_pick(p_1h_total, live_events=mock_events)
        assert r_1h_total.matched is True
        assert r_1h_total.ticker == "KXNFL1HTOTAL-26SEP09KCBAL-24"
        assert r_1h_total.side == "yes"

        # 9. Multi-leg NFL Parlay: Chiefs -3.5 + Lions ML
        p_parlay = PickRecord(
            day="1", date="9/9/2026", sport="NFL", play="Chiefs -3.5 + Lions ML",
            market="Parlay", odds_raw="+260", odds_numeric=260.0,
            implied_cents=27, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="nfl_parlay"
        )
        r_parlay = matcher.match_pick(p_parlay, live_events=mock_events)
        assert r_parlay.matched is True
        assert r_parlay.is_combo is True
        assert len(r_parlay.combo_legs) == 2
        assert r_parlay.combo_legs[0]["market_ticker"] == "KXNFLSPREAD-26SEP09KCBAL-KC4"
        assert r_parlay.combo_legs[0]["side"] == "yes"
        assert r_parlay.combo_legs[1]["market_ticker"] == "KXNFLGAME-26SEP09DETLAR-DET"
        assert r_parlay.combo_legs[1]["side"] == "yes"

