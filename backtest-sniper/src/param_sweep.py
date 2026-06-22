"""
param_sweep.py — min_fvg_size parameter optimization.
Tests multiple values for each coin, reports best.
"""

import csv
import os
import sys
from datetime import datetime, timezone

from fvg import detect_fvgs
from models import Bar
from retrace_state import RetraceStateMachine
from session import DailyBias, SessionPhase, SessionState, detect_phase_from_timestamp

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = os.path.join(os.path.dirname(__file__), "data")

INITIAL_CAPITAL = 10000.0
RISK_PER_TRADE = 0.01
SL_ATR_MULT = 1.5
TP_RR = 2.0
FVG_BUFFER_MULT = 0.25


def load_data(filepath):
    bars = []
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            ts = int(
                datetime.strptime(row["open_time"], "%Y-%m-%d %H:%M:%S").timestamp()
                * 1000
            )
            bars.append(
                Bar(
                    index=i,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    is_closed=True,
                    timestamp=ts,
                )
            )
    return bars


def resample_15m(bars_1m):
    m15 = []
    for i in range(0, len(bars_1m), 15):
        c = bars_1m[i : i + 15]
        if len(c) < 15:
            break
        m15.append(
            Bar(
                index=c[0].index,
                open=c[0].open,
                high=max(b.high for b in c),
                low=min(b.low for b in c),
                close=c[-1].close,
                volume=sum(b.volume for b in c),
                is_closed=True,
                timestamp=c[0].timestamp,
            )
        )
    return m15


