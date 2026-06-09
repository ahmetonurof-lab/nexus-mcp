# Active Context — NEXUS V3

## Mevcut Odak
FVG Missed Flow implementasyonu tamamlandı — V-shape hareketlerde fiyat FVG'yi hiç görmeden kaçtığında sistem artık sonsuz WAIT_RETRACE'de zombiye dönüşmüyor. Case C (MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER) akışı eklendi.

## Son Değişiklikler

### 2026-06-09: Global Rate Limiter — Binance 429 Koruması
- **main.py → `_RateLimiter` sınıfı**: Token bucket rate limiter eklendi. asyncio-safe, dakikada max 5000 istek. Binance IP limiti (6000 req/min) için güvenli mesafe.
- **main.py → `__init__`**: `self._rate_limiter = _RateLimiter(max_per_minute=5000)` eklendi.
- **main.py → `_fetch_binance_signed()`**: `await self._rate_limiter.acquire()` semaphore'den önce eklendi.
- **main.py → `_fetch_binance_signed_post()`**: Aynı acquire eklendi.
- **main.py → `_fetch_binance_signed_delete()`**: Aynı acquire eklendi.
- **Sorun**: 22 sembolün 5m bar kapanışlarında eşzamanlı API istekleri 6000 req/min limitini aşıyordu (HTTP 429).

### 2026-06-09: Strategy Audit Trail — STRATEGY_FIELDS Yeniden Yapılanması
- **performance.py → `STRATEGY_FIELDS`**: Eski kolon seti (d1_close, d1_ema100, d1_ema_slope, d1_adx, trend_direction, choch_*, fvg_timeframe, fvg_top, fvg_bottom, fvg_midpoint, fvg_size, sl_price, tp_price, rr_ratio, lot_size, exit_price, exit_timestamp, gross_rr) kaldırıldı. Yeni kolonlar eklendi:
  - HTF BIAS: d1_bias, h4_bias, bias_strength, d1_bos_bar_index, d1_bos_level
  - HTF Seviyeleri: h4_sl, h1_tp
  - Killzone: killzone_utc, in_killzone
  - Sweep: sweep, sweep_side, sweep_level, sweep_bar_index
  - MSS: mss, mss_level, mss_bar_index, mss_direction, impulse_origin
  - FVG: fvg_upper, fvg_lower, fvg_ce, fvg_bar_index, fvg_direction, fvg_case
  - Flags: retrace, ltf, fvg_missed
  - State: state
  - Trade: entry, sl, tp, rr, lot, exit, exit_time, pnl
- **performance.py → `_write_strategy_csv()`**: Yeni alanlarla tamamen yeniden yazıldı. fvg_case (A/C) hesaplaması, fvg_ce (midpoint) hesaplaması, exit_time format dönüştürme (ms timestamp → human-readable) eklendi.
- **main.py → `_on_5m_close()` active_trades bloğu**: `send_order` sonrası active_trades dict'ine 23 yeni strateji audit trail alanı eklendi: d1_bias, h4_bias, bias_strength, h4_sl, h1_tp, sweep*, mss*, fvg*, retrace, ltf, fvg_missed, state, sl, tp_val, rr, lot_val. Bu alanlar record_trade'e otomatik olarak aktarılıyor.

### 2026-06-09: ATR Parametre Geçişi (main.py → state_machine.py)
- **main.py → `_on_5m_close()`**: `compute_atr_point(bars_15m)` hesaplanıp `_check_missed_fvg(atr=atr)` ve `check_poi_retrace(atr=atr)` metodlarına `atr=` parametresi olarak geçiriliyor.
- **main.py → `_flush_state()`**: `fvg_missed`, `displacement_origin`, `poi_anchor` alanları persist ediliyor.
- **main.py → `_load_state()`**: Aynı 3 field restore ediliyor.
- **state_machine.py → `check_retrace()`**: `atr: float = 0.0` parametresi eklendi; Case A başarısız olunca `_check_missed_fvg(atr=atr)` çağrısı.
- **state_machine.py → `_check_missed_fvg()`**: `MISSED_ATR_MULT × atr` threshold ile `missed_fvg_at_price` kaydı — artık `_get_atr()` fallback'i kullanmıyor, dışarıdan doğrudan ATR alıyor.
- **state_machine.py → `check_poi_retrace()`**: `POI_ATR_BUFFER × atr` zone kontrolü — aynı şekilde dışarıdan ATR alıyor.
- **state_machine.py → `_handle_ltf()`**: `WAIT_POI_CONFIRM` state'i de kabul ediliyor → Case C path.
- **state_machine.py → `path_evaluate()`**: Case A + Case C ayrı if blokları, ikisi de `READY_TO_ENTER`'a çıkıyor.
- **state_machine.py → `_check_stale_state()`**: `MISSED_FVG` + `WAIT_POI_CONFIRM` zombi temizliğine dahil.

