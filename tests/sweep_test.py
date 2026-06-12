"""
sweep_test.py - Pipeline State Dogrulama (summary CSV)
=======================================================
Analyzer ve StateMachine'deki GERCEK kosullarla summary CSV'yi eslestirir.
"""

import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY_FILE = os.path.join(PROJECT_ROOT, "sonnet/src/output/summary/summary_2026-06-12.csv")


def check_pipeline(row):
    stages = {}

    d1_bias = row.get("d1_bias")
    h4_bias = row.get("h4_bias")
    strength = row.get("bias_strength", "NONE")
    bias_ok = d1_bias is not None and str(d1_bias).strip() not in ("", "nan")
    stages["bias"] = {"ok": bias_ok, "detail": f"D1={d1_bias} H4={h4_bias} ({strength})" if bias_ok else "BIAS YOK"}

    sweep_raw = row.get("sweep", False)
    sweep_ok = str(sweep_raw).strip().lower() in ("true", "1", "yes")
    sweep_parts = []
    if sweep_ok:
        sweep_parts.append(
            f"side={row.get('sweep_side', '?')} level={row.get('sweep_level', '?')} bar={row.get('sweep_bar_index', '?')}"
        )
    stages["sweep"] = {"ok": sweep_ok, "detail": " | ".join(sweep_parts) if sweep_parts else "SWEEP YOK"}

    mss_raw = row.get("mss", False)
    mss_ok = str(mss_raw).strip().lower() in ("true", "1", "yes")
    mss_parts = []
    if mss_ok:
        mss_parts.append(
            f"dir={row.get('mss_direction', '?')} level={row.get('mss_level', '?')} bar={row.get('mss_bar_index', '?')}"
        )

    mss_sweep_order_ok = True
    if mss_ok and sweep_ok:
        try:
            if int(row.get("mss_bar_index", 0)) < int(row.get("sweep_bar_index", 0)):
                mss_sweep_order_ok = False
                mss_parts.append("UYARI: MSS bar < Sweep bar")
        except (ValueError, TypeError):
            pass

    mss_bias_match = True
    if mss_ok and bias_ok:
        mss_dir = str(row.get("mss_direction", "")).strip()
        if mss_dir and mss_dir != str(d1_bias).strip():
            mss_bias_match = False
            mss_parts.append(f"UYARI: MSS dir={mss_dir} != bias={d1_bias}")

    stages["mss"] = {
        "ok": mss_ok,
        "detail": " | ".join(mss_parts) if mss_parts else "MSS YOK",
        "sweep_order_ok": mss_sweep_order_ok,
        "bias_match": mss_bias_match,
    }

    fvg_upper = row.get("fvg_upper")
    fvg_lower = row.get("fvg_lower")
    fvg_ce = row.get("fvg_ce")
    fvg_bar = row.get("fvg_bar_index")
    fvg_dir = row.get("fvg_direction", "")
    fvg_tf = row.get("fvg_tf", "")
    fvg_case = row.get("fvg_case", "")

    fvg_ok = fvg_upper is not None and str(fvg_upper).strip() not in ("", "nan")
    fvg_parts = []
    if fvg_ok:
        fvg_parts.append(f"dir={fvg_dir} tf={fvg_tf} case={fvg_case}")
        fvg_parts.append(f"U={fvg_upper} L={fvg_lower} CE={fvg_ce} bar={fvg_bar}")

    fvg_bias_match = True
    if fvg_ok and bias_ok:
        fd = str(fvg_dir).strip().lower()
        bd = str(d1_bias).strip().lower()
        if (fd == "bullish" and bd != "long") or (fd == "bearish" and bd != "short"):
            fvg_bias_match = False
            fvg_parts.append(f"UYARI: FVG {fd} != bias={d1_bias}")
    stages["fvg"] = {
        "ok": fvg_ok,
        "detail": " | ".join(fvg_parts) if fvg_parts else "FVG YOK",
        "bias_match": fvg_bias_match,
    }

    retrace_raw = row.get("retrace", False)
    retrace_ok = str(retrace_raw).strip().lower() in ("true", "1", "yes")
    retrace_detail = ""
    if retrace_ok:
        retrace_detail = "FVG icinde (CASE A: pen 0.15-0.70)"
    else:
        fm = str(row.get("fvg_missed", False)).strip().lower() in ("true", "1", "yes")
        if fm:
            retrace_detail = "MISSED_FVG (CASE C)"
        elif fvg_ok:
            retrace_detail = "BEKLIYOR"
    stages["retrace"] = {"ok": retrace_ok, "detail": retrace_detail or "RETRACE YOK"}

    ltf_raw = row.get("ltf", False)
    ltf_ok = str(ltf_raw).strip().lower() in ("true", "1", "yes")
    stages["ltf"] = {"ok": ltf_ok, "detail": "1m pivot kirilimi onaylandi" if ltf_ok else "LTF YOK"}

    current_state = str(row.get("state", "?")).strip()
    stages["state"] = {"state": current_state, "consistent": True, "warnings": []}

    completed = sum(1 for s in ["sweep", "mss", "fvg", "retrace", "ltf"] if stages[s]["ok"])
    stages["progress"] = {"completed": completed, "total": 5, "pct": completed / 5 * 100}
    return stages


