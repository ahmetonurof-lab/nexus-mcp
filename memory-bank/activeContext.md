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

## 2026-06-14: P0 Bug Fix — 5 Semantic Bug (Completed)

**Tüm fix'ler commitlendi, testler: 139 passed / 10 failed (known)**

| # | Fix | Commit | Dosya | Değişiklik |
|---|-----|--------|-------|-----------|
| **P0-1** | `_update_sl_order` dangling ref | `75df245` | `main.py:_update_sl_order` | `old_sl = None` try öncesi eklendi |
| **P0-2** | `_on_1m_close` bars_m1 rename | `559287e` | `main.py:_on_1m_close` | İkinci fetch `bars_m1_latest` olarak rename |
| **P0-3** | `_startup_cleanup` guard | `3ec8da3` | `main.py:_startup_cleanup` | `active_trades` boş + API'de pozisyon var → guard |
| **P0-4** | Fire-and-forget handler | `54d4411` | `main.py:_safe_sync_positions` | wrapper + create_task güncellemesi |
| **P0-5** | `_sync_positions` desync | `59af55a` | `main.py:_clear_state` | `reset_symbol_cache` sadece ilk cleanup'te |

### Revize Sistem Notu: **7.0/10** (6.5'ten yükseltildi)

**Yükseltme sebepleri:**
- Veri tutarsızlığı (bars_m1 override) → düzeltildi
- Exception safety (dangling ref) → düzeltildi
- Fire-and-forget sessiz çökme → düzeltildi
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
