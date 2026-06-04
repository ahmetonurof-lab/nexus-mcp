# NEXUS V3 — AI Debug Reference
>
> **How to use:** Paste logs → AI maps to function + expected output → flags mismatch.
> Every function has: **SIGNATURE** → **EXPECTED LOG** → **ERROR SYMPTOMS**.

---

## 1. File → Job (1-line)

| File | Job |
|---|---|
| `models.py` | Bar, FVG, CHoCH, SwingPoint dataclasses. No internal imports. |
| `config.py` | All constants, symbols, risk params, thresholds. |
| `pivot.py` | Fractal swing high/low + SwingStateManager (persistent memory). |
| `indicators.py` | EMA, SMMA, ATR, ADX. Numba JIT. |
| `fvg.py` | FVG detection (3-candle imbalance). State: filled/invalidated. Retest check. Quality scoring. |
| `mss.py` | CHoCH/MSS detection. SMC micro-structure veto. LTFTriggerDetector (2 criteria). |
| `analyzer.py` | Event producer — no trade decisions. HTF bias → sweep → MSS → FVG → retrace → LTF. |
| `scoring.py` | Unified signal scoring: FVG quality + CHoCH integration + regime + confluence. |
| `event_router.py` | Publisher → StateMachine.update_from_event(). Zero decision logic. |
| `state_machine.py` | SymbolState dataclass + state transitions + event handlers. |
| `risk_manager.py` | 4H swing SL + 1H liquidity TP + lot sizing + stepped stops. |
| `trader.py` | ExchangeClient + LiveExecutor. MARKET order + SL/TP algo orders + position management. |
| `exchange.py` | BinanceHTTPClient. Raw REST, signed/unsigned, precision, kline, order. |
| `websocket.py` | BinanceWSHub. Multi-symbol × multi-TF WS + user data stream + heartbeat. |
| `main.py` | LiveTradingBot orchestration: WS hub + analyzer + state machine + executor. |
| `monitor.py` | Runtime counters: tick/signal/order/fill/reject + health endpoint. |
| `performance.py` | Trade history + leaderboard. |

---

## 2. Dependency Graph
```
models.py         (zero deps — foundation)
pivot.py ← models
indicators.py ← models
fvg.py ← pivot, indicators
mss.py ← pivot, indicators, fvg
analyzer.py ← pivot, indicators, fvg, mss
scoring.py ← fvg, mss
event_router.py ← analyzer  ──→  state_machine.py
                                   ↓
                              risk_manager.py
                                   ↓
exchange.py  ──→  trader.py  ← risk_manager
                       ↓
websocket.py  ──→  main.py  ← trader
                       ↓
                  monitor.py
                  performance.py
```

---

## 3. State Machine

```
IDLE ──SWEEP(15m)──▶ ARMED
ARMED ──MSS─────────▶ WAIT_RETRACE
WAIT_RETRACE ──RETRACE──▶ WAIT_CONFIRM
WAIT_CONFIRM ──LTF_CONFIRM──▶ READY_TO_ENTER
READY_TO_ENTER ──main.py──▶ ENTERED
ENTERED ──expire/invalidate──▶ EXPIRED
```

| State | Trigger Event | What Happens |
|---|---|---|
| IDLE → ARMED | SWEEP | `state.sweep_detected=True; state.state="ARMED"` |
| ARMED → WAIT_RETRACE | MSS | `state.mss_confirmed=True; state.state="WAIT_RETRACE"` |
| WAIT_RETRACE → WAIT_CONFIRM | RETRACE | `state.retrace_seen=True` (price inside active FVG) |
| WAIT_CONFIRM → READY_TO_ENTER | LTF_CONFIRM | `state.ltf_confirmed=True; state.state="READY_TO_ENTER"` |
| READY_TO_ENTER → ENTERED | main.py | `LiveExecutor.send_order()` |
| ENTERED → EXPIRED | timeout | `state.is_expired()` |

