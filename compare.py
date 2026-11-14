#!/usr/bin/env python3
"""Strategy scoreboard: swing signals vs holding Nifty vs holding the whole list vs monthly momentum picks.
Adds a section to docs/pro.html. Research only, not financial advice. No orders are placed."""
import html, json, os
import numpy as np, pandas as pd
import india_market_brief as m
import pro_engine as pe

N_DAYS, REB, TOP, LOOK, SKIP = 250, 21, 10, 126, 21
COST, RISK, MAXPOS = 0.003, 0.01, 3

def swing_trades(df, sig, k=2.0, H=20):
    """Same swing rules as the Pro page. Returns (fill_time, exit_time, r_multiple)."""
    out, last, a = [], -1, len(df) - N_DAYS
    hi, lo, op, cl = df.High.values, df.Low.values, df.Open.values, df.Close.values
    for i in np.where(sig.values)[0]:
        if i < a or i <= last or i + 1 >= len(df): continue
        e, s = float(df.entry.iloc[i]), float(df.stop.iloc[i]); R = e - s
        if R <= 0 or np.isnan(R): continue
        t1 = e + k * R; fill = op[i + 1]
        if fill <= s or fill >= t1: continue
        res = None
        for j in range(i + 1, min(i + 1 + H, len(df))):
            if lo[j] <= s: res = (min(s, op[j]) if j > i + 1 else s, j); break
            if hi[j] >= t1: res = (t1, j); break
        if res is None:
            if i + H >= len(df): continue
            res = (cl[i + H], i + H)
        out.append((df.index[i + 1], df.index[res[1]], (res[0] - fill) / R - pe.COST_PCT / 100 * fill / R)); last = res[1]
    return out

def swing_curve(trades, idx):
    """Take trades in time order with at most MAXPOS open at once, risking 1% of capital each."""
    trades.sort(key=lambda x: x[0]); open_exits, pnl, taken = [], np.zeros(len(idx)), 0
    for f, e, r in trades:
        open_exits = [x for x in open_exits if x > f]
        if len(open_exits) < MAXPOS:
            open_exits.append(e); taken += 1; p = idx.searchsorted(e)
            if p < len(idx): pnl[p] += r * RISK
    return 100 * np.cumprod(1 + pnl[-N_DAYS:]), taken

def momentum(closes, nclose, n200):
    """Every REB days hold the TOP names by 6-month momentum (skipping the latest month), equal weight. Cash if Nifty is below its 200-day."""
    L = len(closes); start = L - N_DAYS; eq = np.ones(L); prev = []; cur = 100.0; t = start
    while t < L - 1:
        t2 = min(t + REB, L - 1)
        mom = (closes.iloc[t - SKIP] / closes.iloc[t - LOOK] - 1).dropna()
        picks = [] if nclose.iloc[t] < n200.iloc[t] else list(mom.sort_values(ascending=False).head(TOP).index)
        turn = 1 - len(set(picks) & set(prev)) / TOP if picks else (1.0 if prev else 0.0)
        cur *= 1 - COST * turn; prev = picks
        if picks:
            path = (closes.iloc[t:t2 + 1][picks] / closes.iloc[t][picks]).mean(axis=1).values
        else: path = np.ones(t2 - t + 1)
        eq[t:t2 + 1] = cur * path; cur = eq[t2]; t = t2
    return eq[start:] / eq[start] * 100

def stat(eq):
    peak = np.maximum.accumulate(eq); return eq[-1] / eq[0] - 1, float(((peak - eq) / peak).max())

