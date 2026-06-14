# P0-1 → P0-5: Semantic Bug Fix Series

> **Hedef:** Deepseek v4 Pro analizinde tespit edilen 5 semantic bug'ı sırayla fix'le.
> **Yöntem:** Her bug için **önce test → sonra fix** (characterization test + minimal fix).
> **Referans:** P1-0B'deki gibi — mevcut davranışı testle yakala, sonra düzelt.

---

## 🎯 P0-1: `_update_sl_order` Dangling Reference

**Dosya:** `sonnet/src/main.py`
**Problem:** `_update_sl_order()` içinde `old_sl` try bloğunda tanımlanır (`old_sl = next(...)`). Eğer `next()` veya API çağrısı exception fırlatırsa, except bloğuna düşer ama `old_sl` tanımlanmamıştır — `NameError` patlar.

**Fix:**
```python
def _update_sl_order(self, symbol: str, trade: dict, new_sl: float):
    old_sl = None  # <-- try öncesinde tanımla
    try:
        ...
        old_sl = next(...)
    except Exception as e:
        if old_sl is None:
            # old_sl hiç set edilmemiş — pozisyon zaten kapalı olabilir
            log.warning(...)
            return
        ...
```

**Test:** `_update_sl_order`'a exception senaryosu yaz (next() başarısız).

---

## 🎯 P0-2: `_on_1m_close` bars_m1 Double Fetch

**Dosya:** `sonnet/src/main.py`
**Problem:** `_on_1m_close` içinde `bars_m1 = self.hub.get_bars(...)` **2 kere** çağrılır. Fonksiyonun ilk yarısı eski barları, ikinci yarısı yeni bar'ı (güncel) kullanır — veri tutarsızlığı.

**Fix:**
```python
async def _on_1m_close(self, ...):
    bars_m1 = self.hub.get_bars(symbol, "1m")  # TEK çağrı
    bars_m1_latest = bars_m1  # alias kullan
    ...
    # Tüm kod bars_m1 veya bars_m1_latest kullanır, ikinci get_bars çağrısı YOK
```

**Test:** Mock `hub.get_bars` ve sadece 1 kere çağrıldığını doğrula.

---

## 🎯 P0-3: `_startup_cleanup` Invariant Violation

**Dosya:** `sonnet/src/main.py`
**Problem:** `_startup_cleanup` 3 guard'a rağmen hâlâ tehlikeli:
1. `positions_list` boş → cleanup atlanır ✅
2. `symbols_with_position` boş ama `active_trades` dolu → atlanır ✅
3. `active_trades` boş ama `symbols_with_position` dolu → atlanır ✅
4. **Eksik guard:** `active_trades` boş VE `symbols_with_position` boş → cleanup çalışır, tüm open order'lar "orphan" sanılır

**Fix:** 4. durum için guard ekle:
```python
if not symbols_with_position and not self.active_trades:
    log.warning("... cleanup ATLANIYOR")
    return
```

**Test:** Mock ile her guard senaryosunu test et.

---

## 🎯 P0-4: Fire-and-Forget Exception Handler

**Dosya:** `sonnet/src/main.py`
**Problem:** `_safe_sync_positions()` zaten var ama `_manage_open_trades` ve diğer periyodik görevlerin exception handler'ı yok. Bot crash yediğinde sessizce çöker.

**Fix:** `_safe_manage_open_trades()` wrapper ekle, `_on_1m_close` içindeki tüm `await` çağrılarını wrap'le.

---

## 🎯 P0-5: `_sync_positions` → `_clear_state` Desync

**Dosya:** `sonnet/src/main.py`
**Problem:** `_clear_state()` `reset_symbol_cache()` çağırır — bu analyzer'daki `_emitted_fvg_ids` ve `_seen_mss` set'lerini temizler. Aynı sembol için yeni setup oluşmuşsa, bu set'lerin temizlenmesi double emission'a yol açar (FVG/MSS event'leri tekrar emit edilir). Mevcut kodda `if removed is not None` kontrolü var ama yetersiz.

**Fix:** `_clear_state` içinde `reset_symbol_cache` çağrısını daha selektif yap veya `_sync_positions`'ın ikinci kez çağrılması durumunda cache korunsun.

---

## 📊 Başarı Kriteri

- ✅ Her bug için **karakterizasyon testi** (önce behavior capture, sonra fix)
- ✅ Tüm P0 fix'leri commit'lenmiş
- ✅ Mevcut testler kırılmamış (204 test pass)
- ✅ main.py coverage korunmuş (≥33%)
- ✅ Pre-commit hooks: ruff, vulture pass

## 🧪 Test Style (P1-0B'den örnek)

```python
@pytest.mark.asyncio
async def test_update_sl_order_network_error(bot):
    """_update_sl_order: next() exception → NameError patlamaz, graceful return."""
    bot._get_open_orders_async = AsyncMock(side_effect=RuntimeError("API timeout"))
    bot.active_trades["BTCUSDT"] = make_trade()

    # Exception patlamamalı
    await bot._update_sl_order("BTCUSDT", bot.active_trades["BTCUSDT"], 49000.0)
    assert True  # reached without error
```

## 📂 Referans Dosyalar

- `tests/test_sync_positions.py` — fixture'lar, test double'lar, pattern referansı
- `tests/conftest.py` — mevcut fixture'lar
- `memory-bank/` — proje durumu, yapılanlar
- `.github/copilot-instructions.md` — code exploration policy, jCodemunch kullanımı
