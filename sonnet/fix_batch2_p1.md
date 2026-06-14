# Batch 2/4 — P1 Stability Fixes Part 1

Aşağıdaki 4 P1 bug'ı sırayla fixle.

---

## Fix 5: `_sym` attribute hiç set edilmiyor — `risk_manager.py:252,260`

**Sorun:** `calculate_tp_htf()` içinde `getattr(self, "_sym", "?")` her zaman `"?"` döner çünkü `_sym` hiçbir yerde set edilmiyor.

**Yapılacak:** `calculate_tp_htf` metoduna `symbol` parametresi ekle, `"?"` fallback'i kaldır.

**Dosya:** `sonnet/src/risk_manager.py`
- `calculate_tp_htf` signature'a `symbol: str` ekle
- İçeride `getattr(self, "_sym", "?")` → `symbol`
- Bu metodu çağıran yeri bul, `symbol` argümanını geç

---

## Fix 6: `trade_locks` yarış koşulu — `trader.py:23,457`

**Sorun:** `trade_locks.setdefault(symbol, asyncio.Lock())` modül-seviyesi global dict'te iki coroutine aynı anda çağırırsa çift Lock üretilebilir.

**Yapılacak:** `asyncio.Lock` yerine `threading.Lock` veya init zamanında tüm semboller için Lock önceden oluştur. Ya da en basiti: `setdefault` öncesi `if symbol not in trade_locks: trade_locks[symbol] = asyncio.Lock()` yap — bu da atomik değil ama mevcut durumdan iyi. En iyisi: bot init'te `trade_locks = {s: asyncio.Lock() for s in SYMBOLS}` yapıp modül global'ini kaldır.

**Dosya:** `sonnet/src/trader.py`

---

## Fix 7: `fvg_entry_bar_timestamp=0` placeholder — `analyzer.py:536-560, 657`

**Sorun:** `_detect_ltf_confirm()` çağrılırken `fvg_entry_bar_timestamp=0` geçiliyor, temporal filtre devre dışı. FVG oluşmadan önceki pivot'lara da match edebilir.

**Yapılacak:** `_detect_ltf_confirm`'i çağıran yerde, FVG bar'ının timestamp'ini bulup geç. `state.fvg_entry_bar_timestamp` veya FVG dataclass'ından al. Eğer timestamp yoksa şimdilik 0 kalsın ama `# TODO` ile işaretle.

**Dosya:** `sonnet/src/analyzer.py`

---

## Fix 8: `_handle_htf_bias` WAIT_RETRACE'de direction override — `state_machine.py:641-651`

**Sorun:** IDLE dışındaki state'lerde bias değişirse direction override ediliyor. WAIT_RETRACE'de açık yönün tersine emir gidebilir.

**Mevcut kod:**
```python
elif new_direction is not None and state.direction != new_direction:
    logger.warning(...)
    state.direction = new_direction
```

**Yapılacak:** Sadece IDLE ve ARMED state'lerinde override et, diğer state'lerde sadece log'la:
```python
elif new_direction is not None and state.direction != new_direction:
    if state.state in (SetupState.IDLE, SetupState.ARMED):
        logger.warning(...)
        state.direction = new_direction
    else:
        logger.debug("[%s] HTF bias değişti ama state=%s override edilmedi", ...)
```

**Dosya:** `sonnet/src/state_machine.py`

---

## ✅ Bitince

```bash
cd sonnet && ruff check src/ && python -m pytest tests/ -q --tb=short
```
