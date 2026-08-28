import pytest
from src.odds_converter import (
    parse_american_odds,
    american_to_implied_prob,
    implied_prob_to_kalshi_cents,
    calculate_sizing,
    is_price_acceptable
)


class TestOddsConverter:

    def test_parse_american_odds_standard(self):
        assert parse_american_odds("-110") == -110.0
        assert parse_american_odds("+150") == 150.0
        assert parse_american_odds("-130") == -130.0
        assert parse_american_odds("100") == 100.0
        assert parse_american_odds("-100") == -100.0

    def test_parse_american_odds_estimates_and_notes(self):
        assert parse_american_odds("-120 est") == -120.0
        assert parse_american_odds("+100 est") == 100.0
        assert parse_american_odds("-110 (fair)") == -110.0

    def test_parse_american_odds_slash(self):
        # -119/-122 -> average is -120.5
        val = parse_american_odds("-119/-122")
        assert val == pytest.approx(-120.5, 0.01)

    def test_parse_american_odds_invalid(self):
        assert parse_american_odds("") is None
        assert parse_american_odds(None) is None
        assert parse_american_odds("N/A") is None

    def test_american_to_implied_prob(self):
        # -100 or +100 is 50%
        assert american_to_implied_prob(-100) == pytest.approx(0.50, 0.001)
        assert american_to_implied_prob(100) == pytest.approx(0.50, 0.001)

        # -130 -> 130 / 230 = 0.5652
        assert american_to_implied_prob(-130) == pytest.approx(0.5652, 0.001)

        # +150 -> 100 / 250 = 0.40
        assert american_to_implied_prob(150) == pytest.approx(0.40, 0.001)

        # -200 -> 200 / 300 = 0.6667
        assert american_to_implied_prob(-200) == pytest.approx(0.6667, 0.001)

    def test_implied_prob_to_kalshi_cents(self):
        assert implied_prob_to_kalshi_cents(0.5652) == 57
        assert implied_prob_to_kalshi_cents(0.40) == 40
        assert implied_prob_to_kalshi_cents(0.50) == 50
        assert implied_prob_to_kalshi_cents(0.999) == 99
        assert implied_prob_to_kalshi_cents(0.001) == 1

    def test_calculate_sizing_fractional(self):
        # 1.5 units @ $0.50/unit = $0.75 target risk
        # Contract price = 57 cents ($0.57)
        # count_fp = 0.75 / 0.57 = 1.3157... -> "1.32"
        sizing = calculate_sizing(units=1.5, unit_size_dollars=0.50, price_cents=57, allow_fractional=True)
        assert sizing["count_fp"] == "1.32"
        assert sizing["target_risk_dollars"] == 0.75
        assert sizing["actual_risk_dollars"] == pytest.approx(1.32 * 0.57, 0.001)

    def test_calculate_sizing_whole_contracts(self):
        # 1.5 units @ $0.50/unit = $0.75 target risk
        # Contract price = 50 cents ($0.50) -> 0.75 / 0.50 = 1.5 -> rounds to 2
        sizing = calculate_sizing(units=1.5, unit_size_dollars=0.50, price_cents=50, allow_fractional=False)
        assert sizing["count_int"] == 2
        assert sizing["count_fp"] == "2.00"
        assert sizing["actual_risk_dollars"] == 1.00

    def test_is_price_acceptable(self):
        # Sheet odds: -130 -> target_cents is 57c
        # Slippage tolerance: 10c -> max acceptable is 67c
        
        # 1. Kalshi ask is 55c (discount / better price) -> Acceptable
        acc, target, max_b, delta = is_price_acceptable(sheet_odds=-130, kalshi_ask_cents=55, slippage_tolerance_cents=10)
        assert acc is True
        assert target == 57
        assert max_b == 67
        assert delta == -2

        # 2. Kalshi ask is 65c (within 10c slippage) -> Acceptable
        acc, target, max_b, delta = is_price_acceptable(sheet_odds=-130, kalshi_ask_cents=65, slippage_tolerance_cents=10)
        assert acc is True
        assert target == 57
        assert max_b == 67
        assert delta == 8

        # 3. Kalshi ask is 70c (exceeds 10c slippage) -> Rejected
        acc, target, max_b, delta = is_price_acceptable(sheet_odds=-130, kalshi_ask_cents=70, slippage_tolerance_cents=10)
        assert acc is False
        assert target == 57
        assert max_b == 67
        assert delta == 13
