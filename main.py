import argparse
import sys
from src.trader import Trader
from config.settings import KALSHI_ENV, UNIT_SIZE_DOLLARS, PRICE_SLIPPAGE_TOLERANCE_CENTS


def main():
    parser = argparse.ArgumentParser(description="Honest Degen Kalshi Auto Picker")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without placing live orders on Kalshi"
    )
    parser.add_argument(
        "--unit-size",
        type=float,
        default=None,
        help=f"Override unit size in dollars (default from settings: ${UNIT_SIZE_DOLLARS:.2f})"
    )
    parser.add_argument(
        "--slippage",
        type=int,
        default=None,
        help=f"Override max slippage tolerance in cents (default from settings: {PRICE_SLIPPAGE_TOLERANCE_CENTS}¢)"
    )
    args = parser.parse_args()

    effective_unit_size = args.unit_size if args.unit_size is not None else UNIT_SIZE_DOLLARS
    effective_slippage = args.slippage if args.slippage is not None else PRICE_SLIPPAGE_TOLERANCE_CENTS

    print("==========================================================")
    print("           HONEST DEGEN KALSHI AUTO PICKER                ")
    print("==========================================================")
    print(f"Environment         : {KALSHI_ENV.upper()}")
    print(f"Unit Size           : ${effective_unit_size:.2f} per unit")
    print(f"Slippage Tolerance  : {effective_slippage}¢")
    print(f"Dry Run Mode        : {'ENABLED' if args.dry_run else 'DISABLED'}")
    print("==========================================================\n")

    trader = Trader(
        unit_size_dollars=effective_unit_size,
        slippage_tolerance_cents=effective_slippage
    )
    summary = trader.run_cycle(dry_run=args.dry_run)
    
    if summary["errors"] > 0:
        print(f"\nCompleted with {summary['errors']} error(s).")
        sys.exit(0)  # Exit 0 so GitHub Actions doesn't fail the cron pipeline on individual pick skips


if __name__ == "__main__":
    main()
