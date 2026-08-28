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
        Examples:
          - 'Rays ML' -> ['Rays']
          - 'Phillies/Mariners NRFI' -> ['Phillies', 'Mariners']
          - 'Angels vs Rangers' -> ['Angels', 'Rangers']
          - 'Ugo Humbert vs Zizou Bergs Over 23' -> ['Ugo Humbert', 'Zizou Bergs']
        """
        clean_play = re.sub(r"\b(ML|F5|NRFI|YRFI|Over|Under|Spread|Run Line|Total|Sets?|Games?)\b.*", "", play, flags=re.IGNORECASE).strip()
        
        # Split on separators like '/', 'vs', 'vs.', '@'
        split_pattern = r"\s*(?:/|vs\.?|@|\band\b)\s*"
        parts = re.split(split_pattern, clean_play, flags=re.IGNORECASE)
        teams = [p.strip() for p in parts if p.strip()]
        return teams

    def match_pick(self, pick: PickRecord, live_events: Optional[List[Dict[str, Any]]] = None) -> MatchResult:
        """
        Resolves a PickRecord to an active Kalshi market ticker and contract side.
        """
        # 1. Check for parlays (unsupported on Kalshi as single contracts)
        if "parlay" in pick.market.lower() or "parlay" in pick.play.lower() or "sweep" in pick.play.lower():
            return MatchResult(
                matched=False,
                unsupported=True,
                reason="Multi-leg Parlays cannot be placed as a single contract on Kalshi."
            )

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
        is_ml = "moneyline" in market_lower or "ml" in market_lower or "side" in market_lower
        is_total = "total" in market_lower or "over" in play_lower or "under" in play_lower

        # Search through live events for best match
        best_market = None
        best_side = "yes"
        best_event = None

        for event in live_events:
            event_title = event.get("title", "").lower()
            event_ticker = event.get("event_ticker", "").lower()
            sub_title = event.get("sub_title", "").lower()

            # Filter by sport keyword in ticker or title if present
            sport_keywords = {
                "MLB": ["mlb", "baseball", "nrfi", "f5", "rbi", "home run", "strikeout", "run line"],
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

                # Handle F5
                elif is_f5:
                    if "first 5" in m_title or "f5" in m_title or "5 innings" in m_title:
                        best_market = mkt
                        best_side = "yes"
                        best_event = event
                        break

                # Handle Moneyline / Winner
                elif is_ml:
                    if any(t.lower() in m_title for t in teams_extracted + norm_teams) or "winner" in m_title or "win" in m_title:
                        best_market = mkt
                        best_side = "yes"
                        best_event = event
                        break

                # Handle Over / Under Totals
                elif is_total:
                    if "total" in m_title or "over" in m_title or "under" in m_title:
                        best_side = "yes" if "over" in play_lower else "no"
                        best_market = mkt
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
