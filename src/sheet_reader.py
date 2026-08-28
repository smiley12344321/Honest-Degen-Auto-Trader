import hashlib
import io
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
import pandas as pd
import requests

from src.odds_converter import parse_american_odds, american_to_implied_prob, implied_prob_to_kalshi_cents
from config.settings import SHEET_CSV_URL


@dataclass
class PickRecord:
    day: str
    date: str
    sport: str
    play: str
    market: str
    odds_raw: str
    odds_numeric: Optional[float]
    implied_cents: Optional[int]
    grade: str
    units: float
    risk_dollars_sheet: Optional[float]
    result: str
    notes: str
    trade_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_active(self) -> bool:
        """
        A pick is active if it has not been settled (i.e. result is 'pending', empty/blank, or None).
        Settled results include: 'win', 'loss', 'push', 'void', 'loss/scratch', etc.
        """
        if not self.result:
            return True
        res = self.result.strip().lower()
        if res in ("pending", "active", "open", ""):
            return True
        # If result is already graded
        if res in ("win", "loss", "push", "void", "cancel", "cancelled", "draw"):
            return False
        # Catch other text that contains win/loss
        if "win" in res or "loss" in res or "push" in res or "void" in res:
            return False
        return True


def generate_trade_id(date: str, sport: str, play: str, market: str, odds: str) -> str:
    """
    Generates a deterministic 16-character SHA-256 hash identifying the pick.
    """
    raw_key = f"{date.strip()}|{sport.strip().upper()}|{play.strip().lower()}|{market.strip().lower()}|{odds.strip()}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]


def parse_units(raw: Any) -> float:
    """
    Parses unit string like '1.50', '2', '2 units', '1u' into a float.
    Defaults to 1.0 if not parsable.
    """
    if raw is None or pd.isna(raw):
        return 1.0
    raw_str = str(raw).strip()
    match = re.search(r"(\d+(?:\.\d+)?)", raw_str)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return 1.0
    return 1.0


def parse_risk_dollars(raw: Any) -> Optional[float]:
    """
    Parses sheet's Risk $ column if populated (e.g. '1,250.00', '$500.00').
    """
    if raw is None or pd.isna(raw):
        return None
    raw_str = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(raw_str)
    except ValueError:
        return None


def fetch_sheet_csv(url: str = SHEET_CSV_URL, timeout: int = 15) -> str:
    """
    Fetches the raw CSV content from Google Sheets URL.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HonestDegenAutoPicker/1.0"
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_picks_from_csv(csv_text: str) -> List[PickRecord]:
    """
    Parses raw CSV text into a list of PickRecord objects.
    """
    df = pd.read_csv(io.StringIO(csv_text), dtype=str)
    
    # Normalize column names
    df.columns = [col.strip() for col in df.columns]
    
    # Required columns in the sheet
    req_cols = ["Date", "Sport", "Play", "Market", "Odds"]
    for col in req_cols:
        if col not in df.columns:
            raise ValueError(f"Missing expected column '{col}' in Google Sheet CSV. Found: {list(df.columns)}")

    records: List[PickRecord] = []
    
    for _, row in df.iterrows():
        # Skip completely empty rows
        play = str(row.get("Play", "")).strip() if pd.notna(row.get("Play")) else ""
        if not play or play.lower() == "nan":
            continue

        day = str(row.get("Day", "")).strip() if pd.notna(row.get("Day")) else ""
        date = str(row.get("Date", "")).strip() if pd.notna(row.get("Date")) else ""
        sport = str(row.get("Sport", "")).strip() if pd.notna(row.get("Sport")) else ""
        market = str(row.get("Market", "")).strip() if pd.notna(row.get("Market")) else ""
        odds_raw = str(row.get("Odds", "")).strip() if pd.notna(row.get("Odds")) else ""
        grade = str(row.get("Grade", "")).strip() if pd.notna(row.get("Grade")) else ""
        result = str(row.get("Result", "")).strip() if pd.notna(row.get("Result")) else ""
        notes = str(row.get("Notes", "")).strip() if pd.notna(row.get("Notes")) else ""

        odds_numeric = parse_american_odds(odds_raw)
        implied_cents = None
        if odds_numeric is not None:
            prob = american_to_implied_prob(odds_numeric)
            implied_cents = implied_prob_to_kalshi_cents(prob)

        units = parse_units(row.get("Units"))
        risk_dollars_sheet = parse_risk_dollars(row.get("Risk $"))
        
        trade_id = generate_trade_id(date, sport, play, market, odds_raw)

        record = PickRecord(
            day=day,
            date=date,
            sport=sport,
            play=play,
            market=market,
            odds_raw=odds_raw,
            odds_numeric=odds_numeric,
            implied_cents=implied_cents,
            grade=grade,
            units=units,
            risk_dollars_sheet=risk_dollars_sheet,
            result=result,
            notes=notes,
            trade_id=trade_id
        )
        records.append(record)

    return records


def get_active_picks(url: str = SHEET_CSV_URL, max_age_days: int = 3) -> List[PickRecord]:
    """
    Convenience function: fetches CSV and returns only active/pending picks
    from the current or recent slate (within max_age_days of the latest entry).
    """
    csv_text = fetch_sheet_csv(url)
    all_picks = parse_picks_from_csv(csv_text)
    active_unfiltered = [pick for pick in all_picks if pick.is_active]
    
    if not active_unfiltered:
        return []

    # Find the most recent day number / date to prevent stale 'pending' rows from months ago
    def extract_day_num(p: PickRecord) -> int:
        try:
            return int(re.search(r"\d+", p.day).group(0))
        except Exception:
            return 0

    max_day = max((extract_day_num(p) for p in all_picks if p.day), default=0)
    
    if max_day > 0:
        # Only return active picks within max_age_days of the latest day in the sheet
        return [p for p in active_unfiltered if (max_day - extract_day_num(p)) <= max_age_days]

    return active_unfiltered
