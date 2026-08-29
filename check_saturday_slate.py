import requests
import json
from src.sheet_reader import get_active_picks

headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

res = requests.get("https://api.elections.kalshi.com/trade-api/v2/series", headers=headers, timeout=15)
all_series = res.json().get("series", [])

print("Searching series for NCAAF, KBO, and EPL / Soccer:")
targets = ["ncaaf", "cfb", "kbo", "epl", "premier", "soccer"]
matched_s = []
for s in all_series:
    t = s.get("ticker", "")
    title = s.get("title", "")
    if any(k in t.lower() or k in title.lower() for k in targets):
        matched_s.append(s)

print(f"Found {len(matched_s)} matching series:")
for s in matched_s:
    st = s.get("ticker")
    ev_r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={st}&with_nested_markets=true", headers=headers, timeout=5)
    if ev_r.ok:
        evs = ev_r.json().get("events", [])
        if evs:
            print(f"\nSeries {st:20} ({s.get('title')}): {len(evs)} open events")
            for e in evs[:5]:
                print(f"   Event: {e.get('event_ticker')} | {e.get('title')}")
                for m in e.get("markets", []):
                    print(f"      Market: {m.get('ticker')} | {m.get('title')}")
