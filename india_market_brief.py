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
