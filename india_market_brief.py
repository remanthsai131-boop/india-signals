#!/usr/bin/env python3
import datetime as dt, html
import numpy as np, pandas as pd, requests, yfinance as yf

CAPITAL = 100000
RISK_PCT = 1.0
WATCHLIST = ["RELIANCE","TCS","HDFCBANK","ICICIBANK","INFY","SBIN","BHARTIARTL","ITC",
             "LT","AXISBANK","KOTAKBANK","MARUTI","SUNPHARMA","TATAMOTORS","TATASTEEL",
             "BAJFINANCE","HINDUNILVR","NTPC","ONGC","ADANIPORTS","WIPRO","M&M","TITAN","COALINDIA"]
INDICES = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK", "INDIA VIX": "^INDIAVIX"}
SIGNALS = {"breakout": "Breakout (20d high + volume)",
           "bounce": "Oversold bounce (RSI<35)",
           "pullback": "Trend pullback (to 20 EMA)"}

def nse_live():
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
         "Referer": "https://www.nseindia.com/"}
    try:
        s = requests.Session(); s.get("https://www.nseindia.com", headers=h, timeout=10)
        r = s.get("https://www.nseindia.com/api/allIndices", headers=h, timeout=10).json()
        return {d["index"]: (d["last"], d["percentChange"]) for d in r["data"] if d["index"] in INDICES}
    except Exception:
        return {}

def hist(sym, period="2y"):
    df = yf.Ticker(sym).history(period=period, auto_adjust=True)
    return df.dropna() if len(df) else df

