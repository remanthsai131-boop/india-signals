#!/usr/bin/env python3
"""Pro system: trend, BUY/SELL signals, chart-based entry/stop/targets, quality filter, 1-year backtest.
Writes docs/pro.html + docs/pro.json. Research only, not financial advice. No orders are placed."""
import datetime as dt, html, json, os
import numpy as np, pandas as pd
import india_market_brief as m

CAPITAL, RISK_PCT = m.CAPITAL, m.RISK_PCT
HOLD_DAYS = 20          # swing trade: up to about 1 month
COST_PCT = 0.30         # round-trip cost estimate in % (brokerage, taxes, slippage)
TOP_N = 40
MIN_Q = 50              # minimum quality score to appear in the list
MAX_POS_PCT = 20        # one swing position max % of capital
TREND = {2: "Strong up", 1: "Up", 0: "Sideways", -1: "Down", -2: "Strong down"}

# ---------- indicators ----------
def prepare(df, nclose):
    c, h, l, v = df.Close, df.High, df.Low, df.Volume
    for n in (20, 50, 200): df[f"e{n}"] = c.ewm(span=n, adjust=False).mean()
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d = c.diff(); up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn)
    um, dm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((um > dm) & (um > 0), um, 0.0), index=df.index).ewm(alpha=1 / 14, adjust=False).mean()
    mdm = pd.Series(np.where((dm > um) & (dm > 0), dm, 0.0), index=df.index).ewm(alpha=1 / 14, adjust=False).mean()
    pdi, mdi = 100 * pdm / df.atr, 100 * mdm / df.atr
    df["adx"] = (100 * (pdi - mdi).abs() / (pdi + mdi)).ewm(alpha=1 / 14, adjust=False).mean()
    df["hh20"] = h.rolling(20).max().shift(); df["hh60"] = h.rolling(60).max().shift(); df["ll20"] = l.rolling(20).min().shift()
    df["sl10"] = l.rolling(10).min(); df["vavg"] = v.rolling(20).mean(); df["turn"] = (c * v).rolling(20).median()
    df["h52"] = h.rolling(250, min_periods=120).max()
    n = nclose.reindex(df.index).ffill()
    df["rs"] = (c / c.shift(63) - 1) - (n / n.shift(63) - 1)
    su = (c > df.e20) & (df.e20 > df.e50) & (df.e50 > df.e200) & (df.adx > 25); u = (c > df.e50) & (df.e50 > df.e200)
    sd = (c < df.e20) & (df.e20 < df.e50) & (df.e50 < df.e200) & (df.adx > 25); dw = (c < df.e50) & (df.e50 < df.e200)
    df["trend"] = np.select([su, u, sd, dw], [2, 1, -2, -1], 0)
    return df

def signals(df):
    c, o, v, atr = df.Close, df.Open, df.Volume, df.atr; ix = df.index
    pb_lo, pb_hi = df.e50, df.e20 + .25 * atr
    pull = (df.trend >= 1) & (c >= pb_lo) & (c <= pb_hi) & df.rsi.between(35, 62) & (c > o)
    brk = (df.trend >= 1) & (c > df.hh20) & (c <= df.hh20 + .5 * atr) & (v >= 1.5 * df.vavg) & (df.rsi < 75)
    z_lo = pd.Series(np.where(brk, df.hh20, pb_lo), index=ix); z_hi = pd.Series(np.where(brk, df.hh20 + .5 * atr, pb_hi), index=ix)
    stop = pd.Series(np.where(brk, np.minimum(df.sl10, df.hh20 - atr) - .25 * atr, np.minimum(df.sl10, df.e50) - .25 * atr), index=ix)
    entry = c.clip(lower=z_lo, upper=z_hi); stop = pd.Series(np.where(entry - stop < atr, entry - atr, stop), index=ix)
    df["pull"] = pull & ((entry - stop) <= 4 * atr) & ~brk; df["brk"] = brk & ((entry - stop) <= 4 * atr)
    df["z_lo"], df["z_hi"], df["entry"], df["stop"] = z_lo, z_hi, entry, stop
    df["sell"] = ((df.trend <= -1) & (c < df.e20)) | ((c < df.ll20) & (v >= 1.3 * df.vavg) & (df.trend <= 0))
    return df

