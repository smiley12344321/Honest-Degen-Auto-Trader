import requests

headers = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

res = requests.get("https://api.elections.kalshi.com/trade-api/v2/series", headers=headers, timeout=15)
all_series = res.json().get("series", [])

print(f"Total series: {len(all_series)}")

# Let's find every active series with open events
active_sports_series = []
for s in all_series:
    t = s.get("ticker", "")
    title = s.get("title", "").lower()
    cat = s.get("category", "").lower()
    
    # Check sports keywords
    if any(k in t.lower() or k in title for k in ["epl", "kbo", "ncaaf", "cfb", "tottenham", "spurs", "newcastle", "florida state", "jacksonville", "premier", "soccer", "baseball"]):
        try:
            ev_r = requests.get(f"https://api.elections.kalshi.com/trade-api/v2/events?status=open&series_ticker={t}&with_nested_markets=true", headers=headers, timeout=3)
            if ev_r.ok and ev_r.json().get("events"):
                evs = ev_r.json().get("events")
                print(f"[ACTIVE] {t:22} | {s.get('title'):30} | {len(evs)} events")
                for e in evs[:2]:
                    print(f"    Event: {e.get('event_ticker')} | {e.get('title')}")
                    for m in e.get("markets", []):
                        print(f"       Market: {m.get('ticker')} | {m.get('title')}")
        except Exception:
            pass
