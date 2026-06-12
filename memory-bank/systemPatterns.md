# System Patterns — NEXUS V3

## Sistem Mimarisi

```
models.py         (zero deps — foundation)
pivot.py ← models
indicators.py ← models
fvg.py ← pivot, indicators
mss.py ← pivot, indicators, fvg
analyzer.py ← pivot, indicators, fvg, mss
scoring.py ← fvg, mss, volume_profile
volume_profile.py ← models
weekly_range_spy.py ← models
event_router.py ← analyzer  ──→  state_machine.py
                                   ↓
                              risk_manager.py
                                   ↓
exchange.py  ──→  trader.py  ← risk_manager
                       ↓
websocket.py  ──→  main.py  ← trader
                       ↓         ↓
                  monitor.py  weekly_range_spy (log-only)
                  performance.py
```

## Temel Tasarım Kararları

### 1. Tek Yönlü Bağımlılık Zinciri
- Foundation layer (`models.py`) hiçbir iç modülü import etmez.
- Yukarıdan aşağıya döngüsel bağımlılık yok.
- Her modül sadece altındaki layer'lara bağımlı.

### 2. Event-Driven State Machine
- Event'ler `analyzer.py` tarafından üretilir — **tek kaynak**.
- `event_router.py` sadece yönlendirme yapar, karar mantığı SIFIR.
- `state_machine.py` state geçişlerini ve validasyonları yönetir.
- State zinciri: `IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER → ENTERED`

#### Event Pipeline (deterministic single pipeline)
```
analyze() → event_router.publish() → state_machine.update_from_event()
```
Başka MSS/FVG kaynağı yoktur. Replay, cached dispatch, historical re-emit yok.

#### State Geçiş Tablosu
| State → State | Tetikleyici | Koşul |
|---|---|---|
| IDLE → ARMED | SWEEP | state=IDLE, tf ∈ (1H, 2H, 15m) |
| ARMED → WAIT_RETRACE | MSS | since_bar_index set (sweep var) |
| ARMED/WAIT_RETRACE → WAIT_RETRACE | FVG | mss_confirmed=True → FVG kaydedilir |
| WAIT_RETRACE → WAIT_CONFIRM | check_retrace() | CE tap + gövde FVG içinde kapanış |
| WAIT_CONFIRM → READY_TO_ENTER | LTF_CONFIRM veya adaptive mid-band | fvg_upper/lower doluysa veya pen ∈ [0.30, 0.70] |
| READY_TO_ENTER → ENTERED | main.py | LiveExecutor.send_order() |
| ANY → IDLE | timeout/invalidation | _check_stale_state / _check_invalidation → reset_flags + reset_symbol_cache |

#### State Invariantları
| State | Zorunlu (None olamaz) | Yasak kombinasyon |
|---|---|---|
| ARMED | sweep_detected=True, expires_at, sweep_level | mss_confirmed=True |
| WAIT_RETRACE | sweep_detected=True, mss_confirmed=True, direction | fvg_upper=None (bug sinyali) |
| WAIT_CONFIRM | + fvg_upper, fvg_lower, retrace_seen=True | fvg_entry_bar_index=None |
| READY_TO_ENTER | + ltf_confirmed=True veya adaptive pen, entry_price | — |

#### SymbolState Alanları
```python
@dataclass
class SymbolState:
    symbol: str
    state: SetupState = SetupState.IDLE
    direction: str | None = None  # LONG/SHORT
    htf_bias: str | None = None
    htf_strength: str | None = None
    entry_price: float | None = None

    # HTF / structure
    fvg_upper: float | None = None
    fvg_lower: float | None = None
    fvg_time: int | None = None
    sweep_level: float | None = None
    sweep_bar_index: int | None = None
    mss_level: float | None = None
    mss_bar_index: int | None = None
    h4_swing_level: float | None = None
    h1_liquidity_level: float | None = None
    fvg_entry_bar_index: int | None = None

    # flags
    sweep_detected: bool = False
    mss_confirmed: bool = False
    displacement_confirmed: bool = False
    retrace_seen: bool = False
    ltf_confirmed: bool = False
    is_ce_tap: bool = False
    wait_confirm_since_ts: int | None = None  # partial entry time-box için
```

#### Event Handlers
```python
_handle_htf_bias(state, event)   → state.htf_bias, state.htf_strength, state.direction set
_handle_htf_levels(state, event) → state.h4_swing_level, state.h1_liquidity_level set
_handle_sweep(state, event)      → IDLE → ARMED; expires_at artık sweep'te atanmaz (MSS'e taşındı)
_handle_fvg(state, event)        → FVG levels stored; if mss_confirmed → WAIT_RETRACE
_handle_mss(state, event)        → ARMED/WAIT_RETRACE/WAIT_CONFIRM → WAIT_RETRACE; expires_at = MAX_SETUP_WAIT_HOURS
check_retrace(symbol, bar)       → WAIT_RETRACE → WAIT_CONFIRM (CE tap + gövde kapanışı)
_handle_ltf(state, event)        → WAIT_CONFIRM → READY_TO_ENTER
_check_stale_state(state, time)  → Zombi ARMED/WAIT_* setup'ları expire olmuşsa IDLE'a çeker
_check_invalidation(state, bar)  → Mum kapanışı mss_level'i kırarsa IDLE'a çeker
_evaluate()                      → adaptive mid-band READY_TO_ENTER (ADAPTIVE_LTF_ENABLE=True, pen ∈ [0.30, 0.70])
```

