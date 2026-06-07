# System Patterns — NEXUS V3

## Sistem Mimarisi

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

## Temel Tasarım Kararları

### 1. Tek Yönlü Bağımlılık Zinciri
- Foundation layer (`models.py`) hiçbir iç modülü import etmez.
- Yukarıdan aşağıya döngüsel bağımlılık yok.
- Her modül sadece altındaki layer'lara bağımlı.

### 2. Event-Driven State Machine
- Event'ler `analyzer.py` tarafından üretilir.
- `event_router.py` sadece yönlendirme yapar, karar mantığı SIFIR.
- `state_machine.py` state geçişlerini ve valitasyonları yönetir.
- State zinciri: `IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER → ENTERED`

### 3. Pre-Check Layer
```python
def _evaluate(self, state, current_time=None, last_closed_bar=None):
    if self._check_stale_state(state, current_time):   # Zombi temizliği (24 saat)
        return
    if self._check_invalidation(state, last_closed_bar): # Yapısal kırılım (mum kapanışı)
        return
    if not (state.sweep_detected and state.mss_confirmed
            and state.retrace_seen and state.ltf_confirmed):  # 4-flag hard gate
        return
    state.state = "READY_TO_ENTER"
```

### 4. Likidite Havuzu Dedup
- Her sweep seviyesi `_consumed_levels` set'ine eklenir.
- D1 bar değişiminde tüm havuz sıfırlanır.
- Aynı seviyeden tekrar sweep üretilmez.

### 5. Tier Bazlı Risk Yönetimi
- 22 sembol 3 tier'a ayrılmıştır (Tier1: BTC/ETH/BNB, Tier2: SOL/XRP/DOT..., Tier3: geri kalan).
- Her tier için: `max_sl_pct`, `min_sl_pct`, `sl_buffer`, `max_rr`, `lot_decimals`.
- Sembol tier'ı `TIER_MAP` ve `TIER_CFG` dict'leri ile çözümlenir.

### 6. asyncio + Lock ile İşlem Güvenliği
- `async with get_lock(symbol)` → aynı sembolde eşzamanlı emir engellenir.
- WebSocket veri akışı asenkron, state güncellemeleri lock altında.

## Tasarım Desenleri

| Desen | Uygulama | Nerede |
|-------|----------|--------|
| **Publisher-Subscriber** | analyzer event → event_router → state_machine | `analyzer.py` → `event_router.py` → `state_machine.py` |
| **State Machine** | 6 durumlu deterministik geçiş | `state_machine.py` |
| **Strategy** | Tier bazlı SL/TP/lot hesaplama | `risk_manager.py` (`TIER_CFG`) |
| **Facade** | `build_trade()` tüm risk hesaplamalarını tek noktada toplar | `risk_manager.py` |
| **Factory** | `TradeParams` dataclass ile trade nesnesi üretimi | `risk_manager.py` |
| **Observer** | WebSocket stream → analyzer pipeline | `main.py:ws_hub` |
| **Deduplication** | `_consumed_levels`, `_seen_mss`, `_emitted_fvg_ids` set'leri | `analyzer.py` |

## Kritik Implementasyon Yolları

### Sinyal Zinciri (analyzer.py)
```
analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)
  → _detect_htf_bias(bars_d1, bars_h4)     # D1 bias + H4 teyit → (bias, strength)
  → _detect_h4_swing_level(bars_h4, bias)  # SL referansı
  → _detect_h1_liquidity(bars_h1, bias)    # TP referansı
  → _detect_sweep_15m(symbol, bars_15m)    # SSL/BSL sweep (bar_index ile)
  → _detect_mss_events(symbol, bars_15m)   # CHoCH/MSS (FVG'den ÖNCE)
  → detect_fvgs(bars_15m, 60, since_index) # FVG tespiti (sweep sonrası)
  → _detect_retrace(symbol, fvgs, bar)     # 3-aşamalı SMC filtresi
  → _detect_ltf_confirm(symbol, fvgs, bars_m1) # 1m LTF onay (V1 2-kriter)
```

### Trade Akışı (main.py)
```
_on_1m_close()
  → analyzer.analyze()          # event üret
  → event_router.route()        # state'e yönlendir
  → _update_h4_and_h1_levels()  # SL/TP referanslarını güncelle
  → _evaluate()                 # pre-check + 4-flag gate
  → risk_mgr.build_trade()      # SL/TP/lot hesapla
  → executor.send_order()       # MARKET + SL/TP algo order
  → _manage_open_trades()       # breakeven/trailing
```

### Bileşen İlişkileri

| Bileşen | Bağımlı Oldukları | Bağımlı Olanlar |
|----------|-------------------|-----------------|
| `models.py` | — (foundation) | Her şey |
| `config.py` | — | `risk_manager.py`, `state_machine.py` |
| `pivot.py` | `models` | `fvg.py`, `mss.py`, `analyzer.py` |
| `indicators.py` | `models` | `fvg.py`, `mss.py` |
| `fvg.py` | `pivot`, `indicators` | `mss.py`, `analyzer.py`, `scoring.py` |
| `mss.py` | `pivot`, `indicators`, `fvg` | `analyzer.py`, `scoring.py` |
| `analyzer.py` | `pivot`, `indicators`, `fvg`, `mss` | `event_router.py` |
| `scoring.py` | `fvg`, `mss` | — |
| `event_router.py` | `analyzer` | `state_machine.py` |
| `state_machine.py` | `event_router` | `risk_manager.py`, `main.py` |
| `risk_manager.py` | `state_machine`, `config` | `trader.py`, `main.py` |
| `trader.py` | `exchange`, `risk_manager` | `main.py` |
| `exchange.py` | — | `trader.py` |
| `websocket.py` | — | `main.py` |
| `main.py` | `websocket`, `trader`, `state_machine`, `risk_manager` | `monitor.py`, `performance.py` |
