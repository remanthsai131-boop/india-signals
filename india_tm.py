#!/usr/bin/env python3
"""Time Machine add-on: runs india_market_brief.py, then adds simulated outcomes to the page.
Research only, not financial advice."""
import html
import numpy as np
import india_market_brief as m

picked = {}
_orig_pick = m.pick_setup

def simulate(df, entry, stop, tgt, n=10000, days=5):
    """Replay n random 5-day paths built from this stock's own last ~250 daily moves.
    If stop and target are both touched on the same day, the stop is counted first."""
    d = df.tail(250); c = d.Close.values; prev = c[:-1]
    hi = d.High.values[1:] / prev - 1; lo = d.Low.values[1:] / prev - 1; cl = c[1:] / prev - 1
    idx = np.random.default_rng(7).integers(0, len(hi), (n, days))
    price = np.full(n, float(entry)); state = np.zeros(n, int)   # 0 open, 1 target, 2 stop
    for k in range(days):
        h = price * (1 + hi[idx[:, k]]); l = price * (1 + lo[idx[:, k]]); live = state == 0
        s = live & (l <= stop); t = live & ~s & (h >= tgt)
        state[s] = 2; state[t] = 1
        price = np.where(state == 0, price * (1 + cl[idx[:, k]]), price)
    return (state == 1).mean() * 100, (state == 2).mean() * 100, (state == 0).mean() * 100

def pick_with_sim(t, df):
    p = _orig_pick(t, df)
    if p:
        p["tm"] = simulate(df, p["entry"], p["stop"], p["tgt"]); picked[t] = p
    return p

def tm_svg(rows, w=700):
    h = 30 * len(rows) + 30; L = 110; bw = w - L - 10
    o = [f'<svg viewBox="0 0 {w} {h}" class="ch">']
    for i, (s, tp, sp, nn) in enumerate(rows):
        y = 6 + i * 30
        o.append(f'<text x="{L-8}" y="{y+17}" text-anchor="end" class="ax2">{html.escape(s)}</text>')
        x = L
        for v, cls in ((tp, "gt"), (sp, "gs"), (nn, "gn")):
            ww = bw * v / 100
            o.append(f'<rect x="{x:.1f}" y="{y}" width="{ww:.1f}" height="22" class="{cls}"/>')
            if v > 9: o.append(f'<text x="{x+ww/2:.1f}" y="{y+16}" text-anchor="middle" class="bl">{v:.0f}%</text>')
            x += ww
    o.append(f'<text x="{L}" y="{h-6}" class="ax">green = target first, red = stop first, grey = neither in 5 days</text></svg>')
    return "".join(o)

def section(top):
    rows = [(p["t"], *p["tm"]) for p in top]
    tr = "".join(f'<tr><td>{html.escape(p["t"])}</td><td>{p["entry"]:,.1f}</td><td>{p["stop"]:,.1f}</td><td>{p["tgt"]:,.1f}</td>'
                 f'<td class="up">{p["tm"][0]:.0f}%</td><td class="dn">{p["tm"][1]:.0f}%</td><td>{p["tm"][2]:.0f}%</td><td>{p["hit"]}</td></tr>'
                 for p in top)
    return ('<h2>Time Machine - 10,000 simulated 5-day paths per setup</h2>'
            '<p class=n>Each stock is replayed using its own last year of daily moves. This shows the odds if price moves randomly with that stock\'s usual volatility. '
            'It does not know whether the setup itself has an edge. Compare it with the last column, the real past target-hit rate of triggered setups: '
            'if real results are worse than the simulation, the setup has not earned your trust. If stop % is much higher than target %, skipping is a fine decision.</p>'
            + tm_svg(rows) +
            '<div class=tw><table><tr><th>Stock<th>Entry<th>Stop<th>Target<th>Sim target<th>Sim stop<th>Neither<th>Real past hit</tr>' + tr + '</table></div>')

def run():
    m.pick_setup = pick_with_sim
    m.main()
    order = {"Triggered": 0, "Near": 1, "Watch": 2}
    top = sorted(picked.values(), key=lambda p: (-p["score"], order[p["kind"]]))[:m.MAX_SETUPS]
    path = "docs/index.html"; page = open(path, encoding="utf-8").read()
    marker = "<h2>Top 6 charts</h2>"
    if top and marker in page:
        open(path, "w", encoding="utf-8").write(page.replace(marker, section(top) + marker, 1))
        print("Time Machine added for", len(top), "setups")
    else:
        print("Time Machine skipped (no setups or page marker missing)")

if __name__ == "__main__":
    run()