### Event Handlers
```python
_handle_htf_bias(state)    → state.direction = "LONG"|"SHORT", state.htf_bias set
_handle_htf_levels(state)  → state.h4_swing_level, state.h1_liquidity_level set
_handle_sweep(state)       → IDLE → ARMED
_handle_mss(state)         → ARMED → WAIT_RETRACE
_handle_fvg(state)         → FVG levels stored
_handle_retrace(state)     → WAIT_RETRACE → WAIT_CONFIRM
_handle_ltf(state)         → WAIT_CONFIRM → READY_TO_ENTER
_check_stale_state(state, current_time)   → Zombi ARMED/WAIT_* setup'ları 24saat (config.MAX_SETUP_WAIT_HOURS) sonra IDLE'a çeker
_check_invalidation(state, last_closed_bar) → Mum kapanışı mss_break_level'i yapısal kırarsa IDLE'a çeker (LONG: close < mss_break_level, SHORT: close > mss_break_level)
```

### _evaluate() Pre-Check Layer
```python
def _evaluate(self, state, current_time=None, last_closed_bar=None):
    if current_time is None: current_time = datetime.now()

    if self._check_stale_state(state, current_time):   # Zombi temizliği
        return
    if self._check_invalidation(state, last_closed_bar): # Yapısal kırılım
        return

    # ... sert kurallar (4 flag) ...
```
> Both pre-checks run **before** the 4-flag hard-gate. Stale check uses `state.created_at` (int timestamp) vs configurable `MAX_SETUP_WAIT_HOURS`. Invalidation uses `last_closed_bar.close` (not current_price) to avoid stop-hunt fakeouts.

---

## 4. Main Signal Chain (analyzer.py)

### 4.0 analyze() — Entry Point
```python
analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m5) -> list[dict]:
    bias = self._detect_htf_bias(bars_d1, bars_h4)   # → "LONG"|"SHORT"|None
    if bias is None: return []                        # ← CHAIN BREAKS

    # D1 bar değişti mi? → likidite havuzunu sıfırla
    if bars_d1:
        last_d1_idx = bars_d1[-1].index
        if last_d1_idx != self._last_d1_index:
            self._consumed_levels.clear()
            self._last_d1_index = last_d1_idx
            log.info("[RESET] %s gunluk likidite havuzu sifirlandi")

    events = [HTF_BIAS]
    events += HTF_LEVELS                              # h4_sl + h1_tp
    events += self._detect_sweep_15m(symbol, bars_15m, close, bias)  # → [SWEEP]
    events += self._detect_mss_events(symbol, bars_15m, bias)        # → [MSS]
    events += detect_fvgs(bars_15m, 60, bias, since_index=...)       # → [FVG]
    events += self._detect_retrace(symbol, fvgs, bar, bias)          # → [RETRACE] (3-stage)
    events += self._detect_ltf_confirm(symbol, fvgs, bars_m5, close) # → [LTF_CONFIRM]
    return events
```
> **EXPECTED LOG:** `"[ANALYZE] {symbol}: HTF bias={bias}"` / `"[RESET] {symbol} gunluk likidite havuzu sifirlandi"` (D1 bar change)
> **CHAIN BREAK LOG:** `"[ANALYZE] {symbol}: HTF bias yok, event uretilmiyor."`
>
> **ERROR:** bias=None persistently → `_detect_htf_bias()` broken or D1 data empty.
> **ERROR:** bias exists but events missing → check individual detector logs.
> **ERROR:** events produced but state machine stuck in IDLE → `event_router.py` or `SymbolState` stale.

---

