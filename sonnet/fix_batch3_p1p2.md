# Batch 3/4 — P1 Stabilite + P2 Borç

---

## Fix 9: `warnings.warn` modül seviyesinde — `models.py:354`

**Sorun:** `warnings.warn(DeprecationWarning)` modül seviyesinde, her import eden dosyada warning basılıyor. Test çıktılarını kirletiyor.

**Yapılacak:** `warnings.warn` bloğunu sil VEYA `if __name__ == "__main__"` altına al. Alternatif: `__getattr__` içinde ilk erişimde bir kere warn bas.

En temizi: bloğu tamamen kaldır, `__getattr__` zaten lazy import yapıyor, ayrıca warning'e gerek yok.

```python
# Bu bloğu sil:
# warnings.warn(
#     "Import AnalysisResult from analyzer.py instead of models.py",
#     DeprecationWarning,
#     stacklevel=2,
# )
```

**Dosya:** `sonnet/src/models.py`

---

## Fix 10: `_safe_create_order` retry tutarsız — `trader.py:414-429`

**Sorun:** Son denemede `-2021` gelirse `raise` → caller `except` → `None` döner, hata sessizce kaybolur.

**Yapılacak:** `return None` satırına ulaşılmadan önce son bir log bas:
```python
for i in range(retries):
    try:
        resp = await self.client.create_order(**payload)
        return resp
    except Exception as e:
        err_str = str(e)
        if "-2021" in err_str and i < retries - 1:
            log.warning(...)
            await asyncio.sleep(0.3)
            continue
        if i == retries - 1:
            log.error("[ORDER] %s tüm retry'ler başarısız: %s", symbol, e)
        raise
return None
```

**Dosya:** `sonnet/src/trader.py`

---

## Fix 11: Backtest `TAKER_FEE` eksik — `sonnet/src/backtest.py`

**Sorun:** Backtest slippage simüle ediyor ama komisyon (TAKER_FEE) hesaba katılmıyor. Gerçek P&L'den sapar.

**Yapılacak:**
- `config.py`'den `TAKER_FEE = 0.0004` (Binance default) ekle veya mevcutsa kullan
- Her trade açılış ve kapanışta `amount * price * TAKER_FEE` kes
- SL/TP tetiklendiğinde de fee uygula (taker fee)

**Dosya:** `sonnet/src/backtest.py` ve/veya `sonnet/src/config.py`

---

## Fix 12: `state_logger.py` disk doluluk kontrolü

**Sorun:** 10 günlük CSV rotasyonu var ama disk dolduğunda `OSError` → sessiz fail → 15dk snapshot kaybı.

**Yapılacak:** `write_snapshot` metodunda `try/except OSError` ekle, kritik log bas:
```python
try:
    # ... write işlemi ...
except OSError as e:
    logger.critical("[STATE LOGGER] Disk yazma hatası — snapshot kaybedildi: %s", e)
```

**Dosya:** `sonnet/src/state_logger.py`

---

## ✅ Bitince

```bash
cd sonnet && ruff check src/ && python -m pytest tests/ -q --tb=short
```