def run_test(symbol, min_fvg_size):
    csv_file = os.path.join(DATA, f"{symbol}_1m.csv")
    if not os.path.isfile(csv_file):
        return None

    bars_1m = load_data(csv_file)
    bars_15m = resample_15m(bars_1m)

    ss = SessionState()
    rsm = RetraceStateMachine(min_fvg_size=min_fvg_size)
    rsm_retrade = RetraceStateMachine(min_fvg_size=min_fvg_size * 0.3)
    trades = []
    active_trades = []
    WINDOW = 500

    for scan_bar in range(WINDOW, len(bars_15m), 5):
        chunk = bars_15m[scan_bar - WINDOW : scan_bar + 1]
        current = bars_15m[scan_bar]
        atr_val = max(current.range, current.close * 0.0001)
        try:
            entry_dt = datetime.fromtimestamp(current.timestamp / 1000, tz=timezone.utc)
        except Exception:
            continue

        ss.update(
            entry_dt, current.open, current.high, current.low, current.close, atr_val
        )

        if ss.sweep_confirmed and rsm.state_name == "IDLE":
            rsm.on_sweep(
                direction=ss.sweep_direction or "bullish",
                level=ss.sweep_level or 0.0,
                bar_index=current.index,
            )

        if rsm.state_name == "SWEEP_DETECTED":
            rsm.on_sweep_confirmed(chunk, current)

        if rsm.can_trigger():
            sweep_dir = rsm.direction
            daily_bias = ss.daily_bias

            if (
                (sweep_dir == "bullish" and daily_bias == DailyBias.BEARISH)
                or (sweep_dir == "bearish" and daily_bias == DailyBias.BULLISH)
                or daily_bias == DailyBias.NEUTRAL
            ):
                rsm.reset()
                continue

            phase = detect_phase_from_timestamp(current.timestamp)
            if phase != SessionPhase.NEWYORK:
                rsm.reset()
                continue

            side = "long" if sweep_dir == "bullish" else "short"
            entry_price = current.close
            risk_pts = atr_val * SL_ATR_MULT
            trigger_fvg = rsm.trigger_fvg

            if side == "long":
                sl = (
                    trigger_fvg.bottom - (risk_pts * FVG_BUFFER_MULT)
                    if trigger_fvg
                    else entry_price - risk_pts * 2
                )
                tp = (
                    ss.london_high
                    if ss.london_high > entry_price
                    else entry_price + risk_pts * TP_RR
                )
            else:
                sl = (
                    trigger_fvg.top + (risk_pts * FVG_BUFFER_MULT)
                    if trigger_fvg
                    else entry_price + risk_pts * 2
                )
                tp = (
                    ss.london_low
                    if ss.london_low < entry_price
                    else entry_price - risk_pts * TP_RR
                )

            qty = (
                (INITIAL_CAPITAL * RISK_PER_TRADE) / abs(sl - entry_price)
                if abs(sl - entry_price) > 0
                else 0
            )
            if qty <= 0:
                rsm.reset()
                continue

            new_trade = {
                "entry_bar": scan_bar,
                "entry_price": entry_price,
                "sl": sl,
                "tp": tp,
                "qty": qty,
                "side": side,
                "trigger_fvg": trigger_fvg,
                "initial_sl": sl,
                "initial_tp": tp,
                "trailing_count": 0,
                "is_retrade": False,
            }
            active_trades.append(new_trade)
            ss.trades_today += 1
            rsm.reset()

        if active_trades and current.is_closed:
            current_fvgs = detect_fvgs(
                chunk,
                lookback=min(50, len(chunk)),
                timeframe="15m",
                min_fvg_size=min_fvg_size,
            )
            for trade in active_trades:
                if trade.get("closed"):
                    continue
                for fvg in current_fvgs:
                    if (
                        (trade["side"] == "long" and fvg.direction != "bullish")
                        or (trade["side"] == "short" and fvg.direction != "bearish")
                        or fvg.filled
                        or fvg.invalidated
                    ):
                        continue
                    buffer = (
                        abs(trade["initial_sl"] - trade["entry_price"])
                        * FVG_BUFFER_MULT
                    )
                    if trade["side"] == "long":
                        new_sl = fvg.bottom - buffer
                        if new_sl > trade["sl"]:
                            sl_diff = new_sl - trade["sl"]
                            trade["sl"] = new_sl
                            trade["tp"] += sl_diff
                            trade["trailing_count"] += 1
                    else:
                        new_sl = fvg.top + buffer
                        if new_sl < trade["sl"]:
                            sl_diff = trade["sl"] - new_sl
                            trade["sl"] = new_sl
                            trade["tp"] -= sl_diff
                            trade["trailing_count"] += 1

        still_active = []
        for trade in active_trades:
            if trade.get("closed"):
                continue
            exited = False
            if trade["side"] == "long":
                if current.low <= trade["sl"]:
                    trade["exit_price"], trade["result"] = trade["sl"], "SL"
                    trade["closed"] = True
                    exited = True
                elif current.high >= trade["tp"]:
                    trade["exit_price"], trade["result"] = trade["tp"], "TP"
                    trade["closed"] = True
                    exited = True
            else:
                if current.high >= trade["sl"]:
                    trade["exit_price"], trade["result"] = trade["sl"], "SL"
                    trade["closed"] = True
                    exited = True
                elif current.low <= trade["tp"]:
                    trade["exit_price"], trade["result"] = trade["tp"], "TP"
                    trade["closed"] = True
                    exited = True
            if exited:
                diff = (
                    (trade["exit_price"] - trade["entry_price"])
                    if trade["side"] == "long"
                    else (trade["entry_price"] - trade["exit_price"])
                )
                trade["pnl"] = round(diff * trade["qty"], 2)
                trade["rr"] = round(
                    diff / abs(trade["initial_sl"] - trade["entry_price"])
                    if abs(trade["initial_sl"] - trade["entry_price"]) > 0
                    else 0,
                    2,
                )
                trades.append(trade)

                if (
                    not trade.get("is_retrade", False)
                    and ss.trades_today == 1
                    and not ss.retrade_armed
                ):
                    ss.retrade_armed = True
                    ss.retrade_side = "short" if trade["side"] == "long" else "long"
                    ss.retrade_sweep_level = 0.0
                    ss.retrade_entry_bar = trade["entry_bar"]
            else:
                still_active.append(trade)
        active_trades = still_active

        if ss.retrade_armed and ss.trades_today == 1 and not active_trades:
            sweep_found = False
            sweep_bar_idx = None
            lookback = min(5, scan_bar)
            for check_idx in range(scan_bar - 4, scan_bar + 1):
                if check_idx < 0 or check_idx >= len(bars_15m):
                    continue
                cb = bars_15m[check_idx]
                if check_idx - lookback < 0:
                    continue
                recent = bars_15m[check_idx - lookback : check_idx]
                if ss.retrade_side == "short":
                    if cb.high > max(b.high for b in recent) and cb.close < max(
                        b.high for b in recent
                    ):
                        sweep_found, sweep_bar_idx = True, check_idx
                        break
                else:
                    if cb.low < min(b.low for b in recent) and cb.close > min(
                        b.low for b in recent
                    ):
                        sweep_found, sweep_bar_idx = True, check_idx
                        break
            if sweep_found:
                sweep_dir = "bearish" if ss.retrade_side == "short" else "bullish"
                if rsm_retrade.state_name == "IDLE":
                    rsm_retrade.on_sweep(
                        direction=sweep_dir,
                        level=ss.retrade_sweep_level,
                        bar_index=bars_15m[sweep_bar_idx].index,
                    )
            if rsm_retrade.state_name == "SWEEP_DETECTED":
                sweep_bar = bars_15m[sweep_bar_idx]
                sweep_chunk = (
                    bars_15m[sweep_bar_idx - WINDOW : sweep_bar_idx + 1]
                    if sweep_bar_idx >= WINDOW
                    else chunk
                )
                rsm_retrade.on_sweep_confirmed(sweep_chunk, sweep_bar)
            if rsm_retrade.can_trigger():
                phase_rt = detect_phase_from_timestamp(current.timestamp)
                if phase_rt == SessionPhase.NEWYORK:
                    retrade_entry_price = current.close
                    retrade_risk_pts = atr_val * SL_ATR_MULT
                    retrade_fvg = rsm_retrade.trigger_fvg
                    if ss.retrade_side == "long":
                        retrade_sl = (
                            retrade_fvg.bottom - (retrade_risk_pts * FVG_BUFFER_MULT)
                            if retrade_fvg
                            else retrade_entry_price - retrade_risk_pts * 2
                        )
                        retrade_tp = (
                            ss.london_high
                            if ss.london_high > retrade_entry_price
                            else retrade_entry_price + retrade_risk_pts * TP_RR
                        )
                    else:
                        retrade_sl = (
                            retrade_fvg.top + (retrade_risk_pts * FVG_BUFFER_MULT)
                            if retrade_fvg
                            else retrade_entry_price + retrade_risk_pts * 2
                        )
                        retrade_tp = (
                            ss.london_low
                            if ss.london_low < retrade_entry_price
                            else retrade_entry_price - retrade_risk_pts * TP_RR
                        )
                    retrade_qty = (
                        (INITIAL_CAPITAL * RISK_PER_TRADE)
                        / abs(retrade_sl - retrade_entry_price)
                        if abs(retrade_sl - retrade_entry_price) > 0
                        else 0
                    )
                    if retrade_qty > 0:
                        active_trades.append(
                            {
                                "entry_bar": scan_bar,
                                "entry_price": retrade_entry_price,
                                "sl": retrade_sl,
                                "tp": retrade_tp,
                                "qty": retrade_qty,
                                "side": ss.retrade_side,
                                "trigger_fvg": retrade_fvg,
                                "initial_sl": retrade_sl,
                                "initial_tp": retrade_tp,
                                "trailing_count": 0,
                                "is_retrade": True,
                            }
                        )
                        ss.trades_today += 1
                    rsm_retrade.reset()
                    ss.retrade_armed = False

    if bars_15m:
        last_price = bars_15m[-1].close
        for trade in active_trades:
            if not trade.get("closed"):
                trade["exit_price"] = last_price
                trade["result"] = "OPEN"
                trade["closed"] = True
                diff = (
                    (trade["exit_price"] - trade["entry_price"])
                    if trade["side"] == "long"
                    else (trade["entry_price"] - trade["exit_price"])
                )
                trade["pnl"] = round(diff * trade["qty"], 2)
                trade["rr"] = round(
                    diff / abs(trade["initial_sl"] - trade["entry_price"])
                    if abs(trade["initial_sl"] - trade["entry_price"]) > 0
                    else 0,
                    2,
                )
                trades.append(trade)

    if not trades:
        return {
            "trades": 0,
            "wins": 0,
            "pnl": 0,
            "wr": 0,
            "dd": 0,
            "pf": 0,
            "tp_rate": 0,
            "avg_rr": 0,
        }

    total_pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    wr = len(wins) / len(trades) * 100

    dd_peak = INITIAL_CAPITAL
    running = INITIAL_CAPITAL
    dd_max = 0.0
    for t in trades:
        running += t["pnl"]
        if running > dd_peak:
            dd_peak = running
        dd_val = (dd_peak - running) / dd_peak * 100 if dd_peak > 0 else 0
        if dd_val > dd_max:
            dd_max = dd_val

    avg_win_rr = sum(t["rr"] for t in wins) / len(wins) if wins else 0
    avg_loss_rr = sum(t["rr"] for t in losses) / len(losses) if losses else 0
    pf = abs(avg_win_rr / avg_loss_rr) if avg_loss_rr != 0 else 0
    tp_count = sum(1 for t in trades if t["result"] == "TP")
    tp_rate = tp_count / len(trades) * 100

    return {
        "trades": len(trades),
        "wins": len(wins),
        "pnl": round(total_pnl, 2),
        "wr": round(wr, 1),
        "dd": round(dd_max, 1),
        "pf": round(pf, 2),
        "tp_rate": round(tp_rate, 1),
        "avg_rr": round(avg_win_rr, 2),
    }


