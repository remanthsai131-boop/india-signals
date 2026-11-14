#!/usr/bin/env python3
"""Live status of the Pro list: compares the latest price with each buy zone, stop and target.
Writes docs/live.json. Yahoo data is delayed up to 15 minutes. Research only, not advice."""
import datetime as dt, json
import yfinance as yf

def status(px, lo, hi, stop, t1, t2, day_lo, day_hi):
    if day_lo <= stop: return "Stop level touched today"
    if day_hi >= t2: return "T2 touched today"
    if day_hi >= t1: return "T1 touched today"
    if lo <= px <= hi: return "IN BUY ZONE"
    if px > hi: return "Above zone - do not chase"
    return "Below zone - wait"

def main():
    try: plan = json.load(open("docs/pro.json"))
    except Exception: print("No pro.json yet"); return
    rows = []
    for p in plan:
        try:
            h = yf.Ticker(p["sym"] + ".NS").history(period="1d", interval="5m")
            if not len(h): continue
            px = float(h.Close.iloc[-1])
            rows.append(dict(sym=p["sym"], price=px, status=status(px, p["lo"], p["hi"], p["stop"], p["t1"], p["t2"], float(h.Low.min()), float(h.High.max())),
                             zone=f"{p['lo']:.1f} - {p['hi']:.1f}", stop=p["stop"], t1=p["t1"]))
        except Exception:
            continue
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    json.dump(dict(updated=f"{now:%d %b %H:%M} IST (prices delayed up to 15 min)", rows=rows), open("docs/live.json", "w"))
    print("live.json:", len(rows), "rows")

if __name__ == "__main__":
    main()

