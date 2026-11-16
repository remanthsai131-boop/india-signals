#!/usr/bin/env python3
"""India Investor: ONE simple page built on long-tested ideas.
  Long-term: index SIP + 200-day trend check. Monthly: momentum leaders. Swing: trend pullbacks and 20-day breakouts with ATR stops.
Research only, not financial advice. No orders are placed."""
import datetime as dt, html, json, os, time, urllib.parse, urllib.request
import numpy as np, pandas as pd, requests
import india_market_brief as m
import pro_engine as pe
import compare as cp

SWING_N, LEAD_N, HOLD, COST = 40, 25, 20, 0.003
SWING_J, FWD, FLOW = "journal/swing_trades.csv", "journal/forward_picks.csv", "journal/fii_dii.csv"
STALE = ["docs/detail.html", "docs/pro.html", "docs/pro.json", "docs/live.json", "docs/signals.json", "docs/momentum.json"]

# ---------- data ----------
def norm(df):
    df = df.dropna()
    if getattr(df.index, "tz", None) is not None: df.index = df.index.tz_localize(None)
    df.index = df.index.normalize(); return df

def load():
    """Downloads in batches of 100 (fast, gentle on Yahoo). Falls back to one-by-one if a batch fails."""
    nifty = norm(m.hist("^NSEI")); nifty = pe.prepare(nifty, nifty.Close); pe.signals(nifty); data = {}; syms = list(m.UNIVERSE)
    for i in range(0, len(syms), 100):
        chunk = syms[i:i + 100]
        try: d = m.yf.download([x + ".NS" for x in chunk], period="2y", group_by="ticker", auto_adjust=True, progress=False, threads=True)
        except Exception: d = None
        for t in chunk:
            try:
                df = norm(d[t + ".NS"].copy()) if d is not None else norm(m.hist(t + ".NS"))
                if len(df) < cp.LOOK + cp.N_DAYS + 5: continue
                if not (m.MIN_PRICE <= float(df.Close.iloc[-1]) <= m.MAX_PRICE): continue
                data[t] = pe.signals(pe.prepare(df, nifty.Close))
            except Exception:
                continue
    return nifty, data

def leaders(data, nifty, N):
    """Long-term leaders: above the 200-day, near 52-week highs, strongest 12m/6m moves. Quality check uses Yahoo fundamentals when available."""
    rows = []
    for t, df in data.items():
        x = df.iloc[-1]; c = df.Close
        if len(c) < 252 or not (x.Close > x.e200 and x.e50 > x.e200) or x.turn < 2e7: continue
        near = float(x.Close / x.h52)
        if near < .80: continue
        r12 = float(c.iloc[-1] / c.iloc[-252] - 1); r6 = float(c.iloc[-1] / c.iloc[-126] - 1); n6 = float(nifty.Close.iloc[-1] / nifty.Close.iloc[-126] - 1)
        rows.append(dict(t=t, price=float(x.Close), r12=r12, rs6=r6 - n6, near=near, sector=m.SECTOR_OF.get(t, "")))
    if not rows: return []
    d = pd.DataFrame(rows); d["score"] = .4 * d.r12.rank(pct=True) + .3 * d.rs6.rank(pct=True) + .3 * d.near.rank(pct=True)
    top = d.sort_values("score", ascending=False).head(N).to_dict("records"); t0 = time.time()
    for p in top:
        p["roe"] = p["gr"] = p["de"] = None
        if time.time() - t0 > 150: continue
        try:
            i = m.yf.Ticker(p["t"] + ".NS").info
            p["roe"], p["gr"], p["de"] = i.get("returnOnEquity"), i.get("revenueGrowth"), i.get("debtToEquity")
        except Exception: pass
    for p in top:
        p["q"] = sum([p["roe"] is not None and p["roe"] >= .15, p["gr"] is not None and p["gr"] >= .10, p["de"] is not None and p["de"] <= 100])
        p["qk"] = sum(v is not None for v in (p["roe"], p["gr"], p["de"]))
    return top

