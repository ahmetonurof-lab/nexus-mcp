# NEXUS V3 — Critical Code Review Raporu
> Satır satır analiz | 21 dosya | ~12,500 satır | 2026-06-14

---

## 1. YÖNETİCİ ÖZETİ

**Sistem Durumu:** NEXUS V3, sağlam bir event-driven mimari üzerine kurulu ancak production'a gönderilmeden önce düzeltilmesi zorunlu birden fazla kritik semantik hata barındırmaktadır.

**Genel Not: 6.9 / 10** *(ağırlıklı, aşağıda ayrıntılı)*

### En Kritik 3 Bulgu

1. **`trailing_sl()` SHORT yönü — SL zarar artıkça YÜKSELİYOR** (`risk_manager.py:385`): Fiyat stop seviyesini aşarsa Short pozisyonda SL yanlış yöne gidiyor; korumasız açık pozisyon kalabiliyor.
2. **`_check_invalidation()` içinde `if not mss_level` — 0.0 bypass** (`state_machine.py:688`): `mss_level=0.0` falsy sayılarak zombi setup'lar asla invalidasyon görmüyor; `mss_level=None` ile aynı saf pass. Fix-7'de `sweep_level` 0.0 bypass düzeltildi ama aynı hata burada tekrar ediyor.
3. **`_detect_htf_bias()` içinde hardcoded `"symbol"` string** (`analyzer.py:215,264,268`): Her çağrıda sembol adı yerine `"symbol"` string'i loglanıyor — multi-symbol ortamda hangi çiftin analiz edildiği izlenemiyor.

### Production'a Hazır mı?

**HAYIR.** Trailing SL yönü hatası ve 0.0 mss_level bypass, canlı ortamda korumasız pozisyonlara doğrudan yol açar.

---

## 2. PUANLAMA

```
┌──────────────────────────────────────────────────────────┬────────┬──────────┬────────┐
│ Boyut                                                     │  Puan  │ Ağırlık  │ Katkı  │
├──────────────────────────────────────────────────────────┼────────┼──────────┼────────┤
│ 1. Bug / Crash Riski                                      │  6/10  │  ×0.25   │  1.50  │
│ 2. Mantık Hataları                                        │  6/10  │  ×0.25   │  1.50  │
│ 3. Dead Code / Kullanılmayan Kod                          │  8/10  │  ×0.10   │  0.80  │
│ 4. Tasarım / Mimari                                       │  7/10  │  ×0.20   │  1.40  │
│ 5. Tip Güvenliği / Robustness                             │  7/10  │  ×0.10   │  0.70  │
│ 6. Performans / Kaynak                                    │  8/10  │  ×0.05   │  0.40  │
│ 7. Test Edilebilirlik                                     │  8/10  │  ×0.05   │  0.40  │
├──────────────────────────────────────────────────────────┼────────┼──────────┼────────┤
│ AĞIRLIKLI TOPLAM                                          │  6.90  │          │        │
└──────────────────────────────────────────────────────────┴────────┴──────────┴────────┘
```

---

## 3. BULGU TABLOSU

