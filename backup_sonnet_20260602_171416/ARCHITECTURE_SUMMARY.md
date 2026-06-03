# NEXUS V2 — Architecture Summary

## 1. Data Pipeline (WebSocket → Execution)

```
BinanceWSHub (websocket.py)
  → Combined WebSocket stream (N symbols × 4 TFs)
  → _BarBuffer.feed() builds OHLCV bars
  → Calls registered 5m-close callback
    → LiveTradingBot._on_5m_close() (main.py)
      → MarketAnalyzer.analyze() (analyzer.py)
        → pivot.py: SwingStateManager.ingest() → detect swing high/low
        → choch.py: refresh_choch_list() → detect_chochs()
        → fvg.py: refresh_fvg_list() → detect_fvgs() + update_fvg_states()
        → fvg.py: compute_fvg_quality() → FVGQuality score
        → check_ltf_trigger() → 5m engulfing / 5m CHoCH confirmation
      → RiskManager.evaluate() (risk_manager.py)
        → TradeParams (entry, sl, tp, lot)
      → LiveExecutor.send_order() (trader.py)
        → ExchangeClient.create_order() → BinanceHTTPClient
        → SL: create_algo_order(STOP_MARKET) / TP: create_algo_order(TAKE_PROFIT_MARKET)
```

---

## 2. Component Roles

| File | Role |
|---|---|
| **main.py** | `LiveTradingBot` — Orchestrator: startup cleanup, prefills buffers, syncs positions, wires the 5m callback, manages `active_trades`, runs health/API server loops. Does NOT contain analysis logic. |
| **analyzer.py** | `MarketAnalyzer` — Per-symbol analysis engine. Calls H4 trend direction, 15m CHoCH→FVG→quality pipeline, 5m LTF trigger. Owns `AnalysisResult`. |
| **websocket.py** | `BinanceWSHub` — WebSocket connection manager. Multi-symbol, multi-timeframe kline streaming via `_BarBuffer`. Heartbeat monitor, auto-reconnect, user data stream support. |
| **trader.py** | `ExchangeClient` + `LiveExecutor` — Order execution layer. Market entry, algo SL/TP creation via Binance REST. Cooldown, duplicate prevention, emergency close. |
| **models.py** | Dataclasses: `Bar`, `FVG`, `CHoCH`, `SwingPoint`, `FVGQuality`. Foundation layer with zero internal imports. |
| **config.py** | Global constants: symbols, thresholds (ADX, FVG score, impulsive), risk params, tier maps, symbol-specific overrides. |
| **indicators.py** | ADX, ATR, EMA (numba JIT). Pure computation, models-only dependency. |
| **pivot.py** | `SwingStateManager` — Fractal swing high/low detection. Persistent pivot memory with mitigation tracking. |
| **choch.py** | CHoCH detection — scans swing breaks with SMC micro-structure filters (body ratio, SFP follow-through, ATR size filter). |
| **fvg.py** | FVG detection + state management + quality scoring. `detect_fvgs()`, `update_fvg_states()`, `find_latest_unfilled_fvg()`, `compute_fvg_quality()`. |
| **scoring.py** | Higher-level scoring aggregation: `evaluate_trade_signal()`, `detect_market_regime()`, `analyze_confluence()`. Re-imports from fvg.py. **Used mainly as library, NOT by the live bot directly** (analyzer.py calls fvg.py functions directly). |
| **risk_manager.py** | `RiskManager` — SL/TP calculation (tier-based buffers), lot sizing (balance × risk × leverage), ADX sizing, breakeven/trailing logic. |
| **volume_profile.py** | `VolumeProfile` — HVN/LVN detection, POC as TP magnet. Score adjuster (not veto), session-cached. |
| **monitor.py** | Health stats aggregation for dashboard. |
| **performance.py** | Trade recording, leaderboard. |
| **exchange.py** | `BinanceHTTPClient` — Low-level REST wrapper (klines, orders, positions, tick sizes). |

---

