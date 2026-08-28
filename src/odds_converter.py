import re
from typing import Optional, Tuple, Dict, Any


def parse_american_odds(raw: Any) -> Optional[float]:
    """
    Parses a raw odds string/number into a float.
    Handles formats like '-130', '+110', '105', '-110 est', '-119/-122'.
    """
    if raw is None:
        return None
    
    raw_str = str(raw).strip()
    if not raw_str:
        return None

    # Handle split odds like "-119/-122" or "+100/+110" -> take the average
    if "/" in raw_str:
        parts = raw_str.split("/")
        valid_parts = []
        for p in parts:
            p_clean = p.strip()
            match = re.search(r"([+-]?\d+(?:\.\d+)?)", p_clean)
            if match:
                try:
                    valid_parts.append(float(match.group(1)))
                except ValueError:
                    pass
        if valid_parts:
            return sum(valid_parts) / len(valid_parts)

    # Extract first match of signed or unsigned integer/float
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", raw_str)
    if not match:
        return None

    val_str = match.group(1)
    try:
        val = float(val_str)
        # If no sign was explicitly given but it's >= 100, standard convention is positive American odds
        return val
    except ValueError:
        return None


def american_to_implied_prob(american_odds: float) -> float:
    """
    Converts American odds into implied probability (0.0 to 1.0).
    - If negative (-130): 130 / (130 + 100) = 0.5652
    - If positive (+110): 100 / (110 + 100) = 0.4762
    - Even money (+100 / -100): 0.50
    """
    if american_odds == 0:
        return 0.50
    
    if american_odds < 0:
        abs_odds = abs(american_odds)
        return abs_odds / (abs_odds + 100.0)
    else:
        return 100.0 / (american_odds + 100.0)


def implied_prob_to_kalshi_cents(prob: float) -> int:
    """
    Converts implied probability (0.0 to 1.0) into Kalshi cents (1 to 99).
    """
    cents = int(round(prob * 100.0))
    return max(1, min(99, cents))


def calculate_sizing(
    units: float,
    unit_size_dollars: float,
    price_cents: int,
    allow_fractional: bool = True
) -> Dict[str, Any]:
    """
    Calculates target risk, contract count (fixed-point count_fp for Kalshi),
    and expected total cost.
    """
    target_risk = max(0.01, units * unit_size_dollars)
    price_dollars = max(0.01, price_cents / 100.0)
    
    raw_count = target_risk / price_dollars
    
    if allow_fractional:
        # Format to 2 decimal places for Kalshi's count_fp
        count_fp = f"{max(0.01, round(raw_count, 2)):.2f}"
        actual_risk = round(float(count_fp) * price_dollars, 4)
        count_int = max(1, int(round(raw_count)))
    else:
        count_int = max(1, int(round(raw_count)))
        count_fp = f"{count_int}.00"
        actual_risk = round(count_int * price_dollars, 4)

    return {
        "count_fp": count_fp,
        "count_int": count_int,
        "price_cents": price_cents,
        "price_dollars": price_dollars,
        "target_risk_dollars": round(target_risk, 4),
        "actual_risk_dollars": actual_risk,
        "units": units,
        "unit_size_dollars": unit_size_dollars
    }


def is_price_acceptable(
    sheet_odds: float,
    kalshi_ask_cents: int,
    slippage_tolerance_cents: int = 10
) -> Tuple[bool, int, int, int]:
    """
    Evaluates if the available Kalshi ask price is acceptable compared to the sheet's odds.
    
    Returns:
        (is_acceptable, target_cents, max_buy_cents, price_delta)
        - is_acceptable: True if kalshi_ask_cents <= max_buy_cents
        - target_cents: Implied fair price in cents from sheet odds
        - max_buy_cents: target_cents + slippage_tolerance_cents
        - price_delta: kalshi_ask_cents - target_cents (negative means better deal/discount!)
    """
    prob = american_to_implied_prob(sheet_odds)
    target_cents = implied_prob_to_kalshi_cents(prob)
    max_buy_cents = min(99, target_cents + slippage_tolerance_cents)
    price_delta = kalshi_ask_cents - target_cents
    
    is_acceptable = kalshi_ask_cents <= max_buy_cents
    return is_acceptable, target_cents, max_buy_cents, price_delta