def suggest_range(symbol):
    price_map = {
        "BTCUSDT": (5, 35, 5),
        "ETHUSDT": (0.3, 2.0, 0.3),
        "BNBUSDT": (0.3, 2.0, 0.3),
        "SOLUSDT": (0.02, 0.15, 0.02),
        "AVAXUSDT": (0.01, 0.08, 0.01),
        "LINKUSDT": (0.01, 0.06, 0.01),
        "XRPUSDT": (0.002, 0.015, 0.002),
    }
    return price_map.get(symbol, (0.1, 1.0, 0.1))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="min_fvg_size parameter sweep")
    parser.add_argument("--symbol", type=str, help="Coin symbol")
    parser.add_argument("--all", action="store_true", help="Sweep all coins")
    args = parser.parse_args()

    coins = []
    if args.all:
        from coins_config import COINS

        coins = list(COINS.keys())
    elif args.symbol:
        coins = [args.symbol.upper()]
    else:
        parser.print_help()
        sys.exit(0)

    for sym in coins:
        lo, hi, step = suggest_range(sym)
        values = [round(lo + i * step, 3) for i in range(int((hi - lo) / step) + 1)]
        print(f"\n{'='*80}")
        print(f"  {sym} — min_fvg_size sweep ({lo} to {hi}, step={step})")
        print(f"{'='*80}")
        print(
            f"  {'fvg':>8} {'işlem':>6} {'WR':>6} {'PnL':>10} {'DD':>6} {'PF':>6} {'TP%':>6} {'AvgR':>6}"
        )
        print(f"  {'-'*56}")

        results = []
        for val in values:
            r = run_test(sym, val)
            if r is None:
                continue
            results.append((val, r))
            print(
                f"  {val:>8.3f} {r['trades']:>6} {r['wr']:>5.1f}% {r['pnl']:>+9.2f} {r['dd']:>5.1f}% {r['pf']:>5.2f} {r['tp_rate']:>5.1f}% {r['avg_rr']:>+5.2f}"
            )

        if results:
            best = max(results, key=lambda x: x[1]["pnl"])
            print(
                f"\n  BEST: min_fvg_size = {best[0]} → PnL={best[1]['pnl']:+.2f} WR={best[1]['wr']:.1f}% Trades={best[1]['trades']} DD={best[1]['dd']:.1f}%"
            )