# ---------- swing ----------
def swing(nifty, data):
    nx = nifty.iloc[-1]; regime_ok = int(nx.trend) >= 0 and bool(nx.Close > nx.e50); block = int(nx.trend) <= -1
    cands, sells, allres, trades = [], [], [], []
    for t, df in data.items():
        x = df.iloc[-1]; bt = {"Pullback": pe.backtest(df, df.pull), "Breakout": pe.backtest(df, df.brk)}
        allres += bt["Pullback"] + bt["Breakout"]; trades += cp.swing_trades(df, df.pull | df.brk)
        kind, status = None, "IN ZONE"; pb_hi = float(x.e20 + .25 * x.atr)
        if bool(x.brk): kind = "Breakout"
        elif bool(x.pull): kind = "Pullback"
        elif int(x.trend) >= 1 and pb_hi < x.Close <= pb_hi + 2 * x.atr and x.rsi < 70: kind, status = "Pullback", "Approaching: set a limit buy"
        elif int(x.trend) >= 1 and 0 < (x.hh20 - x.Close) / x.Close <= .03 and x.rsi < 70: kind, status = "Breakout", "Approaching: buy only above the trigger"
        if bool(x.sell) and len(sells) < 8: sells.append((t, x))
        if not kind or block: continue
        in_zone = status == "IN ZONE"; st = pe.stats(bt[kind]); xx = x.copy()
        if status.startswith("Approaching: set"):
            xx["entry"] = pb_hi; xx["z_lo"], xx["z_hi"] = x.e50, pb_hi
            s0 = min(x.sl10, x.e50) - .25 * x.atr; xx["stop"] = pb_hi - x.atr if pb_hi - s0 < x.atr else s0
        elif status.startswith("Approaching: buy"):
            xx["entry"] = x.hh20; xx["z_lo"], xx["z_hi"] = x.hh20, x.hh20 + .5 * x.atr
            s0 = min(x.sl10, x.hh20 - x.atr) - .25 * x.atr; xx["stop"] = x.hh20 - x.atr if x.hh20 - s0 < x.atr else s0
        R = float(xx.entry - xx.stop)
        if R <= 0 or R > 4 * x.atr or x.turn < 2e7 or (st["n"] >= 8 and st["avg"] < -.1): continue
        q = pe.quality(xx, st, kind, regime_ok, float(nx.rsi), in_zone)
        if q < pe.MIN_Q: continue
        qty = int(min(m.CAPITAL * m.RISK_PCT / 100 / R, m.CAPITAL * pe.MAX_POS_PCT / 100 / xx.entry))
        cands.append(dict(t=t, kind=kind, in_zone=in_zone, status=status, q=q, price=float(x.Close), lo=float(xx.z_lo), hi=float(xx.z_hi), entry=float(xx.entry),
                          stop=float(xx.stop), sector=m.SECTOR_OF.get(t, ""), tp1=float(xx.entry + 1.5 * R), tp2=float(xx.entry + 2 * R), tp3=float(xx.entry + 3 * R), qty=qty, st=st, date=str(df.index[-1].date())))
    cands.sort(key=lambda p: (not p["in_zone"], -p["q"]))
    return cands[:SWING_N], sells, pe.stats(allres), trades, regime_ok, block

def swing_journal(top, data):
    cols = ["signal_date", "symbol", "kind", "entry", "stop", "target", "qty", "status", "fill", "exit", "exit_date", "r", "pnl"]
    try: j = pd.read_csv(SWING_J)
    except Exception: j = pd.DataFrame(columns=cols)
    for p in top:
        if p["in_zone"] and p["q"] >= 60 and not ((j.signal_date == p["date"]) & (j.symbol == p["t"])).any():
            j.loc[len(j)] = [p["date"], p["t"], p["kind"], round(p["entry"], 2), round(p["stop"], 2), round(p["tp2"], 2), p["qty"], "open", None, None, None, None, None]
    for i, r in j[j.status == "open"].iterrows():
        try:
            df = data.get(r.symbol)
            if df is None: df = m.hist(r.symbol + ".NS", "6mo")
            b = df[df.index.date > pd.to_datetime(r.signal_date).date()]
            if not len(b): continue
            fill = float(b.Open.iloc[0]); res = None
            if fill <= r.stop or fill >= r.target: res = ("skipped", fill, fill, b.index[0])
            else:
                for k in range(min(len(b), HOLD)):
                    if b.Low.iloc[k] <= r.stop: res = ("stop", fill, min(r.stop, float(b.Open.iloc[k])) if k else r.stop, b.index[k]); break
                    if b.High.iloc[k] >= r.target: res = ("target", fill, r.target, b.index[k]); break
                if res is None and len(b) >= HOLD: res = ("expired", fill, float(b.Close.iloc[HOLD - 1]), b.index[HOLD - 1])
            if res:
                st, f, ex, d = res; risk = r.entry - r.stop
                rr = 0 if st == "skipped" or risk <= 0 else (ex - f) / risk - COST * f / risk
                pnl = 0 if st == "skipped" else (ex - f) * r.qty - COST * f * r.qty
                j.loc[i, ["status", "fill", "exit", "exit_date", "r", "pnl"]] = [st, round(f, 2), round(ex, 2), str(d.date()), round(rr, 2), round(pnl, 0)]
        except Exception:
            continue
    os.makedirs("journal", exist_ok=True); j.to_csv(SWING_J, index=False); return j

# ---------- monthly momentum + forward tracker ----------
def forward(mom, closes):
    cols = ["month", "date", "symbol", "entry", "nifty"]
    try: f = pd.read_csv(FWD)
    except Exception: f = pd.DataFrame(columns=cols)
    month = mom["date"][:7]
    if month not in set(f.month.astype(str)):
        if mom["on"] and mom["picks"]:
            for p in mom["picks"]: f.loc[len(f)] = [month, mom["date"], p["sym"], round(p["price"], 2), round(mom["nifty"], 2)]
        else: f.loc[len(f)] = [month, mom["date"], "CASH", 0, round(mom["nifty"], 2)]
        os.makedirs("journal", exist_ok=True); f.to_csv(FWD, index=False)
    out = []
    for mo, g in f.groupby("month", sort=True):
        nr = mom["nifty"] / float(g.nifty.iloc[0]) - 1
        if (g.symbol == "CASH").all(): out.append((mo, 0, 0.0, nr)); continue
        rets = [float(closes[s].iloc[-1]) / e - 1 for s, e in zip(g.symbol, g.entry) if s in closes.columns and e > 0]
        out.append((mo, len(rets), (float(np.mean(rets)) - COST) if rets else None, nr))
    return out