def print_report(symbol, stages):
    p = stages["progress"]
    s = stages["state"]
    print()
    print("=" * 70)
    print(f"  {symbol}")
    print(f"  Bias: {stages['bias']['detail']}")
    print(f"  State: {s['state']}  |  Pipeline: {p['completed']}/{p['total']} ({p['pct']:.0f}%)")
    print("=" * 70)
    for label, key in [
        ("BIAS", "bias"),
        ("SWEEP", "sweep"),
        ("MSS  ", "mss"),
        ("FVG  ", "fvg"),
        ("RETRACE", "retrace"),
        ("LTF  ", "ltf"),
    ]:
        st = stages[key]
        icon = "+" if st["ok"] else ("~" if "BEKLIYOR" in st.get("detail", "") else "-")
        print(f"    {icon} {label}: {st['detail']}")
        if key == "mss":
            if not st.get("sweep_order_ok", True):
                print("         ! MSS bar < Sweep bar")
            if not st.get("bias_match", True):
                print("         ! MSS direction != bias")
        if key == "fvg" and not st.get("bias_match", True):
            print("         ! FVG direction != bias")


def main():
    print(f"Dosya: {SUMMARY_FILE}")
    print(f"Kok:   {PROJECT_ROOT}")
    print()
    if not os.path.exists(SUMMARY_FILE):
        print("HATA: dosya bulunamadi!")
        sys.exit(1)
    df = pd.read_csv(SUMMARY_FILE)
    print(f"Toplam satir: {len(df)}, Sembol: {df['symbol'].nunique()}")
    df["ts"] = pd.to_datetime(df["timestamp"])
    latest = df.loc[df.groupby("symbol")["ts"].idxmax()].sort_values("symbol")
    print(f"{len(latest)} sembolun son snapshot'i analiz ediliyor...")
    print()

    results = []
    for _, row in latest.iterrows():
        rd = row.to_dict()
        stages = check_pipeline(rd)
        results.append({"symbol": rd["symbol"], "stages": stages})
        print_report(rd["symbol"], stages)

    # summary table
    ready = stuck = 0
    print()
    print("=" * 70)
    print("  OZET TABLOSU")
    print("=" * 70)
    print(f"  {'SYMBOL':<12} {'STATE':<18} {'PL':<6} {'S':>3} {'M':>3} {'F':>3} {'R':>3} {'L':>3}")  # noqa: E741
    for r in results:
        st = r["stages"]
        state = st["state"]["state"]
        p = st["progress"]
        s = "Y" if st["sweep"]["ok"] else "N"
        m = "Y" if st["mss"]["ok"] else "N"
        f = "Y" if st["fvg"]["ok"] else "N"
        rc = "Y" if st["retrace"]["ok"] else "N"
        ltf_ok = "Y" if st["ltf"]["ok"] else "N"
        if state == "READY_TO_ENTER":
            disp = "R> READY"
            ready += 1
        elif state in ("WAIT_RETRACE", "WAIT_CONFIRM", "WAIT_NEW_FVG", "MISSED_FVG", "WAIT_POI_CONFIRM"):
            disp = state
            stuck += 1
        else:
            disp = state
        print(
            f"  {r['symbol']:<12} {disp:<18} {p['completed']}/{p['total']:<5} {s:>3} {m:>3} {f:>3} {rc:>3} {ltf_ok:>3}"
        )
    print(f"  READY: {ready} | Takili: {stuck} | Toplam: {len(results)}")

    out = os.path.join(PROJECT_ROOT, "sweep_pipeline_report.csv")
    rows = [
        {
            "symbol": r["symbol"],
            "state": r["stages"]["state"]["state"],
            "sweep": r["stages"]["sweep"]["ok"],
            "mss": r["stages"]["mss"]["ok"],
            "fvg": r["stages"]["fvg"]["ok"],
            "retrace": r["stages"]["retrace"]["ok"],
            "ltf": r["stages"]["ltf"]["ok"],
        }
        for r in results
    ]
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"  Rapor: {out}")


if __name__ == "__main__":
    main()