> **Anti-resurrection guard:** `_handle_fvg` INVALIDATED/EXPIRED/ENTERED state'lerinde FVG event'ini reddeder.

### 3. Event Validity Kuralları
| Event | Upstream koşul | Downstream koşul |
|---|---|---|
| SWEEP | — | state=IDLE, tf ∈ (1H, 2H, 15m) |
| MSS | since_bar_index ≠ None (sweep var) | state ∈ {ARMED, WAIT_RETRACE, WAIT_CONFIRM} |
| FVG_CREATED | mss_since set | state ∉ {INVALIDATED, EXPIRED, ENTERED} |
| LTF_CONFIRM | — | fvg_upper ve fvg_lower doluysa kabul |

> **[FIX-1]** `_detect_mss_events(since_bar_index=None)` → `return []`
> MSS artık anchored event — sweep olmadan kavramsal olarak da yok.

### 4. Pre-Check Layer
```python
def _evaluate(self, state, current_time=None, last_closed_bar=None):
    if self._check_stale_state(state, current_time):   # Zombi temizliği
        return
    if self._check_invalidation(state, last_closed_bar): # Yapısal kırılım
        return
    # Adaptive mid-band: ADAPTIVE_LTF_ENABLE=True, WAIT_CONFIRM, sweep+mss+retrace, ltf_confirmed=False
    if (ADAPTIVE_LTF_ENABLE and state.state == "WAIT_CONFIRM"
        and state.sweep_detected and state.mss_confirmed and state.retrace_seen
        and not state.ltf_confirmed and state.fvg_upper is not None):
        pen = compute_fvg_penetration(state, current_bar)
        if FVG_PENETRATION_MID <= pen <= FVG_PENETRATION_MAX:
            state.state = "READY_TO_ENTER"
            return
    if not (state.sweep_detected and state.mss_confirmed
            and state.retrace_seen and state.ltf_confirmed):  # 4-flag hard gate
        return
    state.state = "READY_TO_ENTER"
```

### 5. Cache Lifecycle Kuralları
State machine = truth. Analyzer cache = derived ephemeral state.

| Cache | Temizlendiği yerler | Kasıtlı korunan |
|---|---|---|
| `_emitted_fvg_ids` | D1 bar değişimi + `reset_symbol_cache()` | — |
| `_seen_mss` | D1 bar değişimi + `reset_symbol_cache()` | — |
| `_mss_state` | `reset_symbol_cache()` (yeni SwingStateManager) | — |
| `_consumed_levels` | D1 bar değişimi | ✅ symbol reset'te KORUNUYOR (D1 bazlı hafıza) |

`reset_symbol_cache()` nerede tetiklenir:
1. `_clear_state(symbol)` — trade kapanışı
2. `_on_5m_close` → `_evaluate()` sonrası state-diff IDLE geçişi (Fix 3b)

```python
# Fix 3b pattern:
_state_before = self.state_machine.get(symbol).state
self.state_machine._evaluate(...)
_state_after = self.state_machine.get(symbol).state
if _state_before != _state_after and _state_after == SetupState.IDLE:
    self.analyzers[symbol].reset_symbol_cache()
```

### 6. Likidite Havuzu Dedup
- Her sweep seviyesi `_consumed_levels` set'ine eklenir.
- D1 bar değişiminde tüm havuz sıfırlanır.
- Aynı seviyeden tekrar sweep üretilmez.

### 7. Tier Bazlı Risk Yönetimi
- 22 sembol 3 tier'a ayrılmıştır (Tier1: BTC/ETH/BNB, Tier2: SOL/XRP/DOT..., Tier3: geri kalan).
- Her tier için: `max_sl_pct`, `min_sl_pct`, `sl_buffer`, `max_rr`, `lot_decimals`.
- Sembol tier'ı `TIER_MAP` ve `TIER_CFG` dict'leri ile çözümlenir.

### 8. asyncio + Lock ile İşlem Güvenliği
- `async with get_lock(symbol)` → aynı sembolde eşzamanlı emir engellenir.
- WebSocket veri akışı asenkron, state güncellemeleri lock altında.

## Tasarım Desenleri

