# Tech Context — NEXUS V3

## Kullanılan Teknolojiler

| Kategori | Teknoloji | Versiyon | Amaç |
|----------|-----------|----------|------|
| **Dil** | Python | 3.12+ | Ana geliştirme dili |
| **Async** | asyncio | stdlib | WebSocket + REST eşzamanlı yönetimi |
| **HTTP Client** | httpx / requests | — | Binance REST API çağrıları |
| **WebSocket** | websockets | — | Binance WS stream bağlantısı |
| **Veri Yapıları** | dataclasses | stdlib | Bar, FVG, CHoCH, TradeParams modelleri |
| **Performans** | Numba (JIT) | — | EMA, SMMA, ATR, ADX hesaplamaları |
| **Loglama** | logging | stdlib | Hiyerarşik log (nexus.analyzer, nexus.risk, vb.) |
| **Konfigürasyon** | Python module | — | `config.py` sabitleri |
| **Exchange API** | Binance Futures REST + WS | — | Kline, order, position endpoint'leri |

## Geliştirme Ortamı

### Gereksinimler
- Python 3.12+
- Windows 11 (geliştirme ortamı)
- `.venv` içinde sanal ortam
- Ruff linter (pyproject.toml: line-length=120, Python 3.12)

### Kurulum
```bash
cd sonnet
pip install -r requirements.txt  # veya pyproject.toml üzerinden
```

### Çalıştırma
```bash
python sonnet/src/main.py
```

## Teknik Kısıtlamalar

1. **Binance Rate Limit**: REST 1200 req/dk, WS connection limit 1024 stream.
2. **22 sembol × 5 timeframe = 110 WebSocket stream** — tek connection üzerinden multiplex.
3. **Memory: Bar cache**: Her sembol için tüm timeframe'lerde ~1000 bar bellekte tutulur.
4. **asyncio event loop**: Tüm I/O tek event loop üzerinde, blocking kod yok (Numba JIT hariç).
5. **No database**: State `SymbolState` dataclass ile bellekte, trade geçmişi `performance.py` ile dosyada.
6. **Lock granularity**: Sembol başına `asyncio.Lock` — aynı sembolde eşzamanlı emir engellenir.

## Bağımlılıklar

### Python Paketleri
```
# Temel
asyncio (stdlib)
dataclasses (stdlib)
logging (stdlib)

# Exchange
httpx
websockets

# Performans
numba
numpy

# Geliştirme
ruff
mypy
pre-commit
```

### Harici Servisler
- Binance Futures API (REST + WebSocket)
- (Opsiyonel) Grafana/Prometheus monitoring

## Araç Kullanım Desenleri

### Log Formatı
```
%(asctime)s | %(name)s | %(levelname)s | %(message)s
```
Logger hiyerarşisi: `nexus` → `nexus.analyzer`, `nexus.risk`, `nexus.executor`, vb.

### Config Erişimi
```python
import config
config.MIN_RR          # Minimum R:R oranı
config.MAX_SETUP_WAIT_HOURS  # Zombi setup temizleme süresi
config.BREAKEVEN_R    # Breakeven tetikleme R değeri
config.TRAILING_ACTIVATE_R  # Trailing stop aktivasyon R değeri
config.TRAILING_STEP_RATIO  # Trailing adım oranı
```

### State Debug
```python
from state_machine import SymbolState
state = SymbolState(symbol="BTCUSDT")
print(state.state)        # IDLE, ARMED, WAIT_RETRACE, ...
print(state.direction)    # LONG, SHORT, None
print(state.sweep_detected, state.mss_confirmed, state.retrace_seen, state.ltf_confirmed)
```

### Risk Manager Kullanımı
```python
from risk_manager import RiskManager

risk_mgr = RiskManager(
    balance=1000.0,
    risk_pct=0.03,
    leverage=10.0,
)

# Tier sorgulama
tier = risk_mgr._tier("BTCUSDT")  # → {"max_sl_pct": 0.025, "sl_buffer": 0.0015, ...}

# Trade parametresi oluşturma
trade_params = risk_mgr.build_trade(
    state=current_state,
    entry_price=50000.0,
    h4_swing_level=49500.0,
        h1_liquidity_level=51000.0,
)

### Test Çalıştırma
```bash
cd tests
python -m pytest -v                           # tüm testler (92 test)
python -m pytest test_pivot.py -v             # pivot testleri
python -m pytest test_risk_manager.py -v      # risk manager testleri
python -m pytest test_state_machine.py -v     # state machine testleri
```

### Test Altyapısı
- `tests/conftest.py` — `sys.path.insert(0, sonnet/src)` ile modül erişimi sağlar.
- `make_bar()`, `make_state()`, `make_risk_manager()` fabrikaları ile bağımlılık minimize edilir.
- Tüm import'lar `warnings.catch_warnings()` içinde yapılır (DeprecationWarning gizlenir).
- Pre-commit hooks: ruff lint + format, vulture (dead code), mypy (type check).

## Key Thresholds (Quick Reference)

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
| SL_BUFFER (tier1/2/3) | 0.15 / 0.30 / 0.60 % | risk_manager.py |
| MAX_SL_PCT (tier1/2/3) | 0.025 / 0.030 / 0.035 | risk_manager.py |
| BREAKEVEN_R | 1.0 | risk_manager.py |
| TRAILING_ACTIVATE_R | 2.0 | risk_manager.py |
| TRAILING_STEP_RATIO | 0.25 | risk_manager.py |
| MIN_TRADE_AGE_MS | 300_000 (5 min) | main.py |
| API_SEMAPHORE | 5 concurrent | main.py |
| WS_RECONNECT_START | 2s, max 60s | websocket.py |
| LTF_TF | 1m | analyzer.py |

## Timeframe Data Flow
```
Daily REST Cache   → bars_d1   → _detect_htf_bias (BOS direction)
WS 4h stream       → bars_h4   → _detect_htf_bias (confirmation) + _detect_h4_swing_level (SL ref)
WS 1h stream       → bars_h1   → _detect_h1_liquidity (TP ref)
WS 15m stream      → bars_15m  → sweep + MSS + FVG detection (primary TF)
WS 1m stream       → bars_m1   → LTF confirm + entry close (V1 2-kriter)
TRIGGER: 1m close fires analyze() for ALL timeframes.
```
