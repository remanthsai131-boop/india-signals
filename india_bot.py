#!/usr/bin/env python3
"""India Signals bot: dashboard + Tomorrow's Trade Plan + paper-trade journal + optional Telegram.
Research only, not financial advice. No real orders are ever placed."""
import datetime as dt, html, json, os
import numpy as np, pandas as pd, requests
import india_market_brief as m
import india_tm as tm

JOURNAL = "journal/paper_trades.csv"
COLS = ["signal_date", "symbol", "setup", "entry", "stop", "target", "qty", "status", "fill", "exit", "exit_date", "pnl", "r"]
_prev = tm.pick_with_sim

def pick_more(t, df):
    p = _prev(t, df)
    if p: p["date"] = str(df.index[-1].date())
    return p
tm.pick_with_sim = pick_more

# ---------- paper-trade journal ----------
def load():
    try: return pd.read_csv(JOURNAL)
    except Exception: return pd.DataFrame(columns=COLS)

def settle(row, bars):
    """Fill at next open. Stop wins a tie. Gaps past stop/target are skipped. Max 5 days."""
    fill = float(bars.Open.iloc[0]); stop, tgt = float(row.stop), float(row.target)
    if fill <= stop or fill >= tgt: return "skipped", fill, fill, bars.index[0]
    for i in range(min(len(bars), 5)):
        if bars.Low.iloc[i] <= stop: return "stop", fill, min(stop, float(bars.Open.iloc[i])), bars.index[i]
        if bars.High.iloc[i] >= tgt: return "target", fill, tgt, bars.index[i]
    if len(bars) >= 5: return "expired", fill, float(bars.Close.iloc[4]), bars.index[4]
    return None

def update_journal(top):
    j = load()
    for p in top:
        if p["kind"] != "Triggered": continue
        if ((j.signal_date == p["date"]) & (j.symbol == p["t"])).any(): continue
        j.loc[len(j)] = [p["date"], p["t"], p["cat"], round(p["entry"], 2), round(p["stop"], 2), round(p["tgt"], 2), p["qty"],
                         "open", None, None, None, None, None]
    for i, row in j[j.status == "open"].iterrows():
        try:
            h = m.hist(row.symbol + ".NS", "6mo"); bars = h[h.index.date > pd.to_datetime(row.signal_date).date()]
            res = settle(row, bars) if len(bars) else None
        except Exception:
            res = None
        if res:
            st, fill, ex, d = res; pnl = (ex - fill) * row.qty if st != "skipped" else 0
            risk = row.entry - row.stop
            j.loc[i, ["status", "fill", "exit", "exit_date", "pnl", "r"]] = [st, round(fill, 2), round(ex, 2), str(d.date()),
                                                                              round(pnl, 0), round((ex - fill) / risk, 2) if risk > 0 and st != "skipped" else 0]
    os.makedirs("journal", exist_ok=True); j.to_csv(JOURNAL, index=False)
    return j

def scorecard(j):
    done = j[j.status.isin(["target", "stop", "expired"])]; n = len(done)
    pct = lambda s: f"{100*(done.status == s).mean():.0f}%" if n else "-"
    tiles = (f'<div class="tile"><div class="k">Closed paper trades</div><div class="v">{n}</div><div class="s">{(j.status == "open").sum()} open, {(j.status == "skipped").sum()} skipped</div></div>'
             f'<div class="tile"><div class="k">Win rate</div><div class="v">{100*(done.pnl.astype(float) > 0).mean() if n else 0:.0f}%</div><div class="s">target {pct("target")} | stop {pct("stop")} | expired {pct("expired")}</div></div>'
             f'<div class="tile"><div class="k">Average R</div><div class="v">{done.r.astype(float).mean() if n else 0:+.2f}</div><div class="s">1R = your planned risk</div></div>'
             f'<div class="tile"><div class="k">Paper P&amp;L</div><div class="v {"up" if n and done.pnl.astype(float).sum() >= 0 else "dn"}">Rs {done.pnl.astype(float).sum() if n else 0:,.0f}</div><div class="s">before costs and tax</div></div>')
    last = j.tail(12).iloc[::-1]
    rows = "".join(f'<tr><td>{html.escape(str(r.symbol))}</td><td>{r.signal_date}</td><td>{r.entry}</td><td>{r.stop}</td><td>{r.target}</td><td>{r.status}</td>'
                   f'<td>{"" if pd.isna(r.pnl) else f"{float(r.pnl):,.0f}"}</td></tr>' for r in last.itertuples())
    return ('<h2>Bot scorecard - automatic paper trades</h2><p class=n>Every strict signal is logged as a paper trade and settled by the bot: fill at next open, '
            'stop 1.5 ATR, target 2 ATR, 5 days max. No real orders are ever placed. Judge a setup only after 30+ closed trades.</p>'
            f'<div class=grid3>{tiles}</div><div class=tw><table><tr><th>Stock<th>Signal day<th>Entry<th>Stop<th>Target<th>Status<th>P&amp;L Rs</tr>{rows or "<tr><td colspan=7>No trades yet - the first ones appear after the next signals.</td></tr>"}</table></div>')

