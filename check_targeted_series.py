import requests

headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

res = requests.get("https://api.elections.kalshi.com/trade-api/v2/series", headers=headers, timeout=15)
all_series = res.json().get("series", [])

series_to_check = [
    # EPL / Soccer
    "KXEPLGAME", "KXEPLMATCH", "KXEPLTOTAL", "KXEPLGOALS", "KXSOCCERTOTAL", "KXEPL1H", "KXEPL2H", "KXEPLBTTS",
    # KBO
    "KXKBOGAME", "KXKBOTOTAL", "KXKBORFI", "KXKBORUNS",
    # NCAAF / CFB
    "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL", "KXCFBGAME", "KXCFBSPREAD", "KXCFBTOTAL", "KXNCAAF"
]

print("=== Checking specific sports series ===")
for st in series_to_check:
    ev_r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={st}&with_nested_markets=true", headers=headers, timeout=5)
    if ev_r.ok:
        evs = ev_r.json().get("events", [])
        print(f"Series: {st:16} -> {len(evs)} open events")
        for e in evs:
            print(f"   Event: {e.get('event_ticker'):30} | {e.get('title')}")
            for m in e.get("markets", []):
                print(f"      Market: {m.get('ticker'):35} | {m.get('title')}")

# Also search all series tickers containing EPL, KBO, NCAAF, CFB, SOCCER
print("\n=== Other series with matching keywords ===")
for s in all_series:
    t = s.get("ticker", "")
    if any(k in t for k in ["EPL", "KBO", "NCAAF", "CFB"]) and t not in series_to_check:
        ev_r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={t}&with_nested_markets=true", headers=headers, timeout=5)
        if ev_r.ok and ev_r.json().get("events"):
            print(f"Series: {t:20} -> {len(ev_r.json().get('events'))} open events ({s.get('title')})")
            for e in ev_r.json().get("events")[:3]:
                print(f"   Event: {e.get('event_ticker')} | {e.get('title')}")
                for m in e.get("markets", []):
                    print(f"      Market: {m.get('ticker')} | {m.get('title')}")