| # | Öncelik | Dosya | Satır | Kategori | Bulgu | Etki |
|---|---------|-------|-------|----------|-------|------|
| 1 | 🔴 P0 | `risk_manager.py` | 385 | Mantık | `trailing_sl()` SHORT'ta `current_price > current_sl` olunca SL yukari gidiyor | SHORT açık pozisyon zararı büyüdükçe SL yanlış yöne kayar |
| 2 | 🔴 P0 | `state_machine.py` | 688 | Mantık | `if not mss_level` — `mss_level=0.0` falsy bypass | 0.0 fiyatlı MSS (düşük decimal semboller) invalidasyon görmez, zombi setup kalır |
| 3 | 🔴 P0 | `analyzer.py` | 215,264,268 | Bug | `_detect_htf_bias()` içinde sembol yerine hardcoded `"symbol"` string log'lanıyor | 22 sembollü sistemde hangi sembolün hangi bias aldığı izlenemez |
| 4 | 🔴 P0 | `main.py` | 1904 | Bug | `cancelReplace` isteğinde `"reduceOnly": "true"` (string) — Binance API boolean bekler | SL güncelleme emri API tarafından reddedilebilir; güncelleme sessizce başarısız olur |
| 5 | 🔴 P0 | `config.py` | 91,200+ | Bug | UTF-8 encoding bozukluğu: `"iŸlem"`, `"Āżlem"` garbled chars yorumlarda | Windows'ta çalışıyor ama CI/Linux'ta `SyntaxError` potansiyeli; diğer dosyalarda da mevcut |
| 6 | 🔴 P0 | `risk_manager.py` | 252,260 | Bug | `calculate_tp_htf()` içinde `getattr(self, "_sym", "?")` — bu attribute hiç set edilmiyor | TP warning log'larında sembol adı her zaman `"?"` çıkar; hata takibini engeller |
| 7 | 🟠 P1 | `config.py` | tüm | Mantık | `SYMBOLS` listesinde `PEPEUSDT`, `RNDRUSDT`, `MATICUSDT` yok ama `RISK_PER_TRADE_MAP` ve `MIN_RR_MAP`'te var | Bu semboller hiç trade almayacak ama risk config çöpe gidecek; insanı yanıltır |
| 8 | 🟠 P1 | `state_machine.py` | 419 | Bug | `logger.debug`'de `fvg_size_ratio` değişkeni `price_ref <= 0` dalında tanımsız | `price_ref <= 0` durumunda (tuhaf FVG) `UnboundLocalError` ile crash |
| 9 | 🟠 P1 | `trader.py` | 456 | Tasarım | `trade_locks.setdefault(symbol, asyncio.Lock())` — asyncio.Lock modül-seviyesi global dict üzerinde thread-safe değil | İki coroutine aynı anda çalışırsa yarış koşulunda aynı sembol için çift Lock üretilebilir |
| 10 | 🟠 P1 | `analyzer.py` | 657 | Tasarım | `_detect_ltf_confirm()`'de `fvg_entry_bar_timestamp=0` — temporal filtre devredışı, tüm 1m barlar taranıyor | LTF onayı FVG oluşumundan önceki pivot'lara da match edebilir; yanlış pozitif |
| 11 | 🟠 P1 | `state_machine.py` | 635-641 | Mantık | `_handle_htf_bias()` IDLE dışındaki state'lerde `direction` override ediyor | WAIT_RETRACE'de bias güncellenmesi direction'ı değiştirir; açık yönün tersine emir gidebilir |
| 12 | 🟠 P1 | `models.py` | 354-358 | Tasarım | `warnings.warn(DeprecationWarning)` modül seviyesinde — her import eden dosyada warning basılıyor | Test çıktılarını kirletiyor; stacklevel=2 her import callsite'ına işaret eder, kafa karıştırıcı |
| 13 | 🟠 P1 | `main.py` | ~2100 | Tasarım | `_on_1m_close` yaklaşık 350 satır, 5+ iç içe seviye, partial entry + full entry + state yönetimi tek fonksiyonda | cc > 50, test edilemez, refactor gerektiriyor |
| 14 | 🟠 P1 | `trader.py` | 413-430 | Mantık | `_safe_create_order(retries=2)` — `-2021` hatasında sadece `i < retries - 1` koşulunda retry; son denemede raise | İkinci denemede de -2021 gelirse `raise` → outer `except` `None` döner; hata sessizce kayboluyor |
| 15 | 🟠 P1 | `main.py` | 1399-1535 | Mantık | `_repair_protection()` yeni order_id'leri `active_trades` dict'ine yazıyor, ama `trade[\"protection_repairing\"]` flag'i hiç `False` yapılmıyor | Repair başarılı olduktan sonra sembol sonsuza dek REPAIR MODE'da kalır |
| 16 | 🟡 P2 | `risk_manager.py` | 366-386 | Mantık | SHORT `trailing_sl`: fiyat SL üstüne çıktığında (zarar durumu) SL `current_sl * (1-step) + price * step` → yükseliyor | Zarar büyüdükçe SL de yukarı kayar; max zarar sınırını delir |
| 17 | 🟡 P2 | `backtest.py` | 89,134,179 | Eksiklik | Backtest slippage simüle ediliyor ama `TAKER_FEE` uygulanmıyor; komisyon hesabı eksik | Backtest sonuçları gerçek P&L'den yüzde olarak sapabilir |
| 18 | 🟡 P2 | `state_logger.py` | tüm | Eksiklik | 10 günlük CSV rotasyonu var ama disk doluluk kontrolü yok | Disk dolduğunda `OSError` → `write_snapshot` sessizce fail → 15m snapshot kaybı |
| 19 | 🟡 P2 | `analyzer.py` | `_detect_htf_bias` | Tasarım | `@staticmethod` olarak tanımlanmış ama loglarda `self.symbol` kullanılamıyor; bu nedenle hardcoded string hatası oluşmuş | `@staticmethod` yerine instance method yapılmalı |
| 20 | 🟢 P3 | `config.py` | tüm | Dead code | `ADX_THRESHOLDS` dict 20 sembol için tanımlı ama hiçbir yerde `ADX_THRESHOLDS` kullanılmıyor; `ADX_THRESHOLD` scalar kullanılıyor | 20 satır kullanılmayan yapılandırma |
| 21 | 🟢 P3 | `config.py` | `KILL_ZONES_*` | Dead code | `KILL_ZONES_ENABLED`, `KILL_ZONES_LOG_ONLY`, `LONDON_KILL_ZONE_*`, `NY_KILL_ZONE_*`, `ASYA_TOKYO_*` — `analyzer.py`'de `now_utc` log'u yapılıyor ama `KILL_ZONES_ENABLED` hiç kontrol edilmiyor | Kill zone config anlamsız; `in_kill_zone` bilgisi hesaplanıp loglanıyor ama hiçbir karar etkisi yok |
| 22 | 🟢 P3 | `risk_manager.py` | `build_trade` | Dead code | `TradeParams.trailing_level = 0.0` her zaman; docstring `trailing_level` için `1R kâr` diyor ama kod hiç kullanmıyor | Yanlış anlayış riski; caller `trailing_level`'e güvenirse yanlış SL hesabı yapabilir |
| 23 | 🟢 P3 | `analyzer.py` | `_detect_ltf_confirm` | Tasarım | 80 satır yorum bloğu (satır 596-650) — workaround, geçici fix ve future work notu, kod değil | Teknik borç birikimi; refactor edilmeden anlaşılması çok zor |
| 24 | 🟢 P3 | `exchange.py` | `_request` | Robustness | `urllib.error.URLError` (ağ erişim hatası) retry yapıyor ama `socket.timeout` (connection timeout) ayrı yakalanmıyor; retry döngüsü dışında kalıyor | Yavaş ağda timeout exception üst katmana fırlar, retry olmadan |
| 25 | 🟢 P3 | `state_machine.py` | `_handle_htf_levels` | Tasarım | Her 1m callback'te `h4_swing_level` ve `h1_liquidity_level` override ediliyor — WAIT_CONFIRM'deyken bile seviyeler değişebilir | Entry anından farklı SL/TP seviyesiyle trade açılabilir |