def backtest(df, sig, days=250, k=2.0, H=HOLD_DAYS, trail=False, a=None, b=None):
    """Replay the rules: fill next open, stop first on ties, target = k*R (or trail below EMA20), max H days, costs included."""
    res, last = [], -1
    a = len(df) - days if a is None else a; b = len(df) if b is None else b
    hi, lo, op, cl, e20 = df.High.values, df.Low.values, df.Open.values, df.Close.values, df.e20.values
    for i in np.where(sig.values)[0]:
        if i < a or i >= b or i <= last or i + 1 >= len(df): continue
        e, s = float(df.entry.iloc[i]), float(df.stop.iloc[i]); R = e - s
        if R <= 0 or np.isnan(R): continue
        t1 = e + k * R; fill = op[i + 1]
        if fill <= s or (not trail and fill >= t1): continue
        out = None
        for j in range(i + 1, min(i + 1 + H, len(df))):
            if lo[j] <= s: out = ("stop", min(s, op[j]) if j > i + 1 else s, j); break
            if trail:
                if j > i + 1 and cl[j] < e20[j]: out = ("trail", cl[j], j); break
            elif hi[j] >= t1: out = ("target", t1, j); break
        if out is None:
            if i + H >= len(df): continue
            out = ("expired", cl[i + H], i + H)
        res.append((df.index[i], out[0], (out[1] - fill) / R - COST_PCT / 100 * fill / R)); last = out[2]
    return res

VARIANTS = [("Fixed target 1.5R, hold 10 days", dict(k=1.5, H=10)), ("Fixed target 2R, hold 20 days", dict(k=2.0, H=20)),
            ("Fixed target 3R, hold 20 days", dict(k=3.0, H=20)), ("Trailing exit (close below 20-day average), up to 40 days", dict(H=40, trail=True))]

def study(data):
    """Walk-forward check: pick the best exit style on the first half of the year, then report it on the second half."""
    N = 250; mid = N // 2; out = []
    for name, kw in VARIANTS:
        h1, h2 = [], []
        for df in data.values():
            L = len(df); sg = df.pull | df.brk
            h1 += backtest(df, sg, a=L - N, b=L - mid, **kw); h2 += backtest(df, sg, a=L - mid, b=L, **kw)
        out.append((name, stats(h1), stats(h2)))
    return out

def stats(res):
    if not res: return dict(n=0, win=0, avg=0, pf=0, dd=0)
    r = np.array([x[2] for x in res]); cum = np.cumsum(r)
    gl = abs(r[r < 0].sum())
    return dict(n=len(r), win=100 * (r > 0).mean(), avg=float(r.mean()), pf=float(r[r > 0].sum() / gl) if gl else 99.0,
                dd=float((np.maximum.accumulate(cum) - cum).max()))

# ---------- quality filter ----------
def quality(x, st, kind, regime_ok, nifty_rsi, in_zone):
    q = {2: 25, 1: 15}.get(int(x.trend), 0) + (10 if x.adx >= 25 else 5 if x.adx >= 20 else 0)
    q += 15 if x.rs > .10 else 8 if x.rs > 0 else 0
    q += (10 if x.Volume >= 1.5 * x.vavg else 0) if kind == "Breakout" else (5 if x.Volume <= x.vavg else 0)
    q += 10 if 40 <= x.rsi <= 65 else 0
    R = float(x.entry - x.stop); room = (x.hh60 - x.entry) / R if R > 0 else 0
    q += 10 if (x.hh60 <= x.entry or room >= 2) else 0
    q += 10 if regime_ok else 0
    q += 5 if x.turn >= 5e7 else 0
    if st["n"] >= 5: q += 15 if st["avg"] >= .5 else 10 if st["avg"] >= .2 else 5 if st["avg"] >= 0 else -10
    if kind == "Breakout" and nifty_rsi > 75: q -= 10
    if not in_zone: q -= 10
    return max(0, min(100, int(q)))

def tier(q): return "A" if q >= 75 else "B" if q >= 60 else "C"

