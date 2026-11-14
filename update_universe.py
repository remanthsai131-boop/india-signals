#!/usr/bin/env python3
"""Weekly: rebuild universe.json from the Nifty 500 list. Research only, not advice."""
import io, json, datetime as dt
import numpy as np, pandas as pd, requests, yfinance as yf

MAX_PRICE = 2000        # same limits as india_market_brief.py
MIN_PRICE = 100
MIN_TURNOVER = 1e8      # avg daily traded value in Rs (about 10 crore) - keeps only liquid stocks
N_MOMENTUM = 150         # strongest names by momentum, nearness to 3-month high, volume surge
N_LIQUID = 50           # plus the most liquid names for stability
URLS = ["https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"]

def fetch_list():
    h = {"User-Agent": "Mozilla/5.0"}
    for u in URLS:
        try:
            r = requests.get(u, headers=h, timeout=30); r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text)); df.columns = [c.strip() for c in df.columns]
            if {"Symbol", "Industry"} <= set(df.columns):
                return dict(zip(df.Symbol.astype(str).str.strip(), df.Industry.astype(str).str.strip()))
        except Exception as e:
            print("list failed:", u, e)
    return {}

def main():
    sectors = fetch_list()
    if not sectors:
        print("Could not fetch the Nifty 500 list. Keeping the old universe."); return
    syms = list(sectors); rows = []
    for i in range(0, len(syms), 100):
        chunk = [s + ".NS" for s in syms[i:i + 100]]
        try:
            d = yf.download(chunk, period="6mo", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception as e:
            print("download failed:", e); continue
        for s in chunk:
            try:
                x = d[s].dropna(); c, v = x.Close, x.Volume
                if len(x) < 80: continue
                px = float(c.iloc[-1])
                if not (MIN_PRICE <= px <= MAX_PRICE): continue
                turn = float((c * v).tail(20).median())
                if turn < MIN_TURNOVER: continue
                rows.append(dict(sym=s[:-3], turn=turn, mom=float(c.iloc[-1] / c.iloc[-63] - 1),
                                 near=float(c.iloc[-1] / c.tail(63).max()), rv=float(v.tail(5).mean() / v.tail(50).mean())))
            except Exception:
                continue
    if len(rows) < 20:
        print("Too few stocks passed the filters (", len(rows), "). Keeping the old universe."); return
    df = pd.DataFrame(rows)
    df["score"] = .4 * df.mom.rank(pct=True) + .3 * df.near.rank(pct=True) + .3 * df.rv.rank(pct=True)
    pick = list(df.sort_values("score", ascending=False).head(N_MOMENTUM).sym)
    pick += [s for s in df.sort_values("turn", ascending=False).head(N_LIQUID * 2).sym if s not in pick][:N_LIQUID]
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    out = {"updated": f"{now:%d %b %Y}", "source": "Nifty 500 list, filtered by price, liquidity and momentum",
           "stocks": {s: sectors[s] for s in pick}}
    json.dump(out, open("universe.json", "w"), indent=1)
    print("Saved universe.json with", len(pick), "stocks (", len(rows), "passed filters ):", " ".join(pick))

if __name__ == "__main__":
    main()