def bars(rows, w=700):
    rows = [r for r in rows if r[2] is not None][-12:]
    if not rows: return ""
    vals = [v for r in rows for v in (r[2], r[3])]; lo, hi = min(0, min(vals)), max(0, max(vals)); span = (hi - lo) or 1
    h, top, bot = 200, 22, 28; Y = lambda v: top + (h - top - bot) * (hi - v) / span; bw = w / len(rows)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch"><line x1="0" x2="{w}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="grid"/>']
    for i, (mo, n, a, b) in enumerate(rows):
        for k, (v, cls) in enumerate(((a, "bp"), (b, "bn"))):
            x = i * bw + bw * (.12 + .4 * k); y0, y1 = Y(0), Y(v)
            o.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{bw*.36:.1f}" height="{max(abs(y1 - y0), 1):.1f}" class="{cls}"/>'
                     f'<text x="{x + bw*.18:.1f}" y="{min(y0, y1) - 4:.1f}" text-anchor="middle" class="val">{v*100:+.0f}%</text>')
        o.append(f'<text x="{i*bw + bw/2:.1f}" y="{h-8}" text-anchor="middle" class="lab">{mo}</text>')
    return "".join(o) + "</svg>"

# ---------- page ----------
LEARN = [("SIP (monthly investing)", "Invest a fixed amount every month in a broad index fund. You buy more units when prices are low and fewer when high. It needs no timing and has the longest track record of the ideas here."),
         ("200-day average (trend check)", "If the index is above its 200-day average the long-term trend is up. Below it, the trend is weak. Many long-term investors keep their SIP going but add lump sums in small parts when the trend is weak."),
         ("Momentum (monthly picks)", "Stocks that have been strongest over the last 6 months have tended to keep outperforming for a while, in many markets. Each month you hold the 10 strongest in equal parts, and stay in cash if the market trend is down."),
         ("Swing trade", "Holding a stock for days to weeks. Classic rules: buy a dip to the 20/50-day average in an uptrend, or a break above the 20-day high. Always set the stop first."),
         ("Stop (get out below)", "The price where you leave if you were wrong. It keeps a loss small and planned."),
         ("Targets (TP1, TP2, TP3)", "Levels where you take profit: 1.5, 2 and 3 times your risk. Selling part at each level locks in gains. A close target is hit more often but pays less."),
         ("Position size", "Risk about 1% of your money per idea. On Rs 1 lakh that is Rs 1,000, so shares = Rs 1,000 divided by the distance to your stop."),
         ("Spread your money", "Do not hold only banks, or only one idea. Several stocks falling together is the main risk. Taxes and costs also apply, so check current rules before investing.")]
CSS = """:root{--bg:#fff;--fg:#111827;--mut:#6b7280;--card:#f3f4f6;--line:#d1d5db;--up:#16a34a;--dn:#dc2626;--blue:#2563eb;--amb:#d97706}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--card:#161b22;--line:#30363d;--up:#3fb950;--dn:#f85149;--blue:#58a6ff;--amb:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.5 system-ui,sans-serif;padding:16px;max-width:720px;margin:auto}
h1{font-size:24px;margin:8px 0}h2{font-size:20px;margin:30px 0 6px}h3{font-size:16px;margin:16px 0 4px}.m{color:var(--mut);font-size:14px}.up{color:var(--up)}.dn{color:var(--dn)}
.warn{border:1px solid var(--dn);border-radius:12px;padding:10px 12px;font-size:14px;margin:10px 0}.say{background:var(--card);border-radius:12px;padding:12px;margin:10px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.t,.card{background:var(--card);border-radius:12px;padding:12px;margin:6px 0}
.t .k{color:var(--mut);font-size:13px}.t .v{font-size:21px;font-weight:700}.row{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:19px}
.big{margin-top:6px}.chip{font-size:12px;padding:3px 8px;border-radius:999px;background:var(--line)}.grn{background:var(--up);color:#fff}.amb{background:var(--amb);color:#fff}
.ch{width:100%;height:auto}.grid{stroke:var(--line);stroke-width:1}.ax{fill:var(--mut);font-size:11px}.lg{font-size:12px;font-weight:600}.ln{fill:none;stroke-width:2}
.c1{stroke:var(--fg)}.c2{stroke:var(--blue)}.c3{stroke:var(--amb)}.c1t{fill:var(--fg)}.c2t{fill:var(--blue)}.c3t{fill:var(--amb)}.bp{fill:var(--blue)}.bn{fill:var(--mut)}.val{fill:var(--fg);font-size:12px}.lab{fill:var(--mut);font-size:12px}
details{background:var(--card);border-radius:12px;padding:10px 12px;margin:6px 0}summary{font-weight:600;cursor:pointer}a{color:var(--blue)}ol{padding-left:22px}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14.5px}td,th{padding:6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}td:first-child,th:first-child{text-align:left}"""

def sip_fv(p=10000, years=15, rate=.10):
    r = rate / 12; n = years * 12; return p * (((1 + r) ** n - 1) / r) * (1 + r)

