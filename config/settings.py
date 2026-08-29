import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Google Sheets Source URL
DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vR4IUv_RLXHLoG3PgvhTtqUFVjkaOgoROCtwZhPMVlOnPSXz8C5ttjq7j1bHRdSR3ccjQ7TS-rwibvT/pub?gid=1669020965&single=true&output=csv"
)
SHEET_CSV_URL = os.getenv("SHEET_CSV_URL", DEFAULT_SHEET_URL)

# Sizing & Execution Settings (Configurable via config.json, .env, or environment variables)
CONFIG_JSON_FILE = BASE_DIR / "config" / "settings.json"
_file_config = {}
if CONFIG_JSON_FILE.exists():
    try:
        import json
        with open(CONFIG_JSON_FILE, "r", encoding="utf-8") as f:
            _file_config = json.load(f)
    except Exception as e:
        print(f"[settings.py] Warning reading config/settings.json: {e}")

DEFAULT_UNIT_SIZE_DOLLARS = float(_file_config.get("unit_size_dollars", 0.50))
UNIT_SIZE_DOLLARS = float(os.getenv("UNIT_SIZE_DOLLARS", str(DEFAULT_UNIT_SIZE_DOLLARS)))

DEFAULT_SLIPPAGE = int(_file_config.get("price_slippage_tolerance_cents", 10))
PRICE_SLIPPAGE_TOLERANCE_CENTS = int(os.getenv("PRICE_SLIPPAGE_TOLERANCE_CENTS", str(DEFAULT_SLIPPAGE)))

DEFAULT_FRACTIONAL = str(_file_config.get("allow_fractional_contracts", True)).lower() in ("true", "1", "yes")
ALLOW_FRACTIONAL_CONTRACTS = os.getenv("ALLOW_FRACTIONAL_CONTRACTS", str(DEFAULT_FRACTIONAL)).lower() in ("true", "1", "yes")

# Kalshi Configuration
KALSHI_ENV = os.getenv("KALSHI_ENV", "prod").lower()  # "prod" or "demo"
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY = os.getenv("KALSHI_PRIVATE_KEY", "")
KALSHI_BASE_URL = (
    "https://api.elections.kalshi.com/trade-api/v2"
    if KALSHI_ENV == "prod"
    else "https://demo-api.kalshi.co/trade-api/v2"
)

# Discord Notifications
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# State Persistence
PLACED_TRADES_FILE = BASE_DIR / os.getenv("PLACED_TRADES_FILE", "placed_trades.json")
TEAM_MAPPINGS_FILE = BASE_DIR / "config" / "team_mappings.json"
