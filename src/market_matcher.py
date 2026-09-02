import datetime
import hashlib
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
    exchange_index: Optional[int] = None


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
        clean_play = re.sub(r"\b[ouOU]?\s*[+-]?\d+(?:\.\d+)?.*", "", play)
        clean_play = re.sub(r"\b(ML|F5|F3|F7|NRFI|YRFI|Over|Under|Spread|Run Line|Total|Sets?|Games?)\b.*", "", clean_play, flags=re.IGNORECASE).strip()
        clean_play = re.sub(r"\s+[ouOU]$", "", clean_play).strip()
        
        # Split on separators like '/', 'vs', 'vs.', '@'
        split_pattern = r"\s*(?:/|vs\.?|@|\band\b)\s*"
        parts = re.split(split_pattern, clean_play, flags=re.IGNORECASE)
        teams = [p.strip() for p in parts if p.strip()]
        return teams

    def extract_parlay_legs(self, play: str, notes: str = "") -> List[str]:
        """
        Extracts individual legs from a parlay play description or notes.
        Examples:
          - 'Rinderknech ML + Tirante ML' -> ['Rinderknech ML', 'Tirante ML']
          - 'Dodgers F5 +1 + Guardians F5 +0.5' -> ['Dodgers F5 +1', 'Guardians F5 +0.5']
          - 'Gauff +3.5 / Tiafoe +4.5' -> ['Gauff +3.5', 'Tiafoe +4.5']
        """
        # 1. Primary: Split the play string on multi-leg separators:
        #    ' + ' (plus sign with spaces), ' / ' (except totals like O/U), ' & ', ' and ', ' | '
        split_pattern = r"\s+\+\s+|\s+/\s+|\s+&\s+|\s+and\s+|\s+\|\s+"
        if not any(k in play.lower() for k in ["under", "over", "o/u", "nrfi", "yrfi"]):
            parts = [p.strip() for p in re.split(split_pattern, play, flags=re.IGNORECASE) if p.strip()]
            if len(parts) >= 2:
                return parts

        # If '+' exists with spaces anywhere in play
        if " + " in play:
            parts = [p.strip() for p in play.split(" + ") if p.strip()]
            if len(parts) >= 2:
                return parts

        # 2. Secondary: If play is a generic sweep title (e.g. '10-Leg Parlay', 'Sunday Sweep'),
        #    only then inspect notes for structured bullet points or lines
        play_lower = play.lower()
        if any(k in play_lower for k in ["sweep", "parlay", "teaser"]) and notes:
            lines = [l.strip() for l in re.split(r"[\r\n]+", notes) if len(l.strip()) > 3]
            bet_lines = [
                l for l in lines 
                if any(k in l.lower() for k in [" ml", "+", "-", "over ", "under ", " to win", " f5"])
            ]
            if len(bet_lines) >= 2:
                return bet_lines

        return [play.strip()]

    def match_pick(self, pick: PickRecord, live_events: Optional[List[Dict[str, Any]]] = None) -> MatchResult:
        """
        Resolves a PickRecord to an active Kalshi market ticker or combo market legs.
        """
        # Fetch relevant open events from Kalshi if not supplied
        if live_events is None:
            try:
                live_events = self.client.get_sports_events(status="open")
            except Exception as e:
                return MatchResult(matched=False, reason=f"Failed to query Kalshi events: {e}")

        # Check for Parlays / Multi-Leg Combos / SGP / Plus in play
        market_lower = pick.market.lower()
        play_lower = pick.play.lower()

        extracted_legs = self.extract_parlay_legs(pick.play, pick.notes)
        is_parlay = (
            len(extracted_legs) >= 2
            or "parlay" in market_lower
            or "parlay" in play_lower
            or "sgp" in market_lower
            or "sgp" in play_lower
            or "combo" in market_lower
            or "sweep" in play_lower
            or "teaser" in market_lower
            or (" + " in pick.play and not re.search(r"f5\s*[+-]\d", play_lower))
        )
        if is_parlay:
            legs = extracted_legs
            resolved_legs = []
            
            for leg_str in legs:
                leg_lower = leg_str.lower()
                if "corner" in leg_lower:
                    sub_market = "Team Corners" if any(k in leg_lower for k in ["+", "over", "under", "total"]) else "Corners"
                elif "btts" in leg_lower or "both team" in leg_lower:
                    sub_market = "BTTS"
                elif "f5" in leg_lower or "first 5" in leg_lower:
                    if "total" in leg_lower or "over" in leg_lower or "under" in leg_lower or re.search(r"[ou]\s*\d", leg_lower):
                        sub_market = "First 5 Total"
                    elif "+" in leg_lower or (re.search(r"-\d", leg_lower) and not re.search(r"[ou]\d", leg_lower) and "spread" in leg_lower):
                        sub_market = "First 5 Spread"
                    elif "+" in leg_lower or "-" in leg_lower:
                        sub_market = "First 5 Spread"
                    elif "ml" in leg_lower or "win" in leg_lower:
                        sub_market = "First 5 Moneyline"
                    else:
                        sub_market = "First 5 Moneyline"
                elif "f3" in leg_lower or "first 3" in leg_lower:
                    sub_market = "First 3 Moneyline"
                elif "nrfi" in leg_lower or "yrfi" in leg_lower or "first inning" in leg_lower:
                    sub_market = "NRFI"
                elif "total" in leg_lower or "over" in leg_lower or "under" in leg_lower or re.search(r"\b[ou]\d", leg_lower):
                    sub_market = "Game Total"
                elif "+" in leg_lower or (re.search(r"-\d", leg_lower) and not re.search(r"ml", leg_lower)):
                    sub_market = "Spread"
                elif "ml" in leg_lower or "win" in leg_lower or "side" in leg_lower:
                    sub_market = "Moneyline"
                else:
                    sub_market = pick.market

                sub_pick = PickRecord(
                    day=pick.day,
                    date=pick.date,
                    sport=pick.sport,
                    play=leg_str,
                    market=sub_market,
                    odds_raw="",
                    odds_numeric=None,
                    implied_cents=None,
                    grade=pick.grade,
                    units=pick.units,
                    risk_dollars_sheet=None,
                    result="pending",
                    notes="",
                    trade_id=f"leg_{hashlib.sha256(leg_str.encode()).hexdigest()[:8]}"
                )
                leg_res = self._match_single_pick(sub_pick, live_events)
                if not leg_res.matched and self.client:
                    # Targeted sport series fallback for this leg
                    sport_series_map = {
                        "MLB": ["KXMLBSPREAD", "KXMLBTOTAL", "KXMLBGAME", "KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL", "KXMLBRFI", "KXMLBF3", "KXMLBF7", "KXMLB"],
                        "KBO": ["KXKBOTOTAL", "KXKBOGAME", "KXKBORFI"],
                        "NPB": ["KXNPBTOTAL", "KXNPBGAME", "KXNPBRFI", "KXNPBSPREAD"],
                        "NCAAF": ["KXNCAAFSPREAD", "KXNCAAFGAME", "KXNCAAFTOTAL", "KXNCAAF1HSPREAD", "KXNCAAF1HTOTAL"],
                        "NFL": ["KXNFLSPREAD", "KXNFLGAME", "KXNFLTOTAL"],
                        "SOCCER": ["KXLALIGAGAME", "KXLALIGATCORNERS", "KXLALIGACORNERS", "KXLALIGATOTAL", "KXLALIGABTTS", "KXLALIGASPREAD", "KXLALIGA", "KXUCLGAME", "KXUCLTOTAL", "KXUCLBTTS", "KXUCLCORNERS", "KXUCLTCORNERS", "KXSERIEAGAME", "KXSERIEATOTAL", "KXSERIEABTTS", "KXSERIEACORNERS", "KXSERIEATCORNERS", "KXBUNDESLIGAGAME", "KXBUNDESLIGATOTAL", "KXBUNDESLIGABTTS", "KXBUNDESLIGACORNERS", "KXBUNDESLIGATCORNERS", "KXMLSGAME", "KXMLSTOTAL", "KXMLSTCORNERS", "KXMLSCORNERS", "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLTCORNERS", "KXEPLCORNERS", "KXSOCCER"],
                        "EPL": ["KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLCORNERS", "KXEPLTCORNERS", "KXEPLSPREAD", "KXEPL1H", "KXEPL2H", "KXEPLMATCH"],
                        "WNBA": ["KXWNBATOTAL", "KXWNBAGAME", "KXWNBASPREAD"],
                        "NBA": ["KXNBATOTAL", "KXNBAGAME", "KXNBASPREAD"],
                        "TENNIS": ["KXATPMATCH", "KXWTAMATCH", "KXUSOPEN", "KXUSOPENMENSINGLES", "KXUSOPENWOMENSINGLES"]
                    }
                    candidate_series = sport_series_map.get(pick.sport.upper(), [])
                    fallback_events = []
                    for st in candidate_series:
                        try:
                            evs = self.client.get_events(series_ticker=st, status="open", with_nested_markets=True)
                            if evs:
                                fallback_events.extend(evs)
                        except Exception:
                            pass
                    if fallback_events:
                        leg_res = self._match_single_pick(sub_pick, fallback_events)

                if not leg_res.matched:
                    return MatchResult(
                        matched=False,
                        reason=f"Parlay leg '{leg_str}' could not be matched on Kalshi ({leg_res.reason})"
                    )
                resolved_legs.append({
                    "leg_description": leg_str,
                    "market_ticker": leg_res.ticker,
                    "event_ticker": leg_res.event_ticker,
                    "side": leg_res.side,
                    "market_title": leg_res.market_title
                })

            return MatchResult(
                matched=True,
                is_combo=True,
                combo_legs=resolved_legs,
                market_title=f"{len(resolved_legs)}-Leg Combo Parlay"
            )

        # Match single pick against provided live events
        res = self._match_single_pick(pick, live_events)
        if res.matched:
            return res

        # If not matched in bulk events, execute targeted sport series fallback
        if self.client:
            sport_series_map = {
                "MLB": ["KXMLBSPREAD", "KXMLBTOTAL", "KXMLBGAME", "KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL", "KXMLBRFI", "KXMLBF3", "KXMLBF7", "KXMLB"],
                "KBO": ["KXKBOTOTAL", "KXKBOGAME", "KXKBORFI"],
                "NPB": ["KXNPBTOTAL", "KXNPBGAME", "KXNPBRFI", "KXNPBSPREAD"],
                "NCAAF": ["KXNCAAFSPREAD", "KXNCAAFGAME", "KXNCAAFTOTAL", "KXNCAAF1HSPREAD", "KXNCAAF1HTOTAL"],
                "NFL": ["KXNFLSPREAD", "KXNFLGAME", "KXNFLTOTAL"],
                "SOCCER": ["KXLALIGAGAME", "KXLALIGATCORNERS", "KXLALIGACORNERS", "KXLALIGATOTAL", "KXLALIGABTTS", "KXLALIGASPREAD", "KXLALIGA", "KXUCLGAME", "KXUCLTOTAL", "KXUCLBTTS", "KXUCLCORNERS", "KXUCLTCORNERS", "KXSERIEAGAME", "KXSERIEATOTAL", "KXSERIEABTTS", "KXSERIEACORNERS", "KXSERIEATCORNERS", "KXBUNDESLIGAGAME", "KXBUNDESLIGATOTAL", "KXBUNDESLIGABTTS", "KXBUNDESLIGACORNERS", "KXBUNDESLIGATCORNERS", "KXMLSGAME", "KXMLSTOTAL", "KXMLSTCORNERS", "KXMLSCORNERS", "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLTCORNERS", "KXEPLCORNERS", "KXSOCCER"],
                "EPL": ["KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLCORNERS", "KXEPLTCORNERS", "KXEPLSPREAD", "KXEPL1H", "KXEPL2H", "KXEPLMATCH"],
                "WNBA": ["KXWNBATOTAL", "KXWNBAGAME", "KXWNBASPREAD"],
                "NBA": ["KXNBATOTAL", "KXNBAGAME", "KXNBASPREAD"],
                "TENNIS": ["KXATPMATCH", "KXWTAMATCH", "KXUSOPEN", "KXUSOPENMENSINGLES", "KXUSOPENWOMENSINGLES"]
            }
            candidate_series = sport_series_map.get(pick.sport.upper(), [])
            fallback_events = []
            for st in candidate_series:
                try:
                    evs = self.client.get_events(series_ticker=st, status="open", with_nested_markets=True)
                    if evs:
                        fallback_events.extend(evs)
                except Exception:
                    pass
            if fallback_events:
                fallback_res = self._match_single_pick(pick, fallback_events)
                if fallback_res.matched:
                    return fallback_res

        return res

    def _match_single_pick(self, pick: PickRecord, live_events: List[Dict[str, Any]]) -> MatchResult:
        play_lower = pick.play.lower()
        market_lower = pick.market.lower()
        sport_upper = pick.sport.upper()

        teams_extracted = self.extract_teams_from_play(pick.play, pick.sport)
        norm_teams = [self.normalize_team(pick.sport, t) for t in teams_extracted]

        # Determine market category
        is_nrfi = "nrfi" in market_lower or "nrfi" in play_lower or "first inning" in market_lower or "1st inning" in market_lower or "yrfi" in market_lower or "yrfi" in play_lower
        is_corner = "corner" in market_lower or "corner" in play_lower
        is_btts = "btts" in market_lower or "btts" in play_lower or "both team" in play_lower
        is_f5_total = (("f5" in market_lower or "first 5" in market_lower or "f5" in play_lower) and ("total" in market_lower or "over" in play_lower or "under" in play_lower or re.search(r"[ou]\s*\d", play_lower)))
        is_f5 = ("f5" in market_lower or "f5" in play_lower or "first 5" in market_lower) and not is_f5_total
        is_f3 = "f3" in market_lower or "f3" in play_lower or "first 3" in market_lower
        is_spread = ("spread" in market_lower or "run line" in market_lower or "spread" in play_lower or "wins by" in play_lower or ("+" in play_lower and not is_corner) or (re.search(r"-\d", play_lower) and not is_nrfi and not is_f3 and not is_f5_total and ("f5" not in play_lower or re.search(r"f5\s*[+-]", play_lower)))) and not is_corner and not is_btts
        is_ml = ("moneyline" in market_lower or "ml" in market_lower or "side" in market_lower or "win" in play_lower or "to win" in play_lower) and not is_corner and not is_btts and not is_f5_total
        is_total = (("total" in market_lower or "over" in play_lower or "under" in play_lower or "points" in market_lower or "runs" in market_lower or "goals" in market_lower or re.search(r"\b[ou]\d+", play_lower)) or is_f5_total) and not is_corner and not is_btts
        is_explicit_no = play_lower.startswith("no ") or play_lower.startswith("no ·") or "to win: no" in play_lower

        # Search through live events for best match
        best_market = None
        best_side = "no" if is_explicit_no else "yes"
        best_event = None

        # Determine target team code/name for side-specific markets
        primary_team = norm_teams[0] if norm_teams else ""
        primary_raw = teams_extracted[0] if teams_extracted else ""

        # Extract numerical total/spread line if present (e.g. 177, 3.5, 23.5)
        num_match = re.search(r"[ouOU]?\s*([+-]?\d+(?:\.\d+)?)", pick.play)
        target_number = abs(float(num_match.group(1))) if num_match else None

        # Filter and score live events for relevance
        date_code = ""
        try:
            parts = [int(p) for p in pick.date.split("/") if p.isdigit()]
            if len(parts) >= 2:
                m, d = parts[0], parts[1]
                y = parts[2] if len(parts) >= 3 else 2026
                dt = datetime.date(y, m, d)
                date_code = f"{dt.strftime('%y')}{dt.strftime('%b').upper()}{d:02d}"
        except Exception:
            pass

        def score_event(ev: Dict[str, Any]) -> int:
            score = 0
            et = ev.get("event_ticker", "").upper()
            title = ev.get("title", "").lower()
            
            # Date bonus
            if date_code and date_code in et:
                score += 100
            
            # Series category match bonus
            if is_corner and ("TCORNER" in et or "team corner" in title):
                score += 100
            elif is_corner and ("CORNER" in et or "corner" in title):
                score += 80
            elif is_btts and ("BTTS" in et or "btts" in title or "both team" in title):
                score += 80
            elif is_f5_total and ("F5TOTAL" in et or "first 5 total" in title):
                score += 120
            elif is_f5 and is_spread and ("F5SPREAD" in et or "first 5 spread" in title):
                score += 80
            elif is_f5 and not is_spread and ("F5" in et or "first 5" in title) and "SPREAD" not in et and "TOTAL" not in et:
                score += 50
            elif is_f3 and ("F3" in et or "first 3" in title):
                score += 50
            elif is_nrfi and ("RFI" in et or "1INNING" in et or "first inning" in title or "1st inning" in title):
                score += 50
            elif is_total and ("TOTAL" in et or "total" in title):
                score += 50
            elif is_spread and ("SPREAD" in et or "spread" in title or "margin" in title):
                score += 50
            elif is_ml and ("GAME" in et or "MATCH" in et):
                score += 30

            # Dual team match bonus
            matched_teams = 0
            for idx_t in range(len(teams_extracted)):
                t_raw = teams_extracted[idx_t] if idx_t < len(teams_extracted) else ""
                t_norm = norm_teams[idx_t] if idx_t < len(norm_teams) else ""
                if (t_norm and t_norm.upper() in et) or (t_raw and t_raw.lower() in title):
                    matched_teams += 1
            if len(teams_extracted) >= 2 and matched_teams >= 2:
                score += 200

            return score

        sorted_events = sorted(live_events, key=score_event, reverse=True)

        for event in sorted_events:
            event_title = event.get("title", "").lower()
            event_ticker = event.get("event_ticker", "").lower()
            sub_title = event.get("sub_title", "").lower()

            sport_keywords = {
                "MLB": ["mlb", "baseball", "nrfi", "rfi", "f5", "f3", "rbi", "home run", "strikeout", "run line"],
                "NPB": ["npb", "baseball", "japan", "japanese"],
                "NBA": ["nba", "basketball"],
                "WNBA": ["wnba", "basketball"],
                "NHL": ["nhl", "hockey"],
                "TENNIS": ["tennis", "atp", "wta", "us open", "wimbledon", "french open", "australian open"],
                "NCAAF": ["ncaaf", "cfb", "college football", "football"],
                "EPL": ["epl", "premier", "soccer", "football", "match"],
                "KBO": ["kbo", "baseball", "korean"],
                "SOCCER": ["soccer", "football", "epl", "uefa", "btts", "goals", "laliga", "seriea", "bundesliga", "corner", "corners"]
            }
            keywords = sport_keywords.get(sport_upper, [])
            if keywords and not any(k in event_ticker or k in event_title for k in keywords):
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

            markets = event.get("markets", [])
            
            # 1. Handle NRFI / YRFI
            if is_nrfi:
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").lower()
                    if "first inning" in m_title or "1st inning" in m_title or "rfi" in m_ticker or "run" in m_title:
                        is_yrfi = "yrfi" in play_lower or "yrfi" in market_lower or "over" in play_lower
                        if "scoreless" in m_title or "no run" in m_title:
                            best_side = "no" if is_yrfi else "yes"
                        else:
                            best_side = "yes" if is_yrfi else "no"
                        best_market = mkt
                        best_event = event
                        break

            # 2. Handle Corners (Total Corners & Team Corners)
            elif is_corner:
                is_under_corner = "under" in play_lower or is_explicit_no
                candidate_markets = []
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = m_ticker.split("-")[-1]

                    team_match = False
                    if primary_team and (m_suffix.startswith(primary_team.upper()) or primary_team.lower() in m_title):
                        team_match = True
                    elif primary_raw and (primary_raw.lower() in m_title or m_suffix.startswith(primary_raw.upper())):
                        team_match = True

                    m_num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", m_title) or re.search(r"(\d+(?:\.\d+)?)$", m_suffix)
                    m_num = float(m_num_match.group(1)) if m_num_match else None

                    if primary_team or primary_raw:
                        if team_match:
                            candidate_markets.append((mkt, m_num))
                    else:
                        candidate_markets.append((mkt, m_num))

                if candidate_markets:
                    valid_candidates = [c for c in candidate_markets if c[1] is not None]
                    if valid_candidates and target_number is not None:
                        # Find closest line or >= line
                        best_market = min(valid_candidates, key=lambda x: abs(x[1] - target_number))[0]
                    else:
                        best_market = candidate_markets[0][0]

                    best_side = "no" if is_under_corner else "yes"
                    best_event = event
                    break

            # 3. Handle BTTS
            elif is_btts:
                is_no_btts = "no" in play_lower or is_explicit_no
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").lower()
                    if "btts" in m_ticker or "both team" in m_title:
                        best_market = mkt
                        best_side = "no" if is_no_btts else "yes"
                        best_event = event
                        break

            # 4. Handle F3, F5 Moneyline, and Full Game Moneyline
            elif (is_f5 and not is_spread) or is_f3 or (is_ml and not is_spread):
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = m_ticker.split("-")[-1]

                    if "tie" in m_title or m_suffix == "TIE":
                        continue

                    team_match = False
                    if primary_team and (m_suffix == primary_team.upper() or primary_team.lower() in m_title):
                        team_match = True
                    elif primary_raw and (primary_raw.lower() in m_title or m_suffix == primary_raw.upper()):
                        team_match = True

                    if team_match:
                        best_market = mkt
                        best_side = "no" if is_explicit_no else "yes"
                        best_event = event
                        break

            # 3. Handle Over / Under Totals
            elif is_total:
                is_under_bet = is_explicit_no or "under" in play_lower or "under" in market_lower or re.search(r"\bu\d+", play_lower)
                candidate_markets = []
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "")
                    if "total" in m_title or "over" in m_title or "under" in m_title or "points" in m_title or "runs" in m_title or "games" in m_title or "goals" in m_title:
                        m_num_match = re.search(r"(?:over|under|total)\s*(\d+(?:\.\d+)?)", m_title, flags=re.IGNORECASE) or re.search(r"(\d+(?:\.\d+)?)\s*(?:runs?|goals?|points?)", m_title, flags=re.IGNORECASE) or re.search(r"-(\d+)$", m_ticker)
                        m_num = float(m_num_match.group(1)) if m_num_match else None
                        candidate_markets.append((mkt, m_num))

                if candidate_markets:
                    valid_candidates = [c for c in candidate_markets if c[1] is not None]
                    if valid_candidates and target_number is not None:
                        if is_under_bet:
                            safe_pool = [c for c in valid_candidates if c[1] >= (target_number - 0.5)]
                            best_market = min(safe_pool, key=lambda x: x[1])[0] if safe_pool else min(valid_candidates, key=lambda x: abs(x[1] - target_number))[0]
                        else:
                            safe_pool = [c for c in valid_candidates if c[1] <= (target_number + 0.5)]
                            best_market = max(safe_pool, key=lambda x: x[1])[0] if safe_pool else min(valid_candidates, key=lambda x: abs(x[1] - target_number))[0]
                    else:
                        best_market = candidate_markets[0][0]

                    best_side = "no" if is_under_bet else "yes"
                    best_event = event
                    break

            # 4. Handle Spreads / Margin
            elif is_spread:
                is_dog = "+" in play_lower
                candidate_markets = []
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = mkt.get("ticker", "").split("-")[-1]

                    team_match = False
                    if primary_team and (m_suffix.startswith(primary_team.upper()) or primary_team.lower() in m_title):
                        team_match = True
                    elif primary_raw and (primary_raw.lower() in m_title or m_suffix.startswith(primary_raw.upper())):
                        team_match = True

                    # Extract line number (e.g. 6.5, 31.5)
                    m_num_match = re.search(r"\b(\d+(?:\.\d+)?)\b", m_title) or re.search(r"(\d+(?:\.\d+)?)$", m_suffix)
                    m_num = float(m_num_match.group(1)) if m_num_match else None

                    # If underdog (+) and market is for opponent/favorite
                    if is_dog and not team_match:
                        candidate_markets.append((mkt, m_num, "no"))
                    elif team_match:
                        candidate_markets.append((mkt, m_num, "yes"))

                if candidate_markets:
                    valid_candidates = [c for c in candidate_markets if c[1] is not None]
                    if valid_candidates and target_number is not None:
                        if is_dog:
                            # Dog (+) prefers line >= target_number - 0.5 on opponent 'no' side
                            safe_pool = [c for c in valid_candidates if c[2] == "no" and c[1] >= (target_number - 0.5)]
                            if safe_pool:
                                best_tuple = min(safe_pool, key=lambda x: x[1])
                            else:
                                best_tuple = min(valid_candidates, key=lambda x: abs(x[1] - target_number))
                        else:
                            # Favorite (-) prefers line <= target_number + 0.5 on 'yes' side
                            safe_pool = [c for c in valid_candidates if c[2] == "yes" and c[1] <= (target_number + 0.5)]
                            if safe_pool:
                                best_tuple = max(safe_pool, key=lambda x: x[1])
                            else:
                                best_tuple = min(valid_candidates, key=lambda x: abs(x[1] - target_number))
                        best_market = best_tuple[0]
                        best_side = best_tuple[2]
                    else:
                        best_market = candidate_markets[0][0]
                        best_side = candidate_markets[0][2]

                    best_event = event
                    break

            if best_market:
                break

        if best_market:
            ex_idx = best_market.get("exchange_index")
            if ex_idx is None and best_event:
                ex_idx = best_event.get("exchange_index")
            return MatchResult(
                matched=True,
                ticker=best_market.get("ticker"),
                event_ticker=best_event.get("event_ticker") if best_event else None,
                side=best_side,
                market_title=best_market.get("title") or best_event.get("title"),
                exchange_index=int(ex_idx) if ex_idx is not None else None
            )

        return MatchResult(
            matched=False,
            reason=f"No active Kalshi market found matching '{pick.play}' ({pick.sport} - {pick.market})."
        )