def target_study(data):
    """Same entries, different targets: shows the trade-off between how often a target is hit and how much it pays."""
    rows = []
    for name, k in (("TP1 at 1.5R", 1.5), ("TP2 at 2R", 2.0), ("TP3 at 3R", 3.0)):
        res = []
        for df in data.values(): res += pe.backtest(df, df.pull | df.brk, k=k)
        if not res: rows.append((name, 0, 0, 0, 0, 0.0)); continue
        o = pd.Series([x[1] for x in res])
        rows.append((name, len(res), 100 * (o == "target").mean(), 100 * (o == "stop").mean(), 100 * (o == "expired").mean(), float(np.mean([x[2] for x in res]))))
    return rows

def nifty_study():
    """Long history test of the classic 200-day trend rule on Nifty (price index, no dividends, cash earns 0)."""
    try: h = m.hist("^NSEI", "max")
    except Exception: return None
    c = h.Close
    if len(c) < 1500: return None
    sma = c.rolling(200).mean(); pos = (c > sma).shift(1).fillna(False).astype(bool); r = c.pct_change().fillna(0.0)
    sw = pos.astype(int).diff().abs().fillna(0); strat = r.where(pos, 0.0) - sw * 0.001
    bh, st = (1 + r).cumprod(), (1 + strat).cumprod(); yrs = (c.index[-1] - c.index[0]).days / 365.25
    cagr = lambda e: float(e.iloc[-1] ** (1 / yrs) - 1); mdd = lambda e: float(((e.cummax() - e) / e.cummax()).max())
    f20 = c.shift(-20) / c - 1; ab = (c > sma) & f20.notna(); be = (c <= sma) & sma.notna() & f20.notna()
    now = bool(c.iloc[-1] > sma.iloc[-1]); flips = pos[pos != pos.shift()].index
    wk = c.resample("W").last().dropna(); w10, w30 = wk.rolling(10).mean().iloc[-1], wk.rolling(30).mean().iloc[-1]
    scan = [("Daily: above 20-day average", c.iloc[-1] > c.rolling(20).mean().iloc[-1]), ("Daily: above 50-day average", c.iloc[-1] > c.rolling(50).mean().iloc[-1]),
            ("Daily: above 200-day average", now), ("Weekly: above 10-week average", wk.iloc[-1] > w10), ("Weekly: above 30-week average", wk.iloc[-1] > w30)]
    return dict(years=yrs, start=str(c.index[0].date()), now=now, last=str(flips[-1].date()) if len(flips) else "-", scan=scan,
                bh=(cagr(bh), mdd(bh), 100.0), rule=(cagr(st), mdd(st), 100 * float(pos.mean())), trades=int((sw > 0).sum() // 2),
                p_up=100 * float((f20[ab] > 0).mean()), p_dn=100 * float((f20[be] > 0).mean()), curves=(bh.values[::5] / bh.values[0] * 100, st.values[::5] / st.values[0] * 100))

def sector_table(data, closes):
    """Average 3-month move and share above the 50-day average, by sector, across everything scanned."""
    g = {}
    for t, df in data.items():
        if t not in closes.columns or len(closes) < 70: continue
        g.setdefault(m.SECTOR_OF.get(t) or "Other", []).append((float(closes[t].iloc[-1] / closes[t].iloc[-64] - 1), bool(df.Close.iloc[-1] > df.e50.iloc[-1])))
    rows = [(k, len(v), 100 * float(np.nanmean([x[0] for x in v])), 100 * float(np.mean([x[1] for x in v]))) for k, v in g.items() if len(v) >= 3]
    return sorted(rows, key=lambda r: -r[2])

def fii_dii():
    """Latest FII/FPI and DII net buying (Rs crore) from NSE's public page. Market-wide, published after the close."""
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    try:
        s = requests.Session(); s.get("https://www.nseindia.com", headers=h, timeout=15)
        r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", headers=h, timeout=15).json(); out, date = {}, None
        for d in r:
            cat = str(d.get("category", "")).upper(); k = "fii" if ("FII" in cat or "FPI" in cat) else "dii" if "DII" in cat else None
            if k: out[k] = float(str(d.get("netValue", "0")).replace(",", "")); date = d.get("date")
        if "fii" in out and "dii" in out and date: return str(pd.to_datetime(date, format="%d-%b-%Y").date()), out["fii"], out["dii"]
    except Exception: pass
    return None

def flow_update():
    cols = ["date", "fii_net", "dii_net"]
    try: f = pd.read_csv(FLOW)
    except Exception: f = pd.DataFrame(columns=cols)
    new = fii_dii()
    if new and new[0] not in set(f.date.astype(str)): f.loc[len(f)] = list(new)
    f = f.sort_values("date").tail(60); os.makedirs("journal", exist_ok=True); f.to_csv(FLOW, index=False)
    return f

def flow_mood(f):
    if not len(f): return "Unknown", "Flow data is not available yet. It builds up day by day from the first successful fetch."
    t = f.tail(5); a, b = float(t.fii_net.sum()), float(t.dii_net.sum())
    if a > 0 and a + b > 0: return "Supportive", "Foreign and domestic institutions are both net buyers recently. Normal position size is fine."
    if a < 0 and a + b < 0: return "Caution", "Both are net sellers recently. Use half size on new swing ideas and take fewer trades."
    return "Mixed", "Foreign and domestic funds are pulling in different directions. Keep your normal rules and small size."

def flow_bars(f, w=700):
    r = f.tail(12)
    if not len(r): return ""
    vals = [float(v) for v in list(r.fii_net) + list(r.dii_net)]; lo, hi = min(0, min(vals)), max(0, max(vals)); span = (hi - lo) or 1
    h, top, bot = 200, 22, 28; Y = lambda v: top + (h - top - bot) * (hi - v) / span; bw = w / len(r)
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch"><line x1="0" x2="{w}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="grid"/>']
    for i, (d, a, b) in enumerate(zip(r.date, r.fii_net, r.dii_net)):
        for k, (v, cls) in enumerate(((float(a), "bp"), (float(b), "bn"))):
            x = i * bw + bw * (.12 + .4 * k); y0, y1 = Y(0), Y(v)
            o.append(f'<rect x="{x:.1f}" y="{min(y0, y1):.1f}" width="{bw*.36:.1f}" height="{max(abs(y1 - y0), 1):.1f}" class="{cls}"/>')
        o.append(f'<text x="{i*bw + bw/2:.1f}" y="{h-8}" text-anchor="middle" class="lab">{str(d)[5:]}</text>')
    return "".join(o) + "</svg>"

def big_deals(universe):
    """Bulk and block deals NSE reports today, limited to the stocks scanned. These are large trades by any client, not all FII/DII trades."""
    h = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/"}; out = []
    try:
        s = requests.Session(); s.get("https://www.nseindia.com", headers=h, timeout=15)
        d = s.get("https://www.nseindia.com/api/snapshot-capital-market-largedeal", headers=h, timeout=20).json()
        for key, label in (("BULK_DEALS_DATA", "Bulk"), ("BLOCK_DEALS_DATA", "Block")):
            for r in d.get(key) or []:
                sym = str(r.get("symbol", "")).strip()
                if sym in universe:
                    out.append((label, sym, str(r.get("clientName") or r.get("name") or "")[:28], str(r.get("buySell") or ""), r.get("qty") or r.get("quantity") or "", r.get("watp") or r.get("tradePrice") or ""))
    except Exception: pass
    return out

def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat: return
    try:
        d = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=d), timeout=20)
    except Exception: pass

