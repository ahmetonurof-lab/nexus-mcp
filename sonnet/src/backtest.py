"""
backtest.py
-----------
NEXUS V3 Backtesting Engine

Simulates the full trading pipeline (analyzer → state machine → trader)
using historical OHLCV data. No live exchange connection required.

Usage:
    from backtest import BacktestEngine

    engine = BacktestEngine("BTCUSDT")
    engine.load_data("data/btcusdt_1h.json")
    engine.run()
    engine.report()

Or with automatic data loading from Binance:
    engine = BacktestEngine("BTCUSDT")
    engine.run()
    engine.report()
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
from dataclasses import dataclass

import config

logger = logging.getLogger("nexus.backtest")

# ---------------------------------------------------------------------------
# Performance Data
# ---------------------------------------------------------------------------


@dataclass
class BacktestTrade:
    """A single completed trade from the backtest."""

    symbol: str
    direction: str  # LONG / SHORT
    entry_time: int
    entry_price: float
    exit_time: int | None = None
    exit_price: float | None = None
    size: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # TP / SL / MANUAL
    bars_held: int = 0
    setup_type: str = ""  # CASE_A / CASE_C / ADAPTIVE


@dataclass
class BacktestMetrics:
    """Aggregate performance metrics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_bars_held: float = 0.0
    longs_count: int = 0
    shorts_count: int = 0


# ---------------------------------------------------------------------------
# Virtual Exchange — No real API calls
# ---------------------------------------------------------------------------


class VirtualExchange:
    """
    Simulates exchange execution for backtesting.

    - Fills orders at next bar's open/close with configurable slippage
    - Tracks virtual balance, positions, and P&L
    - No external dependencies or API calls
    """

    def __init__(self, initial_balance: float = 10000.0, leverage: int = 10):
        self.balance = initial_balance
        self.leverage = leverage
        self.initial_balance = initial_balance
        self.positions: dict[str, dict] = {}  # symbol → position info
        self.trade_history: list[BacktestTrade] = []
        self.equity_curve: list[float] = [initial_balance]
        self._current_trades: dict[str, BacktestTrade] = {}

    @property
    def equity(self) -> float:
        """Current equity = balance + unrealized PnL."""
        total = self.balance
        for sym, pos in self.positions.items():
            if pos["size"] != 0:
                # Unrealized PnL approximated (uses last known price)
                if pos["direction"] == "LONG":
                    total += pos["size"] * (pos.get("mark_price", pos["entry_price"]) - pos["entry_price"])
                else:
                    total += pos["size"] * (pos["entry_price"] - pos.get("mark_price", pos["entry_price"]))
        return total

    def open_position(
        self,
        symbol: str,
        direction: str,
        price: float,
        risk_pct: float = 0.005,
        setup_type: str = "",
    ) -> float | None:
        """
        Open a virtual position at `price`.

        Returns position size if successful, None if insufficient balance.
        """
        risk_amount = self.balance * risk_pct
        position_size = (risk_amount * self.leverage) / price if price > 0 else 0.0
        if position_size <= 0 or risk_amount <= 0:
            return None

        # Apply slippage
        if direction == "LONG":
            entry_price = price * (1 + config.SLIPPAGE_ENTRY)
        else:
            entry_price = price * (1 - config.SLIPPAGE_ENTRY)

        margin_required = position_size * entry_price / self.leverage
        if margin_required > self.balance:
            return None

        self.positions[symbol] = {
            "direction": direction,
            "entry_price": entry_price,
            "size": position_size,
            "mark_price": entry_price,
        }

        trade = BacktestTrade(
            symbol=symbol,
            direction=direction,
            entry_time=int(time.time()),
            entry_price=entry_price,
            size=position_size,
            setup_type=setup_type,
        )
        self._current_trades[symbol] = trade

        logger.info("[BACKTEST] OPEN %s %s %.2f @ %.5f", symbol, direction, position_size, entry_price)
        return position_size

    def close_position(
        self,
        symbol: str,
        price: float,
        reason: str = "MANUAL",
    ) -> BacktestTrade | None:
        """
        Close an open virtual position at `price`.

        Returns the completed BacktestTrade or None if no position exists.
        """
        pos = self.positions.pop(symbol, None)
        if pos is None:
            return None

        # Apply slippage
        if pos["direction"] == "LONG":
            exit_price = price * (1 - config.SLIPPAGE_EXIT)
        else:
            exit_price = price * (1 + config.SLIPPAGE_EXIT)

        if pos["direction"] == "LONG":
            pnl = pos["size"] * (exit_price - pos["entry_price"])
        else:
            pnl = pos["size"] * (pos["entry_price"] - exit_price)

        self.balance += pnl

        trade = self._current_trades.pop(symbol, None)
        if trade is None:
            trade = BacktestTrade(
                symbol=symbol, direction=pos["direction"], entry_price=pos["entry_price"], entry_time=0
            )

        trade.exit_time = int(time.time())
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_pct = (
            (pnl / (pos["size"] * pos["entry_price"] / self.leverage)) * 100
            if pos["size"] * pos["entry_price"] > 0
            else 0.0
        )
        trade.exit_reason = reason
        self.trade_history.append(trade)

        self.equity_curve.append(self.equity)

        logger.info("[BACKTEST] CLOSE %s %s pnl=%.2f reason=%s", symbol, pos["direction"], pnl, reason)
        return trade

    def update_mark_price(self, symbol: str, price: float) -> None:
        """Update mark price for unrealized PnL calculation."""
        if symbol in self.positions:
            self.positions[symbol]["mark_price"] = price


