#!/usr/bin/env python3
"""India Signals dashboard. Research only, not financial advice."""
import datetime as dt, html, os
import numpy as np, pandas as pd, requests, yfinance as yf

CAPITAL = 100000      # your trading capital (Rs)
RISK_PCT = 1.0        # max loss per trade, % of capital
MAX_PRICE = 2000      # only stocks priced at or below this
MIN_PRICE = 100        # skip penny stocks
MAX_SETUPS = 30       # how many ranked setups to show (aim 10-20)
MAX_POS_PCT = 30      # one position never more than this % of capital
SECTORS = {
 "Banks & Finance": "SBIN BANKBARODA PNB CANBK UNIONBANK IDFCFIRSTB FEDERALBNK INDUSINDBK BANDHANBNK AUBANK HDFCBANK ICICIBANK AXISBANK KOTAKBANK RECLTD PFC IRFC",
 "Energy & Power": "ONGC NTPC POWERGRID COALINDIA BPCL IOC GAIL TATAPOWER NHPC ADANIPOWER SUZLON OIL PETRONET",
 "Metals": "TATASTEEL SAIL NMDC HINDALCO JSWSTEEL VEDL NATIONALUM",
 "IT": "WIPRO INFY HCLTECH TECHM",
 "Auto": "ASHOKLEY MOTHERSON MARUTI M&M BAJAJ-AUTO",
 "Consumer": "ITC TATACONSUM DABUR MARICO GODREJCP HINDUNILVR",
 "Pharma": "SUNPHARMA CIPLA DRREDDY ZYDUSLIFE AUROPHARMA BIOCON",
 "Infra & Defence": "BEL BHEL RVNL IRCTC NBCC IRCON DLF AMBUJACEM ADANIPORTS",
 "New-age & Telecom": "IDEA ETERNAL PAYTM NYKAA JIOFIN",
}
SECTOR_OF = {t: sec for sec, ts in SECTORS.items() for t in ts.split()}
UNIVERSE = list(SECTOR_OF)
try:
    import json
    _u = json.load(open("universe.json"))["stocks"]
    UNIVERSE = list(_u); SECTOR_OF.update(_u)
except Exception:
    pass
INDICES = {"NIFTY 50": "^NSEI", "NIFTY BANK": "^NSEBANK", "INDIA VIX": "^INDIAVIX"}
SIGNALS = {"breakout": "Breakout (20d high + volume)",
           "bounce": "Oversold bounce (RSI under 35)",
           "pullback": "Trend pullback (to 20 EMA)"}

def nse_live():
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
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

# ---------- tiny SVG chart helpers (no extra libraries) ----------
def pth(xs, ys):
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))

def line_chart(series, w=700, h=250, fmt="{:,.0f}", extra_h=()):
    arrs = [np.asarray(v, float) for _, v, _ in series]
    allv = np.concatenate(arrs + [np.asarray(extra_h, float)]) if len(extra_h) else np.concatenate(arrs)
    lo, hi = float(np.nanmin(allv)), float(np.nanmax(allv)); p = (hi - lo) * .06 or 1; lo -= p; hi += p
    L, R, T, B = 54, 10, 24, 10
    Y = lambda v: h - B - (v - lo) / (hi - lo) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        o.append(f'<line x1="{L}" x2="{w-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L-6}" y="{Y(v)+4:.1f}" class="ax" text-anchor="end">{fmt.format(v)}</text>')
    lx = L
    for (name, v, cls), a in zip(series, arrs):
        xs = L + np.arange(len(a)) * (w - L - R) / max(len(a) - 1, 1)
        o.append(f'<path d="{pth(xs, [Y(x) for x in a])}" class="ln {cls}"/>')
        o.append(f'<text x="{lx}" y="14" class="lg {cls}t">{name}</text>'); lx += 12 + 7 * len(name)
    for val, cls, lab in extra_h:
        pass
    o.append('</svg>')
    return "".join(o)