# ---------- long-term leaders ----------
def leaders(data, nifty, sectors):
    rows = []
    for t, df in data.items():
        x = df.iloc[-1]; c = df.Close
        if len(c) < 252 or not (x.Close > x.e200 and x.e50 > x.e200) or x.turn < 2e7: continue
        r12 = float(c.iloc[-1] / c.iloc[-252] - 1); r6 = float(c.iloc[-1] / c.iloc[-126] - 1)
        n6 = float(nifty.Close.iloc[-1] / nifty.Close.iloc[-126] - 1); near = float(x.Close / x.h52)
        if near < .80: continue
        rows.append(dict(t=t, price=float(x.Close), r12=r12, rs6=r6 - n6, near=near, e200=float(x.e200), e50=float(x.e50), sector=sectors.get(t, "")))
    if not rows: return []
    d = pd.DataFrame(rows); d["score"] = .4 * d.r12.rank(pct=True) + .3 * d.rs6.rank(pct=True) + .3 * d.near.rank(pct=True)
    top = d.sort_values("score", ascending=False).head(10).to_dict("records")
    for p in top:
        try:
            import yfinance as yf
            i = yf.Ticker(p["t"] + ".NS").info
            p["roe"] = i.get("returnOnEquity"); p["gr"] = i.get("revenueGrowth"); p["de"] = i.get("debtToEquity")
        except Exception:
            p["roe"] = p["gr"] = p["de"] = None
    return top

def next_day(d):
    d = pd.to_datetime(d).date() + dt.timedelta(days=1)
    while d.weekday() >= 5: d += dt.timedelta(days=1)
    return d

EXTRA = """a{color:var(--blue)}.tA{color:var(--up);font-weight:700}.tB{color:var(--amber);font-weight:700}.tC{color:var(--mut);font-weight:700}
.nav{font-size:13px;margin:4px 0}table.s td,table.s th{font-size:12.5px}"""

def fmt(v, p=1): return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.{p}f}"
def pctf(v): return "-" if v is None else f"{v*100:.0f}%"

