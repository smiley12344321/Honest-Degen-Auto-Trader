import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from config.settings import TEAM_MAPPINGS_FILE
from src.sheet_reader import PickRecord
from src.kalshi_client import KalshiClient


@dataclass
class MatchResult:
    matched: bool
    ticker: Optional[str] = None
    event_ticker: Optional[str] = None
    side: str = "yes"  # "yes" or "no"
    market_title: Optional[str] = None
    reason: Optional[str] = None
    unsupported: bool = False
    is_combo: bool = False
    combo_legs: Optional[List[Dict[str, str]]] = None


class MarketMatcher:
    """
    Matches sports picks from the Google Sheet to live Kalshi markets and contract tickers.
    """

    def __init__(self, kalshi_client: KalshiClient, mappings_file: Path = TEAM_MAPPINGS_FILE):
        self.client = kalshi_client
        self.team_mappings = self._load_mappings(mappings_file)

    def _load_mappings(self, filepath: Path) -> Dict[str, Dict[str, str]]:
        if not filepath.exists():
            return {}
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[MarketMatcher] Warning loading team mappings: {e}")
            return {}

    def normalize_team(self, sport: str, raw_team_name: str) -> str:
        """
        Normalizes a team name/nickname using team_mappings.json.
        """
        clean = raw_team_name.strip()
        sport_upper = sport.upper()
        
        sport_map = self.team_mappings.get(sport_upper, {})
        for name_key, code in sport_map.items():
            if name_key.lower() == clean.lower():
                return code
            # Check if name contains key word
            if name_key.lower() in clean.lower():
                return code
        return clean

    def extract_teams_from_play(self, play: str, sport: str) -> List[str]:
        """
        Extracts team names or abbreviations from a play string.
        """
        clean_play = re.sub(r"\b(ML|F5|NRFI|YRFI|Over|Under|Spread|Run Line|Total|Sets?|Games?)\b.*", "", play, flags=re.IGNORECASE).strip()
        
        # Split on separators like '/', 'vs', 'vs.', '@'
        split_pattern = r"\s*(?:/|vs\.?|@|\band\b)\s*"
        parts = re.split(split_pattern, clean_play, flags=re.IGNORECASE)
        teams = [p.strip() for p in parts if p.strip()]
        return teams

    def extract_parlay_legs(self, play: str, notes: str = "") -> List[str]:
        """
        Extracts individual legs from a parlay play description or notes.
        Examples:
          - 'Gauff +3.5 / Tiafoe +4.5' -> ['Gauff +3.5', 'Tiafoe +4.5']
          - 'Brunold ML / Gulin ML' -> ['Brunold ML', 'Gulin ML']
        """
        # First check play string for slashes or ' & '
        if "/" in play and not any(k in play.lower() for k in ["under", "over", "nrfi"]):
            return [p.strip() for p in play.split("/") if p.strip()]
        if "&" in play:
            return [p.strip() for p in play.split("&") if p.strip()]
        
        # If play is generic like '10-Leg Royal Sweep', inspect notes for player names/legs
        if notes:
            # Look for lines or bullet points in notes
            note_lines = [l.strip() for l in re.split(r"[;\n,]+", notes) if len(l.strip()) > 3]
            if len(note_lines) >= 2:
                return note_lines

        return [play.strip()]

    def match_pick(self, pick: PickRecord, live_events: Optional[List[Dict[str, Any]]] = None) -> MatchResult:
        """
        Resolves a PickRecord to an active Kalshi market ticker or combo market legs.
        """
        # Fetch relevant open events from Kalshi if not supplied
        if live_events is None:
            try:
                live_events = self.client.get_events(status="open")
            except Exception as e:
                return MatchResult(matched=False, reason=f"Failed to query Kalshi events: {e}")

        # Check for Parlays / Multi-Leg Combos
        is_parlay = "parlay" in pick.market.lower() or "parlay" in pick.play.lower() or "sweep" in pick.play.lower()
        if is_parlay:
            legs = self.extract_parlay_legs(pick.play, pick.notes)
            resolved_legs = []
            
            for leg_str in legs:
                # Sub-match each leg
                sub_pick = PickRecord(
                    day=pick.day,
                    date=pick.date,
                    sport=pick.sport,
                    play=leg_str,
                    market="Side / ML" if "ml" in leg_str.lower() else pick.market,
                    odds_raw="",
                    odds_numeric=None,
                    implied_cents=None,
                    grade=pick.grade,
                    units=pick.units,
                    risk_dollars_sheet=None,
                    result="pending",
                    notes="",
                    trade_id=f"{pick.trade_id}_leg"
                )
                sub_match = self._match_single_pick(sub_pick, live_events)
                if sub_match.matched and sub_match.ticker:
                    resolved_legs.append({
                        "market_ticker": sub_match.ticker,
                        "event_ticker": sub_match.event_ticker or ""
                    })
            
            # If at least 2 legs are resolved (or in dry run / simulation mode where mock events are used)
            if len(resolved_legs) >= 2:
                return MatchResult(
                    matched=True,
                    is_combo=True,
                    combo_legs=resolved_legs,
                    market_title=f"Parlay: {pick.play} ({len(resolved_legs)} legs)"
                )
            elif len(legs) >= 2:
                # Parlay detected but specific legs could not all be matched in current open events
                return MatchResult(
                    matched=False,
                    is_combo=True,
                    reason=f"Parlay '{pick.play}' has {len(legs)} legs, but active Kalshi markets were not found for all legs."
                )
            else:
                return MatchResult(
                    matched=False,
                    unsupported=True,
                    is_combo=True,
                    reason=f"Could not parse individual legs for parlay '{pick.play}'."
                )

        return self._match_single_pick(pick, live_events)

    def _match_single_pick(self, pick: PickRecord, live_events: List[Dict[str, Any]]) -> MatchResult:
        sport_upper = pick.sport.upper()
        market_lower = pick.market.lower()
        play_lower = pick.play.lower()

        # Extract target teams
        teams_extracted = self.extract_teams_from_play(pick.play, pick.sport)
        norm_teams = [self.normalize_team(pick.sport, t) for t in teams_extracted]

        # Fetch relevant open events from Kalshi if not supplied
        if live_events is None:
            try:
                live_events = self.client.get_events(status="open")
            except Exception as e:
                return MatchResult(matched=False, reason=f"Failed to query Kalshi events: {e}")

        # Determine target category/keywords
        is_nrfi = "nrfi" in market_lower or "nrfi" in play_lower or "first inning" in market_lower
        is_f5 = "f5" in market_lower or "f5" in play_lower or "first 5" in market_lower
        is_f3 = "f3" in market_lower or "f3" in play_lower or "first 3" in market_lower or "first 3" in play_lower
        is_spread = "spread" in market_lower or "run line" in market_lower or "spread" in play_lower or "wins by" in play_lower
        is_ml = "moneyline" in market_lower or "ml" in market_lower or "side" in market_lower or "win" in play_lower or "to win" in play_lower
        is_total = "total" in market_lower or "over" in play_lower or "under" in play_lower or "points" in market_lower or "runs" in market_lower
        is_explicit_no = play_lower.startswith("no ") or play_lower.startswith("no ·") or "to win: no" in play_lower

        # Search through live events for best match
        best_market = None
        best_side = "no" if is_explicit_no else "yes"
        best_event = None

        for event in live_events:
            event_title = event.get("title", "").lower()
            event_ticker = event.get("event_ticker", "").lower()
            sub_title = event.get("sub_title", "").lower()

            # Filter by sport keyword in ticker or title if present
            sport_keywords = {
                "MLB": ["mlb", "baseball", "nrfi", "f5", "f3", "rbi", "home run", "strikeout", "run line"],
                "NBA": ["nba", "basketball"],
                "WNBA": ["wnba", "basketball"],
                "NHL": ["nhl", "hockey"],
                "TENNIS": ["tennis", "atp", "wta", "us open", "wimbledon", "french open", "australian open"]
            }
            keywords = sport_keywords.get(sport_upper, [])
            if keywords and not any(k in event_ticker or k in event_title for k in keywords):
                # If no sport keyword matches, only allow if at least one normalized team code is in event_ticker
                if not any(t.lower() in event_ticker or t.lower() in event_title for t in norm_teams if len(t) >= 2):
                    continue

            # Check team/player overlap
            teams_matched = False
            for t in teams_extracted + norm_teams:
                if len(t) >= 2 and (t.lower() in event_title or t.lower() in sub_title or t.lower() in event_ticker):
                    teams_matched = True
                    break

            if not teams_matched:
                continue

            # Check child markets in event
            markets = event.get("markets", [])
            for mkt in markets:
                m_title = mkt.get("title", "").lower()
                m_ticker = mkt.get("ticker", "")
                m_subtitle = mkt.get("subtitle", "").lower()

                # Handle NRFI
                if is_nrfi:
                    if "first inning" in m_title or "1st inning" in m_title or "nrfi" in m_title or "run" in m_title:
                        # On Kalshi: "Will there be a run in the 1st inning?" -> NRFI is buying 'No'
                        # "Will the 1st inning be scoreless?" -> NRFI is buying 'Yes'
                        if "scoreless" in m_title or "no run" in m_title:
                            best_side = "yes"
                        else:
                            best_side = "no"
                        best_market = mkt
                        best_event = event
                        break

                # Handle F3 (First 3 Innings)
                elif is_f3:
                    if "first 3" in m_title or "f3" in m_title or "3 innings" in m_title:
                        best_market = mkt
                        best_side = "no" if is_explicit_no else "yes"
                        best_event = event
                        break

                # Handle F5 (First 5 Innings)
                elif is_f5:
                    if "first 5" in m_title or "f5" in m_title or "5 innings" in m_title:
                        best_market = mkt
                        best_side = "no" if is_explicit_no else "yes"
                        best_event = event
                        break

                # Handle Spreads / Margin
                elif is_spread:
                    if "spread" in m_title or "run line" in m_title or "margin" in m_title or "by over" in m_title:
                        best_market = mkt
                        best_side = "no" if is_explicit_no else "yes"
                        best_event = event
                        break

                # Handle Over / Under Totals
                elif is_total:
                    if "total" in m_title or "over" in m_title or "under" in m_title or "points" in m_title or "runs" in m_title:
                        if is_explicit_no:
                            best_side = "no"
                        else:
                            best_side = "yes" if "over" in play_lower else "no"
                        best_market = mkt
                        best_event = event
                        break

                # Handle Moneyline / Winner
                elif is_ml:
                    if any(t.lower() in m_title for t in teams_extracted + norm_teams) or "winner" in m_title or "win" in m_title:
                        best_market = mkt
                        best_side = "no" if is_explicit_no else "yes"
                        best_event = event
                        break

            if best_market:
                break

        if best_market:
            return MatchResult(
                matched=True,
                ticker=best_market.get("ticker"),
                event_ticker=best_event.get("event_ticker") if best_event else None,
                side=best_side,
                market_title=best_market.get("title") or best_event.get("title")
            )

        return MatchResult(
            matched=False,
            reason=f"No active Kalshi market found matching '{pick.play}' ({pick.sport} - {pick.market})."
        )
