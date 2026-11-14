#!/usr/bin/env python3
"""Live status of the Pro list. Uses Angel One SmartAPI prices if your secrets are set, else Yahoo (delayed).
Sends Telegram alerts when a stock enters its buy range or touches stop/target. Read-only: never places orders.
Research only, not financial advice."""
import datetime as dt, json, os, time, urllib.parse, urllib.request

MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
ALERT = ("IN BUY ZONE", "Stop level touched today", "T1 touched today", "T2 touched today")

def status(px, lo, hi, stop, t1, t2, day_lo, day_hi):
    if day_lo <= stop: return "Stop level touched today"
    if day_hi >= t2: return "T2 touched today"
    if day_hi >= t1: return "T1 touched today"
    if lo <= px <= hi: return "IN BUY ZONE"
    if px > hi: return "Above range - do not chase"
    return "Below range - wait"

def angel_quotes(symbols):
    """Returns {symbol: (ltp, day_low, day_high)} from Angel One, or {} if not configured or on any error."""
    k, c, p, t = (os.environ.get(n, "").strip() for n in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"))
    if not (k and c and p and t): return {}
    try:
        import pyotp
        from SmartApi import SmartConnect
        obj = SmartConnect(api_key=k)
        s = obj.generateSession(c, p, pyotp.TOTP(t).now())
        if not s or not s.get("status"): print("Angel One login failed"); return {}
        master = json.loads(urllib.request.urlopen(MASTER, timeout=90).read().decode())
        tok = {d["name"]: (d["symbol"], d["token"]) for d in master if d.get("exch_seg") == "NSE" and str(d.get("symbol", "")).endswith("-EQ")}
        out = {}
        for sym in symbols:
            if sym not in tok: continue
            try:
                r = (obj.ltpData("NSE", tok[sym][0], tok[sym][1]) or {}).get("data") or {}
                if r.get("ltp"): out[sym] = (float(r["ltp"]), float(r.get("low") or r["ltp"]), float(r.get("high") or r["ltp"]))
            except Exception: pass
            time.sleep(0.15)
        return out
    except Exception as e:
        print("Angel One failed:", type(e).__name__); return {}

def yahoo_quote(sym):
    import yfinance as yf
    h = yf.Ticker(sym + ".NS").history(period="1d", interval="5m")
    if not len(h): return None
    return float(h.Close.iloc[-1]), float(h.Low.min()), float(h.High.max())

def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not chat: return
    try:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data), timeout=20)
    except Exception: pass

def main():
    try: plan = json.load(open("docs/pro.json"))
    except Exception: print("No pro.json yet"); return
    try: old = {r["sym"]: r.get("key") for r in json.load(open("docs/live.json")).get("rows", [])}
    except Exception: old = {}
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    quotes = angel_quotes([p["sym"] for p in plan]); live_n = len(quotes); rows, alerts = [], []
    for p in plan:
        q = quotes.get(p["sym"])
        if q is None:
            try: q = yahoo_quote(p["sym"])
            except Exception: q = None
        if q is None: continue
        px, dl, dh = q; st = status(px, p["lo"], p["hi"], p["stop"], p["t1"], p["t2"], dl, dh); key = f"{st}|{now:%Y-%m-%d}"
        rows.append(dict(sym=p["sym"], price=px, status=st, zone=f"{p['lo']:.1f} - {p['hi']:.1f}", stop=p["stop"], t1=p["t1"], key=key))
        if st in ALERT and old.get(p["sym"]) != key:
            alerts.append(f"{p['sym']}: {st} at {px:.1f} | buy {p['lo']:.1f}-{p['hi']:.1f} | stop {p['stop']:.1f} | sell {p['t1']:.1f}-{p['t2']:.1f}")
    src = "Angel One live prices" if live_n else "Yahoo prices, delayed up to 15 min"
    json.dump(dict(updated=f"{now:%d %b %H:%M} IST - {src}", rows=rows), open("docs/live.json", "w"))
    if alerts: telegram("Live alerts (" + src + ")\n" + "\n".join(alerts[:12]) + "\nResearch only, not advice. Use your stop.")
    print("live.json:", len(rows), "rows,", live_n, "from Angel One,", len(alerts), "alerts")

if __name__ == "__main__":
    main()