def main():
    nifty = m.hist("^NSEI"); nifty = pe.prepare(nifty, nifty.Close); idx = nifty.index
    data, trades = {}, []
    for t in m.UNIVERSE:
        try:
            df = m.hist(t + ".NS")
            if len(df) < LOOK + N_DAYS + 5: continue
            if not (m.MIN_PRICE <= float(df.Close.iloc[-1]) <= m.MAX_PRICE): continue
            df = pe.signals(pe.prepare(df, nifty.Close)); data[t] = df
            trades += swing_trades(df, df.pull | df.brk)
        except Exception:
            continue
    if len(data) < 15: print("Too few stocks for the scoreboard"); return
    closes = pd.DataFrame({t: d.Close for t, d in data.items()}).reindex(idx).ffill()
    nc, n200 = nifty.Close, nifty.e200
    series = {"Nifty buy and hold": 100 * nc.values[-N_DAYS:] / nc.values[-N_DAYS],
              "Hold the whole list": 100 * (closes.iloc[-N_DAYS:] / closes.iloc[-N_DAYS]).mean(axis=1).values}
    series["Monthly momentum picks"] = momentum(closes, nc, n200)
    sw, taken = swing_curve(trades, idx); series["Swing signals (max 3 open)"] = sw
    res = {k: stat(v) for k, v in series.items()}; best = max(res, key=lambda k: res[k][0])
    rows = "".join(f'<tr><td>{k}</td><td class="{"up" if r[0] >= 0 else "dn"}">{r[0]*100:+.1f}%</td><td>{r[1]*100:.0f}%</td></tr>' for k, r in res.items())
    sw_ret, n_ret = res["Swing signals (max 3 open)"][0], res["Nifty buy and hold"][0]
    verdict = (f"Best over the last year: {best} ({res[best][0]*100:+.1f}%). " +
               ("The swing signals beat simply holding Nifty in this test." if sw_ret > n_ret else
                "The swing signals did NOT beat simply holding Nifty. If that stays true, the simplest plan is the better one."))
    chart = m.line_chart([(k, v, c) for (k, v), c in zip(series.items(), ("c1", "c2", "c3", "c1"))][:3], fmt="{:.0f}")
    chart2 = m.line_chart([("Swing signals (max 3 open)", sw, "c1"), ("Nifty", series["Nifty buy and hold"], "c2")], fmt="{:.0f}")
    lastmom = (closes.iloc[-1 - SKIP] / closes.iloc[-1 - LOOK] - 1).dropna().sort_values(ascending=False).head(TOP)
    on = bool(nc.iloc[-1] > n200.iloc[-1]); amt = m.CAPITAL / TOP
    json.dump(dict(date=str(idx[-1].date()), on=on, nifty=float(nc.iloc[-1]), rsi=float(nifty.rsi.iloc[-1]), trend=pe.TREND[int(nifty.trend.iloc[-1])],
                   picks=[dict(sym=t, price=float(closes[t].iloc[-1]), mom=float(v)) for t, v in lastmom.items()]), open("docs/momentum.json", "w"))
    prow = "".join(f'<tr><td>{html.escape(t)}</td><td>{closes[t].iloc[-1]:,.1f}</td><td>{v*100:+.0f}%</td><td>{int(amt // closes[t].iloc[-1])}</td></tr>' for t, v in lastmom.items())
    sec = ('<h2>Strategy scoreboard: which approach actually did best?</h2>'
           '<p class=n>Same stocks, same last year, costs included. The list was chosen from recent strength, so "hold the list" and momentum look better than real life. '
           'One year is also only one market mood. Use this to compare ideas, not as proof.</p>'
           f'<div class=warn>{verdict}</div><div class=tw><table class=s><tr><th>Approach<th>1-year return<th>Worst drop</tr>{rows}</table></div>'
           f'<p class=n>Lines: Nifty, the whole list, monthly momentum (first three lines). Swing signals took {taken} trades, risking 1% each with at most {MAXPOS} open.</p>{chart}{chart2}'
           f'<h2>Simple option: monthly momentum picks</h2><p class=n>Once a month, hold the {TOP} strongest names in equal parts ({"invest: Nifty is above its 200-day average" if on else "stay in cash: Nifty is below its 200-day average"}). '
           f'No daily watching. Quantities below assume Rs {amt:,.0f} per stock. It can still lose money, and stocks can fall sharply together.</p>'
           f'<div class=tw><table class=s><tr><th>Stock<th>Price<th>6m momentum<th>Qty for equal part</tr>{prow}</table></div>')
    path = "docs/pro.html"; page = open(path, encoding="utf-8").read()
    mk = "<h2>Which exit style worked best?" if "<h2>Which exit style worked best?" in page else "<h2>SELL / avoid list</h2>"
    if mk in page and "Strategy scoreboard" not in page:
        open(path, "w", encoding="utf-8").write(page.replace(mk, sec + mk, 1))
    print("Scoreboard:", {k: f"{r[0]*100:+.1f}%" for k, r in res.items()}, "| best:", best)

if __name__ == "__main__":
    main()
