import datetime
import hashlib
import json
import math
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


MONTHS_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
}


class MarketMatcher:
    """
    Matches sports picks from the Google Sheet to live Kalshi markets and contract tickers.
    Supports Moneyline, Totals, Spreads, NRFI/YRFI, Corners, BTTS, F5, F3, and Multi-Leg Parlays/SGPs.
    """

    def __init__(self, kalshi_client: Optional[KalshiClient] = None, mappings_file: Path = TEAM_MAPPINGS_FILE):
        self.client = kalshi_client
        self.team_mappings = self._load_mappings(mappings_file)

    SPORT_SERIES_MAP = {
        "MLB": ["KXMLBTEAMTOTAL", "KXMLBSPREAD", "KXMLBGAME", "KXMLBTOTAL", "KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL", "KXMLBRFI", "KXMLBF3", "KXMLBF7", "KXMLBKS", "KXMLBHIT", "KXMLBHR", "KXMLB"],
        "KBO": ["KXKBOTOTAL", "KXKBOGAME", "KXKBORFI"],
        "NPB": ["KXNPBTOTAL", "KXNPBGAME", "KXNPBRFI", "KXNPBSPREAD"],
        "BASEBALL": ["KXMLBTEAMTOTAL", "KXMLBSPREAD", "KXMLBGAME", "KXMLBTOTAL", "KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL", "KXMLBRFI", "KXMLBF3", "KXMLBF7", "KXMLBKS", "KXMLBHIT", "KXMLBHR", "KXMLB", "KXNPBTOTAL", "KXNPBGAME", "KXNPBRFI", "KXNPBSPREAD", "KXKBOTOTAL", "KXKBOGAME", "KXKBORFI"],
        "NPB&KBO": ["KXNPBTOTAL", "KXNPBGAME", "KXNPBRFI", "KXNPBSPREAD", "KXKBOTOTAL", "KXKBOGAME", "KXKBORFI"],
        "NCAAF": ["KXNCAAFSPREAD", "KXNCAAFGAME", "KXNCAAFTOTAL", "KXNCAAFTEAMTOTAL", "KXNCAAF1HSPREAD", "KXNCAAF1HTOTAL", "KXNCAAF1H"],
        "NFL": ["KXNFLSPREAD", "KXNFLGAME", "KXNFLTOTAL", "KXNFLTEAMTOTAL", "KXNFL1HSPREAD", "KXNFL1HTOTAL", "KXNFL1H", "KXNFL1HTEAMTOTAL", "KXNFL2HSPREAD", "KXNFL2HTOTAL", "KXNFLPASSYDS", "KXNFLRSHYDS", "KXNFLRECYDS", "KXNFLTD", "KXNFLANYTD", "KXNFLPASSTDS", "KXNFLPASSCOMP", "KXNFLREC"],
        "FOOTBALL": ["KXNFLSPREAD", "KXNFLGAME", "KXNFLTOTAL", "KXNFLTEAMTOTAL", "KXNFL1HSPREAD", "KXNFL1HTOTAL", "KXNFL1H", "KXNFL1HTEAMTOTAL", "KXNFL2HSPREAD", "KXNFL2HTOTAL", "KXNFLPASSYDS", "KXNFLRSHYDS", "KXNFLRECYDS", "KXNFLTD", "KXNFLANYTD", "KXNFLPASSTDS", "KXNFLPASSCOMP", "KXNFLREC", "KXNCAAFSPREAD", "KXNCAAFGAME", "KXNCAAFTOTAL", "KXNCAAFTEAMTOTAL", "KXNCAAF1HSPREAD", "KXNCAAF1HTOTAL", "KXNCAAF1H"],
        "SOCCER": ["KXLALIGATCORNERS", "KXLALIGAGAME", "KXLALIGACORNERS", "KXLALIGATOTAL", "KXLALIGABTTS", "KXLALIGASPREAD", "KXLALIGA", "KXUCLGAME", "KXUCLTOTAL", "KXUCLBTTS", "KXUCLCORNERS", "KXUCLTCORNERS", "KXSERIEAGAME", "KXSERIEATOTAL", "KXSERIEABTTS", "KXSERIEACORNERS", "KXSERIEATCORNERS", "KXBUNDESLIGAGAME", "KXBUNDESLIGATOTAL", "KXBUNDESLIGABTTS", "KXBUNDESLIGACORNERS", "KXBUNDESLIGATCORNERS", "KXMLSGAME", "KXMLSTOTAL", "KXMLSTCORNERS", "KXMLSCORNERS", "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLTCORNERS", "KXEPLCORNERS", "KXSOCCER"],
        "EPL": ["KXEPLTCORNERS", "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLCORNERS", "KXEPLSPREAD", "KXEPL1H", "KXEPL2H", "KXEPLMATCH"],
        "WNBA": ["KXWNBATEAMTOTAL", "KXWNBATOTAL", "KXWNBAGAME", "KXWNBASPREAD", "KXWNBAPTS"],
        "NBA": ["KXNBATEAMTOTAL", "KXNBATOTAL", "KXNBAGAME", "KXNBASPREAD", "KXNBAPTS"],
        "BASKETBALL": ["KXNBATEAMTOTAL", "KXNBATOTAL", "KXNBAGAME", "KXNBASPREAD", "KXNBAPTS", "KXWNBATEAMTOTAL", "KXWNBATOTAL", "KXWNBAGAME", "KXWNBASPREAD", "KXWNBAPTS"],
        "TENNIS": ["KXATPMATCH", "KXWTAMATCH", "KXUSOPEN", "KXUSOPENMENSINGLES", "KXUSOPENWOMENSINGLES"]
    }

    def _get_candidate_series_for_sport(self, sport: str) -> List[str]:
        s = sport.upper().strip()
        if s in self.SPORT_SERIES_MAP:
            return self.SPORT_SERIES_MAP[s]
        if "BASEBALL" in s or "KBO" in s or "NPB" in s:
            return self.SPORT_SERIES_MAP["BASEBALL"]
        if "FOOTBALL" in s or "NFL" in s or "CFB" in s or "NCAAF" in s:
            return self.SPORT_SERIES_MAP["FOOTBALL"]
        if "SOCCER" in s or "EPL" in s:
            return self.SPORT_SERIES_MAP["SOCCER"]
        if "BASKETBALL" in s or "NBA" in s or "WNBA" in s:
            return self.SPORT_SERIES_MAP["BASKETBALL"]
        return []


    @staticmethod
    def parse_pick_date(date_str: str) -> Optional[datetime.date]:
        """
        Parses a date string from the picks sheet into a datetime.date object.
        Supports M/D/YYYY, M/D/YY, M/D, YYYY-MM-DD, etc.
        """
        if not date_str:
            return None
        date_str = date_str.strip()
        parts = [p for p in re.split(r"[/.-]", date_str) if p.isdigit()]
        if len(parts) >= 2:
            try:
                m = int(parts[0])
                d = int(parts[1])
                if len(parts) >= 3:
                    y = int(parts[2])
                    if y < 100:
                        y += 2000
                else:
                    y = datetime.date.today().year
                return datetime.date(y, m, d)
            except Exception:
                pass
        try:
            return datetime.date.fromisoformat(date_str)
        except Exception:
            pass
        return None

    @staticmethod
    def extract_event_date(ev: Dict[str, Any]) -> Optional[datetime.date]:
        """
        Extracts the scheduled event/game date from a Kalshi event dictionary.
        Checks event_ticker (YYMMMDD), sub_title / title ('Sep 9'), and market dates.
        """
        et = ev.get("event_ticker", "").upper()
        # 1. Event ticker format: -26SEP091310MINDET or -24AUG24-TBR
        m = re.search(r"-(\d{2})([A-Z]{3})(\d{2})", et)
        if m:
            y = 2000 + int(m.group(1))
            mon_str = m.group(2)
            d = int(m.group(3))
            if mon_str in MONTHS_MAP:
                try:
                    return datetime.date(y, MONTHS_MAP[mon_str], d)
                except ValueError:
                    pass

        # Format without year: -SEP09
        m2 = re.search(r"-([A-Z]{3})(\d{2})", et)
        if m2:
            mon_str = m2.group(1)
            d = int(m2.group(2))
            if mon_str in MONTHS_MAP:
                try:
                    return datetime.date(datetime.date.today().year, MONTHS_MAP[mon_str], d)
                except ValueError:
                    pass

        # 2. Subtitle / title format: '(Sep 9)' or 'Sep 9'
        text = f"{ev.get('sub_title', '')} {ev.get('title', '')}"
        m3 = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b", text, re.IGNORECASE)
        if m3:
            mon_str = m3.group(1)[:3].upper()
            d = int(m3.group(2))
            if mon_str in MONTHS_MAP:
                try:
                    return datetime.date(datetime.date.today().year, MONTHS_MAP[mon_str], d)
                except ValueError:
                    pass

        # 3. Markets
        markets = ev.get("markets", [])
        if markets and isinstance(markets, list):
            m0 = markets[0]
            for tf in ["occurrence_datetime", "expected_expiration_time", "close_time"]:
                ts = m0.get(tf)
                if ts and isinstance(ts, str) and len(ts) >= 10:
                    try:
                        return datetime.date.fromisoformat(ts[:10])
                    except Exception:
                        pass

        return None

    @staticmethod
    def is_event_date_matching(ev_date: Optional[datetime.date], target_date: Optional[datetime.date]) -> bool:
        """
        Returns True if the event date matches the target pick date.
        If target_date is not provided or ev_date cannot be determined, returns True.
        Requires month and day to match.
        """
        if target_date is None or ev_date is None:
            return True
        return ev_date.month == target_date.month and ev_date.day == target_date.day

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
        Performs exact matching first, then longest-key token matching,
        strictly distinguishing State / St. / Tech schools from their parent universities.
        """
        clean = raw_team_name.strip()
        sport_upper = sport.upper()
        
        # Combine sub-sport mappings for umbrella or composite sport names
        if sport_upper in ("BASEBALL", "NPB&KBO"):
            sport_map = {}
            for sub in ("MLB", "KBO", "NPB"):
                sport_map.update(self.team_mappings.get(sub, {}))
        elif sport_upper in ("FOOTBALL", "CFB", "COLLEGE FOOTBALL"):
            sport_map = {}
            for sub in ("NFL", "NCAAF"):
                sport_map.update(self.team_mappings.get(sub, {}))
        elif "SOCCER" in sport_upper or "WORLD CUP" in sport_upper:
            sport_map = {}
            for sub in ("SOCCER", "EPL"):
                sport_map.update(self.team_mappings.get(sub, {}))
        elif "BASKETBALL" in sport_upper:
            sport_map = {}
            for sub in ("NBA", "WNBA"):
                sport_map.update(self.team_mappings.get(sub, {}))
        else:
            sport_map = self.team_mappings.get(sport_upper, {})

        if not sport_map:
            # Fallback across all sport dictionaries if sport was unrecognized
            combined_all = {}
            for sub_dict in self.team_mappings.values():
                combined_all.update(sub_dict)
            sport_map = combined_all

        if not sport_map:
            return clean

        clean_lower = clean.lower()

        # Pass 1: Exact match (case-insensitive)
        for name_key, code in sport_map.items():
            if name_key.lower() == clean_lower:
                return code

        # Pass 1b: Exact match with St./St normalized to State
        expanded_clean = re.sub(r"\bst\.?\b", "state", clean_lower).strip()
        if expanded_clean != clean_lower:
            for name_key, code in sport_map.items():
                if name_key.lower() == expanded_clean:
                    return code

        # Pass 2: Specificity-ordered matching (longest keys first)
        has_state = bool(re.search(r"\b(state|st\.?)\b", clean_lower))
        has_tech = bool(re.search(r"\btech\b", clean_lower))

        sorted_items = sorted(sport_map.items(), key=lambda x: len(x[0]), reverse=True)
        for name_key, code in sorted_items:
            key_lower = name_key.lower()
            key_has_state = bool(re.search(r"\b(state|st\.?)\b", key_lower))
            key_has_tech = bool(re.search(r"\btech\b", key_lower))

            # Strictly forbid matching non-State key if input has State, and vice versa
            if has_state and not key_has_state:
                continue
            if not has_state and key_has_state:
                continue
            # Strictly forbid matching non-Tech key if input has Tech, and vice versa
            if has_tech and not key_has_tech:
                continue
            if not has_tech and key_has_tech:
                continue

            # Word boundary match
            pattern = r"\b" + re.escape(key_lower) + r"\b"
            if re.search(pattern, clean_lower) or re.search(pattern, expanded_clean):
                return code

        return clean

    @staticmethod
    def is_team_name_in_title(raw_name: str, title: str) -> bool:
        """
        Checks if raw_name matches in title while respecting State/St./Tech distinctions.
        e.g. 'Oregon State' matches 'Oregon St.', but 'Oregon' does NOT match 'Oregon St.'.
        """
        if not raw_name or not title:
            return False
        clean = raw_name.strip()
        has_state = bool(re.search(r"\b(state|st\.?)\b", clean, re.IGNORECASE))
        has_tech = bool(re.search(r"\btech\b", clean, re.IGNORECASE))
        base = re.sub(r"\b(state|st\.?|tech)\b", "", clean, flags=re.IGNORECASE).strip()

        if has_state:
            pattern = r"\b" + re.escape(base) + r"\s+(?:state|st\.?)\b"
            return bool(re.search(pattern, title, re.IGNORECASE))
        elif has_tech:
            pattern = r"\b" + re.escape(base) + r"\s+tech\b"
            return bool(re.search(pattern, title, re.IGNORECASE))
        else:
            # Must NOT be followed by state/st/tech
            pattern = r"\b" + re.escape(base) + r"\b(?!\s+(?:state|st\.?|tech)\b)"
            return bool(re.search(pattern, title, re.IGNORECASE))

    @staticmethod
    def is_team_matching_market(primary_team: str, primary_raw: str, m_suffix: str, m_title: str) -> bool:
        """
        Determines if a market's ticker suffix or title matches the targeted team.
        Accurately distinguishes between State/St/Tech counterparts (e.g. ORST vs ORE).
        """
        # 1. Code match against ticker suffix (e.g. 'ORST' in 'ORST9' or 'ORST')
        if primary_team:
            prefix_match = re.match(r"^([A-Za-z]+)", m_suffix)
            if prefix_match and prefix_match.group(1).upper() == primary_team.upper():
                return True
            if m_suffix.upper() == primary_team.upper():
                return True

        # 2. Text match in market title
        if primary_raw:
            raw_clean = primary_raw.strip()
            has_state = bool(re.search(r"\b(state|st\.?)\b", raw_clean, re.IGNORECASE))
            has_tech = bool(re.search(r"\btech\b", raw_clean, re.IGNORECASE))
            
            base_name = re.sub(r"\b(state|st\.?|tech)\b", "", raw_clean, flags=re.IGNORECASE).strip()
            
            if has_state:
                pattern = r"\b" + re.escape(base_name) + r"\s+(?:state|st\.?)\b"
                if re.search(pattern, m_title, re.IGNORECASE):
                    return True
            elif has_tech:
                pattern = r"\b" + re.escape(base_name) + r"\s+tech\b"
                if re.search(pattern, m_title, re.IGNORECASE):
                    return True
            else:
                pattern = r"\b" + re.escape(base_name) + r"\b(?!\s+(?:state|st\.?|tech)\b)"
                if re.search(pattern, m_title, re.IGNORECASE):
                    return True

        return False

    def extract_teams_from_play(self, play: str, sport: str) -> List[str]:
        """
        Extracts team names or abbreviations from a play string.
        """
        clean_play = re.sub(r"\b(1H|2H|1Q|2Q|3Q|4Q|F5|F3|F7|ML|NRFI|YRFI|Over|Under|Spread|Run Line|Total|Sets?|Games?|TT|Team Total)\b.*", "", play, flags=re.IGNORECASE).strip()
        clean_play = re.sub(r"(?<!\w)[ouOU]?\s*[+-]\d+(?:\.\d+)?.*", "", clean_play).strip()
        clean_play = re.sub(r"\b(?<!\w)\d+(?:\.\d+)?\s*(?:runs?|points?|goals?|games?)\b.*", "", clean_play, flags=re.IGNORECASE).strip()
        clean_play = re.sub(r"\s+[ouOU]$", "", clean_play).strip()
        clean_play = re.sub(r"\b\d+(?:\.\d+)?\b.*", "", clean_play).strip()
        
        # Split on separators like '/', 'vs', 'vs.', '@'
        split_pattern = r"\s*(?:/|vs\.?|@|\band\b)\s*"
        parts = re.split(split_pattern, clean_play, flags=re.IGNORECASE)
        teams = [p.strip() for p in parts if p.strip()]
        return teams

    def is_player_prop_play(self, play: str, market: str = "") -> bool:
        combined = f"{play} {market}".lower()
        prop_keywords = [
            r"\bpass(?:ing)?\s*yds?\b", r"\bpass(?:ing)?\s*yards?\b", r"\bpyards?\b",
            r"\brush(?:ing)?\s*yds?\b", r"\brush(?:ing)?\s*yards?\b", r"\bryards?\b",
            r"\brec(?:eiving)?\s*yds?\b", r"\brec(?:eiving)?\s*yards?\b", r"\breception\s*yards?\b",
            r"\bpass(?:ing)?\s*tds?\b", r"\bpass(?:ing)?\s*touchdowns?\b",
            r"\banytime\s*td\b", r"\banytime\s*touchdown\b", r"\batd\b", r"\btd\s*scorer\b",
            r"\bpass\s*comp(?:letions)?\b", r"\bcompletions\b",
            r"\bpass\s*att(?:empts)?\b",
            r"\bpass\s*int(?:erceptions)?\b",
            r"\brush\s*att(?:empts)?\b", r"\bcarries\b",
            r"\breceptions\b",
            r"\b\d+\+\s*tds?\b",
            r"\bstrikeouts?\b", r"\bks\b", r"\bk's\b",
            r"\bhits?\b", r"\bhome\s*runs?\b", r"\bhrs?\b",
            r"\brbis?\b", r"\btotal\s*bases\b",
            r"\bpoints?\b", r"\bpts\b", r"\brebounds?\b", r"\breb\b", r"\bassists?\b", r"\bast\b",
            r"\b3pt\b", r"\bthrees\b", r"\b3-pointers?\b", r"\bpra\b"
        ]
        return any(re.search(pat, combined) for pat in prop_keywords)

    def normalize_player_name(self, s: str) -> str:
        s = s.lower()
        s = re.sub(r"[.'\"]", "", s)
        tokens = s.split()
        tokens = [t for t in tokens if t not in ["jr", "sr", "ii", "iii", "iv", "v"]]
        return " ".join(tokens).strip()

    def is_player_match(self, pick_player: str, kalshi_market_title: str, kalshi_market_ticker: str = "") -> bool:
        title_parts = kalshi_market_title.split(":")
        kalshi_player_name = title_parts[0].strip() if len(title_parts) > 1 else kalshi_market_title.strip()
        
        p_norm = self.normalize_player_name(pick_player)
        k_norm = self.normalize_player_name(kalshi_player_name)
        
        if p_norm == k_norm:
            return True
            
        p_tokens = p_norm.split()
        k_tokens = k_norm.split()
        
        if not p_tokens or not k_tokens:
            return False
            
        p_last = p_tokens[-1]
        k_last = k_tokens[-1]
        
        if len(p_tokens) >= 2 and p_tokens[-2] in ["st", "van", "de", "la", "von"]:
            p_last = f"{p_tokens[-2]} {p_tokens[-1]}"
        if len(k_tokens) >= 2 and k_tokens[-2] in ["st", "van", "de", "la", "von"]:
            k_last = f"{k_tokens[-2]} {k_tokens[-1]}"
            
        if p_last == k_last:
            p_first = p_tokens[0]
            k_first = k_tokens[0]
            
            if len(p_tokens) == 1:
                return True
                
            if len(p_first) == 1 and k_first.startswith(p_first):
                return True
                
            p_first_all = "".join([t for t in p_tokens if t != p_last])
            k_first_all = "".join([t for t in k_tokens if t != k_last])
            if p_first_all == k_first_all:
                return True
            if len(p_first_all) == 2 and k_first_all.startswith(p_first_all):
                return True
            if p_first == k_first:
                return True
                
        if kalshi_market_ticker:
            parts = kalshi_market_ticker.split("-")
            mkt_suffix = parts[-2].upper() if len(parts) >= 2 else ""
            clean_p_last = re.sub(r"\s+", "", p_last).upper()
            if clean_p_last in mkt_suffix:
                if len(p_tokens) > 1 and len(p_tokens[0]) >= 1:
                    init = p_tokens[0][0].upper()
                    if f"{init}{clean_p_last}" in mkt_suffix:
                        return True
                else:
                    return True

        return False

    def extract_prop_info(self, play: str, market: str = "") -> Dict[str, Any]:
        combined = f"{play} {market}".strip()
        play_clean = play.strip()
        
        # 1. Detect Stat Type
        stat_type = None
        if re.search(r"\b(?:pass(?:ing)?\s*yds?|pass(?:ing)?\s*yards?|pyards?)\b", combined, re.I):
            stat_type = "PASS_YDS"
        elif re.search(r"\b(?:rush(?:ing)?\s*yds?|rush(?:ing)?\s*yards?|ryards?)\b", combined, re.I):
            stat_type = "RUSH_YDS"
        elif re.search(r"\b(?:rec(?:eiving)?\s*yds?|rec(?:eiving)?\s*yards?|reception\s*yards?)\b", combined, re.I):
            stat_type = "REC_YDS"
        elif re.search(r"\b(?:pass(?:ing)?\s*tds?|pass(?:ing)?\s*touchdowns?)\b", combined, re.I):
            stat_type = "PASS_TDS"
        elif re.search(r"\b(?:anytime\s*td|anytime\s*touchdown|atd|touchdowns?|td\s*scorer|\d+\+\s*tds?)\b", combined, re.I):
            stat_type = "TD"
        elif re.search(r"\b(?:pass\s*comp(?:letions)?|completions)\b", combined, re.I):
            stat_type = "PASS_COMP"
        elif re.search(r"\b(?:pass\s*att(?:empts)?)\b", combined, re.I):
            stat_type = "PASS_ATT"
        elif re.search(r"\b(?:pass\s*int(?:erceptions)?|interceptions?)\b", combined, re.I):
            stat_type = "PASS_INT"
        elif re.search(r"\b(?:receptions)\b", combined, re.I):
            stat_type = "REC"
        elif re.search(r"\b(?:rush\s*att(?:empts)?|carries)\b", combined, re.I):
            stat_type = "RUSH_ATT"
        elif re.search(r"\b(?:rush\s*(?:\+|and)\s*rec(?:eiving)?\s*yds?)\b", combined, re.I):
            stat_type = "RR_YDS"
        elif re.search(r"\b(?:strikeouts?|ks?|k's)\b", combined, re.I):
            stat_type = "K"
        elif re.search(r"\b(?:hits?)\b", combined, re.I):
            stat_type = "HIT"
        elif re.search(r"\b(?:home\s*runs?|hrs?)\b", combined, re.I):
            stat_type = "HR"
        elif re.search(r"\b(?:points?|pts?)\b", combined, re.I):
            stat_type = "PTS"
        elif re.search(r"\b(?:rebounds?|reb?)\b", combined, re.I):
            stat_type = "REB"
        elif re.search(r"\b(?:assists?|ast?)\b", combined, re.I):
            stat_type = "AST"
        elif re.search(r"\b(?:3pt|threes?|3-pointers?)\b", combined, re.I):
            stat_type = "3PT"

        # 2. Extract Line & Direction
        line = None
        direction = "over"
        
        plus_match = re.search(r"(\d+(?:\.\d+)?)\s*\+", play_clean)
        over_match = re.search(r"\b(?:over|o)\s*(\d+(?:\.\d+)?)", play_clean, re.I)
        under_match = re.search(r"\b(?:under|u)\s*(\d+(?:\.\d+)?)", play_clean, re.I)
        
        if plus_match:
            line = float(plus_match.group(1))
            direction = "over"
        elif over_match:
            val = float(over_match.group(1))
            line = math.floor(val) + 1.0 if val % 1 == 0.5 else val
            direction = "over"
        elif under_match:
            val = float(under_match.group(1))
            line = math.floor(val) + 1.0 if val % 1 == 0.5 else val
            direction = "under"
        elif stat_type == "TD":
            line = 1.0
            direction = "over"

        # 3. Extract Player Name
        p_name = play_clean
        removals = [
            r"\b(?:pass(?:ing)?\s*yds?|pass(?:ing)?\s*yards?|pyards?)\b",
            r"\b(?:rush(?:ing)?\s*yds?|rush(?:ing)?\s*yards?|ryards?)\b",
            r"\b(?:rec(?:eiving)?\s*yds?|rec(?:eiving)?\s*yards?|reception\s*yards?)\b",
            r"\b(?:pass(?:ing)?\s*tds?|pass(?:ing)?\s*touchdowns?)\b",
            r"\b(?:anytime\s*td|anytime\s*touchdown|atd|touchdown|td\s*scorer|tds?)\b",
            r"\b(?:pass\s*comp(?:letions)?|completions)\b",
            r"\b(?:pass\s*att(?:empts)?|attempts?)\b",
            r"\b(?:pass\s*int(?:erceptions)?|interceptions?)\b",
            r"\b(?:rush\s*att(?:empts)?|carries)\b",
            r"\b(?:receptions?)\b",
            r"\b(?:strikeouts?|ks?|k's)\b",
            r"\b(?:hits?|home\s*runs?|hrs?|points?|pts?|rebounds?|reb?|assists?|ast?|3pt|threes?|3-pointers?)\b",
            r"\b(?:over|under|o|u)\b",
            r"\d+(?:\.\d+)?\s*\+?",
            r"[+\-]"
        ]
        for rem in removals:
            p_name = re.sub(rem, "", p_name, flags=re.I)
        p_name = re.sub(r"\s+", " ", p_name).strip()
        
        return {
            "player": p_name,
            "stat": stat_type,
            "line": line,
            "direction": direction
        }

    def _match_player_prop(self, pick: PickRecord, live_events: List[Dict[str, Any]]) -> MatchResult:
        prop_info = self.extract_prop_info(pick.play, pick.market)
        target_player = prop_info["player"]
        stat_type = prop_info["stat"]
        target_line = prop_info["line"]
        direction = prop_info["direction"]
        sport = pick.sport.upper()

        target_date = self.parse_pick_date(pick.date)
        date_code = target_date.strftime("%y%b%d").upper() if target_date else ""

        prop_series_map = {
            "NFL": {
                "PASS_YDS": ["KXNFLPASSYDS"],
                "RUSH_YDS": ["KXNFLRSHYDS"],
                "REC_YDS": ["KXNFLRECYDS"],
                "TD": ["KXNFLTD", "KXNFLANYTD", "KXNFL2TD"],
                "PASS_TDS": ["KXNFLPASSTDS"],
                "PASS_COMP": ["KXNFLPASSCOMP"],
                "PASS_ATT": ["KXNFLPASSATT"],
                "PASS_INT": ["KXNFLPASSINT"],
                "REC": ["KXNFLREC"],
                "RUSH_ATT": ["KXNFLRSHATT"],
                "RR_YDS": ["KXNFLRRYDS"],
            },
            "MLB": {
                "K": ["KXMLBKS"],
                "HIT": ["KXMLBHIT"],
                "HR": ["KXMLBHR"],
                "RBI": ["KXMLBRBI"],
                "TB": ["KXMLBTB"],
            },
            "NBA": {
                "PTS": ["KXNBAPTS"],
                "REB": ["KXNBAREB"],
                "AST": ["KXNBAAST"],
                "3PT": ["KXNBA3PT"],
            },
            "WNBA": {
                "PTS": ["KXWNBAPTS"],
                "REB": ["KXWNBAREB"],
                "AST": ["KXWNBAAST"],
                "3PT": ["KXWNBA3PT"],
            }
        }
        relevant_series = prop_series_map.get(sport, {}).get(stat_type, [])

        stat_title_keywords = {
            "PASS_YDS": ["passing yards", "pass yds"],
            "RUSH_YDS": ["rushing yards", "rush yds"],
            "REC_YDS": ["receiving yards", "rec yds"],
            "TD": ["touchdown", "td"],
            "PASS_TDS": ["passing touchdown", "pass td"],
            "PASS_COMP": ["passing completion", "pass comp"],
            "PASS_ATT": ["passing attempt", "pass att"],
            "PASS_INT": ["passing interception", "pass int"],
            "REC": ["reception"],
            "RUSH_ATT": ["rushing attempt"],
            "RR_YDS": ["rush and receiving"],
            "K": ["strikeout"],
            "HIT": ["hit"],
            "HR": ["home run"],
            "PTS": ["point"],
            "REB": ["rebound"],
            "AST": ["assist"],
            "3PT": ["three"]
        }
        title_keywords = stat_title_keywords.get(stat_type, [])

        def filter_and_match(events: List[Dict[str, Any]]) -> Optional[MatchResult]:
            for ev in events:
                et = ev.get("event_ticker", "").upper()
                ev_title = ev.get("title", "").lower()
                
                # Check date
                ev_date = self.extract_event_date(ev)
                if target_date and ev_date:
                    if not self.is_event_date_matching(ev_date, target_date):
                        continue
                elif date_code and date_code not in et:
                    continue

                # Check series / stat match
                series_matched = any(s in et for s in relevant_series) if relevant_series else False
                title_matched = any(k in ev_title for k in title_keywords) if title_keywords else False
                if not series_matched and not title_matched:
                    continue

                markets = ev.get("markets", [])
                for mkt in markets:
                    m_title = mkt.get("title", "")
                    m_ticker = mkt.get("ticker", "")
                    if self.is_player_match(target_player, m_title, m_ticker):
                        # Extract line
                        m_line_match = re.search(r"(\d+(?:\.\d+)?)\s*\+", m_title) or re.search(r"-(\d+)$", m_ticker)
                        m_line = float(m_line_match.group(1)) if m_line_match else None
                        
                        if target_line is not None and m_line is not None:
                            if abs(m_line - target_line) > 0.1:
                                continue
                                
                        side = "yes" if direction == "over" else "no"
                        return MatchResult(
                            matched=True,
                            ticker=mkt["ticker"],
                            event_ticker=ev["event_ticker"],
                            side=side,
                            market_title=mkt.get("title")
                        )
            return None

        # 1. Search in live_events
        res = filter_and_match(live_events)
        if res:
            return res

        # 2. Targeted API fallback if client is available
        if self.client and relevant_series:
            fallback_events = []
            for s in relevant_series:
                try:
                    evs = self.client.get_events(series_ticker=s, status="open", with_nested_markets=True)
                    if evs:
                        fallback_events.extend(evs)
                except Exception:
                    pass
            if fallback_events:
                res = filter_and_match(fallback_events)
                if res:
                    return res

        return MatchResult(
            matched=False,
            reason=f"No active Kalshi market found matching player prop '{pick.play}' ({pick.sport} - {stat_type or 'Prop'}) on {pick.date}."
        )

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
                elif "team total" in leg_lower or " tt" in leg_lower or "tt " in leg_lower or "(tt)" in leg_lower:
                    sub_market = "Team Total"
                elif self.is_player_prop_play(leg_str):
                    sub_market = "Player Prop"
                elif "1h" in leg_lower or "first half" in leg_lower:
                    if "total" in leg_lower or "over" in leg_lower or "under" in leg_lower or re.search(r"[ou]\s*\d", leg_lower):
                        sub_market = "First Half Total"
                    elif "+" in leg_lower or "-" in leg_lower or "spread" in leg_lower:
                        sub_market = "First Half Spread"
                    elif "ml" in leg_lower or "win" in leg_lower:
                        sub_market = "First Half Moneyline"
                    else:
                        sub_market = "First Half Moneyline"
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
                    candidate_series = self._get_candidate_series_for_sport(sub_pick.sport)
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
            candidate_series = self._get_candidate_series_for_sport(pick.sport)
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

        # Handle Player Props immediately
        is_player_prop = (
            "prop" in market_lower
            or "passing" in market_lower
            or "rushing" in market_lower
            or "receiving" in market_lower
            or "touchdown" in market_lower
            or "strikeout" in market_lower
            or self.is_player_prop_play(pick.play, pick.market)
        )
        if is_player_prop:
            return self._match_player_prop(pick, live_events)

        teams_extracted = self.extract_teams_from_play(pick.play, pick.sport)
        norm_teams = [self.normalize_team(pick.sport, t) for t in teams_extracted]

        # Determine market category
        is_nrfi = "nrfi" in market_lower or "nrfi" in play_lower or "first inning" in market_lower or "1st inning" in market_lower or "yrfi" in market_lower or "yrfi" in play_lower
        is_corner = "corner" in market_lower or "corner" in play_lower
        is_btts = "btts" in market_lower or "btts" in play_lower or "both team" in play_lower
        is_team_total = (
            "team total" in market_lower
            or market_lower == "tt"
            or "team points" in market_lower
            or "team runs" in market_lower
            or "team goals" in market_lower
            or "team total" in play_lower
            or " tt" in play_lower
            or "tt " in play_lower
            or "(team total)" in play_lower
            or "(tt)" in play_lower
        ) and not is_corner and not is_btts
        is_1h_total = (("1h" in market_lower or "first half" in market_lower or "1h" in play_lower or "first half" in play_lower) and ("total" in market_lower or "over" in play_lower or "under" in play_lower or re.search(r"[ou]\s*\d", play_lower))) and not is_team_total
        is_1h_spread = (("1h" in market_lower or "first half" in market_lower or "1h" in play_lower or "first half" in play_lower) and ("spread" in market_lower or "+" in play_lower or re.search(r"-\d", play_lower))) and not is_1h_total and not is_team_total
        is_1h_ml = ("1h" in market_lower or "first half" in market_lower or "1h" in play_lower or "first half" in play_lower) and not is_1h_total and not is_1h_spread and not is_team_total
        is_1h = is_1h_total or is_1h_spread or is_1h_ml
        is_f5_total = (("f5" in market_lower or "first 5" in market_lower or "f5" in play_lower) and ("total" in market_lower or "over" in play_lower or "under" in play_lower or re.search(r"[ou]\s*\d", play_lower))) and not is_team_total and not is_1h
        is_f5 = ("f5" in market_lower or "f5" in play_lower or "first 5" in market_lower) and not is_f5_total and not is_team_total and not is_1h
        is_f5_plus_half = is_f5 and bool(re.search(r"\+\s*(?:0\.5|1/2|\.5)\b", play_lower))
        is_f5_minus_half = is_f5 and bool(re.search(r"-\s*(?:0\.5|1/2|\.5)\b", play_lower))
        is_f5_half = is_f5_plus_half or is_f5_minus_half
        is_f3 = ("f3" in market_lower or "f3" in play_lower or "first 3" in market_lower) and not is_1h
        is_spread = ("spread" in market_lower or "run line" in market_lower or "spread" in play_lower or "wins by" in play_lower or ("+" in play_lower and not is_corner) or (re.search(r"-\d", play_lower) and not is_nrfi and not is_f3 and not is_f5_total and not is_1h_total and not is_team_total and ("f5" not in play_lower or re.search(r"f5\s*[+-]", play_lower)) and ("1h" not in play_lower or re.search(r"1h\s*[+-]", play_lower)))) and not is_corner and not is_btts and not is_team_total and not is_1h_total and not is_f5_half
        is_ml = ("moneyline" in market_lower or "ml" in market_lower or "side" in market_lower or "win" in play_lower or "to win" in play_lower or is_f5_minus_half) and not is_corner and not is_btts and not is_f5_total and not is_1h_total and not is_team_total and not is_spread and not is_1h_spread
        is_game_total = (("game total" in market_lower or "total" in market_lower or "over" in play_lower or "under" in play_lower or "points" in market_lower or "runs" in market_lower or "goals" in market_lower or re.search(r"\b[ou]\d+", play_lower)) or is_f5_total or is_1h_total) and not is_team_total and not is_corner and not is_btts
        is_total = (is_game_total or is_f5_total or is_1h_total or is_team_total) and not is_corner and not is_btts
        is_explicit_no = play_lower.startswith("no ") or play_lower.startswith("no ·") or "to win: no" in play_lower

        # Search through live events for best match
        best_market = None
        best_side = "no" if is_explicit_no else "yes"
        best_event = None

        # Determine target team code/name for side-specific markets
        primary_team = norm_teams[0] if norm_teams else ""
        primary_raw = teams_extracted[0] if teams_extracted else ""

        # Extract numerical total/spread line if present (e.g. 177, 3.5, 23.5)
        clean_for_num = re.sub(r"\b(1H|2H|1Q|2Q|3Q|4Q|F5|F3|F7)\b", "", pick.play, flags=re.IGNORECASE)
        num_match = re.search(r"(?:[+-]|[ouOU]\s*|over\s*|under\s*)\s*([+-]?\d+(?:\.\d+)?)", clean_for_num, flags=re.IGNORECASE)
        if not num_match:
            num_match = re.search(r"\b(\d+(?:\.\d+)?)\b(?![a-zA-Z])", clean_for_num)
        target_number = abs(float(num_match.group(1))) if num_match else None

        # Parse target pick date and format date code
        target_date = self.parse_pick_date(pick.date)
        date_code = target_date.strftime("%y%b%d").upper() if target_date else ""

        def score_event(ev: Dict[str, Any]) -> int:
            score = 0
            et = ev.get("event_ticker", "").upper()
            title = ev.get("title", "").lower()
            
            # Strict date evaluation: event date MUST match target pick date
            ev_date = self.extract_event_date(ev)
            if target_date and ev_date:
                if self.is_event_date_matching(ev_date, target_date):
                    score += 500  # Massive bonus for exact date match
                else:
                    return -999999  # Disqualify events with mismatched dates
            elif date_code and date_code in et:
                score += 500
            
            # Series category match bonus
            if is_corner and ("TCORNER" in et or "team corner" in title):
                score += 100
            elif is_corner and ("CORNER" in et or "corner" in title):
                score += 80
            elif is_btts and ("BTTS" in et or "btts" in title or "both team" in title):
                score += 80
            elif is_team_total and ("TEAMTOTAL" in et or "team total" in title):
                score += 150
            elif is_team_total and ("TOTAL" in et or "total" in title):
                score -= 50  # Strongly avoid game total events when matching a team total
            elif is_1h_total and ("1HTOTAL" in et or "first half total" in title or "1h total" in title):
                score += 150
            elif is_1h_spread and ("1HSPREAD" in et or "first half spread" in title or "1h spread" in title):
                score += 150
            elif is_1h_ml and ("1H" in et or "first half" in title) and "SPREAD" not in et and "TOTAL" not in et:
                score += 150
            elif not is_1h and ("1H" in et or "first half" in title):
                score -= 150  # Penalize 1H when a full game or other market is requested
            elif not (is_f5 or is_f5_total or is_f3) and ("F5" in et or "first 5" in title):
                score -= 150  # Penalize F5 when full game is requested
            elif is_f5_total and ("F5TOTAL" in et or "first 5 total" in title):
                score += 120
            elif is_f5 and is_f5_half:
                # F5 +0.5 / -0.5 are covered directly by Kalshi's 3-way F5 event (KXMLBF5), NOT KXMLBF5SPREAD
                if "F5" in et and "SPREAD" not in et and "TOTAL" not in et:
                    score += 150
                elif "SPREAD" in et or "TOTAL" in et:
                    score -= 100
            elif is_f5 and is_spread and ("F5SPREAD" in et or "first 5 spread" in title):
                score += 80
            elif is_f5 and not is_spread and ("F5" in et or "first 5" in title) and "SPREAD" not in et and "TOTAL" not in et:
                score += 50
            elif is_f3 and ("F3" in et or "first 3" in title):
                score += 50
            elif is_nrfi and ("RFI" in et or "1INNING" in et or "first inning" in title or "1st inning" in title):
                score += 50
            elif is_game_total and ("TOTAL" in et or "total" in title) and "TEAM" not in et and "1H" not in et and "F5" not in et:
                score += 80
            elif is_spread and ("SPREAD" in et or "spread" in title or "margin" in title) and "1H" not in et and "F5" not in et:
                score += 80
            elif is_spread and ("TEAMTOTAL" in et or "TOTAL" in et):
                score -= 100
            elif is_ml and ("GAME" in et or "MATCH" in et) and "SPREAD" not in et and "TOTAL" not in et and "1H" not in et and "F5" not in et:
                score += 50
            elif is_ml and ("TEAMTOTAL" in et or "TOTAL" in et or "SPREAD" in et):
                score -= 100

            # Team match bonus
            matched_teams = 0
            for idx_t in range(len(teams_extracted)):
                t_raw = teams_extracted[idx_t] if idx_t < len(teams_extracted) else ""
                t_norm = norm_teams[idx_t] if idx_t < len(norm_teams) else ""
                if (t_norm and t_norm.upper() in et) or (t_raw and self.is_team_name_in_title(t_raw, title)):
                    matched_teams += 1
            if len(teams_extracted) >= 2 and matched_teams >= 2:
                score += 200
            elif matched_teams >= 1:
                score += 150

            return score

        sorted_events = sorted(live_events, key=score_event, reverse=True)

        for event in sorted_events:
            event_title = event.get("title", "").lower()
            event_ticker = event.get("event_ticker", "").lower()
            sub_title = event.get("sub_title", "").lower()

            # Strict date match filter: game date must match the spreadsheet date
            ev_date = self.extract_event_date(event)
            if target_date and ev_date and not self.is_event_date_matching(ev_date, target_date):
                continue

            # 1H / Full game isolation
            is_event_1h = "1h" in event_ticker or "1h" in event_title or "first half" in event_title or "1st half" in event_title
            if is_1h and not is_event_1h:
                continue
            if not is_1h and is_event_1h:
                continue

            # F5 / Full game isolation
            is_event_f5 = "f5" in event_ticker or "first 5" in event_title
            if (is_f5 or is_f5_total) and not is_event_f5:
                continue
            if not (is_f5 or is_f5_total or is_f3) and is_event_f5:
                continue

            # Sport-level prefix filter
            sport_prefixes = {
                "MLB": ["KXMLB", "KXNRFI"],
                "BASEBALL": ["KXMLB", "KXNRFI", "KXNPB", "KXKBO"],
                "NPB&KBO": ["KXNPB", "KXKBO"],
                "NFL": ["KXNFL"],
                "NCAAF": ["KXNCAAF"],
                "FOOTBALL": ["KXNFL", "KXNCAAF"],
                "NBA": ["KXNBA"],
                "WNBA": ["KXWNBA"],
                "BASKETBALL": ["KXNBA", "KXWNBA"],
                "NHL": ["KXNHL"],
                "KBO": ["KXKBO"],
                "NPB": ["KXNPB"],
                "SOCCER": ["KXEPL", "KXLALIGA", "KXUCL", "KXSERIEA", "KXBUNDESLIGA", "KXMLS", "KXSOCCER"],
                "EPL": ["KXEPL", "KXSOCCER"],
                "TENNIS": ["KXATP", "KXWTA", "KXUSOPEN", "KXTENNIS"]
            }
            prefixes = sport_prefixes.get(sport_upper)
            if not prefixes:
                if "BASEBALL" in sport_upper:
                    prefixes = sport_prefixes["BASEBALL"]
                elif "FOOTBALL" in sport_upper:
                    prefixes = sport_prefixes["FOOTBALL"]
                elif "SOCCER" in sport_upper:
                    prefixes = sport_prefixes["SOCCER"]
                elif "BASKETBALL" in sport_upper:
                    prefixes = sport_prefixes["BASKETBALL"]

            if prefixes and not any(event_ticker.upper().startswith(p) for p in prefixes):
                continue

            sport_keywords = {
                "MLB": ["mlb", "baseball", "nrfi", "rfi", "f5", "f3", "rbi", "home run", "strikeout", "run line"],
                "BASEBALL": ["mlb", "baseball", "nrfi", "rfi", "f5", "f3", "rbi", "home run", "strikeout", "run line", "kbo", "npb", "japan", "korean"],
                "NPB&KBO": ["kbo", "npb", "baseball", "japan", "japanese", "korean"],
                "NPB": ["npb", "baseball", "japan", "japanese"],
                "NBA": ["nba", "basketball"],
                "WNBA": ["wnba", "basketball"],
                "BASKETBALL": ["nba", "wnba", "basketball"],
                "NHL": ["nhl", "hockey"],
                "TENNIS": ["tennis", "atp", "wta", "us open", "wimbledon", "french open", "australian open"],
                "NCAAF": ["ncaaf", "cfb", "college football", "football"],
                "NFL": ["nfl", "football", "pro football"],
                "FOOTBALL": ["nfl", "ncaaf", "cfb", "football", "pro football", "college football"],
                "EPL": ["epl", "premier", "soccer", "football", "match"],
                "KBO": ["kbo", "baseball", "korean"],
                "SOCCER": ["soccer", "football", "epl", "uefa", "btts", "goals", "laliga", "seriea", "bundesliga", "corner", "corners"]
            }
            keywords = sport_keywords.get(sport_upper, [])
            if not keywords:
                if "BASEBALL" in sport_upper:
                    keywords = sport_keywords["BASEBALL"]
                elif "FOOTBALL" in sport_upper:
                    keywords = sport_keywords["FOOTBALL"]
                elif "SOCCER" in sport_upper:
                    keywords = sport_keywords["SOCCER"]
                elif "BASKETBALL" in sport_upper:
                    keywords = sport_keywords["BASKETBALL"]

            if keywords and not any(k in event_ticker or k in event_title for k in keywords):
                if not any(t.lower() in event_ticker or t.lower() in event_title for t in norm_teams if len(t) >= 2):
                    continue

            # Check team/player overlap
            teams_matched = False
            ticker_suffix = event_ticker.split("-")[-1].upper() if "-" in event_ticker else event_ticker.upper()
            for t_raw in teams_extracted:
                if len(t_raw) >= 3 and (self.is_team_name_in_title(t_raw, event_title) or self.is_team_name_in_title(t_raw, sub_title)):
                    teams_matched = True
                    break
            if not teams_matched:
                for t_code in norm_teams:
                    if t_code and (t_code.upper() in ticker_suffix or re.search(r"\b" + re.escape(t_code) + r"\b", event_title, re.IGNORECASE) or re.search(r"\b" + re.escape(t_code) + r"\b", sub_title, re.IGNORECASE)):
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

            # 4. Handle Team Totals (Team Points, Team Runs, Team Goals)
            elif is_team_total:
                is_under_bet = is_explicit_no or "under" in play_lower or "under" in market_lower or re.search(r"\bu\d+", play_lower)
                candidate_markets = []
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = m_ticker.split("-")[-1]

                    team_match = self.is_team_matching_market(primary_team, primary_raw, m_suffix, m_title)

                    m_num_match = re.search(r"(?:over|under|total)\s*(\d+(?:\.\d+)?)", m_title, flags=re.IGNORECASE) or re.search(r"(\d+(?:\.\d+)?)\s*(?:runs?|goals?|points?)", m_title, flags=re.IGNORECASE) or re.search(r"\b(\d+(?:\.\d+)?)\b", m_title)
                    m_num = float(m_num_match.group(1)) if m_num_match else None

                    if primary_team or primary_raw:
                        if team_match:
                            candidate_markets.append((mkt, m_num))
                    else:
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

            # 5a. Handle F5 +0.5 (Opponent NO in 3-way KXMLBF5)
            elif is_f5_plus_half:
                opponent_team = norm_teams[1] if len(norm_teams) >= 2 else None
                opponent_raw = teams_extracted[1] if len(teams_extracted) >= 2 else None
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = m_ticker.split("-")[-1]

                    if "tie" in m_title or m_suffix == "TIE":
                        continue

                    # If opponent team is explicitly extracted from play (e.g. Pirates/White Sox F5 +0.5)
                    if opponent_team and (m_suffix == opponent_team.upper() or opponent_team.lower() in m_title):
                        best_market = mkt
                        best_side = "no"
                        best_event = event
                        break
                    elif opponent_raw and (opponent_raw.lower() in m_title or m_suffix == opponent_raw.upper()):
                        best_market = mkt
                        best_side = "no"
                        best_event = event
                        break

                    # If only primary team extracted (e.g. Pirates F5 +0.5), opponent is the OTHER non-tie market
                    team_match = self.is_team_matching_market(primary_team, primary_raw, m_suffix, m_title)

                    if not team_match:
                        best_market = mkt
                        best_side = "no"
                        best_event = event
                        break

            # 5b. Handle F5 -0.5, F3, F5 Moneyline, 1H Moneyline, and Full Game Moneyline
            elif (is_f5 and not is_spread) or is_f3 or (is_ml and not is_spread) or (is_1h_ml and not is_1h_spread) or is_f5_minus_half:
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = m_ticker.split("-")[-1]

                    if "tie" in m_title or m_suffix == "TIE":
                        continue

                    team_match = self.is_team_matching_market(primary_team, primary_raw, m_suffix, m_title)

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
            elif (is_spread or is_1h_spread or (is_f5 and is_spread)) and ("SPREAD" in event_ticker.upper() or "spread" in event_title or "margin" in event_title or "run line" in event_title):
                is_dog = "+" in play_lower
                candidate_markets = []
                for mkt in markets:
                    m_title = mkt.get("title", "").lower()
                    m_ticker = mkt.get("ticker", "").upper()
                    m_suffix = mkt.get("ticker", "").split("-")[-1]

                    team_match = self.is_team_matching_market(primary_team, primary_raw, m_suffix, m_title)

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

        date_str = f" on {pick.date}" if pick.date else ""
        return MatchResult(
            matched=False,
            reason=f"No active Kalshi market found matching '{pick.play}' ({pick.sport} - {pick.market}){date_str}."
        )