| Desen | Uygulama | Nerede |
|-------|----------|--------|
| **Publisher-Subscriber** | analyzer event → event_router → state_machine | `analyzer.py` → `event_router.py` → `state_machine.py` |
| **State Machine** | 10 durumlu deterministik geçiş + pre-check layer | `state_machine.py` |
| **Strategy** | Tier bazlı SL/TP/lot hesaplama | `risk_manager.py` (`TIER_CFG`) |
| **Facade** | `build_trade()` tüm risk hesaplamalarını tek noktada toplar | `risk_manager.py` |
| **Factory** | `TradeParams` dataclass ile trade nesnesi üretimi | `risk_manager.py` |
| **Observer** | WebSocket stream → analyzer pipeline | `main.py:ws_hub` |
| **Deduplication** | `_consumed_levels`, `_seen_mss`, `_emitted_fvg_ids` set'leri | `analyzer.py` |
| **State-Diff Lifecycle** | `_state_before / _state_after` ile IDLE geçiş tespiti | `main.py:_on_5m_close` |
| **Score Adjuster** | VP HVN/LVN → FVGQuality score delta; POC → TP magnet | `volume_profile.py` → `scoring.py` |
| **Log-Only Spy** | Haftalık sweep/CISD tespiti, asla trade açmaz | `weekly_range_spy.py` → `main.py` |

## Kritik Implementasyon Yolları

### Sinyal Zinciri (analyzer.py)
```
analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)
  → _detect_htf_bias(bars_d1, bars_h4)     # D1 bias + H4 teyit → (bias, strength)
  → _detect_h4_swing_level(bars_h4, bias)  # SL referansı
  → _detect_h1_liquidity(bars_h1, bias)    # TP referansı
  → _detect_sweep_h1(symbol, bars_h1, bias) # H1 sweep + 2H fallback
      └── _sweep_on_bars() pivot tarama + sweep koşulu
      └── _resample_to_2h() sentetik 2H bar üretimi
  → _detect_mss_events(symbol, bars_15m, bias, since_bar_index)
      └── since_bar_index=None → return [] (sweep yoksa MSS yok)
  → detect_fvgs(bars_15m, 60, since_index) # FVG tespiti (sweep/MSS sonrası)
  → cleanup_fvgs() + sorted(fvgs, key=lambda f: abs(f.top - f.bottom), reverse=True)
  → _interval_overlap_ratio() + _cluster_fvgs() # FVG küme analizi
  → _detect_ltf_confirm(symbol, fvgs, bars_m1) # 1m LTF onay
  [retrace kontrolü state_machine.check_retrace()'e taşındı]
```

### Trade Akışı (main.py → _on_5m_close)
```
_on_5m_close(symbol, bars_m5)
  → _manage_open_trades()
  → asyncio.create_task(_sync_positions())
  → weekly_range_spy.check_5m(symbol, bars_d1, current_bar)  ← log-only, trade açmaz

  Her 1m tick'inde (symbol not in self.active_trades):
    → state_machine.check_retrace(symbol, current_bar)
    → state_machine.check_ltf_fvg_validity(symbol, current_bar)
    → state_machine._evaluate(...)
    → [state_after karşılaştır → IDLE ise reset_symbol_cache()]  ← Fix 3b
    → if READY_TO_ENTER → build_trade → send_order (entry_order_type, stop_offset_pct dahil)

  if no active_trade:
    → analyzer.analyze(...)
    → event_router.publish(event) for each event
```

### 15m Blok Ayrıştırması (2026-06-11)
- **15m kapanışında:** Sadece `export_ohlc_15m()` + `state_logger.write_snapshot()` — ATR/state check/emir yok.
- **Her 1m tick'inde:** `check_retrace`, `check_ltf_fvg_validity`, `_evaluate`, `READY_TO_ENTER` emir kapısı.
- `compute_atr_point` import'u kaldırıldı (check_retrace/check_poi_retrace artık atr parametresi almıyor).

## Protection Mechanisms

### State Persistence (nexus_state.json)
```python
LOAD:  main.py:run() → _load_state()           # reads JSON on startup
WRITE: main.py:_flush_state()                  # writes after trade opened/closed
```

### WS Auto-Reconnect
```python
delay = 2.0s                                    # start
while not stop:
    try: connect_and_listen(); delay = 2.0s     # success → reset
    except (ConnectionClosed, Timeout, OSError):
        delay = min(delay * 2.0, 60.0s)         # cap 60s
```

### Duplicate Order Prevention
```python
# STARTUP: _startup_cleanup()
# RUNTIME: _sync_positions() — >1 SL veya >1 TP → atomic swap (en güncel koru, fazlası iptal)
# RACE: asyncio.Lock per symbol
# COOLDOWN: 2s per symbol
# SAFE MODE: protection_missing=True → monitoring only
```

### Minimum Trade Age
```python
if (now - trade.open_time) < 300_000ms:   # 5 dakika
    continue  # breakeven/trailing atla
```

### API Rate Limit
```python
self._api_semaphore = asyncio.Semaphore(5)  # max 5 eşzamanlı imzalı istek