# ---------- tomorrow's trade plan ----------
def next_day(d):
    d = pd.to_datetime(d).date() + dt.timedelta(days=1)
    while d.weekday() >= 5: d += dt.timedelta(days=1)
    return d

def levels():
    n = m.prep(m.hist("^NSEI")); x = n.iloc[-1]
    H, L, C = float(x.High), float(x.Low), float(x.Close); P = (H + L + C) / 3
    try: vix = float(m.hist("^INDIAVIX", "5d").Close.iloc[-1])
    except Exception: vix = None
    return dict(C=C, P=P, R1=2 * P - L, S1=2 * P - H, R2=P + H - L, S2=P - H + L, rsi=float(x.rsi), vix=vix,
                trend=C > float(x.ema50), date=str(n.index[-1].date()))

def ideas_of(top):
    return [p for p in top if p["kind"] in ("Triggered", "Near")][:10]

def plan_section(top, lv):
    day = next_day(lv["date"]); ideas = ideas_of(top); risk_rs = m.CAPITAL * m.RISK_PCT / 100
    flags = []
    if lv["rsi"] > 75: flags.append(f"Nifty RSI is {lv['rsi']:.0f} (stretched). Consider half size, because breakouts fail more often after big run-ups.")
    elif lv["rsi"] < 30: flags.append(f"Nifty RSI is {lv['rsi']:.0f} (oversold). Bounces can be sharp but trends can continue lower.")
    if not lv["trend"]: flags.append("Nifty is below its 50 EMA. Be selective.")
    if lv["vix"] is not None and lv["vix"] > 20: flags.append(f"India VIX is {lv['vix']:.1f} (elevated). Expect wide swings and use smaller size.")
    flags = flags or ["No special warnings from the Nifty trend, RSI or VIX."]
    tiles = "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{lv[key]:,.0f}</div></div>'
                    for k, key in (("Close", "C"), ("Support 2", "S2"), ("Support 1", "S1"), ("Pivot", "P"), ("Resistance 1", "R1"), ("Resistance 2", "R2")))
    rules = "".join(f"<li>{r}</li>" for r in (
        "Wait until about 9:30 AM. The first 15 minutes are noisy.",
        f"Take at most 3 ideas. Each risks {m.RISK_PCT:g}% of capital (about Rs {risk_rs:,.0f}), so three together stay near {3*m.RISK_PCT:g}%.",
        "Skip any idea that opens above its Skip-if-above price (chasing) or at or below its stop.",
        "Breakout-trigger ideas: place a buy only if price crosses the trigger. No cross, no trade.",
        "Put the stop in as soon as you are filled. Exit on day 5 if neither stop nor target was hit.",
        "If Nifty opens more than 1% from yesterday's close, wait 30 minutes before any entry."))
    focus = [p["t"] for p in ideas if p["tm"][0] >= p["tm"][1]][:3]
    rows = ""
    for i, p in enumerate(ideas, 1):
        brk = p["cat"].startswith("Near breakout"); cap = p["entry"] * 1.01
        zone = f"cross {p['entry']:,.1f}, up to {cap:,.1f}" if brk else f"open, if at or below {cap:,.1f}"
        risk = p["qty"] * (p["entry"] - p["stop"])
        rows += (f'<tr><td>{"&#9733; " if p["t"] in focus else ""}{i}. {html.escape(p["t"])}</td><td>{html.escape(p["cat"])}</td><td>{zone}</td>'
                 f'<td>{p["stop"]:,.1f}</td><td>{p["tgt"]:,.1f}</td><td>{p["qty"]}</td><td>{risk:,.0f}</td>'
                 f'<td class="up">{p["tm"][0]:.0f}%</td><td class="dn">{p["tm"][1]:.0f}%</td><td>{p["hit"]}</td></tr>')
    rows = rows or '<tr><td colspan=10>No ideas for tomorrow. Doing nothing is a valid plan.</td></tr>'
    return (f"<h2>Tomorrow's Trade Plan - {day:%a %d %b %Y}</h2>"
            '<p class=n>Built from the last close. Ideas for paper-trading in score order, not recommendations. Check the NSE holiday list for the date.</p>'
            f'<div class=warn>{"<br>".join(flags)}</div><h2>Nifty levels</h2>'
            '<p class=n>Classic pivot levels from the last session. Price often reacts near them. They are not predictions.</p>'
            f'<div class=grid3>{tiles}</div><h2>Rules for the day</h2><ol class=n>{rules}</ol>'
            '<h2>Trade ideas</h2><p class=n>&#9733; marks up to 3 ideas whose simulated target chance is at least equal to their stop chance. No star means the odds look weak, so skipping is fine.</p>'
            '<div class=tw><table><tr><th>Stock<th>Setup<th>Buy zone<th>Stop<th>Target<th>Qty<th>Risk Rs<th>Sim target<th>Sim stop<th>Real past hit</tr>'
            f'{rows}</table></div>')

