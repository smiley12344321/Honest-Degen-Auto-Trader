from src.sheet_reader import get_active_picks
from src.odds_converter import calculate_sizing
from config.settings import UNIT_SIZE_DOLLARS, PRICE_SLIPPAGE_TOLERANCE_CENTS

def main():
    picks = get_active_picks()
    print(f"\n==========================================")
    print(f"       ACTIVE PICKS PREVIEW ({len(picks)} found)")
    print(f"==========================================\n")
    for p in picks:
        print(f"Play: {p.play}")
        print(f"  Sport / Market : {p.sport} • {p.market}")
        print(f"  Odds (Sheet)   : {p.odds_raw}")
        if p.implied_cents is not None:
            max_buy = min(99, p.implied_cents + PRICE_SLIPPAGE_TOLERANCE_CENTS)
            sizing = calculate_sizing(p.units, UNIT_SIZE_DOLLARS, p.implied_cents)
            print(f"  Target Price   : {p.implied_cents}¢ (Max acceptable buy: {max_buy}¢)")
            print(f"  Unit Sizing    : {p.units}u @ ${UNIT_SIZE_DOLLARS:.2f}/unit")
            print(f"  Target Dollar  : ${sizing['target_risk_dollars']:.2f}")
            print(f"  Contracts      : {sizing['count_fp']} contracts (${sizing['actual_risk_dollars']:.2f} actual risk)")
        else:
            print(f"  Target Price   : Unparsed odds format")
        print(f"  Trade ID       : {p.trade_id}")
        print("-" * 50)

if __name__ == "__main__":
    main()