def main():
    nifty, data = load(); idx = nifty.index; nx = nifty.iloc[-1]; N = max(len(data), 1)
    flows = flow_update(); fm, fmsg = flow_mood(flows); deals = big_deals(set(data)); dmark = {}
    for lab, sym, cl, bs, q, pr in deals: dmark.setdefault(sym, set()).add("Buy" if bs.upper().startswith("B") else "Sell")
    top, sells, ps, trades, regime_ok, block = swing(nifty, data)
    if fm == "Caution":
        for p in top: p["qty"] = int(p["qty"] * 0.5)
    closes = pd.DataFrame({t: d.Close for t, d in data.items()}).reindex(idx).ffill(); nc, n200 = nifty.Close, nifty.e200
    on = bool(nc.iloc[-1] > n200.iloc[-1]); L = len(closes)
    mom_eq = cp.momentum(closes, nc, n200); sw_eq, taken = cp.swing_curve(trades, idx); ni_eq = 100 * nc.values[-cp.N_DAYS:] / nc.values[-cp.N_DAYS]
    res = {k: cp.stat(v) for k, v in (("Just hold Nifty", ni_eq), ("Monthly momentum picks", mom_eq), ("Swing rules (max 3 open)", sw_eq))}
    lastmom = (closes.iloc[-1 - cp.SKIP] / closes.iloc[-1 - cp.LOOK] - 1).dropna().sort_values(ascending=False).head(cp.TOP)
    mom = dict(date=str(idx[-1].date()), on=on, nifty=float(nc.iloc[-1]), picks=[dict(sym=t, price=float(closes[t].iloc[-1]), mom=float(v)) for t, v in lastmom.items()])
    tstudy = target_study(data); ns = nifty_study()
    fw = forward(mom, closes); j = swing_journal(top, data); lead = leaders(data, nifty, LEAD_N); secs = sector_table(data, closes)
    above200 = sum(bool(d.Close.iloc[-1] > d.e200.iloc[-1]) for d in data.values()); off52 = 1 - float(nx.Close / nx.h52)
    trend = pe.TREND[int(nx.trend)]; rsi = float(nx.rsi)
    heat = "very hot, so dips are common" if rsi > 75 else "very weak" if rsi < 30 else "normal"
    lump = ("Nifty is above its 200-day average. Normal conditions for investing." if on else "Nifty is below its 200-day average. Keep your SIP running, but add any lump sum in small parts.")
    sw_say = ("Swing buying is paused: Nifty is in a downtrend." if block else "Be selective: the market is not in a clear uptrend, so use small size." if not regime_ok else "Conditions allow swing ideas, with small size.")
    if fm == "Caution" and not block: sw_say += " Institutional flows are negative, so use half size."
    tiles = (f'<div class="t"><div class="k">Nifty 50</div><div class="v">{nx.Close:,.0f}</div></div><div class="t"><div class="k">Trend</div><div class="v">{trend}</div></div>'
             f'<div class="t"><div class="k">Below 52-week high</div><div class="v">{off52*100:.1f}%</div></div><div class="t"><div class="k">Stocks above 200-day</div><div class="v">{100*above200/N:.0f}%</div></div><div class="t"><div class="k">Stocks scanned</div><div class="v">{len(data)}</div></div>')
    sip = (f'<div class="say"><b>Keep a monthly index-fund SIP running.</b> It is the simplest idea here and has the longest track record. {lump} Market heat (RSI {rsi:.0f}) is {heat}.</div>'
           f'<p class="m">Illustration only, not a forecast: Rs 10,000 a month for 15 years at 10% a year would grow to about Rs {sip_fv()/1e5:,.0f} lakh. Real returns vary and can be negative for years.</p>')
    chart = m.line_chart([("Just hold Nifty", ni_eq, "c1"), ("Momentum picks", mom_eq, "c2"), ("Swing rules", sw_eq, "c3")], fmt="{:.0f}")
    srows = "".join(f'<tr><td>{k}</td><td class="{"up" if r[0] >= 0 else "dn"}">{r[0]*100:+.1f}%</td><td>{r[1]*100:.0f}%</td></tr>' for k, r in res.items())
    amt = m.CAPITAL / cp.TOP
    prow = "".join(f'<tr><td>{html.escape(t)}</td><td>{closes[t].iloc[-1]:,.1f}</td><td>{v*100:+.0f}%</td><td>{int(amt // closes[t].iloc[-1])}</td></tr>' for t, v in lastmom.items())
    mtext = ("Hold these 10 in equal parts and review once a month." if on else "Nifty is below its 200-day average, so this method says stay in cash this month.")
    fdone = [r for r in fw if r[2] is not None]; beat = sum(r[2] > r[3] for r in fdone)
    frows = "".join(f'<tr><td>{mo}</td><td>{n or "cash"}</td><td>{"-" if a is None else f"{a*100:+.1f}%"}</td><td>{b*100:+.1f}%</td></tr>' for mo, n, a, b in fw)
    verdict = (f"In the last year these swing rules lost money after costs ({ps['avg']:+.2f}R per trade, profit factor {ps['pf']:.1f}). Use paper money only until your own journal proves otherwise."
               if ps["n"] and (ps["avg"] <= 0 or ps["pf"] < 1) else f"Last year these swing rules made {ps['avg']:+.2f}R per trade (profit factor {ps['pf']:.1f}). Still confirm on paper first.")
    cards = ""
    for p in top[:3]:
        chip, cls = ("In buy range now", "grn") if p["in_zone"] else (p["status"], "amb")
        why = "a dip in an uptrend" if p["kind"] == "Pullback" else "a break above a recent high on strong volume"
        cards += (f'<div class="card"><div class="row"><b>{html.escape(p["t"])}</b><span class="chip {cls}">{html.escape(chip)}</span></div><div class="m">Idea: {why}</div>'
                  f'<div class="big">Buy between <b>{p["lo"]:,.1f}</b> and <b>{p["hi"]:,.1f}</b></div><div class="big">Targets: <b>{p["tp1"]:,.1f}</b> / <b>{p["tp2"]:,.1f}</b> / <b>{p["tp3"]:,.1f}</b> <span class="m">(1.5R / 2R / 3R)</span></div>'
                  f'<div class="big">Get out if it falls to <b>{p["stop"]:,.1f}</b></div><div class="m">Shares: {p["qty"]} (a loss at the stop is about Rs {p["qty"]*(p["hi"]-p["stop"]):,.0f})</div></div>')
    cards = cards or '<div class="card">No swing ideas pass the filters today. Doing nothing is a good decision.</div>'
    trows = "".join(f'<tr><td>{html.escape(p["t"])}</td><td>{html.escape(p["sector"][:16])}</td><td>{p["kind"]}</td><td>{p["q"]}</td><td>{p["lo"]:,.1f} - {p["hi"]:,.1f}</td><td>{p["stop"]:,.1f}</td><td>{p["tp1"]:,.1f} - {p["tp3"]:,.1f}</td><td>{p["qty"]}</td>'
                    f'<td>{"in zone" if p["in_zone"] else "approaching"}</td><td>{" ".join(sorted(dmark.get(p["t"], [])))}</td></tr>' for p in top)
    sellrows = "".join(f'<tr><td>{html.escape(t)}</td><td>{pe.TREND[int(x.trend)]}</td><td>{x.Close:,.1f}</td></tr>' for t, x in sells) or "<tr><td colspan=3>None today.</td></tr>"
    lrows = "".join(f'<tr><td>{html.escape(p["t"])}</td><td>{html.escape(p["sector"][:16])}</td><td>{p["price"]:,.1f}</td><td class="up">{p["r12"]*100:+.0f}%</td><td>{(1-p["near"])*100:.0f}%</td><td>{pe.pctf(p["roe"])} / {pe.pctf(p["gr"])} / {pe.fmt(p["de"], 0)}</td><td>{f"{p[chr(113)]} of 3" if p["qk"] else "n/a"}</td></tr>' for p in lead) or "<tr><td colspan=7>None today.</td></tr>"
    done = j[j.status.isin(["target", "stop", "expired"])]; n = len(done)
    if n:
        pnl, rr = done.pnl.astype(float), done.r.astype(float)
        jt = (f'<div class="tiles"><div class="t"><div class="k">Finished trades</div><div class="v">{n}</div></div><div class="t"><div class="k">Winners</div><div class="v">{100*(pnl > 0).mean():.0f}%</div></div>'
              f'<div class="t"><div class="k">Average result</div><div class="v">{rr.mean():+.2f}R</div></div><div class="t"><div class="k">Practice profit</div><div class="v {"up" if pnl.sum() >= 0 else "dn"}">Rs {pnl.sum():,.0f}</div></div></div>')
        jt += f'<p class="m">{"Wait for 100 finished trades before judging." if n < 100 else ("Average is positive. Keep testing." if rr.mean() > 0 else "Average is negative. Do not use real money on this.")}</p>'
    else: jt = f'<div class="card">{int((j.status == "open").sum())} practice swing trades are open. Results appear when they finish (up to {HOLD} trading days).</div>'
    if ns:
        ntab = (f'<div class="tw"><table><tr><th>Approach<th>Yearly growth<th>Worst drop<th>Time invested</tr>'
                f'<tr><td>Just hold Nifty</td><td>{ns["bh"][0]*100:.1f}%</td><td>{ns["bh"][1]*100:.0f}%</td><td>100%</td></tr>'
                f'<tr><td>Hold only above 200-day</td><td>{ns["rule"][0]*100:.1f}%</td><td>{ns["rule"][1]*100:.0f}%</td><td>{ns["rule"][2]:.0f}%</td></tr></table></div>')
        scan = "".join(f'<tr><td>{a}</td><td class="{"up" if b else "dn"}">{"Up" if b else "Down"}</td></tr>' for a, b in ns["scan"])
        nsec = (f'<div class="say">Signal now: <b>{"INVEST (Nifty is above its 200-day average)" if ns["now"] else "STAY IN CASH (Nifty is below its 200-day average)"}</b>. Last change: {ns["last"]}. '
                f'Use a Nifty 50 index fund or ETF. Avoid futures and options, where most individuals lose money.</div>'
                f'<h3>Trend scanner</h3><div class="tw"><table><tr><th>Check<th>Now</tr>{scan}</table></div>'
                f'<h3>{ns["years"]:.0f} years of Nifty history ({ns["start"][:4]} to now)</h3>{ntab}'
                f'{m.line_chart([("Just hold Nifty", ns["curves"][0], "c1"), ("200-day rule", ns["curves"][1], "c2")], fmt="{:.0f}")}'
                f'<p class="m">After days when Nifty closed above its 200-day average, the next 20 trading days were positive {ns["p_up"]:.0f}% of the time. Below it: {ns["p_dn"]:.0f}%. '
                f'The rule changed position about {ns["trades"]} times. Its main value is a smaller worst drop, not higher returns, and it can lose small amounts in sideways markets. '
                f'Price index only: dividends, taxes, fund costs and what cash earns are not included.</p>')
    else: nsec = '<div class="card">Nifty history is not available right now.</div>'
    if len(flows):
        l = flows.iloc[-1]; t5 = flows.tail(5)
        ftiles = (f'<div class="tiles"><div class="t"><div class="k">FII net, latest ({l.date})</div><div class="v {"up" if l.fii_net >= 0 else "dn"}">{l.fii_net:+,.0f}</div></div>'
                  f'<div class="t"><div class="k">DII net, latest</div><div class="v {"up" if l.dii_net >= 0 else "dn"}">{l.dii_net:+,.0f}</div></div>'
                  f'<div class="t"><div class="k">FII net, last {len(t5)} days</div><div class="v">{t5.fii_net.sum():+,.0f}</div></div>'
                  f'<div class="t"><div class="k">DII net, last {len(t5)} days</div><div class="v">{t5.dii_net.sum():+,.0f}</div></div></div>')
        fsec = (f'{ftiles}<div class="say"><b>Flow mood: {fm}.</b> {fmsg}</div>{flow_bars(flows)}<p class="m">Rs crore, cash market, after the close. Blue = FII, grey = DII. '
                'Stock-by-stock FII/DII buying is only published quarterly (shareholding patterns), so this is a market-wide mood, not a stock signal. Never use it alone.</p>')
    else: fsec = f'<div class="say">{fmsg}</div>'
    drow = "".join(f'<tr><td>{a}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td><td>{d}</td><td>{e}</td><td>{f}</td></tr>' for a, b, c, d, e, f in deals[:15]) or "<tr><td colspan=6>None in your stocks today, or the data is not available.</td></tr>"
    fsec += (f'<h3>Large deals today in your stocks (bulk and block)</h3><div class="tw"><table><tr><th>Type<th>Stock<th>Client<th>Side<th>Quantity<th>Price</tr>{drow}</table></div>'
             '<p class="m">These show who traded in size, but the client can be a fund, a foreign investor, a domestic institution or a trader. One big buy is not proof a stock will rise. The Big deal column in the swing table marks stocks that appear here.</p>')
    sech = "".join(f'<tr><td>{html.escape(k)}</td><td>{n}</td><td class="{"up" if r >= 0 else "dn"}">{r:+.1f}%</td><td>{a:.0f}%</td></tr>' for k, n, r, a in (secs[:8] + [x for x in secs[-4:] if x not in secs[:8]]))
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30); learn = "".join(f"<details><summary>{a}</summary><p>{b}</p></details>" for a, b in LEARN)
    page = f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>My Investing Dashboard</title>
