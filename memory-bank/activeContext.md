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