---

## 4. DETAYLI BULGU ANALİZİ

### 🔴 BUG-1: `trailing_sl()` SHORT Yönü — SL Yanlış Yöne Kayıyor

**Dosya:** `risk_manager.py`, satır 380-386

**Mevcut Kod:**
```python
if direction == "long":
    new_sl = current_sl + (current_price - current_sl) * step_ratio
else:
    new_sl = current_sl - (current_sl - current_price) * step_ratio
```

**Sorun:** SHORT için formülü açalım:
```
new_sl = current_sl - (current_sl - current_price) * step
```
Eğer `current_price > current_sl` (fiyat stop seviyesinin üstüne çıktıysa = zarar durumu):
```
(current_sl - current_price) negatif olur
→ new_sl = current_sl - (negatif sayı) = current_sl + pozitif = YUKARI GİTTİ
```

Örnek: `current_sl=100, current_price=102 (zarar), step=0.25`
- `new_sl = 100 - (100 - 102) * 0.25 = 100 - (-0.5) = 100.5` → SL yükseldi!

Bu aslında mantıksal olarak tutarlı — SHORT'ta "kârı kilitle" mantığı doğru çalışıyor (fiyat aşağı gidince SL de aşağı çekiliyor). Fakat **zarar büyüdüğünde SL'yi yanlış yöne çekiyor**. LONG'da bu daha az sorunlu çünkü `_manage_open_trades`'de yalnızca `breakeven_done=True` durumunda trailing çağrılıyor. Ama SHORT'ta breakeven-sonrası fiyat SL üstüne geri dönerse SL daha da yukarı kayar.