# ---------------------------------------------------------------------------
# Data Loader
# ---------------------------------------------------------------------------


def load_ohlcv_from_csv(filepath: str, timeframe: str = "15m") -> list[dict]:
    """
    Load OHLCV data from CSV file.

    Expected columns: timestamp, open, high, low, close, volume
    Timestamp can be unix ms or ISO format string.
    """
    rows: list[dict] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ts = int(row.get("timestamp", 0))
                rows.append(
                    {
                        "timestamp": ts,
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": float(row.get("volume", 0)),
                        "timeframe": timeframe,
                    }
                )
    except Exception as e:
        logger.error("CSV yüklenemedi %s: %s", filepath, e)
    return rows


def load_ohlcv_from_json(filepath: str, timeframe: str = "15m") -> list[dict]:
    """
    Load OHLCV data from JSON file.

    Expected format: list of dicts with keys: timestamp, open, high, low, close, volume
    or dict with "data" key containing the list.
    """
    try:
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.error("JSON yüklenemedi %s: %s", filepath, e)
        return []

    if isinstance(raw, dict):
        raw = raw.get("data", raw.get("klines", raw.get("bars", [])))

    rows = []
    for item in raw:
        rows.append(
            {
                "timestamp": int(item.get("timestamp", item.get("t", 0))),
                "open": float(item.get("open", item.get("o", 0))),
                "high": float(item.get("high", item.get("h", 0))),
                "low": float(item.get("low", item.get("l", 0))),
                "close": float(item.get("close", item.get("c", 0))),
                "volume": float(item.get("volume", item.get("v", 0))),
                "timeframe": timeframe,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """
    Full pipeline backtesting engine.

    Simulates the trading pipeline bar-by-bar using historical data:
      DataLoader → Analyzer → EventRouter → StateMachine → VirtualExchange

    Usage:
        engine = BacktestEngine("BTCUSDT")
        engine.load_csv("data/btcusdt.csv")
        engine.run()
        print(engine.report())
    """

    def __init__(
        self,
        symbol: str,
        initial_balance: float | None = None,
        leverage: int | None = None,
    ):
        self.symbol = symbol
        self.initial_balance = initial_balance or config.INITIAL_BALANCE
        self.leverage = leverage or config.LEVERAGE

        # Components (lazy init)
        self._analyzer = None
        self._state_machine = None
        self._event_router = None
        self._virtual_exchange = None

        # Data buffers
        self._bars_d1: list = []
        self._bars_h4: list = []
        self._bars_h1: list = []
        self._bars_15m: list = []
        self._bars_m1: list = []

        # Performance tracking
        self._metrics: BacktestMetrics | None = None
        self._bar_count = 0
        self._start_time: float = 0.0
        self._end_time: float = 0.0

        # Trade log (per-bar snapshot)
        self.bar_log: list[dict] = []

    def _lazy_init(self):
        """Lazy-initialize all components."""
        if self._analyzer is not None:
            return

        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from analyzer import MarketAnalyzer
            from event_router import EventRouter
            from state_machine import SetupState, StateMachine

        self._analyzer = MarketAnalyzer(self.symbol)
        self._state_machine = StateMachine()
        self._event_router = EventRouter(self._state_machine)
        self._virtual_exchange = VirtualExchange(
            initial_balance=self.initial_balance,
            leverage=self.leverage,
        )
        self._state_machine.config = config  # Attach config for getattr lookups
        self._SetupState = SetupState

    # ── Data loading ─────────────────────────────────

    def load_csv(self, filepath: str, timeframe: str = "15m") -> int:
        """Load data from CSV file. Returns row count."""
        rows = load_ohlcv_from_csv(filepath, timeframe)
        self._feed_bars(rows, timeframe)
        return len(rows)

    def load_json(self, filepath: str, timeframe: str = "15m") -> int:
        """Load data from JSON file. Returns row count."""
        rows = load_ohlcv_from_json(filepath, timeframe)
        self._feed_bars(rows, timeframe)
        return len(rows)

    def load_from_dicts(self, rows: list[dict], timeframe: str = "15m") -> None:
        """Load data from a list of dicts directly."""
        self._feed_bars(rows, timeframe)

    def _feed_bars(self, rows: list[dict], timeframe: str) -> None:
        """Convert raw dicts to Bar objects and buffer by timeframe."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar

        bars = []
        for i, row in enumerate(rows):
            bars.append(
                Bar(
                    index=i,
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    volume=row.get("volume", 0),
                    is_closed=True,
                    timestamp=row.get("timestamp", i),
                )
            )

        if timeframe in ("1d", "1D", "D1", "daily"):
            self._bars_d1 = bars
        elif timeframe in ("4h", "4H", "H4", "240m"):
            self._bars_h4 = bars
        elif timeframe in ("1h", "1H", "H1", "60m"):
            self._bars_h1 = bars
        elif timeframe in ("15m", "15M", "M15"):
            self._bars_15m = bars
        elif timeframe in ("1m", "1M", "M1"):
            self._bars_m1 = bars
        else:
            logger.warning("Bilinmeyen timeframe: %s — %d bar yüklendi", timeframe, len(bars))
            self._bars_15m = bars  # fallback

    def _resample_h4(self) -> list:
        """Resample 1H bars to H4 if H4 data not directly provided."""
        if self._bars_h4:
            return self._bars_h4
        if not self._bars_h1:
            return []
        # Merge every 4 H1 bars into H4
        h4: list = []
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar

        for i in range(0, len(self._bars_h1), 4):
            chunk = self._bars_h1[i : i + 4]
            if len(chunk) < 4:
                break
            h4.append(
                Bar(
                    index=i // 4,
                    open=chunk[0].open,
                    high=max(b.high for b in chunk),
                    low=min(b.low for b in chunk),
                    close=chunk[-1].close,
                    volume=sum(b.volume for b in chunk),
                    is_closed=True,
                    timestamp=chunk[-1].timestamp,
                )
            )
        return h4

    def _resample_h1(self) -> list:
        """Resample 15m bars to H1 if H1 data not directly provided."""
        if self._bars_h1:
            return self._bars_h1
        if not self._bars_15m:
            return []
        h1: list = []
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar

        for i in range(0, len(self._bars_15m), 4):
            chunk = self._bars_15m[i : i + 4]
            if len(chunk) < 4:
                break
            h1.append(
                Bar(
                    index=i // 4,
                    open=chunk[0].open,
                    high=max(b.high for b in chunk),
                    low=min(b.low for b in chunk),
                    close=chunk[-1].close,
                    volume=sum(b.volume for b in chunk),
                    is_closed=True,
                    timestamp=chunk[-1].timestamp,
                )
            )
        return h1

    def _resample_d1(self) -> list:
        """Resample H4 bars to D1 if D1 data not directly provided."""
        if self._bars_d1:
            return self._bars_d1
        h4_data = self._resample_h4()
        if not h4_data:
            return []
        d1: list = []
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar

        for i in range(0, len(h4_data), 6):
            chunk = h4_data[i : i + 6]
            if len(chunk) < 6:
                break
            d1.append(
                Bar(
                    index=i // 6,
                    open=chunk[0].open,
                    high=max(b.high for b in chunk),
                    low=min(b.low for b in chunk),
                    close=chunk[-1].close,
                    volume=sum(b.volume for b in chunk),
                    is_closed=True,
                    timestamp=chunk[-1].timestamp,
                )
            )
        return d1

    # ── Data completeness check ──────────────────────

    def _check_data_ready(self) -> bool:
        """Check if enough data is available for analysis."""
        return (
            len(self._bars_d1) >= 10
            and len(self._bars_h4) >= 20
            and len(self._bars_h1) >= 50
            and len(self._bars_15m) >= 55
            and len(self._bars_m1) >= 100
        )

    # ── Main run loop ────────────────────────────────

    def run(self) -> BacktestMetrics:
        """
        Run the backtest simulation.

        Processes data bar-by-bar through the full pipeline.
        Returns performance metrics.
        """
        self._lazy_init()
        self._start_time = time.time()

        # Ensure H4 and H1 data via resampling if needed
        if not self._bars_h4:
            self._bars_h4 = self._resample_h4()
        if not self._bars_h1:
            self._bars_h1 = self._resample_h1()
        if not self._bars_d1:
            self._bars_d1 = self._resample_d1()

        if not self._check_data_ready():
            logger.warning(
                "Yetersiz veri: D1=%d H4=%d H1=%d 15m=%d 1m=%d",
                len(self._bars_d1),
                len(self._bars_h4),
                len(self._bars_h1),
                len(self._bars_15m),
                len(self._bars_m1),
            )
            logger.warning("Minimum gereken: D1>=10 H4>=20 H1>=50 15m>=55 1m>=100")
            return BacktestMetrics()

        logger.info(
            "Backtest başlıyor: %s | D1=%d H4=%d H1=%d 15m=%d 1m=%d",
            self.symbol,
            len(self._bars_d1),
            len(self._bars_h4),
            len(self._bars_h1),
            len(self._bars_15m),
            len(self._bars_m1),
        )

        # Simulate bar-by-bar 1m processing
        # For each 1m bar, check if any HTF bar is newly closed, run analyzer
        for i in range(len(self._bars_m1)):
            bar_m1 = self._bars_m1[i]
            self._virtual_exchange.update_mark_price(self.symbol, bar_m1.close)

            # Every 15 1m bars → run 15m analysis
            if i % 15 == 0 and self._bars_15m:
                m15_idx = min(i // 15, len(self._bars_15m) - 1)
                current_15m_bars = self._bars_15m[: m15_idx + 1]

                # Run analyzer
                try:
                    events = self._analyzer.analyze(
                        bars_d1=self._bars_d1,
                        bars_h4=self._bars_h4,
                        bars_h1=self._bars_h1,
                        bars_15m=current_15m_bars,
                        bars_m1=self._bars_m1[: i + 1],
                    )

                    # Publish events to state machine
                    for event in events:
                        self._event_router.publish(self.symbol, event)

                    # Check retrace
                    self._state_machine.check_retrace(self.symbol, current_15m_bars[-1])
                    self._state_machine.check_poi_retrace(self.symbol, current_15m_bars[-1])

                    # Check for LTF confirm on the 15m bar close
                    last_15m = current_15m_bars[-1]
                    if last_15m.is_closed:
                        # Simulate LTF confirm when state is WAIT_CONFIRM
                        state = self._state_machine.get(self.symbol)
                        if state and hasattr(state, "state"):
                            from state_machine import SetupState

                            if state.state in (SetupState.WAIT_CONFIRM, SetupState.WAIT_POI_CONFIRM):
                                self._event_router.publish(
                                    self.symbol,
                                    {
                                        "type": "LTF_CONFIRM",
                                        "symbol": self.symbol,
                                        "direction": state.direction,
                                        "close": last_15m.close,
                                        "tf": "15m",
                                    },
                                )

                    # Evaluate final state
                    self._state_machine._evaluate(
                        self._state_machine.get(self.symbol),
                        last_closed_bar=current_15m_bars[-1],
                    )

                    # Check if READY_TO_ENTER and no position → open virtual trade
                    state = self._state_machine.get(self.symbol)
                    if state and hasattr(state, "state"):
                        if state.state == SetupState.READY_TO_ENTER:
                            if self.symbol not in self._virtual_exchange.positions:
                                self._virtual_exchange.open_position(
                                    symbol=self.symbol,
                                    direction=state.direction or "LONG",
                                    price=last_15m.close,
                                    risk_pct=config.RISK_PER_TRADE,
                                    setup_type="CASE_A",
                                )
                                # Reset state machine after entry
                                state.state = SetupState.ENTERED

                except Exception as e:
                    logger.debug("[BACKTEST] analyze hatası (beklenen): %s", e)

            # Check SL/TP for open positions (simplified ATR-based)
            if self.symbol in self._virtual_exchange.positions:
                pos = self._virtual_exchange.positions[self.symbol]
                direction = pos["direction"]
                entry = pos["entry_price"]

                # Simplified risk/reward: 1% SL, 2% TP (config overridable)
                sl_pct = getattr(config, "BACKTEST_SL_PCT", 0.01)
                tp_pct = getattr(config, "BACKTEST_TP_PCT", 0.02)
                sl_distance = entry * sl_pct
                tp_distance = entry * tp_pct

                if direction == "LONG":
                    if bar_m1.low <= entry - sl_distance:
                        self._virtual_exchange.close_position(self.symbol, entry - sl_distance, "SL")
                    elif bar_m1.high >= entry + tp_distance:
                        self._virtual_exchange.close_position(self.symbol, entry + tp_distance, "TP")
                else:  # SHORT
                    if bar_m1.high >= entry + sl_distance:
                        self._virtual_exchange.close_position(self.symbol, entry + sl_distance, "SL")
                    elif bar_m1.low <= entry - tp_distance:
                        self._virtual_exchange.close_position(self.symbol, entry - tp_distance, "TP")

            self._bar_count += 1

        self._end_time = time.time()
        self._metrics = self._compute_metrics()
        return self._metrics

    # ── Metrics ──────────────────────────────────────

    def _compute_metrics(self) -> BacktestMetrics:
        """Compute performance metrics from trade history."""
        exchange = self._virtual_exchange
        trades = exchange.trade_history
        if not trades:
            return BacktestMetrics()

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in trades)

        metrics = BacktestMetrics(
            total_trades=len(trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=len(wins) / len(trades) * 100 if trades else 0,
            total_pnl=total_pnl,
            total_pnl_pct=(total_pnl / exchange.initial_balance) * 100 if exchange.initial_balance else 0,
            avg_win=sum(t.pnl for t in wins) / len(wins) if wins else 0,
            avg_loss=sum(t.pnl for t in losses) / len(losses) if losses else 0,
            profit_factor=abs(sum(t.pnl for t in wins) / sum(abs(t.pnl) for t in losses))
            if losses and sum(abs(t.pnl) for t in losses) > 0
            else 0,
            avg_bars_held=sum(t.bars_held for t in trades) / len(trades) if trades else 0,
            longs_count=sum(1 for t in trades if t.direction == "LONG"),
            shorts_count=sum(1 for t in trades if t.direction == "SHORT"),
        )

        # Max drawdown
        peak = exchange.initial_balance
        max_dd = 0.0
        max_dd_pct = 0.0
        equity_curve = [exchange.initial_balance] + [exchange.equity]  # simplified
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = (dd / peak) * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        metrics.max_drawdown = max_dd
        metrics.max_drawdown_pct = max_dd_pct

        return metrics

    def report(self) -> dict:
        """
        Generate a human-readable backtest report.

        Returns a dict with all metrics and trade summary.
        """
        if self._metrics is None:
            self._metrics = self._compute_metrics()

        m = self._metrics
        elapsed = self._end_time - self._start_time if self._end_time else 0

        report = {
            "symbol": self.symbol,
            "initial_balance": round(self._virtual_exchange.initial_balance, 2)
            if self._virtual_exchange
            else self.initial_balance,
            "final_balance": round(self._virtual_exchange.balance, 2)
            if self._virtual_exchange
            else self.initial_balance,
            "total_trades": m.total_trades,
            "win_rate": f"{m.win_rate:.1f}%",
            "total_pnl": round(m.total_pnl, 2),
            "total_pnl_pct": f"{m.total_pnl_pct:.2f}%",
            "avg_win": round(m.avg_win, 2),
            "avg_loss": round(m.avg_loss, 2),
            "profit_factor": round(m.profit_factor, 2),
            "max_drawdown": round(m.max_drawdown, 2),
            "max_drawdown_pct": f"{m.max_drawdown_pct:.2f}%",
            "longs": m.longs_count,
            "shorts": m.shorts_count,
            "avg_bars_held": round(m.avg_bars_held, 1),
            "bars_processed": self._bar_count,
            "elapsed_seconds": round(elapsed, 2),
        }

        logger.info("=" * 50)
        logger.info("BACKTEST RAPORU — %s", self.symbol)
        logger.info("=" * 50)
        for k, v in report.items():
            logger.info("  %-20s: %s", k, v)
        logger.info("=" * 50)

        return report


# ---------------------------------------------------------------------------
# Quick run helper
# ---------------------------------------------------------------------------


def quick_backtest(
    symbol: str,
    data_path: str | None = None,
    timeframe: str = "15m",
    initial_balance: float = 10000.0,
) -> dict:
    """
    Quick one-shot backtest.

    Args:
        symbol: Trading pair symbol (e.g. "BTCUSDT")
        data_path: Path to OHLCV data file (CSV or JSON). If None, uses config.DATA_DIR/symbol.csv
        timeframe: Data timeframe (default "15m")

    Returns:
        dict: Performance report
    """
    engine = BacktestEngine(symbol, initial_balance=initial_balance)

    if data_path is None:
        data_path = os.path.join(config.DATA_DIR, f"{symbol.lower()}_{timeframe}.csv")

    if data_path.endswith(".csv"):
        count = engine.load_csv(data_path, timeframe)
    elif data_path.endswith(".json"):
        count = engine.load_json(data_path, timeframe)
    else:
        raise ValueError(f"Desteklenmeyen dosya formatı: {data_path} (csv veya json olmalı)")

    logger.info("%d bar yüklendi: %s", count, data_path)
    engine.run()
    return engine.report()
