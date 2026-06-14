# Batch 4/4 — P3 Temizlik + Kod Kalitesi

---

## Fix 13: `_detect_htf_bias` instance method yap — `analyzer.py:171`

**Not:** Bu zaten Batch-1 Fix 3 ile aynı iş. Orada yapıldıysa ATLA.

**Dosya:** `sonnet/src/analyzer.py`

---

## Fix 14: `ADX_THRESHOLDS` dead code temizliği — `config.py:48-67`

**Sorun:** 20 sembol için `ADX_THRESHOLDS` dict tanımlı ama hiçbir yerde kullanılmıyor. `ADX_THRESHOLD` scalar değeri kullanılıyor.

**Yapılacak:** `ADX_THRESHOLDS` dict'i tamamen sil. Eğer ileride per-symbol ADX gerekirse diye tutmak isteniyorsa başına `# DEPRECATED` yorumu ekle.

**Dosya:** `sonnet/src/config.py`

---

## Fix 15: `KILL_ZONES_*` unused config temizliği — `config.py:291-310`

**Sorun:** `KILL_ZONES_ENABLED`, `KILL_ZONES_LOG_ONLY`, `LONDON_KILL_ZONE_*`, `NY_KILL_ZONE_*`, `ASYA_TOKYO_*` tanımlı ama `analyzer.py`'de `in_kill_zone` bilgisi hesaplanıp loglanıyor, hiçbir kararı etkilemiyor.

**Seçenek A (temizlik):** Kill zone config'lerini sil, analyzer'daki kill zone log'unu da kaldır.
**Seçenek B (implementasyon):** `KILL_ZONES_ENABLED=True` ise kill zone'da trade alma — `analyzer.py` veya `main.py`'de gate ekle.

**Önerilen:** Seçenek A — kill zone kompleksitesi gereksiz, sistem onsuz da çalışıyor.

**Dosyalar:** `sonnet/src/config.py`, `sonnet/src/analyzer.py`

---

## Fix 16: `exchange.py` socket.timeout yakala — `exchange.py:293`

**Sorun:** `urllib.error.URLError` retry yapıyor ama raw `socket.timeout` (connection timeout) bu exception'a düşmeyebilir.

**Yapılacak:** `except urllib.error.URLError as e:` yanına `except OSError as e:` ekle (socket.timeout OSError subclass'ıdır):
```python
except (urllib.error.URLError, OSError) as e:
    # retry logic...
```

**Dosya:** `sonnet/src/exchange.py`

---

## Fix 17: `_handle_htf_levels` state guard — `state_machine.py:656-664`

**Sorun:** Her 1m callback'te `h4_swing_level` ve `h1_liquidity_level` override ediliyor. WAIT_CONFIRM'deyken bile seviyeler değişebilir, entry anından farklı SL/TP'ye yol açar.

**Yapılacak:** Sadece IDLE ve ARMED state'lerinde override et:
```python
def _handle_htf_levels(self, state: SymbolState, event: dict):
    if state.state in (SetupState.IDLE, SetupState.ARMED):
        state.h4_swing_level = event.get("h4_swing_level")
        state.h1_liquidity_level = event.get("h1_liquidity_level")
    # diğer state'lerde log sadece
    logger.debug(...)
```

**Dosya:** `sonnet/src/state_machine.py`

---

## Fix 18: `fvg_size_ratio` başlangıç değeri — `state_machine.py:405`

**Düşük öncelik.** Ternary guard (`fvg_size_ratio if price_ref > 0 else 0`) zaten UnboundLocalError'ı engelliyor. Ama defensive coding için:

```python
fvg_size_ratio = 0.0
if price_ref > 0 and fvg_size > 0:
    fvg_size_ratio = fvg_size / price_ref
```

**Dosya:** `sonnet/src/state_machine.py`

---

## Fix 19 (bonus): 80 satır yorum bloğu — `analyzer.py:596-650`

`_detect_ltf_confirm` içindeki workaround/geçici fix notlarını ayrı bir docstring veya MD dosyasına taşı. Kod içinde sadece 2-3 satır özet kalsın.

**Dosya:** `sonnet/src/analyzer.py`

---

## ✅ Bitince

```bash
cd sonnet && ruff check src/ && python -m pytest tests/ -q --tb=short
```
