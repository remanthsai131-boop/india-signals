#!/usr/bin/env python3
"""Simple home page + forward tracker of the monthly momentum picks. Research only, not financial advice."""
import datetime as dt, html, json, os, shutil
import numpy as np, pandas as pd
import india_market_brief as m

FWD, JNL, COST = "journal/forward_picks.csv", "journal/paper_trades.csv", 0.003

def jload(p, default=None):
    try: return json.load(open(p))
    except Exception: return default

def price(sym):
    try:
        h = m.hist(sym, "5d"); return float(h.Close.iloc[-1]) if len(h) else None
    except Exception: return None

def forward(mom):
    cols = ["month", "date", "symbol", "entry", "nifty"]
    try: f = pd.read_csv(FWD)
    except Exception: f = pd.DataFrame(columns=cols)
    if mom:
        month = mom["date"][:7]
        if month not in set(f.month.astype(str)):
            if mom["on"] and mom["picks"]:
                for p in mom["picks"]: f.loc[len(f)] = [month, mom["date"], p["sym"], round(p["price"], 2), round(mom["nifty"], 2)]
            else: f.loc[len(f)] = [month, mom["date"], "CASH", 0, round(mom["nifty"], 2)]
            os.makedirs("journal", exist_ok=True); f.to_csv(FWD, index=False)
    nnow = price("^NSEI"); out, cache = [], {}
    for month, g in f.groupby("month", sort=True):
        nr = (nnow / float(g.nifty.iloc[0]) - 1) if nnow else None
        if (g.symbol == "CASH").all(): out.append((month, 0, 0.0, nr)); continue
        rets = []
        for s, e in zip(g.symbol, g.entry):
            if s == "CASH" or e <= 0: continue
            if s not in cache: cache[s] = price(s + ".NS")
            if cache[s]: rets.append(cache[s] / e - 1)
        out.append((month, len(rets), (float(np.mean(rets)) - COST) if rets else None, nr))
    return out

def bars(rows, w=700):
    rows = [r for r in rows if r[2] is not None and r[3] is not None][-12:]
    if not rows: return ""
    vals = [v for r in rows for v in (r[2], r[3])]; lo, hi = min(0, min(vals)), max(0, max(vals)); span = (hi - lo) or 1
    h, top, bot = 210, 22, 28; Y = lambda v: top + (h - top - bot) * (hi - v) / span; bw = w / len(rows)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch"><line x1="0" x2="{w}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="grid"/>']
    for i, (mo, n, a, b) in enumerate(rows):
        for k, (v, cls) in enumerate(((a, "bp"), (b, "bn"))):
            x = i * bw + bw * (.12 + .4 * k); y0, y1 = Y(0), Y(v)
            o.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{bw*.36:.1f}" height="{max(abs(y1 - y0), 1):.1f}" class="{cls}"/>'
                     f'<text x="{x + bw*.18:.1f}" y="{min(y0, y1) - 4:.1f}" text-anchor="middle" class="val">{v*100:+.0f}%</text>')
        o.append(f'<text x="{i*bw + bw/2:.1f}" y="{h-8}" text-anchor="middle" class="lab">{mo}</text>')
    o.append("</svg>"); return "".join(o)

def market(mom):
    if not mom: return "", "Market data is not ready yet. It appears after the next full run."
    t, r = mom["trend"], mom["rsi"]
    mood = ("Very hot. Pullbacks are common, so be extra careful and use small size." if r > 75 else
            "Very weak. Wait for signs of recovery." if r < 30 else "Normal range.")
    safe = ("Do not open new buys. The market is falling." if t in ("Down", "Strong down") else
            "Be selective. There is no clear uptrend." if t == "Sideways" else "Practice buying only on dips, with small size.")
    tiles = (f'<div class="t"><div class="k">Nifty 50</div><div class="v">{mom["nifty"]:,.0f}</div></div>'
             f'<div class="t"><div class="k">Trend</div><div class="v">{t}</div></div>'
             f'<div class="t"><div class="k">Heat (RSI)</div><div class="v">{r:.0f}</div></div>')
    return tiles, f"{mood} {safe}"