def rsi_chart(vals, w=700, h=110):
    a = np.asarray(vals, float); L, R, T, B = 54, 10, 8, 8
    Y = lambda v: h - B - v / 100 * (h - T - B)
    xs = L + np.arange(len(a)) * (w - L - R) / max(len(a) - 1, 1)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">',
         f'<rect x="{L}" y="{Y(70):.1f}" width="{w-L-R}" height="{Y(30)-Y(70):.1f}" class="band"/>']
    for v in (30, 50, 70):
        o.append(f'<line x1="{L}" x2="{w-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L-6}" y="{Y(v)+4:.1f}" class="ax" text-anchor="end">{v}</text>')
    o.append(f'<path d="{pth(xs, [Y(x) for x in a])}" class="ln c2"/></svg>')
    return "".join(o)

def heatmap(items, cols=6):
    tw, th = 116, 62; rows = (len(items) + cols - 1) // cols
    o = [f'<svg viewBox="0 0 {cols*tw} {rows*th}" class="ch">']
    for i, (s, ch) in enumerate(items):
        x, y = (i % cols) * tw, (i // cols) * th
        col = "34,197,94" if ch >= 0 else "239,68,68"; a = .18 + .6 * min(abs(ch) / 3, 1)
        o.append(f'<rect x="{x+2}" y="{y+2}" width="{tw-4}" height="{th-4}" rx="8" fill="rgba({col},{a:.2f})"/>'
                 f'<text x="{x+tw/2}" y="{y+27}" text-anchor="middle" class="hs">{html.escape(s)}</text>'
                 f'<text x="{x+tw/2}" y="{y+46}" text-anchor="middle" class="hv">{ch:+.2f}%</text>')
    o.append('</svg>')
    return "".join(o)

def bar_chart(rows, w=700):
    h = 46 * len(rows) + 26; L = 190; o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for i, (name, n, t, s) in enumerate(rows):
        y = 10 + i * 46; bw = w - L - 12; n1 = max(n, 1)
        tp, sp = t / n1, s / n1; np_ = 1 - tp - sp
        o.append(f'<text x="{L-8}" y="{y+17}" text-anchor="end" class="ax2">{name}</text>'
                 f'<text x="{L-8}" y="{y+32}" text-anchor="end" class="ax">{n} trades</text>')
        x = L
        for frac, cls in ((tp, "gt"), (sp, "gs"), (np_, "gn")):
            ww = bw * frac
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{ww:.1f}" height="28" class="{cls}"/>')
            if frac > .08: o.append(f'<text x="{x+ww/2:.1f}" y="{y+19}" text-anchor="middle" class="bl">{frac*100:.0f}%</text>')
            x += ww
    o.append(f'<text x="{L}" y="{h-6}" class="ax">green = target hit, red = stop hit, grey = neither in 5 days</text></svg>')
    return "".join(o)

def fan_chart(last, rets, days=10, w=700, h=260):
    rng = np.random.default_rng(1)
    paths = np.cumsum(rng.choice(rets, (5000, days)), axis=1)
    q = {p: np.concatenate([[last], last * (1 + np.percentile(paths, p, axis=0))]) for p in (10, 25, 50, 75, 90)}
    lo, hi = q[10].min(), q[90].max(); pd_ = (hi - lo) * .08 or 1; lo -= pd_; hi += pd_
    L, R, T, B = 54, 10, 12, 22; X = lambda i: L + i * (w - L - R) / days
    Y = lambda v: h - B - (v - lo) / (hi - lo) * (h - T - B)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        o.append(f'<line x1="{L}" x2="{w-R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                 f'<text x="{L-6}" y="{Y(v)+4:.1f}" class="ax" text-anchor="end">{v:,.0f}</text>')
    for d in range(0, days + 1, 2):
        o.append(f'<text x="{X(d):.1f}" y="{h-6}" class="ax" text-anchor="middle">day {d}</text>')
    for a, b, cls in ((10, 90, "f1"), (25, 75, "f2")):
        up = [f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(q[b])]
        dn = [f"{X(i):.1f},{Y(v):.1f}" for i, v in reversed(list(enumerate(q[a])))]
        o.append(f'<polygon points="{" ".join(up+dn)}" class="{cls}"/>')
    o.append(f'<path d="{pth([X(i) for i in range(days+1)], [Y(v) for v in q[50]])}" class="ln c1"/></svg>')
    return "".join(o), q

def spark(closes, entry, stop, tgt, w=300, h=96):
    a = np.asarray(closes, float); lo, hi = min(a.min(), stop), max(a.max(), tgt); p = (hi - lo) * .08 or 1; lo -= p; hi += p
    Y = lambda v: h - 6 - (v - lo) / (hi - lo) * (h - 12); xs = 4 + np.arange(len(a)) * (w - 8) / max(len(a) - 1, 1)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for v, cls in ((tgt, "gl"), (entry, "el"), (stop, "sl")):
        o.append(f'<line x1="4" x2="{w-4}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="{cls}"/>')
    o.append(f'<path d="{pth(xs, [Y(x) for x in a])}" class="ln c1"/></svg>')
    return "".join(o)

CSS = """
:root{--bg:#fff;--fg:#111827;--mut:#6b7280;--card:#f3f4f6;--line:#d1d5db;--up:#16a34a;--dn:#dc2626;--blue:#2563eb;--amber:#d97706}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--card:#161b22;--line:#30363d;--up:#3fb950;--dn:#f85149;--blue:#58a6ff;--amber:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif;padding:14px;max-width:960px;margin:auto}
h1{font-size:21px;margin:6px 0}h2{font-size:16px;margin:24px 0 4px}p.n{color:var(--mut);font-size:13px;margin:0 0 8px}
.warn{border:1px solid var(--dn);border-radius:10px;padding:8px 10px;font-size:12.5px;margin:10px 0}
.grid3{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.tile,.card{background:var(--card);border-radius:12px;padding:10px 12px}.tile .k{color:var(--mut);font-size:12px}.tile .v{font-size:20px;font-weight:700}.tile .s{color:var(--mut);font-size:11px}
.up{color:var(--up)}.dn{color:var(--dn)}.ch{width:100%;height:auto;display:block}
.grid{stroke:var(--line);stroke-width:1}.ax{fill:var(--mut);font-size:11px}.ax2{fill:var(--fg);font-size:12px}.lg{font-size:12px;font-weight:600}
.ln{fill:none;stroke-width:2}.c1{stroke:var(--fg);fill:none}.c2{stroke:var(--blue)}.c3{stroke:var(--amber)}.c1t{fill:var(--fg)}.c2t{fill:var(--blue)}.c3t{fill:var(--amber)}
.band{fill:var(--line);opacity:.35}.hs{fill:var(--fg);font-size:13px;font-weight:700}.hv{fill:var(--fg);font-size:12px}
.gt{fill:var(--up)}.gs{fill:var(--dn)}.gn{fill:var(--mut);opacity:.5}.bl{fill:#fff;font-size:12px;font-weight:700}
.f1{fill:var(--blue);opacity:.15}.f2{fill:var(--blue);opacity:.3}
.gl{stroke:var(--up);stroke-dasharray:4 3}.el{stroke:var(--mut)}.sl{stroke:var(--dn);stroke-dasharray:4 3}
.sig{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}.sig .h{display:flex;justify-content:space-between;font-weight:700}
.sig .m{color:var(--mut);font-size:12.5px}table{border-collapse:collapse;width:100%;font-size:13.5px}
.dgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.dn2{width:100%;max-width:200px;margin:auto;display:block}.dt{fill:var(--fg);font-size:26px;font-weight:700}.ds{fill:var(--mut);font-size:11px}
.lgd{font-size:12.5px;margin-top:4px}.lgd span{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}
.tag{font-size:11px;padding:1px 6px;border-radius:6px;background:var(--line)}
.tw{overflow-x:auto}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}
"""


PAL = ["#3fb950", "#58a6ff", "#e3b341", "#f85149", "#a371f7", "#db61a2", "#79c0ff", "#8b949e", "#f0883e"]

def donut(title, parts, size=200):
    parts = [(n, v) for n, v in parts if v > 0]
    tot = sum(v for _, v in parts)
    if not tot:
        return f'<div class="card"><b>{title}</b><p class="n">No data</p></div>'
    c = size / 2; r = size * .36; sw = size * .18; circ = 2 * 3.14159265 * r; off = 0
    o = [f'<svg viewBox="0 0 {size} {size}" class="dn2">']
    lg = []
    for i, (n, v) in enumerate(parts):
        col = PAL[i % len(PAL)]; d = circ * v / tot
        o.append(f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{col}" stroke-width="{sw}" '
                 f'stroke-dasharray="{d:.2f} {circ-d:.2f}" stroke-dashoffset="{-off:.2f}" transform="rotate(-90 {c} {c})"/>')
        off += d; lg.append(f'<div><span style="background:{col}"></span>{html.escape(n)} ({v})</div>')
    o.append(f'<text x="{c}" y="{c+6}" text-anchor="middle" class="dt">{tot}</text></svg>')
    return f'<div class="card"><b>{title}</b>{"".join(o)}<div class="lgd">{"".join(lg)}</div></div>'

def pick_setup(t, df):
    x = df.iloc[-1]; c = float(x.Close); atr = float(x.atr); rsi = float(x.rsi)
    if np.isnan(atr) or atr <= 0: return None
    trend = bool(x.ema20 > x.ema50 and c > x.ema50)
    hh = float(x.hh20); dist = (hh - c) / c
    volr = float(x.Volume / x.vavg) if x.vavg else 0.0
    trig = [k for k in SIGNALS if bool(x[k])]
    if trig: cat, kind = SIGNALS[trig[0]], "Triggered"
    elif trend and 0 < dist <= .02: cat, kind = "Near breakout (within 2% of 20d high)", "Near"
    elif trend and abs(c - x.ema20) / c < .025 and rsi < 65: cat, kind = "Near pullback to 20 EMA", "Near"
    elif rsi < 38: cat, kind = "Oversold watch (RSI under 38)", "Near"
    else: cat, kind = "Watch (no setup yet)", "Watch"
    score = (3 if trig else 0) + (2 if trend else 0) + (1 if kind == "Near" else 0) + (1 if volr > 1.2 else 0) \
            + (1 if 45 <= rsi <= 70 else 0) - (1 if rsi > 75 else 0)
    entry = hh * 1.001 if cat.startswith("Near breakout") else c
    stop, tgt = entry - 1.5 * atr, entry + 2 * atr
    qty = int((CAPITAL * RISK_PCT / 100) / (entry - stop))
    qty = max(min(qty, int(CAPITAL * MAX_POS_PCT / 100 / entry)), 0)
    chg = (c / float(df.Close.iloc[-2]) - 1) * 100
    hit = "-"
    if trig:
        n, w, l = backtest(df, trig[0]); hit = f"{100*w/n:.0f}% of {n}" if n else "n/a"
    return dict(t=t, price=c, cat=cat, kind=kind, score=score, entry=entry, stop=stop, tgt=tgt, qty=qty,
                chg=chg, rsi=rsi, hit=hit, sector=SECTOR_OF.get(t, "Other"), closes=df.Close.tail(40))

def main():
    live = nse_live(); pool = {k: [0, 0, 0] for k in SIGNALS}; data = {}; failed = 0
    for t in UNIVERSE:
        try:
            df = hist(t + ".NS")
            if len(df) < 120: failed += 1; continue
            px = float(df.Close.iloc[-1])
            if not (MIN_PRICE <= px <= MAX_PRICE): continue
            data[t] = prep(df)
            for k in SIGNALS:
                n, w, l = backtest(data[t], k)
                pool[k][0] += n; pool[k][1] += w; pool[k][2] += l
        except Exception:
            failed += 1
    N = max(len(data), 1)

    tiles, vix = "", None
    for name, y in INDICES.items():
        try:
            d = hist(y, "5d"); last, prev = d.Close.iloc[-1], d.Close.iloc[-2]
            lv, ch = live.get(name, (last, (last / prev - 1) * 100)); lv, ch = float(lv), float(ch)
            if name == "INDIA VIX": vix = lv
            src = "NSE live" if name in live else "Yahoo, delayed"
            tiles += (f'<div class="tile"><div class="k">{name}</div><div class="v">{lv:,.2f}</div>'
                      f'<div class="{"up" if ch >= 0 else "dn"}">{ch:+.2f}%</div><div class="s">{src}</div></div>')
        except Exception:
            pass

    picks = [p for p in (pick_setup(t, df) for t, df in data.items()) if p]
    order = {"Triggered": 0, "Near": 1, "Watch": 2}
    picks.sort(key=lambda p: (-p["score"], order[p["kind"]]))
    top = picks[:MAX_SETUPS]
    adv = sum(p["chg"] > .05 for p in picks); dec = sum(p["chg"] < -.05 for p in picks); flat = len(picks) - adv - dec
    above = sum(bool(df.Close.iloc[-1] > df.ema50.iloc[-1]) for df in data.values())
    rsis = [float(df.rsi.iloc[-1]) for df in data.values()]
    reg = "n/a" if vix is None else ("low" if vix < 14 else "moderate" if vix < 20 else "elevated")
    trig_n = sum(p["kind"] == "Triggered" for p in picks)
    tiles += (f'<div class="tile"><div class="k">Stocks scanned</div><div class="v">{len(data)}</div><div class="s">priced Rs {MIN_PRICE}-{MAX_PRICE}</div></div>'
              f'<div class="tile"><div class="k">Triggered today</div><div class="v">{trig_n}</div><div class="s">strict signals</div></div>'
              f'<div class="tile"><div class="k">Above 50 EMA</div><div class="v">{100*above/N:.0f}%</div><div class="s">avg RSI {np.mean(rsis) if rsis else 0:.0f}, VIX {reg}</div></div>')

    kinds = {"Triggered": "Triggered today", "Near": "Near a trigger", "Watch": "Watch only"}
    d1 = donut("Setups by type", [(kinds[k], sum(p["kind"] == k for p in top)) for k in kinds])
    secs = {}
    for p in top: secs[p["sector"]] = secs.get(p["sector"], 0) + 1
    d2 = donut("Setups by sector", sorted(secs.items(), key=lambda x: -x[1]))
    tg = sum(v[1] for v in pool.values()); sp = sum(v[2] for v in pool.values()); nn = sum(v[0] for v in pool.values())
    d3 = donut("Past outcomes (all setups)", [("Target hit", tg), ("Stop hit", sp), ("Neither", max(nn - tg - sp, 0))])
    d4 = donut("Today's moves (universe)", [("Up", adv), ("Down", dec), ("Flat", flat)])

    nifty = prep(hist("^NSEI")); r = nifty.Close.pct_change().dropna().values
    n6 = nifty.tail(126); last_n = float(nifty.Close.iloc[-1])
    fan, q = fan_chart(last_n, r)
    read = (f"Nifty is {'above' if last_n > nifty.ema50.iloc[-1] else 'below'} its 50 EMA, RSI {nifty.rsi.iloc[-1]:.0f}. "
            f"{adv} of {len(picks)} scanned stocks rose today; {100*above/N:.0f}% sit above their 50 EMA.")
    outlook = (f"Simulated from 2 years of daily returns: 80% of 10-day outcomes fall between {q[10][-1]:,.0f} and "
               f"{q[90][-1]:,.0f} (median {q[50][-1]:,.0f}). A range of possibilities, not a forecast.")

    rows = ""
    for i, p in enumerate(top, 1):
        risk = p["qty"] * (p["entry"] - p["stop"])
        rows += (f'<tr><td>{i}. {html.escape(p["t"])}</td><td>{p["price"]:,.1f}</td><td>{html.escape(p["cat"])}</td><td>{p["score"]}</td>'
                 f'<td>{p["entry"]:,.1f}</td><td>{p["stop"]:,.1f}</td><td>{p["tgt"]:,.1f}</td><td>{p["qty"]}</td><td>{risk:,.0f}</td><td>{p["hit"]}</td></tr>')
    cards = ""
    for p in top[:6]:
        cards += (f'<div class="card"><div class="h"><span>{html.escape(p["t"])}</span><span class="{"up" if p["chg"]>=0 else "dn"}">{p["chg"]:+.2f}%</span></div>'
                  f'<div class="m">{html.escape(p["cat"])} | {html.escape(p["sector"])}</div>{spark(p["closes"], p["entry"], p["stop"], p["tgt"])}'
                  f'<div>Entry {p["entry"]:,.1f} | Stop {p["stop"]:,.1f} | Target {p["tgt"]:,.1f}</div>'
                  f'<div class="m">Qty {p["qty"]} | RSI {p["rsi"]:.0f} | Score {p["score"]}</div></div>')
    items = sorted([(p["t"], p["chg"]) for p in top], key=lambda x: -x[1])
    bars = bar_chart([(SIGNALS[k], v[0], v[1], v[2]) for k, v in pool.items()])
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)

    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>India Signals</title>
<link rel=manifest href=manifest.json><meta name=theme-color content="#0d1117">
<link rel=apple-touch-icon href=icon-180.png><meta name=apple-mobile-web-app-capable content=yes>
<meta name=mobile-web-app-capable content=yes><style>{CSS}</style></head><body>
<h1>India Signals - {now:%d %b %Y %H:%M} IST</h1>
<div class=warn>Research and practice only, not financial advice. Backtests are history, not a promise. Always use a stop-loss and paper-trade first.</div>
<div class=grid3>{tiles}</div>
<h2>Your data at a glance</h2><div class=dgrid>{d1}{d2}{d3}{d4}</div>
<h2>Top {len(top)} setups under Rs {MAX_PRICE}</h2>
<p class=n>Score: +3 triggered, +2 uptrend, +1 near a trigger, +1 volume above 1.2x average, +1 RSI 45-70, -1 RSI above 75. Stop 1.5 ATR, target 2 ATR, risk {RISK_PCT:g}% of Rs {CAPITAL:,}, one position max {MAX_POS_PCT}% of capital. Past target-hit exists only for triggered setups.</p>
<div class=tw><table><tr><th>Stock<th>Price<th>Setup<th>Score<th>Entry<th>Stop<th>Target<th>Qty<th>Risk Rs<th>Past hit</tr>{rows}</table></div>
<h2>Top 6 charts</h2><p class=n>Last 40 closes. Dashed green = target, dashed red = stop, grey = entry.</p><div class=sig>{cards}</div>
<h2>Heatmap of the top setups - today's change</h2>{heatmap(items)}
<h2>Nifty 50 - 6 months</h2><p class=n>Price with 20 and 50 day averages.</p>
{line_chart([("Nifty", n6.Close, "c1"), ("EMA20", n6.ema20, "c2"), ("EMA50", n6.ema50, "c3")])}
<p class=n>RSI(14): above 70 stretched, below 30 oversold.</p>{rsi_chart(n6.rsi)}<p>{read}</p>
<h2>How often did these setups work?</h2><p class=n>Whole universe, 2 years, stop 1.5 ATR, target 2 ATR, 5-day hold.</p>{bars}
<h2>10-day scenario for Nifty</h2><p class=n>Dark band 50% of outcomes, light band 80%, line is the median.</p>{fan}<p>{outlook}</p>
<p class=n>Data: NSE public site and Yahoo Finance (free, may be delayed or wrong). {failed} tickers could not be loaded. Check your broker before acting.</p>
</body></html>"""
    os.makedirs("docs", exist_ok=True)
    open("docs/index.html", "w", encoding="utf-8").write(page)
    print("Saved docs/index.html;", len(data), "stocks;", len(top), "setups")

if __name__ == "__main__":
    main()
