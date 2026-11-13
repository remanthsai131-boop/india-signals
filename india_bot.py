#!/usr/bin/env python3
"""India Signals bot: runs the dashboard, keeps a paper-trade journal, scores it,
adds next-day +5% odds to the page and (optionally) sends a Telegram message.
Research only, not financial advice. No real orders are ever placed."""
import html, json, os
import numpy as np, pandas as pd, requests
import india_market_brief as m
import india_tm as tm

JOURNAL = "journal/paper_trades.csv"
COLS = ["signal_date", "symbol", "setup", "entry", "stop", "target", "qty", "status", "fill", "exit", "exit_date", "pnl", "r"]
_prev = tm.pick_with_sim

def pick_more(t, df):
    p = _prev(t, df)
    if p:
        c, h, l = df.Close.values[-501:], df.High.values[-501:], df.Low.values[-501:]
        p["date"] = str(df.index[-1].date())
        p["up5"] = float((h[1:] / c[:-1] - 1 >= .05).mean() * 100)
        p["close5"] = float((c[1:] / c[:-1] - 1 >= .05).mean() * 100)
        p["dn5"] = float((l[1:] / c[:-1] - 1 <= -.05).mean() * 100)
    return p
tm.pick_with_sim = pick_more

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

def five_pct(top):
    rows = sorted(top, key=lambda p: -p["up5"])
    tr = "".join(f'<tr><td>{html.escape(p["t"])}</td><td>{p["price"]:,.1f}</td><td class="up">{p["up5"]:.1f}%</td><td>{p["close5"]:.1f}%</td><td class="dn">{p["dn5"]:.1f}%</td></tr>' for p in rows)
    return ('<h2>Next-day +5% odds (past 2 years)</h2><p class=n>How often each stock rose 5% or more the next day, and how often it fell 5% or more. '
            'These are usually rare, low single digits. Chasing 5% in one day means relying on a rare event with a similar chance of a sharp fall, so no setup can promise it.</p>'
            f'<div class=tw><table><tr><th>Stock<th>Price<th>Touched +5%<th>Closed +5%<th>Touched -5%</tr>{tr}</table></div>')

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
    j = update_journal(top)
    path = "docs/index.html"; page = open(path, encoding="utf-8").read()
    marker = "<h2>Time Machine -"
    if marker in page: page = page.replace(marker, scorecard(j) + five_pct(top) + marker, 1)
    open(path, "w", encoding="utf-8").write(page)
    json.dump([{k: (round(v, 2) if isinstance(v, float) else v) for k, v in p.items() if k not in ("closes", "tm")} for p in top],
              open("docs/signals.json", "w"), indent=1)
    trig = [p for p in top if p["kind"] == "Triggered"][:6]
    done = j[j.status.isin(["target", "stop", "expired"])]
    msg = f"India Signals {top[0]['date']}\n" + "\n".join(
        f"{p['t']}: entry {p['entry']:.1f} stop {p['stop']:.1f} target {p['tgt']:.1f} qty {p['qty']} (sim target {p['tm'][0]:.0f}% / stop {p['tm'][1]:.0f}%)"
        for p in trig) + (f"\nPaper record: {len(done)} closed, win {100*(done.pnl.astype(float) > 0).mean():.0f}%" if len(done) else "\nPaper record: no closed trades yet") \
        + "\nResearch only, not advice. Use stop-losses."
    telegram(msg); print("Bot done:", len(top), "setups,", len(j), "journal rows")

if __name__ == "__main__":
    main()