def cards():
    rows = (jload("docs/pro.json", []) or [])[:3]; out = ""
    for r in rows:
        px = price(r["sym"] + ".NS")
        if px is None: st, cls = "Check the live price first", "amb"
        elif px <= r["stop"]: st, cls = "Skip: price is already at the stop", "red"
        elif r["lo"] <= px <= r["hi"]: st, cls = "In buy range now", "grn"
        elif px > r["hi"]: st, cls = "Wait: price is above the range. Do not chase", "amb"
        else: st, cls = "Wait: price is below the range", "amb"
        tier = "A" if r["q"] >= 75 else "B" if r["q"] >= 60 else "C (weak, watch only)"
        why = "a dip in an uptrend" if r["kind"] == "Pullback" else "breaking above a recent high with strong volume"
        risk = r["qty"] * (r["hi"] - r["stop"])
        out += (f'<div class="card"><div class="row"><b>{html.escape(r["sym"])}</b><span class="chip {cls}">{st}</span></div>'
                f'<div class="m">Idea: {why}. Strength: {tier}</div>'
                f'<div class="big">Buy between <b>{r["lo"]:,.1f}</b> and <b>{r["hi"]:,.1f}</b></div>'
                f'<div class="big">Sell for profit around <b>{r["t1"]:,.1f}</b> to <b>{r["t2"]:,.1f}</b></div>'
                f'<div class="big">Get out if it falls to <b>{r["stop"]:,.1f}</b></div>'
                f'<div class="m">Shares: {r["qty"]} (a loss at the stop is about Rs {risk:,.0f})</div></div>')
    return out or '<div class="card">No good ideas today. Doing nothing is a good decision.</div>'

def results():
    try: j = pd.read_csv(JNL)
    except Exception: return '<div class="card">No practice trades yet. They appear after the next signals.</div>'
    d = j[j.status.isin(["target", "stop", "expired"])]; n = len(d)
    if not n: return f'<div class="card">{(j.status == "open").sum()} practice trades are open. Results appear when they finish.</div>'
    pnl, r = d.pnl.astype(float), d.r.astype(float)
    tiles = (f'<div class="t"><div class="k">Finished trades</div><div class="v">{n}</div></div>'
             f'<div class="t"><div class="k">Winners</div><div class="v">{100*(pnl > 0).mean():.0f}%</div></div>'
             f'<div class="t"><div class="k">Average result</div><div class="v">{r.mean():+.2f}R</div></div>'
             f'<div class="t"><div class="k">Practice profit</div><div class="v {"up" if pnl.sum() >= 0 else "dn"}">Rs {pnl.sum():,.0f}</div></div>')
    note = "Wait until you have 100 finished trades before judging." if n < 100 else ("The average is positive. Keep testing." if r.mean() > 0 else "The average is negative. Do not use real money.")
    return f'<div class="grid">{tiles}</div><p class="m">{note}</p>'

LEARN = [("Buy range", "The price area where an idea makes sense. If the price is above it, you would be chasing, so wait."),
         ("Stop (get out below)", "The price where you leave if you were wrong. Decide it before you buy, so a loss stays small and planned."),
         ("Sell range", "Where you take profit. The first level is twice your risk and the second is three times."),
         ("Risk per trade", "Never risk more than 1% of your money on one idea. On Rs 1 lakh, that is Rs 1,000."),
         ("R", "One R is what you risk on a trade. Winning 2R means winning twice what you risked."),
         ("Practice (paper) trading", "Trade with pretend money until your record proves the idea works. Real money only after that."),
         ("Why most traders lose", "Costs, emotions and random noise. Even good ideas lose about half the time, so winners must be bigger than losers."),
         ("Trend", "Price above its 50 and 200 day averages means an uptrend. Buy dips in uptrends and avoid falling markets.")]

