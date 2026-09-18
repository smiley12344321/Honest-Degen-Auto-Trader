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

    def test_f5_half_spread_matching(self, matcher):
        mock_f5_events = [
            {
                "event_ticker": "KXMLBF5-26SEP091940PITCWS",
                "title": "Pittsburgh vs Chicago WS: First 5 Innings",
                "markets": [
                    {"ticker": "KXMLBF5-26SEP091940PITCWS-PIT", "title": "Pittsburgh first 5 innings winner"},
                    {"ticker": "KXMLBF5-26SEP091940PITCWS-CWS", "title": "Chicago WS first 5 innings winner"},
                    {"ticker": "KXMLBF5-26SEP091940PITCWS-TIE", "title": "first 5 innings tie"}
                ]
            },
            {
                "event_ticker": "KXMLBF5SPREAD-26SEP091940PITCWS",
                "title": "Pittsburgh vs Chicago WS: First 5 Spread",
                "markets": [
                    {"ticker": "KXMLBF5SPREAD-26SEP091940PITCWS-CWS2", "title": "Chicago WS wins first 5 innings by over 1.5 runs?"},
                    {"ticker": "KXMLBF5SPREAD-26SEP091940PITCWS-PIT2", "title": "Pittsburgh wins first 5 innings by over 1.5 runs?"}
                ]
            }
        ]

        # 1. Pirates F5 +0.5 -> NO Chicago WS first 5 innings winner
        p_plus_half = PickRecord(
            day="1", date="9/9/2026", sport="MLB", play="Pirates F5 +0.5",
            market="F5 Run Line", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="pit_f5_plus"
        )
        r_plus_half = matcher.match_pick(p_plus_half, live_events=mock_f5_events)
        assert r_plus_half.matched is True
        assert r_plus_half.event_ticker == "KXMLBF5-26SEP091940PITCWS"
        assert r_plus_half.ticker == "KXMLBF5-26SEP091940PITCWS-CWS"
        assert r_plus_half.side == "no"

        # 2. White Sox F5 +0.5 -> NO Pittsburgh first 5 innings winner
        p_cws_plus_half = PickRecord(
            day="1", date="9/9/2026", sport="MLB", play="White Sox F5 +0.5",
            market="F5 Run Line", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="cws_f5_plus"
        )
        r_cws_plus_half = matcher.match_pick(p_cws_plus_half, live_events=mock_f5_events)
        assert r_cws_plus_half.matched is True
        assert r_cws_plus_half.ticker == "KXMLBF5-26SEP091940PITCWS-PIT"
        assert r_cws_plus_half.side == "no"

        # 3. Pirates F5 -0.5 -> YES Pittsburgh first 5 innings winner
        p_minus_half = PickRecord(
            day="1", date="9/9/2026", sport="MLB", play="Pirates F5 -0.5",
            market="F5 Run Line", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="pit_f5_minus"
        )
        r_minus_half = matcher.match_pick(p_minus_half, live_events=mock_f5_events)
        assert r_minus_half.matched is True
        assert r_minus_half.ticker == "KXMLBF5-26SEP091940PITCWS-PIT"
        assert r_minus_half.side == "yes"

        # 4. Pirates F5 +1.5 -> Routes to KXMLBF5SPREAD on CWS2 (no)
        p_spread_15 = PickRecord(
            day="1", date="9/9/2026", sport="MLB", play="Pirates F5 +1.5",
            market="F5 Run Line", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="pit_f5_spread15"
        )
        r_spread_15 = matcher.match_pick(p_spread_15, live_events=mock_f5_events)
        assert r_spread_15.matched is True
        assert r_spread_15.event_ticker == "KXMLBF5SPREAD-26SEP091940PITCWS"
        assert r_spread_15.ticker == "KXMLBF5SPREAD-26SEP091940PITCWS-CWS2"
        assert r_spread_15.side == "no"

    def test_ncaaf_state_vs_non_state_isolation(self, matcher):
        mock_ncaaf_events = [
            {
                "event_ticker": "KXNCAAFSPREAD-26SEP12TTUORST",
                "title": "Texas Tech at Oregon St. Spread",
                "markets": [
                    {"ticker": "KXNCAAFSPREAD-26SEP12TTUORST-TTU28", "title": "Texas Tech by over 27.5 points"},
                    {"ticker": "KXNCAAFSPREAD-26SEP12TTUORST-ORST9", "title": "Oregon State by over 8.5 points"}
                ]
            },
            {
                "event_ticker": "KXNCAAFSPREAD-26SEP12OREOKST",
                "title": "Oklahoma St. at Oregon Spread",
                "markets": [
                    {"ticker": "KXNCAAFSPREAD-26SEP12OREOKST-ORE25", "title": "Oregon by over 24.5 points"},
                    {"ticker": "KXNCAAFSPREAD-26SEP12OREOKST-OKST10", "title": "Oklahoma State by over 9.5 points"}
                ]
            },
            {
                "event_ticker": "KXNCAAFSPREAD-26SEP12MSUBC",
                "title": "Michigan State at Boston College Spread",
                "markets": [
                    {"ticker": "KXNCAAFSPREAD-26SEP12MSUBC-BC6", "title": "Boston College by over 5.5 points"},
                    {"ticker": "KXNCAAFSPREAD-26SEP12MSUBC-MSU14", "title": "Michigan State by over 13.5 points"}
                ]
            },
            {
                "event_ticker": "KXNCAAFSPREAD-26SEP12MICHTEX",
                "title": "Texas at Michigan Spread",
                "markets": [
                    {"ticker": "KXNCAAFSPREAD-26SEP12MICHTEX-MICH7", "title": "Michigan by over 6.5 points"},
                    {"ticker": "KXNCAAFSPREAD-26SEP12MICHTEX-TEX14", "title": "Texas by over 13.5 points"}
                ]
            }
        ]

        # 1. Oregon State +26 -> Must match TTUORST, NOT OREOKST!
        p_orst = PickRecord(
            day="1", date="9/12/2026", sport="NCAAF", play="Oregon State +26",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="orst_spread"
        )
        r_orst = matcher.match_pick(p_orst, live_events=mock_ncaaf_events)
        assert r_orst.matched is True
        assert r_orst.event_ticker == "KXNCAAFSPREAD-26SEP12TTUORST"
        assert r_orst.ticker == "KXNCAAFSPREAD-26SEP12TTUORST-TTU28"
        assert r_orst.side == "no"

        # 2. Oregon -26 (or Oregon -25) -> Must match OREOKST, NOT TTUORST!
        p_ore = PickRecord(
            day="1", date="9/12/2026", sport="NCAAF", play="Oregon -25",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="ore_spread"
        )
        r_ore = matcher.match_pick(p_ore, live_events=mock_ncaaf_events)
        assert r_ore.matched is True
        assert r_ore.event_ticker == "KXNCAAFSPREAD-26SEP12OREOKST"
        assert r_ore.ticker == "KXNCAAFSPREAD-26SEP12OREOKST-ORE25"
        assert r_ore.side == "yes"

        # 3. Michigan State +6 -> Must match MSUBC, NOT MICHTEX!
        p_msu = PickRecord(
            day="1", date="9/12/2026", sport="NCAAF", play="Michigan State +6",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="msu_spread"
        )
        r_msu = matcher.match_pick(p_msu, live_events=mock_ncaaf_events)
        assert r_msu.matched is True
        assert r_msu.event_ticker == "KXNCAAFSPREAD-26SEP12MSUBC"
        assert r_msu.ticker == "KXNCAAFSPREAD-26SEP12MSUBC-BC6"
        assert r_msu.side == "no"

        # 4. Michigan -7 -> Must match MICHTEX, NOT MSUBC!
        p_mich = PickRecord(
            day="1", date="9/12/2026", sport="NCAAF", play="Michigan -7",
            market="Spread", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="mich_spread"
        )
        r_mich = matcher.match_pick(p_mich, live_events=mock_ncaaf_events)
        assert r_mich.matched is True
        assert r_mich.event_ticker == "KXNCAAFSPREAD-26SEP12MICHTEX"
        assert r_mich.ticker == "KXNCAAFSPREAD-26SEP12MICHTEX-MICH7"
        assert r_mich.side == "yes"

    def test_player_props_matching(self, matcher):
        mock_events = [
            {
                "event_ticker": "KXNFLPASSYDS-26SEP17DETBUF",
                "title": "Detroit vs Buffalo: Passing Yards",
                "markets": [
                    {"ticker": "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-175", "title": "Josh Allen: 175+ passing yards"},
                    {"ticker": "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-200", "title": "Josh Allen: 200+ passing yards"},
                    {"ticker": "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-225", "title": "Josh Allen: 225+ passing yards"},
                    {"ticker": "KXNFLPASSYDS-26SEP17DETBUF-DETJGOFF16-250", "title": "Jared Goff: 250+ passing yards"}
                ]
            },
            {
                "event_ticker": "KXNFLRSHYDS-26SEP20CARATL",
                "title": "Carolina vs Atlanta: Rushing Yards",
                "markets": [
                    {"ticker": "KXNFLRSHYDS-26SEP20CARATL-ATLBROBINSON7-50", "title": "Bijan Robinson: 50+ rushing yards"},
                    {"ticker": "KXNFLRSHYDS-26SEP20CARATL-ATLBROBINSON7-60", "title": "Bijan Robinson: 60+ rushing yards"}
                ]
            },
            {
                "event_ticker": "KXNFLTD-26SEP20CARATL",
                "title": "Carolina vs Atlanta: Touchdowns",
                "markets": [
                    {"ticker": "KXNFLTD-26SEP20CARATL-ATLDLONDON5-1", "title": "Drake London: 1+ touchdowns"},
                    {"ticker": "KXNFLTD-26SEP20CARATL-ATLDLONDON5-2", "title": "Drake London: 2+ touchdowns"}
                ]
            },
            {
                "event_ticker": "KXMLBKS-26SEP181840CHCCIN",
                "title": "Chicago C vs Cincinnati: Strikeouts",
                "markets": [
                    {"ticker": "KXMLBKS-26SEP181840CHCCIN-CINCBURNS26-2", "title": "Chase Burns: 2+ strikeouts?"},
                    {"ticker": "KXMLBKS-26SEP181840CHCCIN-CINCBURNS26-3", "title": "Chase Burns: 3+ strikeouts?"}
                ]
            }
        ]

        # 1. J. Allen 200+ Pass Yds (exact match from yesterday's failed trade)
        p1 = PickRecord(
            day="1", date="9/17/2026", sport="NFL", play="J. Allen 200+ Pass Yds",
            market="Player Prop", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="jallen_200"
        )
        r1 = matcher.match_pick(p1, live_events=mock_events)
        assert r1.matched is True
        assert r1.event_ticker == "KXNFLPASSYDS-26SEP17DETBUF"
        assert r1.ticker == "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-200"
        assert r1.side == "yes"

        # 2. Josh Allen Over 199.5 Passing Yards (sportsbook alternate line converts to 200+)
        p2 = PickRecord(
            day="1", date="9/17/2026", sport="NFL", play="Josh Allen Over 199.5 Passing Yards",
            market="Passing Yards", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="jallen_over_199"
        )
        r2 = matcher.match_pick(p2, live_events=mock_events)
        assert r2.matched is True
        assert r2.ticker == "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-200"
        assert r2.side == "yes"

        # 3. Jared Goff Under 249.5 Pass Yds -> NO on 250+
        p3 = PickRecord(
            day="1", date="9/17/2026", sport="NFL", play="Jared Goff Under 249.5 Pass Yds",
            market="Player Prop", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="goff_under_250"
        )
        r3 = matcher.match_pick(p3, live_events=mock_events)
        assert r3.matched is True
        assert r3.ticker == "KXNFLPASSYDS-26SEP17DETBUF-DETJGOFF16-250"
        assert r3.side == "no"

        # 4. Bijan Robinson 50+ Rush Yds
        p4 = PickRecord(
            day="1", date="9/20/2026", sport="NFL", play="Bijan Robinson 50+ Rush Yds",
            market="Player Prop", odds_raw="-110", odds_numeric=-110.0,
            implied_cents=52, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="bijan_rush"
        )
        r4 = matcher.match_pick(p4, live_events=mock_events)
        assert r4.matched is True
        assert r4.ticker == "KXNFLRSHYDS-26SEP20CARATL-ATLBROBINSON7-50"
        assert r4.side == "yes"

        # 5. Drake London 1+ TD (Anytime Touchdown)
        p5 = PickRecord(
            day="1", date="9/20/2026", sport="NFL", play="Drake London Anytime TD",
            market="Player Prop", odds_raw="+140", odds_numeric=140.0,
            implied_cents=41, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="london_td"
        )
        r5 = matcher.match_pick(p5, live_events=mock_events)
        assert r5.matched is True
        assert r5.ticker == "KXNFLTD-26SEP20CARATL-ATLDLONDON5-1"
        assert r5.side == "yes"

        # 6. Chase Burns 2+ Ks (MLB Strikeouts)
        p6 = PickRecord(
            day="1", date="9/18/2026", sport="MLB", play="Chase Burns 2+ Strikeouts",
            market="Player Prop", odds_raw="-130", odds_numeric=-130.0,
            implied_cents=56, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="burns_ks"
        )
        r6 = matcher.match_pick(p6, live_events=mock_events)
        assert r6.matched is True
        assert r6.ticker == "KXMLBKS-26SEP181840CHCCIN-CINCBURNS26-2"
        assert r6.side == "yes"

        # 7. Disqualification of mismatched player (Kyle Allen vs Josh Allen)
        p7 = PickRecord(
            day="1", date="9/17/2026", sport="NFL", play="Kyle Allen 200+ Pass Yds",
            market="Player Prop", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="kyle_allen"
        )
        r7 = matcher.match_pick(p7, live_events=mock_events)
        assert r7.matched is False

        # 8. Disqualification of mismatched date
        p8 = PickRecord(
            day="1", date="9/18/2026", sport="NFL", play="J. Allen 200+ Pass Yds",
            market="Player Prop", odds_raw="-115", odds_numeric=-115.0,
            implied_cents=53, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="jallen_wrong_date"
        )
        r8 = matcher.match_pick(p8, live_events=mock_events)
        assert r8.matched is False

    def test_parlay_with_player_prop(self, matcher):
        mock_events = [
            {
                "event_ticker": "KXNFLGAME-26SEP17DETBUF",
                "title": "Detroit at Buffalo",
                "markets": [
                    {"ticker": "KXNFLGAME-26SEP17DETBUF-BUF", "title": "Buffalo Bills to win"},
                    {"ticker": "KXNFLGAME-26SEP17DETBUF-DET", "title": "Detroit Lions to win"}
                ]
            },
            {
                "event_ticker": "KXNFLPASSYDS-26SEP17DETBUF",
                "title": "Detroit vs Buffalo: Passing Yards",
                "markets": [
                    {"ticker": "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-200", "title": "Josh Allen: 200+ passing yards"}
                ]
            }
        ]

        # Multi-leg SGP/Parlay: Bills ML + J. Allen 200+ Pass Yds
        p_parlay = PickRecord(
            day="1", date="9/17/2026", sport="NFL", play="Bills ML + J. Allen 200+ Pass Yds",
            market="Parlay", odds_raw="+140", odds_numeric=140.0,
            implied_cents=41, grade="A", units=1.0, risk_dollars_sheet=None,
            result="pending", notes="", trade_id="bills_allen_sgp"
        )
        r_parlay = matcher.match_pick(p_parlay, live_events=mock_events)
        assert r_parlay.matched is True
        assert r_parlay.is_combo is True
        assert len(r_parlay.combo_legs) == 2
        assert r_parlay.combo_legs[0]["market_ticker"] == "KXNFLGAME-26SEP17DETBUF-BUF"
        assert r_parlay.combo_legs[0]["side"] == "yes"
        assert r_parlay.combo_legs[1]["market_ticker"] == "KXNFLPASSYDS-26SEP17DETBUF-BUFJALLEN17-200"
        assert r_parlay.combo_legs[1]["side"] == "yes"