def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat: return
    try: requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", data={"chat_id": chat, "text": text[:4000]}, timeout=20)
    except Exception: pass

def main():
    tm.run()
    order = {"Triggered": 0, "Near": 1, "Watch": 2}
    top = sorted(tm.picked.values(), key=lambda p: (-p["score"], order[p["kind"]]))[:m.MAX_SETUPS]
    if not top: print("No setups, bot skipped"); return
    j = update_journal(top); lv = levels()
    path = "docs/index.html"; page = open(path, encoding="utf-8").read()
    a, b = "<h2>Your data at a glance</h2>", "<h2>Time Machine -"
    if a in page: page = page.replace(a, plan_section(top, lv) + a, 1)
    if b in page: page = page.replace(b, scorecard(j) + b, 1)
    open(path, "w", encoding="utf-8").write(page)
    rows = [dict({k: (round(v, 2) if isinstance(v, float) else v) for k, v in p.items() if k not in ("closes", "tm")}, skip_above=round(p["entry"] * 1.01, 2)) for p in top]
    json.dump(rows, open("docs/signals.json", "w"), indent=1)
    day = next_day(lv["date"]); done = j[j.status.isin(["target", "stop", "expired"])]
    msg = (f"Plan for {day:%a %d %b}. Nifty close {lv['C']:,.0f} | S1 {lv['S1']:,.0f} | R1 {lv['R1']:,.0f}\n"
           + "\n".join(f"{i}. {'* ' if p['tm'][0] >= p['tm'][1] else ''}{p['t']}: " + (f"buy only if it crosses {p['entry']:.1f}" if p["cat"].startswith("Near breakout") else f"buy near open, skip if above {p['entry']*1.01:.1f}")
                       + f" | stop {p['stop']:.1f} | target {p['tgt']:.1f} | qty {p['qty']}" for i, p in enumerate(ideas_of(top)[:5], 1))
           + (f"\nPaper record: {len(done)} closed, win {100*(done.pnl.astype(float) > 0).mean():.0f}%" if len(done) else "\nPaper record: no closed trades yet")
           + "\nMax 3 trades. Wait until 9:30. Research only, not advice.")
    telegram(msg); print("Bot done:", len(top), "setups,", len(j), "journal rows")

if __name__ == "__main__":
    main()