### 4.1 _detect_htf_bias() — GATEKEEPER
```python
_detect_htf_bias(bars_d1, bars_h4) -> "LONG" | "SHORT" | None:
    # D1: lookback 25 bars, swing left=2 right=2
    d1_highs = find_swing_highs(bars_d1[-25:], left=2, right=2)
    d1_lows  = find_swing_lows(bars_d1[-25:], left=2, right=2)
    close = bars_d1[-1].close

    # last_bull_bos: highest swing high with close > swing.price
    # last_bear_bos: highest swing low  with close < swing.price
    # If none broken → None

    d1_bias = "LONG" if last_bull_bos >= last_bear_bos else "SHORT"

    # H4 teyit (same logic, H4_BOS_LOOKBACK)
    h4_bias = ...  # same algorithm on H4

    # D1-H4 resolution:
    #   H4=None     → "D1={} H4=belirsiz → D1 kazanir"
    #   H4==D1      → "D1={} H4={} → GUCLU bias"
    #   H4!=D1      → "D1={} H4={} → ZAYIF bias, D1 kazanir"

    return d1_bias   # always D1 wins on conflict
```
> **EXPECTED LOG:** `"D1=LONG H4=LONG → GUCLU bias"` or `"D1=LONG H4=SHORT → ZAYIF bias, D1 kazanir"`
>
> **ERROR:** Always None → lookback too small OR `find_swing_highs/lows` from `pivot.py` returning empty.
> **ERROR:** Bias flips every bar → market ranging, normal. Should produce many chain breaks.
> **ERROR:** D1=LONG H4=None always → H4 data not arriving (WS issue) OR H4 lookback too small.

---

### 4.2 _detect_sweep_15m() — LIQUIDITY HUNT
```python
_detect_sweep_15m(self, symbol, bars_15m, current_close, bias) -> list[dict]:
    consumed = self._consumed_levels.setdefault(symbol, set())
    events = []
    highs = find_swing_highs(bars_15m, left=3, right=3)
    lows  = find_swing_lows(bars_15m, left=3, right=3)

    if bias == "LONG":
        for sl in reversed(lows[-5:]):     # last 5 swing lows (most recent first)
            if sl.price in consumed:       # ← DEDUP: zaten tüketildiyse atla
                continue
            if close < sl.price:
                consumed.add(sl.price)
                events.append({"type": "SWEEP", "side": "SSL", "level": sl.price})
                break
    else:  # SHORT
        for sh in reversed(highs[-5:]):    # last 5 swing highs
            if sh.price in consumed:
                continue
            if close > sh.price:
                consumed.add(sh.price)
                events.append({"type": "SWEEP", "side": "BSL", "level": sh.price})
                break
    return events
```
> **EXPECTED LOG:** `"[SWEEP-CHECK] {symbol} | bias={bias} | close={price} | lows={} | highs={}"`
> **D1 RESET LOG:** `"[RESET] {symbol} gunluk likidite havuzu sifirlandi"`
>
> **ERROR:** Sweep same level repeatedly → `consumed` dedup not working (check `_consumed_levels` dict).
> **ERROR:** Sweep fires wrong side → bias passed incorrectly.
> **ERROR:** Never sweeps → 15m swing lists empty, pivot.py not detecting.
> **NOTE:** `@staticmethod` kaldırıldı, artık instance method. `_consumed_levels` D1 bar değişiminde sıfırlanır.

---

### 4.3 _detect_mss_events() — STRUCTURAL BREAK
```python
_detect_mss_events(self, symbol, bars_15m, bias) -> list[dict]:
    self._mss_state.ingest(bars_15m, left=3, right=3)
    chochs = detect_mss(bars_15m, self._mss_state, timeframe="15m")  # from mss.py
    for c in chochs:
        key = hash((c.bar_index, c.direction, c.level))
        if key in self._seen_mss:        # ← DEDUP
            continue
        self._seen_mss.add(key)

        direction = "LONG" if c.direction == "bullish" else "SHORT"
        if direction != bias:             # ← BIAS FILTER
            continue
        yield {"type": "MSS", "direction": direction, "level": c.level, "bar_index": c.bar_index}
```
> **THRESHOLD:** Only MSS whose direction == bias are emitted. Bar-index dedup via `_seen_mss` set.
>
> **EXPECTED LOG:** `"[ANALYZE] {symbol}: MSS detected direction={bias} level={price}"`
>
> **ERROR:** CHoCH fires but MSS never emitted → bias filter eating all CHoCHs.
> **ERROR:** Same MSS emitted repeatedly → `_seen_mss` dedup not working.
> **ERROR:** No MSS ever → `mss.py:detect_mss()` broken or SMC micro-veto too aggressive.

