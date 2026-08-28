import pytest
from src.sheet_reader import (
    parse_picks_from_csv,
    generate_trade_id,
    parse_units,
    PickRecord,
    get_active_picks
)

SAMPLE_CSV = """Day,Date,Sport,Play,Market,Odds,Grade,Units,Risk $,Result,close,P/L Units,P/L $,Notes
1,5/17/2026,MLB,Rangers F5 -0.5,F5 Spread,+106,A-,2.50,"1,250.00",Win,,2.65,"1,325.00",Eovaldi edge
2,5/18/2026,MLB,Mets ML,Moneyline,-145 est,B+,2.00,"1,000.00",Loss,,-2.00,"-1,000.00",Missed
112,8/24/2026,MLB,Rays ML,Moneyline,-130,B+,1.50,,pending,,,,Rasmussen vs Valdez
112,8/24/2026,MLB,Nationals F5 -0.5,F5 Run Line,-115,A,3.00,,pending,,,,Cavalli vs Feltner
112,8/24/2026,MLB,Phillies/Mariners NRFI,NRFI,-148,A,2.50,,,,,,Wheeler vs Gilbert
111,8/23/2026,Tennis,Gauff +3.5 / Tiafoe +4.5,Parlay,105,A,3,,Win,,,,Cincinnati Finals
"""


class TestSheetReader:

    def test_parse_picks_from_csv(self):
        picks = parse_picks_from_csv(SAMPLE_CSV)
        assert len(picks) == 6  # 6 valid rows

        # Check first row (Win)
        p1 = picks[0]
        assert p1.play == "Rangers F5 -0.5"
        assert p1.sport == "MLB"
        assert p1.odds_numeric == 106.0
        assert p1.implied_cents == 49
        assert p1.units == 2.5
        assert p1.is_active is False

        # Check pending row (Rays ML)
        p3 = picks[2]
        assert p3.play == "Rays ML"
        assert p3.odds_numeric == -130.0
        assert p3.implied_cents == 57
        assert p3.units == 1.5
        assert p3.result == "pending"
        assert p3.is_active is True

        # Check blank result row (Phillies/Mariners NRFI)
        p5 = picks[4]
        assert p5.play == "Phillies/Mariners NRFI"
        assert p5.odds_numeric == -148.0
        assert p5.units == 2.5
        assert p5.result == ""
        assert p5.is_active is True

    def test_deterministic_trade_id(self):
        id1 = generate_trade_id("8/24/2026", "MLB", "Rays ML", "Moneyline", "-130")
        id2 = generate_trade_id("8/24/2026", "MLB", "Rays ML", "Moneyline", "-130")
        id3 = generate_trade_id("8/24/2026", "MLB", "Rays ML", "Moneyline", "-125")
        
        assert id1 == id2
        assert id1 != id3
        assert len(id1) == 16

    def test_parse_units(self):
        assert parse_units("1.50") == 1.5
        assert parse_units("2 units") == 2.0
        assert parse_units("3") == 3.0
        assert parse_units(None) == 1.0
        assert parse_units("") == 1.0

    def test_live_sheet_fetching(self):
        # Fetches live Google Sheet to ensure production compatibility
        active_picks = get_active_picks()
        assert isinstance(active_picks, list)
        print(f"\nFound {len(active_picks)} active picks in live Google Sheet:")
        for p in active_picks:
            print(f"  - [{p.sport}] {p.play} ({p.market}) @ {p.odds_raw} | {p.units}u (ID: {p.trade_id})")
        
        # Verify all returned picks are active
        for p in active_picks:
            assert p.is_active is True
            assert p.play != ""