def main():
    live_hist = m.hist
    nifty = live_hist("^NSEI"); nifty = prepare(nifty, nifty.Close); signals(nifty)
    nx = nifty.iloc[-1]; regime_ok = int(nx.trend) >= 0 and bool(nx.Close > nx.e50)
    block = int(nx.trend) <= -1
    data, sec = {}, dict(m.SECTOR_OF)
    for t in m.UNIVERSE:
        try:
            df = live_hist(t + ".NS")
            if len(df) < 260: continue
            px = float(df.Close.iloc[-1])
            if not (m.MIN_PRICE <= px <= m.MAX_PRICE): continue
            data[t] = signals(prepare(df, nifty.Close))
        except Exception:
            continue
    allres, cands, sells = {"Pullback": [], "Breakout": []}, [], []
    for t, df in data.items():
        x = df.iloc[-1]; bt = {"Pullback": backtest(df, df.pull), "Breakout": backtest(df, df.brk)}
        for k in bt: allres[k] += bt[k]
        kind, status = None, "IN ZONE"
        pb_hi = float(x.e20 + .25 * x.atr)
        if bool(x.brk): kind = "Breakout"
        elif bool(x.pull): kind = "Pullback"
        elif int(x.trend) >= 1 and pb_hi < x.Close <= pb_hi + 2 * x.atr and x.rsi < 70:
            kind, status = "Pullback", "Approaching: limit buy at top of zone"
        elif int(x.trend) >= 1 and 0 < (x.hh20 - x.Close) / x.Close <= .03 and x.rsi < 70:
            kind, status = "Breakout", "Approaching: buy only above trigger"
        if bool(x.sell) and len(sells) < 40: sells.append((t, x))
        if not kind or block: continue
        in_zone = status == "IN ZONE"; st = stats(bt[kind]); xx = x.copy()
        if status.startswith("Approaching: limit"):
            xx["entry"] = pb_hi; xx["z_lo"], xx["z_hi"] = x.e50, pb_hi
            s0 = min(x.sl10, x.e50) - .25 * x.atr; xx["stop"] = pb_hi - x.atr if pb_hi - s0 < x.atr else s0
        elif status.startswith("Approaching: buy only"):
            xx["entry"] = x.hh20; xx["z_lo"], xx["z_hi"] = x.hh20, x.hh20 + .5 * x.atr
            s0 = min(x.sl10, x.hh20 - x.atr) - .25 * x.atr; xx["stop"] = x.hh20 - x.atr if x.hh20 - s0 < x.atr else s0
        R = float(xx.entry - xx.stop)
        if R <= 0 or R > 4 * x.atr or x.turn < 2e7 or (st["n"] >= 8 and st["avg"] < -.1): continue
        q = quality(xx, st, kind, regime_ok, float(nx.rsi), in_zone)
        if q < MIN_Q: continue
        qty = int(min(CAPITAL * RISK_PCT / 100 / R, CAPITAL * MAX_POS_PCT / 100 / xx.entry))
        cands.append(dict(t=t, kind=kind, in_zone=in_zone, status=status, q=q, tier=tier(q), trend=TREND[int(x.trend)], price=float(x.Close), lo=float(xx.z_lo), hi=float(xx.z_hi),
                          entry=float(xx.entry), stop=float(xx.stop), t1=float(xx.entry + 2 * R), t2=float(xx.entry + 3 * R), risk_pct=100 * R / float(xx.entry),
                          qty=qty, cost=qty * float(xx.entry), st=st, sector=sec.get(t, "")))
    cands.sort(key=lambda p: (not p["in_zone"], -p["q"])); top = cands[:TOP_N]
    pooled = allres["Pullback"] + allres["Breakout"]; ps = stats(pooled)
    order = sorted(pooled, key=lambda x: x[0]); cum = np.cumsum([x[2] for x in order]) if order else np.array([0.0])
    lead = leaders(data, nifty, sec); sv = study(data)
    pick = max((v for v in sv if v[1]["n"] >= 20), key=lambda v: v[1]["avg"], default=None)
    cell = lambda t: f'{t["n"]} / {t["avg"]:+.2f}R / PF {t["pf"]:.1f}'
    srows = "".join(f'<tr><td>{n}{" (chosen on first half)" if pick and n == pick[0] else ""}</td><td>{cell(a1)}</td><td>{cell(a2)}</td></tr>' for n, a1, a2 in sv)
    edge = bool(pick and pick[1]["avg"] > 0 and pick[2]["avg"] > 0)
    study_msg = ("The chosen exit style was profitable in both halves. That is encouraging but still needs paper trading to confirm." if edge else "No exit style was profitable in both halves of the year. That means the rules show no proven edge yet, so stay on paper trading and do not risk real money.")

    adv = sum(int(d.iloc[-1].trend) >= 1 for d in data.values()); N = max(len(data), 1)
    verdict = ("New BUY signals are paused: Nifty is in a downtrend." if block else
               "Caution: Nifty RSI is stretched, so breakout scores are reduced." if nx.rsi > 75 else
               "Market trend supports swing buying, but keep size small." if regime_ok else "Nifty trend is weak. Be selective.")
    tiles = (f'<div class="tile"><div class="k">Nifty trend</div><div class="v">{TREND[int(nx.trend)]}</div><div class="s">close {nx.Close:,.0f}, RSI {nx.rsi:.0f}, ADX {nx.adx:.0f}</div></div>'
             f'<div class="tile"><div class="k">Stocks in uptrend</div><div class="v">{100*adv/N:.0f}%</div><div class="s">{adv} of {N} scanned</div></div>'
             f'<div class="tile"><div class="k">Trades passing filters</div><div class="v">{len(cands)}</div><div class="s">{sum(p["in_zone"] for p in cands)} in zone now</div></div>'
             f'<div class="tile"><div class="k">1-year system test</div><div class="v">{ps["n"]} trades</div><div class="s">win {ps["win"]:.0f}%, avg {ps["avg"]:+.2f}R, PF {ps["pf"]:.1f}</div></div>')
    tiers = {t: sum(p["tier"] == t for p in top) for t in "ABC"}
    d1 = m.donut("Quality tiers", [("A (75+)", tiers["A"]), ("B (60-74)", tiers["B"]), ("C (50-59, watch)", tiers["C"])])
    sc = {}
    for p in top: sc[p["sector"] or "Other"] = sc.get(p["sector"] or "Other", 0) + 1
    d2 = m.donut("Sector mix of the list", sorted(sc.items(), key=lambda x: -x[1]))
    eq = m.line_chart([("Cumulative R (all signals, last year)", cum, "c1")], fmt="{:.0f}R")
    byk = "".join(f'<tr><td>{k}</td><td>{s["n"]}</td><td>{s["win"]:.0f}%</td><td>{s["avg"]:+.2f}R</td><td>{s["pf"]:.1f}</td><td>{s["dd"]:.1f}R</td></tr>'
                  for k, s in ((k, stats(v)) for k, v in allres.items()))

    rows = ""
    for i, p in enumerate(top, 1):
        s = p["st"]; rec = f'{s["n"]} / {s["win"]:.0f}% / {s["avg"]:+.2f}R' if s["n"] >= 3 else f'{s["n"]} (too few)'
        rows += (f'<tr><td>{i}. {html.escape(p["t"])}</td><td>{p["trend"]}</td><td>{p["kind"]}</td><td class="t{p["tier"]}">{p["q"]} ({p["tier"]})</td><td>{p["price"]:,.1f}</td>'
                 f'<td>{p["lo"]:,.1f} - {p["hi"]:,.1f}</td><td>{p["stop"]:,.1f}</td><td>{p["t1"]:,.1f} - {p["t2"]:,.1f}</td><td>{p["risk_pct"]:.1f}%</td>'
                 f'<td>{p["qty"]}</td><td>{p["cost"]:,.0f}</td><td>{rec}</td><td>{html.escape(p["status"])}</td></tr>')
    rows = rows or '<tr><td colspan=14>No trades pass the filters today. Doing nothing is a valid position.</td></tr>'
    srow = "".join(f'<tr><td>{html.escape(t)}</td><td>{TREND[int(x.trend)]}</td><td>{x.Close:,.1f}</td><td>{"below 20d low on volume" if x.Close < x.ll20 else "downtrend, below EMA20"}</td><td>{x.e20:,.1f}</td></tr>'
                   for t, x in sells[:15]) or "<tr><td colspan=5>None today.</td></tr>"
    lrow = "".join(f'<tr><td>{html.escape(p["t"])}</td><td>{html.escape(p["sector"])}</td><td>{p["price"]:,.1f}</td><td class="up">{p["r12"]*100:+.0f}%</td><td>{p["rs6"]*100:+.0f}%</td>'
                   f'<td>{(1-p["near"])*100:.0f}%</td><td>{pctf(p["roe"])} / {pctf(p["gr"])} / {fmt(p["de"],0)}</td><td>{p["e50"]:,.1f}</td><td>{p["e200"]:,.1f} ({(p["e200"]/p["price"]-1)*100:.0f}%)</td></tr>' for p in lead) \
           or "<tr><td colspan=9>No stocks pass the long-term screen today.</td></tr>"
    day = next_day(nifty.index[-1].date()); now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    live = ("<h2>Live status of the list</h2><p class=n id=lt>Loading...</p><p class=n>Prices come from Yahoo (delayed up to 15 minutes) and refresh about every 15 minutes in market hours. "
            "This page re-reads them every minute. Status compares price with each buy zone, stop and target.</p>"
            '<div class=tw><table class=s id=lv><tr><th>Stock<th>Price<th>Status<th>Buy zone<th>Stop<th>T1</tr></table></div>'
            "<script>async function L(){try{const r=await fetch('live.json?'+Date.now());const d=await r.json();"
            "document.getElementById('lt').textContent='Updated '+d.updated;const t=document.getElementById('lv');"
            "while(t.rows.length>1)t.deleteRow(1);for(const p of d.rows){const w=t.insertRow();"
            "[p.sym,p.price.toFixed(1),p.status,p.zone,p.stop.toFixed(1),p.t1.toFixed(1)].forEach(v=>{w.insertCell().textContent=v})}}"
            "catch(e){document.getElementById('lt').textContent='No live data yet. It starts when the live job runs in market hours.'}}L();setInterval(L,60000)</script>")
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>India Signals Pro</title>
<link rel=manifest href=manifest.json><meta name=theme-color content="#0d1117"><style>{m.CSS}{EXTRA}</style></head><body>
<h1>India Signals Pro - {now:%d %b %Y %H:%M} IST</h1><div class=nav><a href="index.html">Short-term page</a></div>
<div class=warn>Research and practice only, not financial advice. No system can promise profit. Paper-trade first and always use the stop.</div>
<div class=warn>{verdict}</div><div class=grid3>{tiles}</div>
<h2>Swing trades: top {len(top)} for {day:%a %d %b %Y}</h2>
<p class=n>Hold up to about 1 month. In-zone trades first, then ones approaching the zone. Buy zone is set from the 20 and 50 day averages (pullbacks) or the 20-day high (breakouts). Stop sits below the recent swing low with an ATR buffer. T1 = 2R, T2 = 3R, where R is your stop distance. Tier A is 75+, B is 60-74, C is watch only. If fewer than {TOP_N} pass the filters, that is by design, since padding the list with weak trades would hurt.</p>
<div class=tw><table class=s><tr><th>Stock<th>Trend<th>Signal<th>Quality<th>Price<th>Buy range<th>Stop (exit below)<th>Sell range (T1 - T2)<th>Risk %<th>Qty<th>Cost Rs<th>1y record: trades / win / avg R<th>Status</tr>{rows}</table></div>
<h2>How the same rules did over the last year</h2><p class=n>Every signal the rules would have given in the last 250 trading days, filled at the next open, stop first on ties, exit at T1 (2R) or after {HOLD_DAYS} days, with {COST_PCT}% costs. The stock list was chosen from recent strength, so this looks better than live results are likely to be.</p>
<div class=dgrid>{d1}{d2}</div>
<div class=tw><table class=s><tr><th>Signal<th>Trades<th>Win rate<th>Avg R<th>Profit factor<th>Max drawdown</tr>{byk}</table></div>{eq}
<h2>Which exit style worked best? (walk-forward test)</h2><p class=n>Each exit style was tested on the first half of the last year, then on the second half. A style that wins in both halves is more believable than one that only looks good on the period it was tuned on. Columns show trades / average R / profit factor.</p><div class=tw><table class=s><tr><th>Exit style<th>First half<th>Second half</tr>{srows}</table></div><p>{study_msg}</p><h2>SELL / avoid list</h2><p class=n>Stocks in a downtrend or breaking down on volume. If you hold one, consider exiting or trailing your stop. In India, short selling for delivery is not allowed; shorting is only intraday or in F&amp;O, which carries high risk.</p>
<div class=tw><table class=s><tr><th>Stock<th>Trend<th>Price<th>Reason<th>EMA20</tr>{srow}</table></div>
<h2>Long-term leaders (multibagger watch)</h2><p class=n>Stocks in long-term uptrends (above the 200-day average, near 52-week highs, strongest 12-month and 6-month moves). Nobody can pick multibaggers in advance, so this is a shortlist to research, not a promise. Fundamentals (ROE / revenue growth / debt-to-equity) show only if Yahoo provides them. Plan: buy in three parts (now, on a dip to the 50-day, near the 200-day), and review if it closes below the 200-day. Only from your scanned list.</p>
<div class=tw><table class=s><tr><th>Stock<th>Sector<th>Price<th>12m return<th>vs Nifty (6m)<th>Below 52w high<th>ROE / Rev growth / D/E<th>EMA50<th>EMA200 (distance)</tr>{lrow}</table></div>
{live}<p class=n>Data: NSE and Yahoo Finance, free and may be delayed or wrong. Check your broker before acting.</p></body></html>"""
    os.makedirs("docs", exist_ok=True); open("docs/pro.html", "w", encoding="utf-8").write(page)
    json.dump([dict(sym=p["t"], lo=round(p["lo"], 2), hi=round(p["hi"], 2), stop=round(p["stop"], 2), t1=round(p["t1"], 2), t2=round(p["t2"], 2),
                    qty=p["qty"], q=p["q"], kind=p["kind"]) for p in top], open("docs/pro.json", "w"), indent=1)
    try:
        idx = open("docs/index.html", encoding="utf-8").read()
        if "pro.html" not in idx and "</h1>" in idx:
            open("docs/index.html", "w", encoding="utf-8").write(idx.replace("</h1>", '</h1><p><a href="pro.html">Open the Pro page: swing trades, SELL list, long-term leaders, live status</a></p>', 1))
    except Exception: pass
    print("Pro page:", len(top), "trades,", len(lead), "leaders,", len(sells), "sells, 1y trades", ps["n"])

if __name__ == "__main__":
    main()