### 2026-06-09: Logging Altyapısı — TimedRotatingFileHandler
- **main.py import bloğu**: `import logging.handlers` eklendi.
- **main.py `logging.basicConfig()`**: `FileHandler("live_trading.log", mode="w")` → `TimedRotatingFileHandler(filename="live_trading.log", when="midnight", backupCount=10, encoding="utf-8")` olarak değiştirildi.
- Log dosyaları artık her gece yarısı otomatik rotate edilir; en fazla 10 eski log tutulur.

### 2026-06-09: set_state() Log Düzeltmesi
- **state_machine.py → `set_state()`**: Log mesajı "manually forced" yerine `"State geçişi: %s → %s"` formatına düzeltildi. Artık sembol bazlı tutarlı log basıyor: `[XRPUSDT] State geçişi: READY_TO_ENTER → ENTERED`.

### 2026-06-08: FVG Missed Flow (Tüm 8 Parça)
- **config.py**: `MISSED_ATR_MULT = 1.5`, `POI_ATR_BUFFER = 0.3` sabitleri eklendi.
- **SetupState enum**: `MISSED_FVG`, `WAIT_POI_CONFIRM` state'leri eklendi.
- **SymbolState**: `fvg_missed`, `poi_anchor`, `poi_anchor_bar_index`, `displacement_origin`, `missed_fvg_at_price` field'ları eklendi. `reset_flags()` güncellendi.
- **`_handle_mss()`**: `displacement_origin = event.get("impulse_origin")` kaydı eklendi.
- **`check_retrace()`**: Case A (CE+body → WAIT_CONFIRM) / Case C (`_check_missed_fvg`) ayrımı yapıldı.
- **`_check_missed_fvg()`**: Deterministik — `retrace_seen==False` ve `close > fvg_mid + MISSED_ATR_MULT*ATR` (LONG) / `close < fvg_mid - MISSED_ATR_MULT*ATR` (SHORT) → `MISSED_FVG`.
- **`check_poi_retrace()`**: MISSED_FVG'de fiyat poi_anchor ± POI_ATR_BUFFER*ATR bandına gelirse → WAIT_POI_CONFIRM.
- **`_evaluate()`**: Case A path (4 flag) + Case C path (sweep+mss+fvg_missed+ltf → WAIT_POI_CONFIRM'den READY_TO_ENTER).
- **`_get_atr()`**: ATR_MAP / DEFAULT_ATR fallback yardımcı metodu.
- **analyzer.py `_detect_mss_events()`**: MSS kırılım barından önceki son karşı-yön swing pivot'u `impulse_origin` olarak event'e eklendi.
- **main.py `_on_5m_close()`**: `check_poi_retrace()` çağrısı eklendi.

### 2026-06-07: _handle_ltf State Guard + exchange.py recvWindow Fix + HTF Bias Override Koruması
- **state_machine.py → `_handle_ltf()`**: State guard eklendi — LTF sadece `WAIT_CONFIRM` veya `WAIT_RETRACE` state'lerinde kabul edilir.
- **state_machine.py → `_handle_htf_bias()`**: FIX-5 — Setup aktifken (ARMED+) direction override etme.
- **exchange.py → `_request()`**: `recvWindow` koşulu düzeltildi.

### 2026-06-07: MSS Log Zinciri + reset_flags Genişletme + _handle_mss Guard
- **reset_flags()**: Tüm yapısal alanları sıfırlar (15 satır).
- **_handle_mss()**: State gate kontrolü, HTF bias overwrite koruması, log prefix'leri.
- **analyzer.py**: `[MSS-EMIT]` log prefix'i eklendi.

### 2026-06-07: test_analyzer.py — 4 Hata Düzeltme
- SSL sweep, float precision, HTF bias/levels testleri düzeltildi.
- Ruff F841 fix.

### 2026-06-06: main.py STATE-DEBUG Renklendirme
- ANSI renk kodları ile boolean renklendirme eklendi.

### 2026-06-06: Unit Test Altyapısı + Config Güncellemesi
- Test dosyaları: `test_pivot.py` (22 test), `test_risk_manager.py` (40+ test), `test_state_machine.py` (30 test).
- `conftest.py` ile fabrika fonksiyonları.
- `HTF_STRICT_FILTER: True → False`.

### 2026-06-08: MISSED_FVG_ATR_MULT İsim Uyumu + STATE-DEBUG fvg= Alanı + Emoji Formatı
- **config.py**: `MISSED_ATR_MULT` → `MISSED_FVG_ATR_MULT` olarak yeniden adlandırıldı (isim tutarlılığı).
- **state_machine.py**: `getattr("MISSED_ATR_MULT")` → `getattr("MISSED_FVG_ATR_MULT")` olarak güncellendi.
- **main.py STATE-DEBUG**: Eski `fvg_a= fvg_b= fvg_c=` üçlü alanı kaldırıldı, yerine **tek dinamik `fvg=` alanı** eklendi.
  - `fvg=❌` → FVG None (henüz oluşmamış)
  - `fvg=🟡` → FVG var, case yok (beklemede)
  - `fvg=fvg_a=✅` → CASE A: CE tap + body inside
  - `fvg=fvg_c=✅` → CASE C: MISSED_FVG tetiklenmiş
  - `fvg=invalid` → FVG geçersiz (state IDLE'a düşmüş)
- **STATE-DEBUG emoji formatı güncellendi** (kozmetik): Tüm flag'ler artık `fmt_bool()` ile `✅`/`❌` formatında.

### 2026-06-08: MISSED_FVG 3 Patch (KONTROL → PATCH-1 → PATCH-3 → PATCH-5)
- **KONTROL**: `SymbolState`'te `fvg_bar_index` yok, `fvg_entry_bar_index` kullanılıyor — tüm patch'ler bunun üzerine inşa edildi.
- **PATCH-1**: `_check_missed_fvg()` içine `min_bars_after_fvg = 3` kontrolü eklendi. FVG giriş barından sonra en az 3 bar geçmeden missed FVG tetiklenmez — erken false-positive'leri engeller.
- **PATCH-3**: `_check_missed_fvg()` transition bloğunda `state.missed_fvg_bar_index = current_bar.index` kaydı eklendi (MISSED_FVG state'ine geçmeden hemen önce).
- **PATCH-5**: `reset_flags()` içine `missed_fvg_bar_index`, `displacement_high`, `displacement_low` reset'leri eklendi. Dataclass'a aynı field'lar tanımlandı.
- **Test**: 29/29 passed — mevcut suite bozulmadı.

## Sonraki Adımlar
1. FVG Missed Flow canlı/backtest doğrulaması — Case C patikasının log'da görünüp görünmediğini kontrol et. `fvg=fvg_c=✅` görünmeli.
2. `DEFAULT_ATR` veya `ATR_MAP` config'e eklenmesi gerekebilir (`_get_atr()` şu anda fallback olarak None döner).
3. `fvg=invalid` log'unu canlı izle — invalidations'ları tespit etmek için.

## Aktif Kararlar
- **FVG Missed Flow**: Case C'de sistem beklemez — anında re-anchor eder ve MISSED_FVG state'inde yeni POI'yi izler.
- **Deterministik eşikler**: `MISSED_FVG_ATR_MULT=1.5`, `POI_ATR_BUFFER=0.3` — tüm koşullar sayısal, "yakın/muhtemelen" gibi ifadeler yok.
- **SL stratejisi**: 4H swing high/low + tier buffer.
- **TP stratejisi**: 1H BSL/SSL likidite seviyesi.
- **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir.

## Önemli Desenler ve Tercihler
- `_get_atr()`: `ATR_MAP[symbol]` → `DEFAULT_ATR` → `None` fallback zinciri.
- `_check_missed_fvg()`: displacement_origin'dan değil, `fvg_mid`'den mesafe hesaplar (daha doğru).
- `check_poi_retrace()`: LOW/HIGH bazlı bölge kontrolü (wick değil gövde).
- 3 lint aracı da geçiyor: **ruff** ✅, **mypy** ✅, **vulture** ✅.

## Öğrenimler
- V-shape hareketlerde FVG hiç dokunulmadan fiyat kaçarsa, sistem `WAIT_RETRACE`'te sonsuz beklerdi. Çözüm: displacement_origin + ATR eşiği ile MISSED tespiti.
- `displacement_origin` MSS kırılım barından önceki son pivot olarak hesaplanır — impulse başlangıcını temsil eder.
- `poi_anchor` = displacement_origin (yeniden giriş için referans noktası).
