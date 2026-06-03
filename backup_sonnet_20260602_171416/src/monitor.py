"""
debug_monitor.py
----------------
Minimal runtime observability module for live trading systems.

Rules:
- No trading logic
- No decision making
- No strategy code
- No external dependencies
- Only state tracking + health reporting
"""

import contextlib
import time

# ---------------------------------------------------------------------------
# Internal state store
# ---------------------------------------------------------------------------

_state: dict = {
    # per-symbol tick times  { symbol: float (epoch) }
    "last_tick_time": {},
    # global event times
    "last_signal_time": None,
    "last_order_time": None,
    "last_fill_time": None,
    # per-symbol counters  { symbol: int }
    "signal_count": {},
    "rejected_count": {},
    "order_count": {},
    # ADDED: per-symbol fill tracking
    "fill_count": {},
    # ADDED: per-symbol last event timestamps
    "last_signal_time_per_symbol": {},
    "last_order_time_per_symbol": {},
    "last_fill_time_per_symbol": {},
    # optional reason logs (last N entries)
    "_signal_reasons": [],
    "_reject_reasons": [],
}

_REASON_LOG_LIMIT = 50  # keep last 50 reason strings in memory

# STALE threshold: no tick for this many seconds → STALE
STALE_SECONDS: float = 360.0

# DEAD threshold: no tick for this many seconds → DEAD
DEAD_SECONDS: float = 600.0


# ---------------------------------------------------------------------------
# Public update hooks  (call-and-forget; never raise)
# ---------------------------------------------------------------------------


def update_tick(symbol: str) -> None:
    """Call immediately after a market data tick is received for `symbol`."""
    with contextlib.suppress(Exception):
        _state["last_tick_time"][symbol] = time.time()


def update_signal(symbol: str, reason: str | None = None) -> None:
    """Call immediately after a trading signal is generated for `symbol`."""
    try:
        now = time.time()
        _state["last_signal_time"] = now
        _state["signal_count"][symbol] = _state["signal_count"].get(symbol, 0) + 1
        # ADDED: per-symbol last signal time
        _state["last_signal_time_per_symbol"][symbol] = now
        if reason:
            _append_reason(_state["_signal_reasons"], symbol, reason, now)
    except Exception:
        pass


def update_order(symbol: str) -> None:
    """Call immediately after an order is submitted for `symbol`."""
    try:
        now = time.time()
        _state["last_order_time"] = now
        _state["order_count"][symbol] = _state["order_count"].get(symbol, 0) + 1
        # ADDED: per-symbol last order time
        _state["last_order_time_per_symbol"][symbol] = now
    except Exception:
        pass


def update_fill(symbol: str) -> None:
    """Call immediately after an execution fill is confirmed for `symbol`."""
    try:
        now = time.time()
        _state["last_fill_time"] = now
        # ADDED: per-symbol fill count and last fill time
        _state["fill_count"][symbol] = _state["fill_count"].get(symbol, 0) + 1
        _state["last_fill_time_per_symbol"][symbol] = now
    except Exception:
        pass


def update_reject(symbol: str, reason: str | None = None) -> None:
    """Call immediately after a signal/order is rejected (risk filter, etc.)."""
    try:
        now = time.time()
        _state["rejected_count"][symbol] = _state["rejected_count"].get(symbol, 0) + 1
        if reason:
            _append_reason(_state["_reject_reasons"], symbol, reason, now)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public reason log queries (ADDED)
# ---------------------------------------------------------------------------


def get_signal_reasons(limit: int | None = None) -> list:
    """Return recent signal reasons (newest first)."""
    reasons = list(reversed(_state["_signal_reasons"]))
    return reasons[:limit] if limit else reasons


def get_reject_reasons(limit: int | None = None) -> list:
    """Return recent reject reasons (newest first)."""
    reasons = list(reversed(_state["_reject_reasons"]))
    return reasons[:limit] if limit else reasons


# ---------------------------------------------------------------------------
# Public health query
# ---------------------------------------------------------------------------


def get_health(symbol: str | None = None) -> dict:
    """
    Return a health snapshot.

    If `symbol` is provided → per-symbol view.
    If `symbol` is None     → aggregate view across all tracked symbols.

    Health status:
        LIVE  — last tick within STALE_SECONDS
        STALE — last tick between STALE_SECONDS and DEAD_SECONDS ago
        DEAD  — no tick ever, or last tick older than DEAD_SECONDS
    """
    now = time.time()

    if symbol:
        symbols = [symbol]
    else:
        # union of all symbols seen across all counters
        symbols = list(
            set(_state["last_tick_time"].keys())
            | set(_state["signal_count"].keys())
            | set(_state["rejected_count"].keys())
            | set(_state["order_count"].keys())
            | set(_state["fill_count"].keys())  # ADDED
        )

    # --- per-symbol health blocks ---
    symbol_health = {}

    def _age(ts):
        return round(now - ts, 2) if ts else None

    for sym in symbols:
        last_tick = _state["last_tick_time"].get(sym)
        if last_tick is None:
            age = None
            status = "DEAD"
        else:
            age = round(now - last_tick, 2)
            if age <= STALE_SECONDS:
                status = "LIVE"
            elif age <= DEAD_SECONDS:
                status = "STALE"
            else:
                status = "DEAD"

        symbol_health[sym] = {
            "status": status,
            "seconds_since_last_tick": age,
            "signal_count": _state["signal_count"].get(sym, 0),
            "rejected_count": _state["rejected_count"].get(sym, 0),
            "order_count": _state["order_count"].get(sym, 0),
            # added fields
            "fill_count": _state["fill_count"].get(sym, 0),
            "last_signal_seconds": _age(_state["last_signal_time_per_symbol"].get(sym)),
            "last_order_seconds": _age(_state["last_order_time_per_symbol"].get(sym)),
            "last_fill_seconds": _age(_state["last_fill_time_per_symbol"].get(sym)),
        }

    # --- aggregate timing ---
    aggregate = {
        "symbols": symbol_health,
        "last_signal_seconds": _age(_state["last_signal_time"]),
        "last_order_seconds": _age(_state["last_order_time"]),
        "last_fill_seconds": _age(_state["last_fill_time"]),
    }

    # If a single symbol was requested, flatten for convenience
    if symbol and symbol in symbol_health:
        result = symbol_health[symbol].copy()
        result.update(
            {
                "symbol": symbol,
                "last_signal_seconds": aggregate["last_signal_seconds"],
                "last_order_seconds": aggregate["last_order_seconds"],
                "last_fill_seconds": aggregate["last_fill_seconds"],
            }
        )
        return result

    return aggregate


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _append_reason(log: list, symbol: str, reason: str, ts: float) -> None:
    """Append a reason entry; trim to _REASON_LOG_LIMIT."""
    log.append({"symbol": symbol, "reason": reason, "ts": ts})
    if len(log) > _REASON_LOG_LIMIT:
        del log[0]
