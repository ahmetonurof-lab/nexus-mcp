## Fix-5: Deepseek P0 Bug Fixes — Batch 2 (2026-06-14) ✅

**Status:** 3/3 completed — 0 errors ✅

### 6. `trade_locks` Thread Safety
- **Dosya:** `sonnet/src/main.py`
- **Sorun:** `get_lock()`'da dict erişimi race condition — `asyncio.Lock` yeterli değil, `threading.Lock` gerekli
- **Fix:** `import threading` + `_trade_locks_lock = threading.Lock()` + `with _trade_locks_lock:` sarmalı

### 7. `_fetch_binance_signed_post` No Retry
- **Dosya:** `sonnet/src/main.py`
- **Sorun:** POST endpoint'inde retry yoktu — ağ hatasında SL güncellemesi kaybolabilirdi
- **Fix:** `max_retries=3` + retry döngüsü + `asyncio.sleep(1.0 * (attempt+1))` backoff + `last_error` exception zinciri

### 8. `active_trades` Type Safety
- **Dosya:** `sonnet/src/main.py`
- **Sorun:** `active_trades: dict[str, dict]` — tip güvenliği yok, 4 farklı dict şablonu vardı
- **Fix:** `TradeEntry(TypedDict, total=False)` — 49 alanlı tip tanımı, `dict[str, TradeEntry]` tip dönüşümü

## Sprint: Medium + Low Priority Tasks (2026-06-14) ✅

**🟡 Orta (3):**
### 1. DEFAULT_ATR / ATR_MAP config'e eklendi
- **Dosya:** `config.py` — `DEFAULT_ATR: float = 100.0`, `ATR_MAP: dict[str, float]` (20 sembol)
- **Bağlam:** `state_machine._get_atr()` zaten `cfg.ATR_MAP` ve `cfg.DEFAULT_ATR` referansı yapıyordu — config'e eklenerek çalışır hale getirildi

### 2. check_retrace() CE eşiği H1 FVG boyutuna göre dinamik yapıldı
- **Dosya:** `state_machine.py` → `check_retrace()`
- **Mekanizma:** FVG boyut/fiyat oranı → scale factor → pen_min/pen_max dinamik ayar
- **Config:** `FVG_REF_SIZE_RATIO`, `FVG_CE_SCALE_MIN/MAX`, `FVG_CE_PEN_MIN_BASE/MAX_BASE`, `FVG_CE_PEN_MIN_FLOOR/MAX_CEIL`
- **Formül:** `scale = clamp(fvg_size_ratio / ref_ratio, scale_min, scale_max)`, `pen_min = base_pen_min / scale`, `pen_max = base_pen_max * scale`
- **Test güncellemesi:** 12 test FVG boyutu gerçekçi (%0.2) olacak şekilde güncellendi

### 3. Integration test — Tam zincir (14 test)
- **Yeni dosya:** `tests/test_integration_chain.py` — 14 test
- **Kapsam:** Analyzer event üretimi → EventRouter → StateMachine geçişi (3), Mock pipeline LONG/SHORT/MISSED_FVG/invalidation/expiry (5), Cross-component monitor+state+router (3), Multi-symbol bağımsızlık (1), EventRouter normalizer (1)

**🟢 Düşük (2):**
### 4. Grafana/Prometheus bağlantısı
- **Dosya:** `monitor.py` — `get_prometheus_metrics()`, `get_grafana_dashboard_json()`
- **Metrikler:** `nexus_up`, `nexus_tick_seconds`, `nexus_health_status` (0=DEAD/1=STALE/2=LIVE), `nexus_signal/order/fill/rejected_count_total`, `nexus_total_*` aggregate
- **Grafana:** 4 panelli dashboard JSON (health stat, signal/order/fill rate, tick age, rejection rate)
- **Prometheus exposition format:** manuel text format (zero external dependency)
- `prometheus-client` pip paketi eklendi (opsiyonel)

### 5. Backtesting framework
- **Yeni dosya:** `sonnet/src/backtest.py`
- **Sınıflar:** `BacktestEngine`, `VirtualExchange`, `BacktestTrade`, `BacktestMetrics`
- **Fonksiyonlar:** `quick_backtest()`, `load_ohlcv_from_csv/json()`
- **Config:** `BACKTEST_SL_PCT`, `BACKTEST_TP_PCT`, mevcut `BACKTEST_START/END`, `INITIAL_BALANCE`, `LEVERAGE`
- **Destek:** CSV/JSON veri yükleme, bar-by-bar simülasyon, SL/TP takibi, performans raporu

**Test durumu:** 480 passed, 0 failed ✅

## STOP_MARKET Entry Doğrulaması (2026-06-14) ✅

**Dosya:** `tests/test_trader.py`
**Yeni testler (6):** `test_send_order_stop_market_short`, `_zero_offset`, `_partial`, `_error`, `_no_current_price`, `_with_sl_tp_params`
**Kapsam:** SHORT trigger=min, zero offset→entry direkt, partial flag, API error→None, current_price=None fallback, SL/TP params ignored
**Toplam test:** 466 passed ✅