---

### 4.4 FVG Detection — IMBALANCE
```python
fvgs = detect_fvgs(
    bars_15m, lookback=60, timeframe="15m",
    min_fvg_size=MIN_FVG_SIZE, since_index=fvg_since  # MSS/sweep sonrasi
)
fvg_direction = "bullish" if bias == "LONG" else "bearish"
fvgs = [f for f in fvgs if f.direction == fvg_direction]  # bias filter

# Dedup: _emitted_fvg_ids ile her FVG bir kez emit edilir
new_fvgs = [f for f in fvgs if f.real_index not in self._emitted_fvg_ids]
for f in new_fvgs:
    self._emitted_fvg_ids.add(f.real_index)
```
> **THRESHOLD:** Only FVGs matching bias direction. Lookback=60 bars. `since_index` son yapısal event'ten (MSS/sweep) sonraki FVG'leri sınırlar.
>
> **EXPECTED LOG:** `"[ANALYZE] {symbol}: FVG detected direction=bullish upper={} lower={}"`
>
> **ERROR:** Zero FVGs — lookback too small, 15m bars sparse, or `fvg.py` pattern broken.
> **ERROR:** Same FVG emitted every cycle → `_emitted_fvg_ids` dedup not working.

---

### 4.5 _detect_retrace() — 3-AGAMALI SMC FILTRESI
```python
_detect_retrace(symbol, fvgs, current_bar, bias) -> list[dict]:
    for f in fvgs:
        if not f.is_active: continue

        # 1. KESISIM (Touch): Mum fitili FVG icinde mi?
        touched = (current_bar.high >= f.bottom) and (current_bar.low <= f.top)
        if not touched: continue

        # 2. SAYGI (Respect): Kapanis FVG'yi delip gecmedi mi?
        if bias == "SHORT":
            respected = current_bar.close <= f.top
        else:
            respected = current_bar.close >= f.bottom
        if not respected:
            object.__setattr__(f, "invalidated", True)   # FVG delindi
            continue

        # 3. DERINLIK (CE Tap): Fitil FVG %50'sine ulasti mi?
        ce_level = (f.top + f.bottom) / 2.0
        deep_enough = (current_bar.high >= ce_level) if bias == "SHORT" \
                      else (current_bar.low <= ce_level)

        return [{"type": "RETRACE", "is_ce_tap": deep_enough, ...}]
    return []
```
> **THRESHOLD:** 3 asaminin tamami gecilince RETRACE emit edilir.
>
> **EXPECTED LOG:** `"[RETRACE-DETAIL] {symbol} | fvg=[{bottom}-{top}] touched=True respected=True deep=True"`
>
> **ERROR:** FVG_CREATED fires but RETRACE never fires → price didn't reach, `is_active=False`, or Respect check failed (close broke FVG).
> **ERROR:** Same FVG retraces every bar → invalidation not sticking (object.__setattr__ not working).

---

