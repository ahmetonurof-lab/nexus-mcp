#!/usr/bin/env python3
"""Sentetik trade ile yeni snapshot formatini uctan uca dogrula (bot'a dokunmaz)."""

import sys
import time

BASE = "/root/sniper/src"
sys.path.insert(0, BASE)

from snapshot.snapshot import capture_snapshot  # noqa: E402

now_ms = int(time.time() * 1000)
entry_ms = now_ms - 3 * 60 * 60 * 1000
exit_ms = now_ms - 60 * 1000

cases = [
    ("DOGEUSDT", 0.10, 0.11, 0.095, 0.12),
    ("RENDERUSDT", 3.50, 3.55, 3.40, 3.70),
    ("APTUSDT", 5.20, 5.25, 5.05, 5.50),
]

produced = []
for sym, entry, exit_, sl, tp in cases:
    trade = {
        "entry_price": entry,
        "exit_price": exit_,
        "sl": sl,
        "tp": tp,
        "side": "long",
        "timestamp": entry_ms,
        "exit_timestamp": exit_ms,
        "pnl": 5.0,
    }
    try:
        fname = capture_snapshot(sym, trade)
        produced.append(fname)
        print(f"OK  {fname}")
    except Exception as e:  # noqa: BLE001
        print(f"ERR {sym}: {type(e).__name__}: {e}")

print("\n--- SORT CHECK (alfabetik == ters kronolojik) ---")
import re  # noqa: E402

parsed = []
for f in produced:
    m = re.match(r"^(.+?)_([A-Z0-9]+)_(\d{4}-\d{2}-\d{2})_(\d{6})\.html$", f)
    if not m:
        print(f"FORMAT UYUMSUZ: {f}")
        continue
    parsed.append((f, f"{m.group(3)}_{m.group(4)}"))

alpha = [p[1] for p in sorted(parsed, key=lambda x: x[0])]
chrono = [p[1] for p in sorted(parsed, key=lambda x: x[1], reverse=True)]
if alpha == chrono:
    print("PASS: alfabetik siralama ters kronolojik ile birebir eslesiyor")
    for i, (f, ts) in enumerate(sorted(parsed, key=lambda x: x[0]), 1):
        print(f"  {i}. {f}")
else:
    print("FAIL:")
    print("  alpha:", alpha)
    print("  chrono:", chrono)