## 3. RAM State Memory

| State | Location | Structure |
|---|---|---|
| **active_trades** | `LiveTradingBot.active_trades` (main.py) | `dict[str, dict]` — `{symbol: {direction, entry, initial_sl, current_sl, tp, sl_order_id, tp_order_id, lot, status, pnl, ...}}` |
| **_pending_symbols** | `LiveExecutor._pending_symbols` (trader.py) | `set[str]` — symbols with in-flight orders |
| **_used_fvg_signals** | `LiveTradingBot._used_fvg_signals` (main.py) | `dict[str, set]` — `{symbol: {(fvg_real_index, timeframe, direction), ...}}` — dedup signals per symbol |
| **trade_locks** | Module-level in main.py AND trader.py | `dict[str, asyncio.Lock]` — per-symbol async mutex |
| **last_trade_time** | Module-level in websocket.py | `dict[str, float]` — cooldown tracker (15min) |
| **_breakeven_log** | `LiveTradingBot._breakeven_log` (main.py) | `dict[str, dict]` — `{symbol: {count, adx_gt_35, last_time}}` |
| **_last_order_time** | `LiveExecutor._last_order_time` (trader.py) | `dict[str, float]` — per-symbol timestamp for executor cooldown |
| **_tick_size_cache** | Module-level in main.py | `dict[str, float]` |
| **fvgs / chochs** | `MarketAnalyzer.fvgs` / `.chochs` (analyzer.py) | `list[FVG]`, `list[CHoCH]` — per-analyzer-instance lists |
| **_choch_state** | `MarketAnalyzer._choch_state` (analyzer.py) | `SwingStateManager` instance — persistent swing memory per symbol |
| **Daily cache** | `DailyDataCache._cache` (main.py) | `dict[str, list[Bar]]` — D1 bars cached 24h |
| **bar buffers** | `BinanceWSHub._buffers` (websocket.py) | `dict[(sym, tf), _BarBuffer]` — rolling OHLCV for each sym×TF |
| **_last_seen** | `BinanceWSHub._last_seen` (websocket.py) | `dict[(sym, tf), float]` — heartbeat timestamps |
| **vp cache** | `VolumeProfile._cache` (volume_profile.py) | `dict[str, (session_ts, VPLevels)]` |

---

## 4. Logic Distribution

| Concern | File(s) | Details |
|---|---|---|
| **HTF Bias/Trend** | `analyzer.py::_trend_direction()` | H4 fractal swing break analysis (HH/HL, LL/LH). Determines `"long"` / `"short"` / `None`. Uses `pivot.py::find_swing_highs/lows` with `config.H4_SWING_*` params. |
| **FVG Extraction** | `fvg.py::detect_fvgs()` + `refresh_fvg_list()` + `find_latest_unfilled_fvg()` + `update_fvg_states()` | 3-bar imbalance scan, dedup, fill/invalidation tracking on each bar close. Called by analyzer.py on 15m bars. |
| **Vetoes (Giyotin)** | **analyzer.py** `is_valid_signal()`: direction=None, choch=None, direction↔choch mismatch, fvg=None, FVG age, threshold<br>**analyzer.py** `analyze()`: ADX < threshold block, impulsive sweep veto, 15m ADX < 20 in impulsive mode<br>**fvg.py** `compute_fvg_quality()`: CHoCH direction mismatch, premium/discount violation, sweep absent in reversal<br>**risk_manager.py** `evaluate()`: SL too wide, lot=0, min profit, gross/net RR |
| **Scoring** | `fvg.py::compute_fvg_quality()` — displacement×0.55 + size×0.25 + choch×0.10 + retest×0.10 (impulsive) OR sweep×0.25 + choch×0.25 + disp×0.25 + size×0.15 + retest×0.10 (reversal), then VP penalty (-0.20 HVN), clamped<br>`scoring.py::evaluate_trade_signal()` — adds confluence bonus, regime calibration. **Not used by live bot path** (bot calls fvg.py directly). |