### 4.6 _detect_ltf_confirm() — 5M FINAL GATE
```python
LTFTriggerDetector.validate(bar_m5, retracement_swing) -> LTFResult:
    # CRITERIA 1: body >= ATR(14) * 0.5
    body_ok = bar.body >= (atr * 0.5)

    # CRITERIA 2: close breaks retracement swing
    close_ok = bar.close > retracement_swing.price    # bullish
    close_ok = bar.close < retracement_swing.price    # bearish

    is_valid = body_ok AND close_ok   # BOTH must be true
```
> **THRESHOLDS:** `body_atr_mult=0.5`, ATR period=14.
> **NOTE:** Old 4-criteria system (body+volume+fvg+close) removed in V1.
>
> **EXPECTED LOG:** `"[ANALYZE] {symbol}: LTF_CONFIRM body_ok={} close_ok={} valid={}"`
>
> **ERROR:** body_ok always false → ATR calculation wrong or `body_atr_mult=0.5` too high.
> **ERROR:** close_ok always false → `retracement_swing` price wrong or market too weak at 5m level.
> **ERROR:** valid=true but state machine doesn't transition → `_handle_ltf()` not called or `_evaluate()` blocking.

---

## 5. Risk / Trade Execution

### 5.1 build_trade() — Entry
```python
build_trade(state) -> Trade | None:
    entry = state.entry_price               # primary: 5m LTF confirm close
    if entry is None:
        entry = (state.fvg_upper + state.fvg_lower) / 2.0  # fallback: FVG midpoint
```
> **ERROR:** entry=None AND fvg bounds None → state not populated. Check if RETRACE fired.

---

### 5.2 calculate_sl_htf() — Stop Loss
```python
calculate_sl_htf(direction, entry, h4_swing_level) -> float | None:
    buf = tier_buffer                         # tier1=0.15, tier2=0.30, tier3=0.60
    raw_sl = h4_swing * (1.0 - buf)           # LONG: below 4H swing low
    raw_sl = h4_swing * (1.0 + buf)           # SHORT: above 4H swing high
    dist = abs(entry - raw_sl)

    if dist < min_sl_pct * entry:   raw_sl = entry - min_dist    # too close → push out
    if dist > max_sl_pct * entry:   return None                   # too wide → REJECT

    # max_sl_pct: tier1=0.025, tier2=0.030, tier3=0.035
```
> **ERROR:** `return None` (too wide) → 4H swing too far from entry. Check h4_swing_level value.
> **ERROR:** SL impossibly close → h4_swing_level stale, wrong TF.

---

### 5.3 calculate_tp_htf() — Take Profit
```python
calculate_tp_htf(entry, risk_dist, h1_liquidity_level) -> float:
    if h1_liquidity_level:
        rr = abs(h1_liquidity_level - entry) / risk_dist
        if rr >= 2.0:                           # min R:R
            return h1_liquidity_level
    return entry + risk_dist * default_rr       # fallback
```
> **ERROR:** Always hits fallback → h1_liquidity_level=None OR R:R < 2.0. Check `_detect_h1_liquidity()`.

---

### 5.4 calculate_lot() — Position Size
```python
calculate_lot(available_margin, entry, sl, risk_pct=0.005) -> float:
    risk_usd = available_margin * risk_pct      # risk_pct = 0.5%–3.0%
    sl_dist = abs(entry - sl)
    raw_lot = risk_usd / sl_dist
    max_lot = (available_margin * leverage * margin_usage) / entry
    return min(raw_lot, max_lot)
```
> **ERROR:** Lot too small / zero → risk_pct too low OR sl_dist huge.

---

### 5.5 Stepped Stop Levels

```python
_calc_stop_levels(direction, entry, sl) -> (breakeven_trigger, trailing_level):
    # Called during build_trade() — pre-computes trigger levels
    risk_dist = abs(entry - sl)
    # Breakeven: price moves +1R → SL = entry
    breakeven_trigger = entry + risk_dist * 1.0    # BREAKEVEN_R = 1.0
    # Trailing:  price moves +2R → SL = entry + 1R
    trailing_level  = entry + risk_dist * (TRAILING_ACTIVATE_R - 1.0)  # 2.0 - 1.0 = 1.0

# ── Runtime (called by main.py _manage_open_trades every 5m bar) ──

should_move_to_breakeven(trade, current_price) -> bool:
    # Does price reach the breakeven trigger yet?
    # LONG:  current_price >= trade["breakeven_level"]
    # SHORT: current_price <= trade["breakeven_level"]
    # Falls back to entry ± risk_dist * BREAKEVEN_R if breakeven_level missing.

breakeven_sl(trade) -> float:
    # SL = entry (zero loss)
    return trade["entry"]

trailing_sl(trade, current_price, current_sl, step_ratio=0.25) -> float:
    # Step-based trailing after breakeven.
    # LONG:  new_sl = current_sl + (current_price - current_sl) * step_ratio
    # SHORT: new_sl = current_sl - (current_sl - current_price) * step_ratio
    # step_ratio = TRAILING_STEP_RATIO = 0.25
```