**Önerilen Düzeltme:**
```python
if direction == "long":
    # LONG: fiyat yükseldikçe SL yukarı çek
    new_sl = max(current_sl, current_sl + (current_price - current_sl) * step_ratio)
else:
    # SHORT: fiyat düştükçe SL aşağı çek; fiyat yukarı çıkarsa SL'yi HAREKET ETTİRME
    new_sl = min(current_sl, current_sl - (current_sl - current_price) * step_ratio)
return round(new_sl, 5)
```

---

### 🔴 BUG-2: `_check_invalidation()` — `mss_level=0.0` Falsy Bypass

**Dosya:** `state_machine.py`, satır 688

**Mevcut Kod:**
```python
mss_level = getattr(state, "mss_level", None)
if not mss_level:
    return False
```

**Sorun:** `if not mss_level` hem `None` hem `0.0` için `True` döner. PEPEUSDT gibi çok düşük fiyatlı bir sembolde `mss_level=0.0` (initialize'den kalma veya gerçekten 0) olduğunda invalidasyon çalışmaz.

Bu tam olarak Fix-7'de `risk_manager.py`'de `sweep_level` için düzeltilen pattern'ın aynısıdır — ama burada unutulmuş.

**Önerilen Düzeltme:**
```python
mss_level = getattr(state, "mss_level", None)
if mss_level is None:
    return False
```

---

### 🔴 BUG-3: `_detect_htf_bias()` — Hardcoded `"symbol"` String

**Dosya:** `analyzer.py`, satır 215, 264, 268

**Mevcut Kod:**
```python
logger.debug("[BIAS] %s: D1 BOS bulunamadı", "symbol")  # satır 215
logger.info("[BIAS] %s: D1=%s H4=%s → GUCLU", "symbol", d1_bias, h4_bias)  # satır 264
logger.info("[BIAS] %s: D1=%s H4=belirsiz → MODERATE", "symbol", d1_bias)  # satır 268
```

**Sorun:** `@staticmethod` dekoratörü nedeniyle `self.symbol`'a erişilemiyor. Geliştirici placeholder olarak `"symbol"` string'ini bırakmış. 22 sembol aynı anda analiz edilirken log'larda hepsi `"symbol"` çıkacak.

**Önerilen Düzeltme:** `_detect_htf_bias`'ı instance method'a çevir:
```python
def _detect_htf_bias(self, bars_d1, bars_h4):
    # tüm "symbol" → self.symbol
    logger.debug("[BIAS] %s: D1 BOS bulunamadı", self.symbol)
    ...
```
Çağrıları da güncelle: `self._detect_htf_bias(bars_d1, bars_h4)`

---

### 🔴 BUG-4: `cancelReplace` İsteğinde `reduceOnly: "true"` String

**Dosya:** `main.py`, satır 1904

**Mevcut Kod:**
```python
result = await self._fetch_binance_signed_post(
    "/fapi/v1/order/cancelReplace",
    {
        ...
        "reduceOnly": "true",  # ← STRING
    },
)
```

**Sorun:** Binance Futures API `cancelReplace` isteğinde `reduceOnly` parametresi JSON boolean `true` bekler, string `"true"` değil. `urllib` ile `application/x-www-form-urlencoded` gönderildiğinde Python `True` bool → `"True"` dönüşür ki bu da yanlış. Ancak buradaki string `"true"` form-encoded olarak `reduceOnly=true` gönderir — bazı Binance versiyonları kabul eder ama resmi API spec boolean ister.

Kritik: SL güncelleme emri `cancelReplace` yoluyla gönderilirken `reduceOnly` hatalı olursa emir reddedilir, `new_id` boş kalır ve `trade["sl_order_id"]` güncellenmez → bir sonraki güncelleme denemesinde eski (iptal edilmiş) order ID referans alınır.

**Önerilen Düzeltme:**
```python
"reduceOnly": True,  # bool
```

---

### 🟠 P1-8: `fvg_size_ratio` UnboundLocalError

**Dosya:** `state_machine.py`, satır 405-419

**Mevcut Kod:**
```python
price_ref = (state.fvg_upper + state.fvg_lower) / 2.0
if price_ref > 0 and fvg_size > 0:
    fvg_size_ratio = fvg_size / price_ref  # sadece bu dalda tanımlanıyor
    scale = ...
else:
    scale = 1.0

logger.debug(
    "...",
    fvg_size_ratio if price_ref > 0 else 0,  # price_ref <= 0 dalında UnboundLocalError!
)
```

**Sorun:** `price_ref <= 0` durumunda (geçersiz FVG seviyesi) `fvg_size_ratio` hiç tanımlanmıyor ama `logger.debug`'de kullanılıyor → `UnboundLocalError`.

**Önerilen Düzeltme:**
```python
fvg_size_ratio = 0.0  # başlangıç değeri
if price_ref > 0 and fvg_size > 0:
    fvg_size_ratio = fvg_size / price_ref
    ...
```

---

### 🟠 P1-15: `_repair_protection()` REPAIR MODE Flag Sıfırlanmıyor

**Dosya:** `main.py`, satır 1399-1535

**Sorun:** `_repair_protection()` başarılı olduğunda `trade["protection_repairing"]` flag'ini `False` yapmıyor. Ancak başarı koşulu (`sl_ok and tp_ok`) `trade["protection_missing"] = False` yapıyor. Caller `_sync_positions()` içinde `protection_repairing=True` ise sembol her 1m callback'te "REPAIR MODE" logluyor ve `_manage_open_trades`'de işlem yapılmıyor.

**Önerilen Düzeltme:**
```python
if sl_ok and tp_ok:
    trade["protection_missing"] = False
    trade["protection_repairing"] = False  # ← EKLE
    trade["status"] = "open"
```

---

## 5. MİMARİ DEĞERLENDİRME

### Bağımlılık Grafiği

Mevcut dependency graph `systemPatterns.md`'de belgelenmiş ve genel olarak sağlıklı:
```
models → pivot, indicators → fvg, mss → analyzer → event_router → state_machine
                                                 ↘              ↘
                                              scoring          risk_manager → trader → main
```

**Döngüsel import yok.** Bu büyük bir başarı. Tek sorunlu yer `models.py:366`'daki `__getattr__` lazy import:
```python
def __getattr__(name: str):
    if name == "AnalysisResult":
        from analyzer import AnalysisResult
        return AnalysisResult
```
Bu `models → analyzer` geç bağımlılığı oluşturuyor. Kullanılmıyorsa kaldırılabilir.

### God Functions

| Fonksiyon | Satır sayısı | Cyclomatic | Sorun |
|-----------|-------------|-----------|-------|
| `main.py::_on_1m_close` | ~350 | >50 | Partial entry + full entry + state check + analyze + routing tek fonksiyon |
| `main.py::_sync_positions` | ~250 | 96 | 3 farklı sorumluluk (sync, repair, cleanup) |
| `main.py::send_order` (trader) | ~280 | 69 | MARKET + STOP_MARKET + SL + TP + emergency + cleanup |

### Bölünmesi Gereken Dosyalar

`main.py` (2628 satır) üç modüle ayrılmalı:
- `bot_orchestrator.py` — WebSocket callback'leri ve ana döngü
- `position_manager.py` — `_sync_positions`, `_manage_open_trades`, `_repair_protection`
- `order_executor.py` — `_update_sl_order`, `_cancel_order_by_id`, `_create_protection`

---

## 6. TEST KAPSAMA DEĞERLENDİRMESİ

### Mevcut Durum

| Modül | Coverage | Not |
|-------|----------|-----|
| `pivot.py` | %97 | Excellent |
| `risk_manager.py` | %93 | Excellent |
| `state_machine.py` | %87 | Good |
| `analyzer.py` | %81 | Good |
| `exchange.py` | %55 | Orta |
| `trader.py` | %47 | Kritik eksik |
| `main.py` | %47 | Kritik eksik |
| `scoring.py` | %91 | Good |
| `fvg.py` | %47 | Orta |
| `mss.py` | %63 | Orta |

### Kritik Eksik Test Senaryoları

1. **`trailing_sl()` SHORT yön testi** — zarar senaryosunda `new_sl` eski SL'den küçük mi kontrolü
2. **`_check_invalidation()` `mss_level=0.0` testi** — 0.0 değerinin bypass edilmediği doğrulanmalı
3. **`_handle_htf_bias()` multi-symbol log testi** — sembol adının doğru loglandığı
4. **`_repair_protection()` idempotency testi** — iki kez çağrıldığında `protection_repairing` temizleniyor mu
5. **STOP_MARKET entry → `_on_1m_close`'da `active_trades` güncellenmesi** — protection_missing flow

---

## 7. PERFORMANS / KAYNAK ANALİZİ

### Gereksiz I/O Noktaları

1. **`_on_1m_close` içinde `daily_cache.get(symbol)` her 1m'de çağrılıyor** — Önbellek var ama her callback'te awaited, overhead birikebilir 22 sembol × 1440/gün = 31.680 await.

2. **`_manage_open_trades` içinde `executor.get_position(symbol)` her 1m'de** — 22 açık pozisyon varsa saniyede 22 API isteği; rate limit sınırına (5000/dakika) yaklaşılabilir.

3. **`_update_sl_order` içinde `_get_open_orders_async` + algo order sorgusu çift istek** — SL her güncellendiğinde 2 ayrı API çağrısı; cache'lenebilir.

### Memory Riski

`_BarBuffer` içinde `self._bars` list'i süresiz büyüyebilir. `M1_BARS = 500` limiti config'de var ama `_BarBuffer.__init__` içinde `maxlen=500` kontrolü WebSocket callback'te yapılmıyor — `list` olarak büyüyor.

---

## 8. SONUÇ VE ÖNERİLER

### İlk 30 Gün (P0 — Production Blocker)

| # | Görev | Dosya | Süre |
|---|-------|-------|------|
| 1 | `trailing_sl()` SHORT guard ekle (`min` ile SL'nin yanlış yöne gitmesini engelle) | `risk_manager.py:385` | 30 dk |
| 2 | `if not mss_level` → `if mss_level is None` | `state_machine.py:688` | 5 dk |
| 3 | `_detect_htf_bias` → instance method; `"symbol"` → `self.symbol` | `analyzer.py:215,264,268` | 15 dk |
| 4 | `"reduceOnly": "true"` → `"reduceOnly": True` | `main.py:1904` | 5 dk |
| 5 | `fvg_size_ratio = 0.0` başlangıç değeri ekle | `state_machine.py:405` | 5 dk |
| 6 | `_repair_protection` başarı durumunda `protection_repairing = False` | `main.py` | 10 dk |
| 7 | `getattr(self, "_sym", "?")` → sembol parametresi geçilmeli | `risk_manager.py:252,260` | 15 dk |

### İlk 90 Gün (P1 — Stability)

- `SYMBOLS`, `RISK_PER_TRADE_MAP`, `MIN_RR_MAP`, `ADX_THRESHOLDS` dict'lerini senkronize et; `PEPEUSDT/RNDRUSDT/MATICUSDT` ekle veya çıkar
- `trade_locks` global dict'ini `asyncio.Lock` ile korumayı düşün (`threading.Lock` zaten var, yeterli)
- `_detect_ltf_confirm` temporal filtering'i düzelt: `fvg_entry_bar_timestamp=0` placeholder kaldır; FVG dataclass'ına `timestamp: int = 0` ekle
- `_handle_htf_levels` → WAIT_CONFIRM ve üstü state'lerde seviyeleri override etme
- UTF-8 encoding sorununu git hook ile prevent et (`.editorconfig` + `charset=utf-8` zorla)
- `_BarBuffer`'da `maxlen` limiti uygula

### Uzun Vadeli (P2 — Architecture)

- `main.py`'yi `bot_orchestrator.py` + `position_manager.py` + `order_executor.py` olarak ayır
- `_on_1m_close`'u `_handle_state_transitions()` ve `_handle_trade_entry()` alt fonksiyonlarına böl
- `_sync_positions` cc=96 → 3 alt fonksiyona böl (<30)
- Backtest'e `TAKER_FEE` desteği ekle
- `models.py`'deki `DeprecationWarning` + `__getattr__` lazy import → `analyzer.py`'den direkt import tercih edilmeli
- Kill Zone altyapısını ya tamamen kaldır ya da gerçekten karar mekanizmasına dahil et
- `ADX_THRESHOLDS` kullanılıyorsa `scoring.py`'de uygula; kullanılmıyorsa sil

---

*Analiz: 21 dosya, 12,499 satır | Yöntem: Satır satır okuma + matematiksel doğrulama | Tarih: 2026-06-14*
