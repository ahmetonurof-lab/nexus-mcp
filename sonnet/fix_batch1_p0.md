# Batch 1/4 — P0 Critical Bug Fixes

Aşağıdaki 4 P0 bug'ı sırayla fixle. Her fix sonrası `test_p0_bugs.py` çalıştır, 222 test pass kalmalı.

---

## Fix 1: `trailing_sl()` SHORT guard — `risk_manager.py:385-390`

**Sorun:** SHORT'ta `current_price > current_sl` (zarar) iken SL yukarı kayıyor.

**Mevcut kod:**
```python
if direction == "long":
    new_sl = current_sl + (current_price - current_sl) * step_ratio
else:
    new_sl = current_sl - (current_sl - current_price) * step_ratio
```

**İstenen:** `max()`/`min()` guard ekle:
```python
if direction == "long":
    new_sl = max(current_sl, current_sl + (current_price - current_sl) * step_ratio)
else:
    new_sl = min(current_sl, current_sl - (current_sl - current_price) * step_ratio)
return round(new_sl, 5)
```

**Dosya:** `sonnet/src/risk_manager.py`

---

## Fix 2: `mss_level=0.0` falsy bypass — `state_machine.py:702`

**Sorun:** `if not mss_level` hem `None` hem `0.0` için True döner. Düşük fiyatlı sembollerde `mss_level=0.0` invalidasyon görmez.

**Mevcut kod:**
```python
mss_level = getattr(state, "mss_level", None)
if not mss_level:
    return False
```

**İstenen:**
```python
mss_level = getattr(state, "mss_level", None)
if mss_level is None:
    return False
```

**Dosya:** `sonnet/src/state_machine.py`

---

## Fix 3: Hardcoded `"symbol"` string — `analyzer.py:215,249,256,264,268`

**Sorun:** `_detect_htf_bias` `@staticmethod` olduğu için `self.symbol` kullanılamıyor, onun yerine `"symbol"` string'i placeholder olarak bırakılmış.

**Yapılacaklar:**
1. `@staticmethod` dekoratörünü kaldır
2. Metoda `self` parametresi ekle
3. Tüm `"symbol"` yerine `self.symbol` yaz (5 yer)
4. `analyze()` içindeki çağrı zaten `self._detect_htf_bias(...)` — değişiklik gerekmez

**Dosya:** `sonnet/src/analyzer.py`

---

## Fix 4: UTF-8 garbled chars — `config.py:91,126`

**Sorun:** `iÅŸlem` (işlem olmalı), `gittiÄŸinde` (gittiğinde olmalı)

**Dosya:** `sonnet/src/config.py`
- Satır 91: `iÅŸlem` → `işlem`
- Satır 126: `gittiÄŸinde` → `gittiğinde`

---

## ✅ Bitince

```bash
cd sonnet && ruff check src/ && python -m pytest tests/test_p0_bugs.py -q
```