| Stage | Trigger | SL Moves To | Method |
|---|---|---|---|
| Breakeven | Price hits +1R | entry (breakeven) | `should_move_to_breakeven()` → `breakeven_sl()` |
| Trailing | After breakeven | slides incrementally | `trailing_sl()` step_ratio=0.25 |

---

## 6. Protection Mechanisms

### 6.1 State Persistence (nexus_state.json)
```python
LOAD:  main.py:run() → _load_state()           # reads JSON on startup
WRITE: main.py:_flush_state()                  # writes after trade opened
```
> **FILE:** `../nexus_state.json`
> **FIELDS:** `setup_id, state, direction, fvg_upper, fvg_lower, sweep_level, mss_break_level, created_at, expires_at`
>
> **ERROR:** State reset to IDLE after restart → `_flush_state()` not called OR JSON corrupted.

---

### 6.2 WS Auto-Reconnect
```python
# websocket.py — exponential backoff
delay = 2.0s                                    # start
while not stop:
    try: connect_and_listen(); delay = 2.0s     # success → reset
    except (ConnectionClosed, Timeout, OSError):
        delay = min(delay * 2.0, 60.0s)         # cap 60s
```
> **HEARTBEAT:** Every 30s checks last tick time.
> **TIMEOUT:** 5m=450s, 15m=1350s tolerance. If exceeded → reconnect.
> **FACT:** No new signals during WS outage (no bars arrive). Open positions stay on Binance (SL/TP orders are server-side).

---

### 6.3 Duplicate Order Prevention
```python
# STARTUP: _startup_cleanup()
# 1. Fetch ALL open orders + algo orders from Binance
# 2. Group by symbol
# 3. IF symbol has NO position:
#      IF symbol in active_trades → skip (ORPHAN-GUARD)
#      ELSE → cancel all orders (ORPHAN)
# 4. IF symbol HAS position AND (>1 SL OR >1 TP):
#      → cancel all protection → rebuild from scratch (SAFE MODE)

# RUNTIME: _sync_positions()
# Every cycle: if >1 SL or >1 TP → cancel all → recreate

# RACE: LiveExecutor.send_order()
if symbol in self._pending_symbols: return None  # reject duplicate
async with lock:                                  # asyncio.Lock
    self._pending_symbols.add(symbol)

# COOLDOWN: 2s per symbol
def _check_cooldown(symbol): return (now - last_order_time) < 2.0

# SAFE MODE:
if active_trades[symbol]["protection_missing"]:
    log.warning("SAFE MODE | %s | new signal BLOCKED", symbol)
    return   # monitoring only, no new trades
```
> **LOG MARKERS:**
>   ORPHAN cancel: `"ORPHAN orders cancelled for {symbol}"`
>   DUPLICATE: `"DUPLICATE protection detected for {symbol} → cancelling all"`
>   SAFE MODE: `"SAFE MODE | {symbol} | yeni sinyal ENGELLENDI"`

---

### 6.4 Minimum Age (Breakeven/Trailing Guard)
```python
if (now - trade.open_time) < 300_000ms:   # 5 minutes
    continue                                # skip all stop updates
```
> **ERROR:** Breakeven never activates → trade closed within 5min OR open_time incorrect.

---