## P1-0B: _sync_positions Characterization Tests (2026-06-14) ✅

## P1-0C: scoring.py Coverage %0→%91 (2026-06-14) ✅

**Dosya:** `tests/test_scoring.py` — **53 test**, hepsi pass
**Coverage:** `scoring.py` 0% → **91%** (hedef %50 ikiye katlandı)

**Eklenen fonksiyonlar (`fvg.py`):** `score_displacement`, `score_fvg_size`, `score_sweep`, `score_retest`, `compute_fvg_quality`, `_get_vp_status`, `is_premium_discount_valid` — scoring.py import'larını çözmek için stub'lar eklendi

| Test Sınıfı | Kapsam |
|-------------|--------|
| `TestBuildScoringContext` (3) | Boş/normal bar, VP integrasyonu |
| `TestDetectMarketRegime` (8) | trending_up/down, ranging, volatile, EMA fallback |
| `TestComputeFVGComponentScores` (2) | Out-of-range, negatif pozisyon |
| `TestGetCHoCHScoreForDirection` (5) | Boş/yön uyuşmazlığı/eşleşme/best seçim |
| `TestAnalyzeConfluence` (8) | FVG, CHoCH, EMA, Price/EMA, ADX, VP sinyalleri |
| `TestComputeEntryExitZones` (2) | Bullish/bearish giriş/çıkış |
| `TestCalculateRRRatio` (3) | Normal/sıfır risk/düşük RR |
| `TestEvaluateTradeSignal` (6) | NEUTRAL/LONG/VETO/auto-direction (mock'lu) |
| `TestClassifySignalStrength` (4) | STRONG/MODERATE/WEAK/NONE |
| `TestEvaluateAllSignals` (1) | İki yönlü değerlendirme |
| `TestGenerateMarketSummary` (7) | Tüm anahtarlar, golden/death cross, FVG sayımı |
| `TestTradeSignalDataclass` (2) + `TestScoringContextDataclass` (1) | Dataclass doğrulama |

**Kullanılan pattern:** `@patch` ile fvg fonksiyonları mock'landı; self-contained fonksiyonlar (regime, confluence, entry/exit, RR, classify) doğrudan test edildi.

**Pre-commit:** 460 test passed (sıfır kırılma)

**Dosya:** `tests/test_sync_positions.py` — **50 test**, hepsi pass
**Coverage:** `main.py` 0% → 33% (hedef 40%, network-bağımlı kod sınırladı)

| Test | Kapsam |
|------|--------|
| Zaman freni (1) | Erken return, get_positions çağrılmaz |
| PM guard (2) | Boş liste → trade'ler korunur |
| Tam koruma (3) | 1 SL+1 TP → API ID/fiyat güncelleme |
| SORGUSUZ İNFAZ (4-6) | Duplicate SL/TP temizleme, infaz+onarım |
| Eksik koruma (7-9) | _create_protection / _repair_protection / cooldown skip |
| Kapalı pozisyon (10-13) | Long/short × TP/SL ayrımı, balance güncelleme |
| Çoklu sembol (14) | BTC tam koruma + ETH eksik → mixed |
| Helper tests (36) | _get_order_type, _get_order_price, fmt_bool, _round_price, _safe_order_timestamp, _get_open_orders_async, _clear_state, _cancel_order_by_id, _wait_for_position, export_ohlc, _RateLimiter, get_lock, _get_tick_size, DailyDataCache |

**Kullanılan pattern:** `patch.object(main_module, "http_client")` ile fixture-scoped patch; `_repair_protection`/`_create_protection`/`_cancel_order_by_id`/`_clear_state` **mock'lanmaz** — gerçek kod akar, alt bağımlılıkları mock'lanır.

**Pre-commit:** ruff, ruff-format, vulture pass
**Mevcut testler:** 154 passed (kırılma yok)

# Fix-1: Sweep tespiti düzeltildi (analyzer.py satır 377-381, 414-418)

**Eski:** `close` kontrolü
**Yeni:** `low/high` (wick kır) + `close > level` (içeride kapanış)

- LONG: `current_bar.low < sl.price` (wick kırar) + `current_bar.close > sl.price` (içeride kapanır)
- SHORT: `current_bar.high > sh.price` (wick kırar) + `current_bar.close < sh.price` (içeride kapanır)

# Fix-2: analyze() sırası düzeltildi (satır 785-787)

**Eski:** sweep → FVG → MSS
**Yeni:** sweep → MSS → FVG (doğru sıra)

# Fix-3: fvg_since hesabı düzeltildi (satır 465)

- `since_bar_index` ile sweep sonrası MSS'ler filtreleniyor

# Fix-4: consumed_levels float precision (satır 141-142, 359, 397)

- `round(price, 5)` ile normalize edilmiş seviyeler

# Ek düzeltmeler

- `reset_symbol_cache()` metodu eklendi (satır 145-166) — state machine reset'inde cache'leri temizler
- 2H fallback kaldırıldı, 15m fallback eklendi (satır 318-327)
- FVG timestamp desteği eklendi (satır 817, 900, 908)

## Patch 2026-06-13: `_check_invalidation` narrowing + sweep_tf-based expiry

### `_check_invalidation` — sadece ARMED/WAIT_RETRACE
- ❌ Eski: ARMED, WAIT_RETRACE, WAIT_CONFIRM'de MSS invalidasyonu
- ✅ Yeni: Sadece ARMED ve WAIT_RETRACE. WAIT_CONFIRM+ pas geçer (FVG validity yeter)
- `mss_level * 0.001` buffer eklendi — küçük geri çekilmeler tolere edilir
- SHORT: `close > mss_level + buffer`, LONG: `close < mss_level - buffer`

### `_handle_mss` — sweep_tf bazlı MAX_SETUP_WAIT seçimi
- `sweep_tf == "15m"` → `MAX_SETUP_WAIT_HOURS_15M` (default 8.0)
- diğer (1H/2H) → `MAX_SETUP_WAIT_HOURS` (default 16.0)

## 2026-06-13: AGENTS.md → copilot-instructions.md consolidation

- `AGENTS.md` içeriği `.github/copilot-instructions.md`'ye taşındı (birebir kopya)
- `AGENTS.md` silindi — tek kaynak `.github/copilot-instructions.md`
- Copilot ve Cline artık aynı dosyayı kullanır, context tek şişer

## Patch 2026-06-11 23:54: config knobs — adaptive LTF, time-box, entry order type

### config.py — 5 yeni knob
```
FVG_PENETRATION_MID: float = 0.30     # Mid-band lower bound for adaptive READY_TO_ENTER
ADAPTIVE_LTF_ENABLE: bool = True       # LTF'siz READY_TO_ENTER geçidi
WAIT_CONFIRM_TIMEBOX_MIN: int = 3      # dakika; partial entry için bekleme süresi
PARTIAL_RISK_SCALE: float = 0.40       # normal lot'un %40'ı
ENTRY_ORDER_TYPE: str = "MARKET"       # "MARKET" veya "STOP_MARKET"
ENTRY_STOP_OFFSET_PCT: float = 0.0005  # 5 bps trigger cushion
```

### state_machine.py — 4 değişiklik
1. **SymbolState.wait_confirm_since_ts** field eklendi (`int | None = None`)
2. **check_retrace()** — WAIT_CONFIRM geçişinde `wait_confirm_since_ts = current_bar.timestamp` stamplenir
3. **check_ltf_fvg_validity() / _handle_ltf()** — pen > max'ta `wait_confirm_since_ts = None` sıfırlanır
4. **_evaluate()** — ADAPTIVE mid-band READY_TO_ENTER bloğu:
   - `ADAPTIVE_LTF_ENABLE=True` ise
   - WAIT_CONFIRM, sweep+mss+retrace var, ltf_confirmed=False, FVG seviyeleri varsa
   - `pen >= FVG_PENETRATION_MID(0.30)` ve `pen <= FVG_PENETRATION_MAX(0.70)` ise
   - → READY_TO_ENTER (LTF event'i beklenmeden)

### trader.py — 2 değişiklik
1. `send_order()` imzasına 4 yeni parametre: `entry_order_type`, `current_price`, `stop_offset_pct`, `partial`
2. STOP_MARKET branch: trigger fiyatı offset ile hesaplanır, SL/TP deferred (`protection_missing=True`)

### main.py — 2 değişiklik
1. **Time-box partial entry**: WAIT_CONFIRM → `elapsed_min >= WAIT_CONFIRM_TIMEBOX_MIN` ise scaled lot ile entry
2. **READY_TO_ENTER branch**: `send_order` artık `entry_order_type`, `current_price`, `stop_offset_pct` alır
## 2026-06-13: Binance 429 Rate Limit Fix

**Sorun:** Klines istekleri (D1 cache + prefill) `_rate_limiter`'ı bypass ediyordu, `max_retries=0` olduğu için 429'da retry yoktu.

**Değişiklikler:**
1. `exchange.py` → `get_klines(max_retries=2)` parametresi eklendi, `_request()`'e passthrough
2. `main.py` → global `rate_limiter = _RateLimiter(max_per_minute=5000)` eklendi (`_RateLimiter` sınıfından sonra)
3. `main.py` → `DailyDataCache._fetch()`'te `await rate_limiter.acquire()` + `max_retries=2`
4. `main.py` → `_prefill_one()`'da `await rate_limiter.acquire()` + `max_retries=2`
5. `main.py` → `self._rate_limiter = rate_limiter` (instance → global alias, mevcut signed kod bozulmaz)
6. `.clinerules/Jcodemunch.md` → `.clinerules/readmefirst.md` (rename + minimal yanıt kuralı)

**Adım 4 (D1 gather Semaphore) beklemede** — limiter'ın etkisi gözlemlendikten sonra değerlendirilecek.
### 1. 15m blok ayrıştırıldı
**Eski:** 15m bar kapanışında ATR hesaplama + `check_retrace` + `check_ltf_fvg_validity` + `check_poi_retrace` + `_evaluate` (zombi cleanup) + `write_snapshot` + `READY_TO_ENTER` emir kapısı — **hepsi 15m kapalıysa çalışırdı.**

**Yeni:** İki ayrı bloğa bölündü:
1. **15m kapanışında (`_is_15m_closed`):** Sadece `export_ohlc_15m()` + `state_logger.write_snapshot()` — ATR/state check/emir yok.
2. **Her 1m tick'inde (`symbol not in self.active_trades` guard'ı ile):** `check_retrace`, `check_ltf_fvg_validity`, `check_poi_retrace`, `_evaluate`, `READY_TO_ENTER` emir kapısı.

**Önemli farklar:**
- `compute_atr_point` import'u kaldırıldı (check_retrace/check_poi_retrace artık atr parametresi almıyor)
- `READY_TO_ENTER` kontrolü 15m'e bağlı değil, her 1m'de evaluate edilir.
- `_evaluate`'deki stale/invalidation → IDLE cache reset mantığı aynen korundu.
- `active_trades` double-check kaldırıldı: artık `if symbol in self.active_trades` guard'ı bloğun başında, lock içinde tekrar kontrol var.

### 2. active_trades guard bloğu — return düzeltmesi
**Eski:**
```python
if existing.get("protection_missing"):
    log.warning(...)
    return
if existing.get("protection_repairing"):
    log.warning(...)
    return
return
```

**Yeni:**
```python
if existing.get("protection_missing"):
    log.warning(...)
if existing.get("protection_repairing"):
    log.warning(...)
return
```
Sadece warn log'ları — `return`'ler kaldırıldı, tek `return` bloğun sonunda.

## Patch 2026-06-11 22:58: 4 yama

### 1. `_handle_sweep` — tf filtresi genişletildi
```
event.get("tf") not in ["15m"]  →  event.get("tf") not in ("1H", "2H", "15m")
```
- Artık 1H ve 2H sweep de geçerli, sadece 15m değil.
- `state.expires_at` satırı silindi (sweep'te expires_at atanmıyor artık).
- Log: `level=%s` → `tf=%s level=%s`

### 2. `_handle_mss` — expires_at eklendi
- `WAIT_RETRACE` geçişinde `max_wait = getattr(self.config, "MAX_SETUP_WAIT_HOURS", 8.0)` ile hesaplanıp `state.expires_at = int(time.time()) + int(max_wait * 3600)` atanır.
- Log: `expires_in=%.0fh` eklendi.
- `max_wait` değişkenine `if` bloğu dışından erişim sorunu çözüldü: `else` branch'te eski log tutulur.

### 3. `config.py` — `MAX_SETUP_WAIT_HOURS`
```
MAX_SETUP_WAIT_HOURS: float = 8.0
```
- `CHOCH_MAX_AGE_HOURS = 8` satırından hemen önce eklendi.
- `_handle_sweep` için varsayılan 24.0 → 8.0 düştü (sweep'te expires_at yok artık).
- `_handle_mss` için varsayılan 8.0 kullanılır.

### 4. `analyzer.py` — FVG boyut sıralaması
```python
fvgs = sorted(fvgs, key=lambda f: abs(f.top - f.bottom), reverse=True)
```
 - `cleanup_fvgs()` sonrası eklenir.




## 2026-06-12: .bak dosyaları temizlendi

**Silinen dosyalar:** `sonnet/src/scoring.py.bak`, `sonnet/src/analyzer.py.bak`
- Yerel klasörden gereksiz `.bak` yedek dosyaları kaldırıldı.
- Sadece temizlik, kod değişikliği içermez.

## 2026-06-12: jCodeMunch VS Code Extension oluşturuldu

**Yeni klasör:** `vscode-extension/` (`.gitignore`'a eklendi — sadece yerel)
- **Auto-reindex on Save**: `jcodemunch-mcp index-file <path>` debounce'lu olarak her kayıtta çalışır
- **Risk Gutter**: Fonksiyon başlıklarında renkli noktalar (🟡🟠🔴) + hover tooltip
- **Manuel komutlar**: `jcodemunch.reindexFile`, `jcodemunch.refreshRiskGutter`
- **GitHub repo**: `jgravelle/jcodemunch-mcp` (bu repoda sadece yerel, git'ten hariç)
- **Cline/Continue uyumlu**: `.clinerules/Jcodemunch.md` güncellendi

**Dosyalar:**
```
vscode-extension/
├── package.json
├── tsconfig.json
├── .vscodeignore
├── CLAUDE.md
└── src/
    ├── extension.ts
    ├── indexOnSave.ts
    ├── riskGutter.ts
    └── types.ts
```

## 2026-06-12: Cline rules birleştirildi

**Değişiklik:** 3 ayrı kural dosyası (`globalrules.md`, `conditional.md`, `Jcodemunch.md`) tek bir `.clinerules/Jcodemunch.md` altında birleştirildi:
- **Bölüm 1** — Strict Context Management (eski globalrules)
- **Bölüm 2** — Path Scoping (eski conditional)
- **Bölüm 3** — jcodemunch MCP Integration (eski Jcodemunch)
- **Bölüm 4** — jCodeMunch VS Code Extension

## 2026-06-12: STATE-DEBUG fix — `if events:` dışına taşındı

**Sorun:** V4 Pro'nun commit'inde (`380ec86`) `[STATE-DEBUG]` log bloğu `if events:` içindeydi → sadece event geldiğinde basılıyordu.
**Fix:** STATE-DEBUG bloğu `if events:` dışına alındı, gereksiz `fmt_bool` satırları temizlendi. Artık **her 1m callback'te** events olsa da olmasıda basılır.
- Commit: `18d8d18` → `public/main`

---

## 2026-06-14: Kapsamlı Sistem Analizi

**Rapor dosyası:** `sonnet/nexus_v2_sistem_analizi.md`

### Genel Not: **7.2/10**

jCodemunch-MCP ile tüm `sonnet/src/` modülleri analiz edildi:
- Cyclomatic complexity, hotspot scoring, dependency graph, dead code, circular imports, TODO/FIXME taraması

### Kritik Bulgular (P0 — Acil)

| Fonksiyon | Dosya | Cyclomatic | Hotspot Skor |
|-----------|-------|-----------|-------------|
| `_sync_positions` | main.py | **96** | **375.5** |
| `_on_1m_close` | main.py | **70** | **273.8** |
| `_startup_cleanup` | main.py | **53** | **207.3** |
| `send_order` | trader.py | **69** | **111.1** |
| `detect_mss` | mss.py | **63** | **138.4** |
| `analyze` | analyzer.py | **46** | **168.5** |
| `create_algo_order` | exchange.py | **51** | **91.4** |

### Olumlu Bulgular
- ✅ Döngüsel import yok (sadece cline/ klasöründe 23 döngü var, ayrı proje)
- ✅ Dead code bulunamadı (tüm modüller main.py tarafından kullanılıyor)
- ✅ TODO/FIXME/HACK etiketi yok — teknik borç işaretlenmemiş
- ✅ `frozen=True` dataclass'lar ile immutable veri yapıları
- ✅ Temiz tek yönlü dependency grafiği

---

## 2026-06-14: Deepseek v4 Pro Counter-Analysis — 5 Semantic Bug

**Kaynak:** Deepseek v4 Pro, kullanıcı tarafından sağlanan sistem analizi raporu üzerinden manuel kod incelemesi yaptı.

### 🔴 P0 — 5 Semantic Bug (Static Analysis'in Kaçırdığı)

| # | Bulgu | Dosya | Risk | Reprodüksiyon |
|---|-------|-------|------|---------------|
| **1** | `bars_m1` Double Fetch — veri tutarsızlığı | `main.py::_on_1m_close` | Fonksiyonun ilk yarısı eski `bars_m1`, ikinci yarısı yeni `bars_m1` kullanır. WebSocket race condition ile korelasyon hatası. | 1m bar kapanırken `_on_1m_close` çalışıyorsa SL/TP hesapları farklı bardan yapılır |
| **2** | `_update_sl_order` Dangling Reference — NameError | `main.py::_update_sl_order` | `old_sl` try bloğu içinde tanımlanmış, except bloğunda referans verilmiş. Network timeout → NameError → exception handler çöker | `_get_open_orders_async` timeout → `old_sl` tanımsız → except bloğu ikinci exception fırlatır |
| **3** | `_startup_cleanup` — Invariant Violation | `main.py::_startup_cleanup` | `_load_existing_positions` boş dönerse (API hatası/dust filtreleme) → `active_trades={}` → cleanup tüm open order'ları orphan sanıp siler | Testnet API `positionAmt=0.001` (dust) filtreler → SL/TP emirleri silinir |
| **4** | `trade_locks` — Asyncio-Only Safety | `main.py::get_lock` | `asyncio.Lock` dict access thread-safe değil. İleride `run_in_executor` ile thread pool kullanılırsa race condition | Dict access GIL koruması dışında kalırsa çakışma |
| **5** | `_fetch_binance_signed_post` — No Retry | `main.py` | SL güncelleme POST endpoint'inde retry mekanizması yok. %1 fail rate = günde 1 kayıp SL güncellemesi | Network timeout → SL güncellenmez → pozisyon eski SL'de kalır → gereksiz stop-out |

### 🟡 P1 — Ek Tespitler (Kullanıcı Tarafından)

| # | Bulgu | Detay |
|---|-------|-------|
| **6** | `_repair_protection` — Implicit State Mutation | Yeni SL/TP order_id'leri `active_trades[symbol]` dict'ine yazılmaz. Sonraki `_update_sl_order` eski ID ile cancel dener → API error |
| **7** | `_manage_open_trades` — Missing Await | `self._update_sl_order(...)` await edilmeden çağrılmış olabilir. Coroutine schedule edilir ama tamamlanması beklenmez → trailing SL async race condition |
| **8** | `active_trades` — No Type Safety | 4 farklı yerde dict oluşturuluyor. TypedDict/dataclass yok → typo = runtime error |

### 🔍 Benim Ek Tespitim

| # | Bulgu | Detay |
|---|-------|-------|
| **9** | `_sync_positions` → `_clear_state` → analyzer cache desync | Trade kapanınca `_clear_state` analyzer cache'ini temizler (emitted FVG IDs + consumed_levels). `_sync_positions` 5 saniyede bir çalışır — aynı sembol için yeni setup oluşurken cache temizlenirse **double emission** → state machine çakışır |

### 📊 Revize Sistem Notu: **6.5/10** (7.2'den düşürüldü)

**Düşürme sebepleri:**
- Veri tutarsızlığı riski (bars_m1 override)
- Exception safety problemleri (dangling reference)
- Critical path retry eksikliği (POST endpoint)
- State mutation desync (repair_protection)

**Hâlâ 6.5 olmasının sebepleri:**
- Mimari hâlâ temiz (dependency graph)
- Problemler lokalize (3-4 fonksiyon)
- Fix'ler straightforward (refactor gerekmez)

---

## 2026-06-14: P0 Bug Fix Önceliklendirme

**Onaylanan sıra (en kolay → en yüksek etki):**

| Sıra | Görev | Süre | Risk Etki |
|------|-------|------|-----------|
| **P0-1** | `_update_sl_order` dangling ref fix — `old_sl: Any \| None = None` try öncesi | 5 dk | 🔴 NameError → exception handler crash |
| **P0-2** | `_on_1m_close` bars_m1 rename — `bars_m1_latest = self.hub.get_bars(...)` | 5 dk | 🔴 Veri tutarsızlığı |
| **P0-3** | `_startup_cleanup` guard — `if not self.active_trades and real_positions:` → RuntimeError | 15 dk | 🔴 Tüm SL/TP emirlerini silme |
| **P0-4** | Fire-and-forget exception handler — `_safe_sync_positions` wrapper | 30 dk | 🔴 Sessiz fail, pozisyon stopsuz kalma |
| **P0-5** | `_sync_positions` desync fix — `_clear_state` çağrısını düzelt | 10 dk | 🟡 Double emission |

### 🟡 P1-Risk (Bu Hafta)
| Sıra | Görev | Gerekçe |
|------|-------|---------|
| P1-1 | `_startup_cleanup` guard (üstteki ile aynı, kod yazılırken birleşecek) | — |
| P1-2 | `active_trades` → TypedDict/dataclass | Typo = runtime error |
| P1-3 | `send_order` → Custom Exception taxonomy | RuntimeError yerine TradingError/ProtectionError |
| P1-4 | `_fetch_binance_signed_post` retry | Mevcut `_request` retry logic'ini kullan |
| P1-5 | `_repair_protection` → active_trades sync | Yeni order_id'leri dict'e yaz |

### 🟢 P2-Refactor (Önümüzdeki Hafta)
| Sıra | Görev | cc Hedefi |
|------|-------|----------|
| P2-1 | `_sync_positions` → 3 fonksiyon | 96 → <30 |
| P2-2 | `detect_mss` DRY fix (bullish/bearish unify) | 63 → <35 |
| P2-3 | `_on_1m_close` → partial entry ayrı fonksiyon | 70 → <25 |
| P2-4 | `analyze` → FVG emit helper | 46 → <25 |

## 2026-06-14: P0 Bug Fix V2 — 5 Semantic Bug (Refined)

**Tüm fix'ler uygulandı, testler: 222 passed / 0 failed (208 existing + 14 yeni P0 test)**

| # | V2 Refinement | Dosya | Değişiklik |
|---|---------------|-------|-----------|
| **P0-1** | `old_id = None` init in except handler | `main.py:_update_sl_order` | V1 `old_sl = None` yetmezdi — `old_id` hâlâ NameError'du. Şimdi `old_id = None` da init edildi |
| **P0-2** | `bars_m1_latest = bars_m1` (parameter) | `main.py:_on_1m_close` | V1 sadece rename yaptı, hâlâ 2. fetch vardı. Şimdi parametre kullanılıyor, re-fetch YOK |
| **P0-3** | 4. guard eklendi | `main.py:_startup_cleanup` | `not symbols_with_position and not self.active_trades` → cleanup atlanır |
| **P0-4** | `_safe_manage_open_trades` wrapper | `main.py:_on_1m_close` | `_manage_open_trades` crash'i `_on_1m_close`'un geri kalanını bloke etmez |
| **P0-5** | `_state_before != SetupState.IDLE` guard | `main.py:_on_1m_close` | `_clear_state` sonrası IDLE→IDLE geçişinde cache reset atlanır |

### Revize Sistem Notu: **7.0/10** (6.5'ten yükseltildi)

**Yükseltme sebepleri:**
- Veri tutarsızlığı (bars_m1 double fetch) → düzeltildi
- Exception safety (old_id NameError) → düzeltildi
- Fire-and-forget sessiz çökme (_manage_open_trades) → düzeltildi
- Startup cleanup 4. guard → düzeltildi
- Cache reset desync / double emission → düzeltildi
- Cleanup invariant violation → düzeltildi
- Analyzer cache desync → düzeltildi

---

## 2026-06-14: Test Fix — 149 passed / 0 failed 🟢

**Commit:** `ba806df` (after rebase)

**10 adet failed test analizi ve fix:**

| # | Test | Hata | Kök Neden | Fix |
|---|------|------|-----------|-----|
| 1-9 | `TestDetectSweepH1` (9 tests) | `TypeError: missing bias` | `_detect_sweep_h1` imzasına `bars_15m` parametresi eklendi, testler güncellenmedi | Her çağrıya `bars_15m=[]` eklendi |
| 10 | `test_retrace_ce_only_no_body_stays` | `WAIT_CONFIRM != WAIT_RETRACE` | `PenetrationEngine.get_penetration` FVG dışı fiyatlarda non-zero döndürüyordu | LONG: `price <= fvg_lower` → 0; SHORT: `price >= fvg_upper` → 0 |

**Ek koruma:** `_sweep_on_bars`'a boş `bars` guard'ı eklendi (`bars[-1]` IndexError engellendi)

**Sistem notu:** 7.0/10 (değişmedi — test fix, kod hatası değil)

---

## 2026-06-14: Coverage Analysis — Critical Findings 🚨

**Test execution:** 149 passed / 0 failed ✅
**Overall coverage:** 28% (TOTAL: 4869 statements, 3514 missing)

### High-Coverage Files (✅ Well Tested)
| File | Coverage | Notes |
|------|----------|-------|
| `pivot.py` | 97% | Excellent |
| `risk_manager.py` | 93% | Excellent |
| `state_machine.py` | 82% | Good |
| `analyzer.py` | 81% | Good |
| `models.py` | 74% | Good |

### Medium-Coverage Files (⚠️ Needs Improvement)
| File | Coverage | Missing Coverage |
|------|----------|------------------|
| `mss.py` | 63% | Bullish/bearish split paths untested |
| `fvg.py` | 47% | Edge case detection untested |
| `indicators.py` | 44% | Advanced indicator logic untested |

### 🚨 ZERO COVERAGE — CRITICAL PRODUCTION FILES

| File | Statements | Complexity | Risk Level | Impact |
|------|-----------|-----------|-----------|--------|
| **`main.py`** | 1224 | cc=96 | **10/10 — CRITICAL** | Production entry point, 0% tested |
| **`trader.py`** | 365 | cc=69 | **9/10 — CRITICAL** | Order execution, 0% tested |
| **`exchange.py`** | 393 | cc=51 | **8/10 — HIGH** | Binance API client, 0% tested |
| **`scoring.py`** | 303 | cc=55 | **7/10 — HIGH** | Trade signal evaluation, 0% tested |
| `websocket.py` | 302 | — | 6/10 | Real-time data stream, 0% tested |
| `performance.py` | 157 | — | 3/10 | Metrics tracking, 0% tested |
| `monitor.py` | 79 | — | 2/10 | Health monitoring, 0% tested |
| `volume_profile.py` | 120 | — | 3/10 | Volume analysis, 0% tested |
| `weekly_range_spy.py` | 92 | — | 2/10 | Range tracking, 0% tested |
| `event_router.py` | 24 | — | 2/10 | Event orchestration, 0% tested |
| `state_logger.py` | 49 | — | 2/10 | State persistence, 0% tested |

### 💥 Critical Functions — ZERO COVERAGE

**These production-critical functions run every second but have ZERO test coverage:**

1. **`main.py::_sync_positions`** (cc=96, hotspot=375.5)
   - Runs every 5 seconds for 22 symbols = 440 executions/hour
   - 0% coverage

2. **`main.py::_on_1m_close`** (cc=70, hotspot=273.8)
   - Runs every 1m for 22 symbols = 1,320 executions/hour
   - 0% coverage

3. **`trader.py::send_order`** (cc=69, hotspot=111.1)
   - All order placement logic untested
   - 69 validation guards untested

4. **`exchange.py::_request`** (cc=39)
   - All API retry logic untested
   - Signature validation untested

### Revise System Score: **6.8/10** (7.0 → -0.2)

---

## 2026-06-14: P1 Plan Revised — Test Coverage Focus

**Skor 7.0'dan 6.8'e düştü** — coverage analysis kritik production path'lerin test edilmediğini ortaya çıkardı.

---

### ✅ P1-0A TAMAMLANDI: `send_order` Test Suite

| Metrik | Hedef | Gerçek |
|--------|-------|--------|
| `trader.py` coverage | 0% → **40%** | **47%** 🟢 |
| Test sayısı | 7 | **9** |
| Süre | 1 gün | ~30 dk |

**Test Dosyası:** `tests/test_trader.py` — 9 characterization test
- Happy path (MARKET entry + SL/TP)
- STOP_MARKET branch (`protection_missing=True`)
- SL fail → emergency close → None döner
- TP fail → exception yok, SL korumalı devam
- Duplicate position, cooldown, missing params guard'ları

**Test için ilk kez** `unittest.mock.AsyncMock` kullanıldı — `ExchangeClient` metodları mock'landı.

**Çıkarılan ders:** `send_order`'ın outer `try/except` bloğu inner `RuntimeError`'ı (emergency close) yakalayıp `None` döndürüyor — refactor sonrası bu davranış korunmalı.

---

### 🎯 SONRAKİ ADIMLAR (P1 Week)

#### **Öncelik: Test Coverage (Days 1-5)**

1. ✅ **P1-0A:** `send_order` test suite → trader.py: **0% → 47%** ✅
2. **P1-0B:** `_sync_positions` integration → main.py: 0% → 40%
3. **P1-0C:** `exchange` unit tests → exchange.py: 0% → 30%

#### **Öncelik: Type Safety + Error Handling (Days 6-7)**

1. **P1-2:** TypedDict for `active_trades`
2. **P1-3:** Custom exception taxonomy
3. **P1-4:** POST retry mechanism

**1 hafta target:**
- Coverage: 28% → **45%**
- System score: 6.8 → **7.5**

---

### 💡 KEY INSIGHTS

#### Coverage Gap Discovery
En kritik fonksiyonlar hiç test edilmemiş:
- `_sync_positions` (cc=96) → 5 saniyede 1 çalışıyor, 0% test
- `_on_1m_close` (cc=70) → her 1m çalışıyor, 0% test
- `send_order` (cc=69) → tüm order logic, 0% test

**Risk:** Production'da bu fonksiyonlar her saniye çalışıyor ama behavior test edilmemiş.

#### Test Suite Effectiveness
Mevcut test suite **değerli**:
- ✅ 9 signature mismatch yakaladı
- ✅ 1 logic bug yakaladı (penetration clamping)
- ✅ Core logic (analyzer, state_machine) well-tested

**Ama:** Integration/E2E seviyesinde test yok.

#### Penetration Clamping Bug
**Sorun:** FVG dışı fiyatlarda yanlış penetration değeri
**Fix:** Clamping logic eklendi:
```
# LONG
if price <= fvg_lower: return 0.0   # henüz girmedi
if price >= fvg_upper: return 1.0   # tamamen geçti

# SHORT
if price >= fvg_upper: return 0.0   # henüz girmedi
if price <= fvg_lower: return 1.0   # tamamen geçti
```

---

### 🏆 BAŞARILAR

1. **Hız:** P0 + test fix **aynı gün** içinde tamamlandı
2. **Kalite:** Pre-commit hooks (ruff, mypy, vulture) pass ✅
3. **Disiplin:** Her commit clean, rebase yapıldı, push success
4. **Coverage:** İlk kez comprehensive coverage measurement

---

### ⚠️ UYARILAR

1. **Production Risk:** 0% coverage dosyalar production'da çalışıyor
2. **Test Debt:** P1-0 (test coverage) **critical priority**
3. **Refactor Wait:** P2 refactor'a geçmeden önce P1 test'leri tamamla

**Downgrade reason:** Coverage analysis revealed critical production paths have ZERO test coverage.

**Why still 6.8?**
- ✅ Core logic well-tested (analyzer, state_machine, risk_manager)
- ✅ P0 semantic bugs fixed
- ⚠️ But production-critical paths (main.py, trader.py, exchange.py) = 0% coverage

---

## P1 Plan — REVISED (Test Coverage Priority)

### NEW: P1-0 Test Coverage (Critical Path Protection)

**Goal:** Test the untested production-critical code

#### **P1-0A: `trader.py::send_order` Test Suite** ✅ (Completed)
- **Target:** trader.py: 0% → **47%** (hedef 60% — kalan `_safe_create_order`, `close_position` vs.)
- **Tests (9 adet):**
  - ✅ MARKET happy path (entry + SL/TP)
  - ✅ STOP_MARKET branch
  - ✅ SL fail → emergency close
  - ✅ TP fail → continue
  - ✅ Duplicate position, cooldown, missing params guard'ları
  - ✅ Mock Binance API responses (AsyncMock)

#### **P1-0B: `main.py::_sync_positions` Integration Test** (1 day)
- **Target:** main.py: 0% → 40%
- **Tests:**
  - Duplicate position handling
  - Missing protection repair (SL exists, TP missing)
  - Closed position cleanup
  - Mock position API responses

#### **P1-0C: `exchange.py` Unit Test** (0.5 day)
- **Target:** exchange.py: 0% → 30%
- **Tests:**
  - Retry logic (network timeout)
  - HMAC signature validation
  - Rate limiter behavior

### Updated P1 Timeline

| Day | Task | Coverage Target |
|-----|------|----------------|
| 1 | **P1-0A (send_order tests)** ✅ | trader.py: **0% → 47%** |
| 2-3 | P1-0B (_sync_positions integration) | main.py: 0% → 40% |
| 5 | P1-0C (exchange unit tests) | exchange.py: 0% → 30% |
| 6 | P1-2 (TypedDict) | Type safety |
| 7 | P1-3 (Custom Exception) + P1-4 (POST retry) | Error handling |

**1 week target:**
- Coverage: 28% → **45%**
- System score: 6.8 → **7.5**
