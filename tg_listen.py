#!/usr/bin/env python3
"""Telegram command listener (runs every ~10 min on GitHub Actions). Standard library only.
Commands, from YOUR chat only: update, top, help. Research only, not financial advice."""
import json, os, urllib.parse, urllib.request

TOK = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = str(os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

def api(method, **params):
    url = f"https://api.telegram.org/bot{TOK}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=25) as r:
        return json.loads(r.read().decode())

def send(text):
    try: api("sendMessage", chat_id=CHAT, text=text[:4000])
    except Exception: pass

def cmd(text):
    w = (text or "").strip().lower().split()
    return w[0].lstrip("/").split("@")[0] if w else ""

def top_text():
    try: rows = json.load(open("docs/signals.json"))
    except Exception: return "No saved setups yet. Send: update"
    trig = [p for p in rows if p.get("kind") == "Triggered"] or rows
    lines = [f"{p['t']}: entry {p['entry']:.1f} stop {p['stop']:.1f} target {p['tgt']:.1f} qty {p['qty']} ({p['cat']})" for p in trig[:6]]
    return f"Latest saved setups ({rows[0].get('date', '')}):\n" + "\n".join(lines) + "\nResearch only, not advice. Use stop-losses."

HELP = ("Commands:\nupdate - run a fresh analysis (about 2-5 min, GitHub timing varies)\n"
        "top - show the latest saved setups right now\nhelp - this message\nResearch only, not financial advice.")

def out(run):
    line = f"run={'true' if run else 'false'}\n"
    path = os.environ.get("GITHUB_OUTPUT")
    open(path, "a").write(line) if path else print(line.strip())

def main():
    if not TOK or not CHAT: print("Telegram secrets missing"); out(False); return
    try: ups = api("getUpdates", timeout=0).get("result", [])
    except Exception as e: print("getUpdates failed:", e); out(False); return
    run = False
    for u in ups:
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != CHAT: continue   # ignore everyone else
        c = cmd(msg.get("text"))
        if c in ("update", "refresh", "run"):
            if not run: send("Got it. Running a fresh analysis now. Your setups arrive in a few minutes.")
            run = True
        elif c == "top": send(top_text())
        elif c in ("help", "start"): send(HELP)
        elif c: send("Unknown command. " + HELP)
    if ups:
        try: api("getUpdates", offset=max(u["update_id"] for u in ups) + 1, timeout=0)   # confirm, so they are not read twice
        except Exception: pass
    out(run)

if __name__ == "__main__":
    main()