CSS = """:root{--bg:#fff;--fg:#111827;--mut:#6b7280;--card:#f3f4f6;--line:#d1d5db;--up:#16a34a;--dn:#dc2626;--blue:#2563eb;--amb:#d97706}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--card:#161b22;--line:#30363d;--up:#3fb950;--dn:#f85149;--blue:#58a6ff;--amb:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.5 system-ui,sans-serif;padding:16px;max-width:720px;margin:auto}
h1{font-size:24px;margin:8px 0}h2{font-size:19px;margin:28px 0 8px}.m{color:var(--mut);font-size:14px}.up{color:var(--up)}.dn{color:var(--dn)}
.warn{border:1px solid var(--dn);border-radius:12px;padding:10px 12px;font-size:14px;margin:10px 0}.say{background:var(--card);border-radius:12px;padding:12px;margin:10px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.t,.card{background:var(--card);border-radius:12px;padding:12px;margin:6px 0}
.t .k{color:var(--mut);font-size:13px}.t .v{font-size:22px;font-weight:700}.row{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:20px}
.big{margin-top:6px}.chip{font-size:12px;padding:3px 8px;border-radius:999px;background:var(--line)}.grn{background:var(--up);color:#fff}.amb{background:var(--amb);color:#fff}.red{background:var(--dn);color:#fff}
.ch{width:100%;height:auto}.grid line,.grid{stroke:var(--line)}.bp{fill:var(--blue)}.bn{fill:var(--mut)}.val{fill:var(--fg);font-size:12px}.lab{fill:var(--mut);font-size:12px}
details{background:var(--card);border-radius:12px;padding:10px 12px;margin:6px 0}summary{font-weight:600;cursor:pointer}a{color:var(--blue)}ol{padding-left:22px}table{width:100%;border-collapse:collapse;font-size:15px}td,th{padding:6px;border-bottom:1px solid var(--line);text-align:right}td:first-child,th:first-child{text-align:left}"""

def main():
    mom = jload("docs/momentum.json"); fw = forward(mom); tiles, say = market(mom)
    done = [r for r in fw if r[2] is not None and r[3] is not None]; beat = sum(r[2] > r[3] for r in done)
    frows = "".join(f'<tr><td>{mo}</td><td>{n or "cash"}</td><td>{"-" if a is None else f"{a*100:+.1f}%"}</td><td>{"-" if b is None else f"{b*100:+.1f}%"}</td></tr>' for mo, n, a, b in fw)
    ftxt = (f"So far the monthly picks beat Nifty in {beat} of {len(done)} months. Judge after at least 6 months." if done else
            "The first month is recorded. Results appear as the days pass.")
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    learn = "".join(f"<details><summary>{a}</summary><p>{b}</p></details>" for a, b in LEARN)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>My Trading Dashboard</title>
<link rel=manifest href=manifest.json><meta name=theme-color content="#0d1117"><link rel=apple-touch-icon href=icon-180.png><style>{CSS}</style></head><body><!--home-->
<h1>My Trading Dashboard</h1><div class="m">Updated {now:%d %b %Y, %H:%M} IST</div>
<div class="warn">Practice mode. Paper trading only. This is research, not financial advice, and no system can promise profit.</div>
<h2>1. How is the market?</h2><div class="grid">{tiles}</div><div class="say">{say}</div>
<h2>2. Today's practice ideas</h2><p class="m">At most 3. Pick the ones you understand, and always use the stop.</p>{cards()}
<h2>3. My practice results</h2>{results()}
<h2>4. Monthly picks vs Nifty (a fair test)</h2><p class="m">Each month the 10 strongest stocks are recorded and tracked. Blue = picks, grey = Nifty.</p>{bars(fw)}
<div class="tw"><table><tr><th>Month<th>Stocks<th>Picks<th>Nifty</tr>{frows or "<tr><td colspan=4>Starting now</td></tr>"}</table></div><p class="m">{ftxt}</p>
<h2>5. Learn in 2 minutes</h2>{learn}
<h2>6. My 10-minute routine</h2><ol><li>Read the market mood above.</li><li>Look at today's ideas. Choose at most 3.</li><li>Write down why you chose each one.</li><li>Place practice orders with the stop.</li><li>On Sunday, check section 3 and 4.</li></ol>
<h2>More details</h2><p><a href="detail.html">Short-term plan and charts</a> | <a href="pro.html">Pro page and live status</a></p></body></html>"""
    src = "docs/index.html"
    try: old = open(src, encoding="utf-8").read()
    except Exception: old = ""
    if old and "<!--home-->" not in old:
        old = old.replace("</h1>", '</h1><p><a href="index.html">Back to Home</a></p>', 1); open("docs/detail.html", "w", encoding="utf-8").write(old)
    open(src, "w", encoding="utf-8").write(page)
    try:
        pro = open("docs/pro.html", encoding="utf-8").read()
        pro = pro.replace('<a href="index.html">Short-term page</a>', '<a href="index.html">Home</a> | <a href="detail.html">Short-term details</a>')
        open("docs/pro.html", "w", encoding="utf-8").write(pro)
    except Exception: pass
    print("Home page written. Forward batches:", len(fw))

if __name__ == "__main__":
    main()

