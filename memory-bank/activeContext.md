# Sweep Değişikliği — H1 → 2H Fallback

## Eski: `_detect_sweep_15m`
- 15m barlardan swing pivot tespiti (`left=3, right=3`)
- Son 5 pivot taranır
- Body boyu filtresi YOK
- Sadece wick kır + close dönüş kontrolü

## Yeni: `_detect_sweep_h1` + `_sweep_on_bars`

### `_detect_sweep_h1`
```python
def _detect_sweep_h1(
    self,
    symbol: str,
    bars_h1: list[Bar],
    bias: Literal["LONG", "SHORT"],
) -> list[dict]:
```

**Akış:**
1. Önce `_sweep_on_bars(symbol, bars_h1, bias, tf="1H")` — H1'de sweep dene
2. H1'de bulunamazsa `_resample_to_2h(bars_h1)` → sentetik 2H bar
3. `_sweep_on_bars(symbol, bars_2h, bias, tf="2H")` — 2H fallback

### `_sweep_on_bars`
```python
def _sweep_on_bars(
    self,
    symbol: str,
    bars: list[Bar],
    bias: Literal["LONG", "SHORT"],
    tf: str,
) -> list[dict]:
```

**Pivot tespiti:** `find_swing_highs(bars, left=3, right=3)` — her pivot için sağda 3, solda 3 bar = **7 bar** aralığı. HH/LH ayrımı YOK — sadece lokal extreme high/low.

**Taranan pivot sayısı:** Son **5 pivot** (`reversed(highs[-5:])`)

**Body boyu filtresi:** YOK

**Sweep koşulu:**
- LONG bias → SSL: `current_bar.low < sl.price AND current_bar.close > sl.price`
- SHORT bias → BSL: `current_bar.high > sh.price AND current_bar.close < sh.price`

**consumed_levels:** `round(price, 5)` ile normalize edilir, aynı seviye tekrar sweep sayılmaz.

### `analyze()` çağrısı
```python
sweep_events = self._detect_sweep_h1(self.symbol, bars_h1, bias)
```

### `_resample_to_2h`
```python
def _resample_to_2h(bars_h1: list[Bar]) -> list[Bar]:
```
2 adet 1H barını birleştirir:
- `high = max(b1.high, b2.high)`
- `low = min(b1.low, b2.low)`
- `close = b2.close`
- `open = b1.open`
- `volume = b1.volume + b2.volume`

## Son Fix (2026-06-11): `sl.index` → `sl.bar_index`

**Dosya:** `analyzer.py` — `_sweep_on_bars()` metodundaki pivot kalite filtresi

**Sorun:** `SwingPoint` dataclass'ında `bar_index` alanı var (`kind`, `price`, `bar_index`), `index` diye bir alan yok. `sl.index` ve `sh.index` kullanılıyordu.

**Değişiklik:**
```
sl.index → sl.bar_index
sh.index → sh.bar_index
```
(bars listesinde de `bars[sl.index - 1]` → `bars[sl.bar_index - 1]`)

**Pivot kalite filtresi akışı:**
1. `sl.bar_index > 0` ve `sl.bar_index < len(bars) - 1` kontrolü
2. Sol/sağ komşu barlardan `low` alınıp `swing_size` hesaplanır
3. `swing_size < atr * SWEEP_PIVOT_QUALITY_ATR(0.20)` ise → zayıf pivot, skip

**Test:** 144 pass, 1 pre-existing fail (alakasız `test_retrace_ce_only_no_body_stays`)

## Patch 2026-06-11 23:07: main.py — 15m/1m state machine refactoring

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