### 6.5 API Rate Limit
```python
self._api_semaphore = asyncio.Semaphore(5)  # max 5 concurrent signed requests
```
> **ERROR:** "429 Too Many Requests" → semaphore not working OR Binance rate limit lowered.

---

## 7. Timeframe Data Flow

```
Daily REST Cache  ──→ bars_d1   → _detect_htf_bias (BOS direction)
WS 4h stream      ──→ bars_h4   → _detect_htf_bias (confirmation) + _detect_h4_swing_level (SL ref)
WS 1h stream      ──→ bars_h1   → _detect_h1_liquidity (TP ref)
WS 15m stream     ──→ bars_15m  → sweep + MSS + FVG detection (primary TF)
WS 5m stream      ──→ bars_m5   → LTF confirm + entry close

TRIGGER: 5m close fires analyze() for ALL timeframes.
```

---

## 8. Key Thresholds (Quick Reference)

| Param | Value | Where |
|---|---|---|
| D1_BOS_LOOKBACK | 25 | analyzer.py |
| H4_BOS_LOOKBACK | 25 | analyzer.py |
| FVG_LOOKBACK | 60 bars (15m) | fvg.py |
| SWEEP_WINDOW | last 5 swings | analyzer.py |
| MIN_RR | 2.0 | risk_manager.py |
| BODY_ATR_MULT | 0.5 | mss.py:LTFTriggerDetector |
| ATR_PERIOD | 14 | indicators.py |
| RISK_PCT | 0.5% – 3.0% | config.py |
| SL_BUFFER (tier1/2/3) | 0.15 / 0.30 / 0.60 | risk_manager.py |
| MAX_SL_PCT (tier1/2/3) | 0.025 / 0.030 / 0.035 | risk_manager.py |
| BREAKEVEN_R | 1.0 | risk_manager.py |
| TRAILING_ACTIVATE_R | 2.0 | risk_manager.py |
| TRAILING_STEP_RATIO | 0.25 | risk_manager.py |
| MIN_TRADE_AGE_MS | 300_000 (5 min) | main.py |
| API_SEMAPHORE | 5 concurrent | main.py |
| WS_RECONNECT_START | 2s, max 60s | websocket.py |
| TIMEOUT_5M | 450s | websocket.py |
| TIMEOUT_15M | 1350s | websocket.py |
| ORDER_COOLDOWN | 2s | trader.py |

---

## 9. Debug Workflow (AI Protocol)

```
1. Read log line.
2. Match to function via log prefix.
3. Compare log values against EXPECTED thresholds above.
4. If mismatch → trace ERROR section of that function.
5. If chain break (events stop mid-flow) → walk state machine backwards.
```

### Common Patterns & Root Causes

| Symptom | Most Likely Cause |
|---|---|
| All symbols IDLE, no events ever | D1 data not loading, `analyze()` returns `[]` |
| Bias=None on all symbols | `find_swing_highs/lows` in pivot.py broken |
| SWEEP never fires | 15m swing lists empty — pivot.py not running on 15m |
| MSS never fires | bias filter kills all CHoCHs OR `detect_choch()` logic broken |
| RETRACE never fires | FVGs expire before price reaches them OR `is_active` logic broken |
| LTF_CONFIRM false always | body_atr_mult=0.5 too strict for that symbol's volatility |
| State stuck at WAIT_RETRACE | RETRACE event produced but `_handle_retrace()` not called |
| State stuck at WAIT_CONFIRM | `_evaluate()` not called OR one of 4 flags still False |
| READY_TO_ENTER but no trade | `build_trade()` returns None (SL too wide) OR send_order blocked |
| Trade opened but no SL/TP | `_create_protection()` failed silently OR rate limited |
| Duplicate SL/TP after restart | `_startup_cleanup()` not running OR ORPHAN-GUARD bug |
| WS disconnected, positions gone | Check Binance directly — server-side orders stay. WS only affects new signals. |