<link rel=manifest href=manifest.json><meta name=theme-color content="#0d1117"><link rel=apple-touch-icon href=icon-180.png><style>{CSS}</style></head><body>
<h1>My Investing Dashboard</h1><div class="m">Updated {now:%d %b %Y, %H:%M} IST. Data after market close.</div>
<div class="warn">Research and practice only, not financial advice. No method can promise profit. Use paper money first, and only invest money you can afford to lose.</div>
<h2>How is the market?</h2><div class="tiles">{tiles}</div>
<h2>Institutional flows (FII / DII)</h2>{fsec}
<h2>Whole-market scan</h2><p class="m">Scanned {len(data)} stocks from the broad NSE market list (Nifty Total Market, about 750 stocks, or Nifty 500 if that list is unavailable; priced Rs {m.MIN_PRICE} to {m.MAX_PRICE}, with enough trading volume). That covers most of the market's value. Sectors with the strongest and weakest 3-month moves:</p>
<div class="tw"><table><tr><th>Sector<th>Stocks<th>3-month avg<th>Above 50-day</tr>{sech}</table></div>
<h2>1. Long-term: index SIP (years)</h2>{sip}
<h2>2. Nifty: the 200-day trend rule (months to years)</h2><p class="m">A classic, widely studied rule: hold the index while it is above its 200-day average, step aside when it is below.</p>{nsec}
<h2>3. Monthly: momentum leaders (months)</h2><p class="m">A long-studied method: hold the strongest stocks, rebalance monthly, go to cash when the market trend is down.</p>
<div class="say">{mtext}</div><div class="tw"><table><tr><th>Stock<th>Price<th>6m momentum<th>Shares for Rs {amt:,.0f}</tr>{prow}</table></div>
<h3>How it did vs just holding Nifty (last year)</h3><div class="tw"><table><tr><th>Approach<th>Return<th>Worst drop</tr>{srows}</table></div>{chart}
<p class="m">Same stocks and costs. The stock list was picked from recent strength, so past results look better than real life. One year is one market mood.</p>
<h3>Live test: monthly picks vs Nifty</h3>{bars(fw)}<div class="tw"><table><tr><th>Month<th>Stocks<th>Picks<th>Nifty</tr>{frows}</table></div>
<p class="m">{f"So far the picks beat Nifty in {beat} of {len(fdone)} months. Judge after at least 6 months." if fdone else "The first month is recorded. Results appear as days pass."}</p>
<h2>4. Swing trades (days to weeks)</h2><p class="m">Classic trend rules: buy dips to the 20/50-day average in an uptrend, or a break above the 20-day high. Stop below the recent low, sell near 2x to 3x your risk.</p>
<div class="say">{sw_say}</div><div class="warn">{verdict}</div>{cards}
<h3>How often each target was reached (last year, same entries)</h3><div class="tw"><table><tr><th>Target<th>Trades<th>Reached<th>Stop first<th>Neither<th>Avg result</tr>{"".join(f'<tr><td>{a}</td><td>{b}</td><td>{c:.0f}%</td><td>{d:.0f}%</td><td>{e:.0f}%</td><td>{f:+.2f}R</td></tr>' for a, b, c, d, e, f in tstudy)}</table></div>
<p class="m">A close target is hit more often but pays less. A high hit rate alone proves nothing, so always check the average result. After costs it needs to be above zero.</p>
<div class="tw"><table><tr><th>Stock<th>Sector<th>Idea<th>Score<th>Buy range<th>Stop<th>Sell range<th>Shares<th>Status<th>Big deal</tr>{trows or "<tr><td colspan=10>No ideas today.</td></tr>"}</table></div>
<h3>Avoid or exit if you hold</h3><div class="tw"><table><tr><th>Stock<th>Trend<th>Price</tr>{sellrows}</table></div>
<h3>My practice swing journal</h3>{jt}
<h2>5. Long-term leaders to research</h2><p class="m">Strong long-term trends near 52-week highs. Nobody can pick winners in advance. Treat this as a shortlist to study, not a promise. Quality check counts: ROE of 15% or more, revenue growth of 10% or more, debt-to-equity of 100 or less. It shows n/a when Yahoo has no data. Read the company's own reports before investing.</p>
<div class="tw"><table><tr><th>Stock<th>Sector<th>Price<th>12m<th>Below high<th>ROE / growth / debt<th>Quality check</tr>{lrows}</table></div>
<h2>Learn in 2 minutes</h2>{learn}
<h2>Simple routine</h2><ol><li>Keep the monthly SIP running.</li><li>Once a month, review the momentum list.</li><li>For swing ideas, choose at most 3, set the stop first.</li><li>On Sunday, check the journal and the live test.</li></ol></body></html>"""
    os.makedirs("docs", exist_ok=True); open("docs/index.html", "w", encoding="utf-8").write(page)
    for f in STALE:
        try: os.remove(f)
        except OSError: pass
    ideas = [p for p in top if p["in_zone"]][:5]
    telegram(f"Plan {mom['date']}: Nifty {nx.Close:,.0f} ({trend}). {sw_say}\n" + ("\n".join(f"{p['t']}: buy {p['lo']:.1f}-{p['hi']:.1f} stop {p['stop']:.1f} sell {p['tp1']:.1f}-{p['tp3']:.1f} qty {p['qty']}" for p in ideas) or "No swing ideas in the buy range today.")
             + f"\nFII/DII flow mood: {fm}.\nMonthly momentum: {'invest' if on else 'stay in cash'}.\nPractice only, not advice.")
    print("Done:", len(top), "swing ideas,", len(lead), "leaders,", len(data), "stocks,", ps["n"], "1y trades")

if __name__ == "__main__":
    main()
