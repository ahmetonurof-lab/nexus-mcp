# Known Bugs & Architectural Risks

## D-2: Trailing/entry formülleri live + 2 backtest motorunda kopya kod, senkronizasyon garantisi yok

**Severity:** HIGH
**Status:** OPEN
**Date:** 2026-07-24
**Files:**
- `sniper/src/trading/trailing_manager.py` (live — TrailingManager.evaluate_trail)
- `sniper/simulate.py` (fast backtest — inline trailing block)
- `backtest-sniper/src/analyzer_v5.py` (benchmark engine — collect_fvg_profile trailing block)

### Problem

Trailing/entry formülleri üç ayrı yerde elle kopyalanmış, tek bir modülden import edilmiyor.
Geçmişte yapılan fix'ler sadece birine uygulanmış, diğerleri kalmış.

### Tespit Edilen Farklar

#### Fark 1 (HIGH): `exit_now` guard — FVG kırıldı exit'i

Live (`trailing_manager.py:95-96, 109-110`):
```python
# Long
if new_sl >= current.close:
    return TrailResult(exit_now=True)
# Short
if new_sl <= current.close:
    return TrailResult(exit_now=True)
```

Backtest'lerde (**simulate.py** ve **analyzer_v5.py**): **YOK**

**Etki:** Canlıda FVG fiyatı geçtiyse (FVG kırıldıysa) trade hemen kapatılıyor.
Backtest'lerde fiyat eski FVG'yi geçmiş olsa bile trailing devam ediyor —
trade normalden uzun açık kalabilir, backtest sonuçları optimist olur.

#### Fark 2 (MEDIUM): `fvg_close_confirmed` — `is_closed` kontrolü

Live (`trailing_manager.py:39-40`):
```python
if not b.is_closed:
    break
```

Backtest'ler (**simulate.py:141-156**, **analyzer_v5.py:152-167**): **YOK**

**Etki:** Backtest'lerde tüm barlar `is_closed=True` ile oluşturulduğu için
pratikte farklılık üretmiyor. Ancak kod mantıksal olarak farklı — live'da açık
bar taranırken backtest'lerde bu guard yok.

#### Fark 3 (MEDIUM): `is_closed` guard — trigger seviyesinde

`simulate.py`, `SignalEngine.evaluate_trigger()` kullanıyor —
`signal_engine.py:103-107`'de `if not current.is_closed: ... rsm.reset(); SKIP` var.

`analyzer_v5.py` inline RSM ilerletiyor (`rsm.on_sweep`, `rsm.on_sweep_confirmed`,
`rsm.can_trigger()`) — **`is_closed` guard'ı yok**. Açık bar'da trigger olabilir.

**Etki:** analyzer_v5 open-bar'da trade girebilir, live/simulate giremez.

#### Fark 4 (LOW): `trailing_count` sayımı

| Dosya | Davranış |
|---|---|
| `trailing_manager.py` (live) | Her qualifying FVG'de `trail_count += 1` |
| `analyzer_v5.py` | `ltc += 1` per FVG, sonra `+ ltc` (live ile aynı) |
| `simulate.py:385` | Loop sonunda `+ 1` (her zaman 1, FVG sayısına bakmaz) |

**Etki:** simulate.py birden fazla FVG tetiklendiğinde trail sayısını eksik sayar.

#### Fark 5 (LOW): Session filter farkı

| Dosya | Session filtresi |
|---|---|
| `simulate.py` | `SignalEngine` → `detect_phase_from_timestamp()` → `SessionPhase.LONDON/NEWYORK` |
| `analyzer_v5.py` | Inline: `(h >= sh or h < eh) if spans_midnight else (sh <= h < eh)` — `get_session_hours()` |

Farklı session boundary hesaplayıcıları, bazı sembollerde farklı giriş noktalarına yol açabilir.

### Aynı Olan Kısım

- Core trailing condition: `new_sl > current_sl AND (new_sl - current_sl) > risk_pts * TRAIL_MIN_MOVE_MULT` → **birebir aynı**
- FVG detect params: `lookback=min(50, len(tc))`, `timeframe="15m"`, `min_fvg_size` → **birebir aynı**
- Trailing buffer: `atr * ATR_TRAIL_MULT` → **birebir aynı**
- Entry/SL/TP hesaplama (buffer, TP_RR, quality_mult, CBDR) → **birebir aynı**

### Önerilen Çözüm

1. `trailing_manager.py`'deki `evaluate_trail()` ve `fvg_close_confirmed()` fonksiyonlarını
   ortak bir modüle çıkar (ör. `trading/formulas.py` veya mevcut `trading/trailing_manager.py`'i import).
2. Backtest'lerde inline trailing blokları yerine bu import'u kullan.
3. `exit_now` guard'ı backtest'lere de ekle veya live'dan kaldır (karar gerekiyor).
4. `is_closed` guard'ı `fvg_close_confirmed`'e ekle (backtest'lerde de一致 olsun).
5. Session filter'ı tek bir yere indir — analyzer_v5 inline hesaplamayı `session_router`'a devretsin.

---

*Bu dosya projectId'ye ait bilinen mimari riskleri ve kopya kod sorunlarını takip eder.*
