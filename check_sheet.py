import pandas as pd, io
from src.sheet_reader import fetch_sheet_csv

csv_text = fetch_sheet_csv()
df = pd.read_csv(io.StringIO(csv_text), dtype=str)
df.columns = [c.strip() for c in df.columns]

for idx, r in df.iterrows():
    play = str(r.get('Play'))
    if 'sweep' in play.lower() or '10-leg' in play.lower() or 'parlay' in str(r.get('Market')).lower():
        print(f"Row {idx} | Date: {r.get('Date')} | Play: {play} | Odds: {r.get('Odds')} | Result: {r.get('Result')}")
        print(f"  Notes: {str(r.get('Notes'))[:150]}")
        print("-" * 50)