def prep(df):
    c = df.Close
    df["ema20"] = c.ewm(span=20).mean(); df["ema50"] = c.ewm(span=50).mean()
    d = c.diff(); up = d.clip(lower=0).rolling(14).mean(); dn = (-d.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn)
    tr = pd.concat([df.High - df.Low, (df.High - c.shift()).abs(), (df.Low - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["hh20"] = df.High.rolling(20).max().shift(); df["vavg"] = df.Volume.rolling(20).mean()
    df["breakout"] = (c > df.hh20) & (df.Volume > 1.5 * df.vavg)
    df["bounce"] = (df.rsi < 35) & (c > df.Open)
    df["pullback"] = (df.ema20 > df.ema50) & (c > df.ema50) & ((c - df.ema20).abs() / c < 0.01)
    return df

def backtest(df, sig, hold=5):
    t = s = n = 0
    for i in np.where(df[sig].values)[0]:
        if i + hold >= len(df) or np.isnan(df.atr.iloc[i]): continue
        e, a = df.Close.iloc[i], df.atr.iloc[i]; stop, tgt = e - 1.5 * a, e + 2 * a
        n += 1
        for j in range(i + 1, i + 1 + hold):
            if df.Low.iloc[j] <= stop: s += 1; break
            if df.High.iloc[j] >= tgt: t += 1; break
    return n, t, s

def outlook(df, days=10):
    r = df.Close.pct_change().dropna().values
    sims = np.random.default_rng(1).choice(r, (5000, days)).sum(axis=1)
    last = df.Close.iloc[-1]
    q = np.percentile(sims, [10, 50, 90])
    return last, [last * (1 + x) for x in q], float((sims > 0).mean())

def main():
    live = nse_live(); pool = {k: [0, 0, 0] for k in SIGNALS}; data = {}
    for t in WATCHLIST:
        try:
            df = hist(t + ".NS")
            if len(df) < 120: continue
            data[t] = prep(df)
            for k in SIGNALS:
                n, w, l = backtest(data[t], k)
                pool[k][0] += n; pool[k][1] += w; pool[k][2] += l
        except Exception:
            continue

    idx_rows = ""
    for name, y in INDICES.items():
        try:
            d = hist(y, "5d"); last, prev = d.Close.iloc[-1], d.Close.iloc[-2]
            lv, ch = live.get(name, (last, (last / prev - 1) * 100))
            src = "NSE live" if name in live else "Yahoo (delayed)"
            idx_rows += f"<tr><td>{name}</td><td>{lv:,.2f}</td><td>{ch:+.2f}%</td><td>{src}</td></tr>"
        except Exception:
            pass

    rows = ""
    for t, df in data.items():
        x = df.iloc[-1]
        for k in SIGNALS:
            if bool(x[k]):
                n, w, l = backtest(df, k)
                e, a = x.Close, x.atr; stop, tgt = e - 1.5 * a, e + 2 * a
                qty = int((CAPITAL * RISK_PCT / 100) / (e - stop)) if e > stop else 0
                hit = f"{100 * w / n:.0f}%" if n else "-"
                rows += (f"<tr><td>{t}</td><td>{SIGNALS[k]}</td><td>{e:.1f}</td><td>{stop:.1f}</td>"
                         f"<td>{tgt:.1f}</td><td>{qty}</td><td>{hit} of {n}</td></tr>")
    rows = rows or "<tr><td colspan=7>No setups today - skipping is a valid trade.</td></tr>"

    bt = "".join(f"<tr><td>{SIGNALS[k]}</td><td>{v[0]}</td><td>{100*v[1]/max(v[0],1):.0f}%</td>"
                 f"<td>{100*v[2]/max(v[0],1):.0f}%</td></tr>" for k, v in pool.items())

    nifty = prep(hist("^NSEI"))
    last, (lo, mid, hi), pup = outlook(nifty)
    tr_ = "above" if nifty.Close.iloc[-1] > nifty.ema50.iloc[-1] else "below"
    out = (f"Nifty {last:,.0f} is {tr_} its 50 EMA, RSI {nifty.rsi.iloc[-1]:.0f}. Historical-return simulation for the "
           f"next ~10 trading days: 80% of outcomes fall between <b>{lo:,.0f}</b> and <b>{hi:,.0f}</b> "
           f"(median {mid:,.0f}); {pup*100:.0f}% of simulations end higher. This is a range of possibilities, not a forecast.")

    page = f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>India Signals</title><link rel=manifest href=manifest.json><meta name=theme-color content="#0d1117"><link rel=apple-touch-icon href=icon-180.png><meta name=apple-mobile-web-app-capable content=yes><meta name=mobile-web-app-capable content=yes><style>
body{{font:15px system-ui;max-width:900px;margin:auto;padding:16px;background:#fff;color:#111}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px;display:block;overflow-x:auto}}
td,th{{border-bottom:1px solid #8884;padding:6px 8px;text-align:left;white-space:nowrap}}
.w{{background:#f8514926;padding:10px;border-radius:8px}}
@media(prefers-color-scheme:dark){{body{{background:#0d1117;color:#e6edf3}}}}</style>
<h2>India Market Brief - {(dt.datetime.utcnow()+dt.timedelta(hours=5,minutes=30)):%d %b %Y %H:%M} IST</h2>
<div class=w>Research only, not financial advice. Backtests are history, not a promise. Always use a stop-loss; paper-trade first.</div>
<h3>Indices</h3><table><tr><th>Index<th>Level<th>Change<th>Source</tr>{idx_rows}</table>
<h3>Next-day watchlist (today's signals)</h3>
<table><tr><th>Stock<th>Setup<th>Entry<th>Stop<th>Target<th>Qty<th>Past hit-rate</tr>{rows}</table>
<h3>Backtest across watchlist (2y, 5-day hold)</h3>
<table><tr><th>Setup<th>Trades<th>Target hit<th>Stop hit</tr>{bt}</table>
<h3>1-2 week scenario</h3><p>{out}</p>"""
    import os; os.makedirs("docs", exist_ok=True)
    open("docs/index.html", "w", encoding="utf-8").write(page)
    print("Saved docs/index.html")

if __name__ == "__main__":
    main()
