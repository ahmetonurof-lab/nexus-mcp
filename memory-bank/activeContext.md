# Active Context — NEXUS V3

## Mevcut Odak
FVG tespiti H1/2H timeframe'ine taşındı (15m → H1 + 2H fallback). `_resample_to_2h()` ile sentetik 2H bar desteği eklendi. `state_logger.py`'ye `fvg_tf` alanı eklendi. Log dosyası yolu `output/trading/live_trading.log` olarak değiştirildi.

## Son Değişiklikler

### 2026-06-10: Penetration Engine Yeniden Yapılanması (state_machine.py)
- **config.py**: `FVG_PENETRATION_MIN = 0.15`, `FVG_PENETRATION_MAX = 0.70` eklendi.
- **state_machine.py → `check_retrace()`**: Eski: `PenetrationEngine` + ATR bağımlılığı + CE + body inside. Yeni: `PenetrationEngine` 0.15-0.70 trade zone. `getattr(self.config, "FVG_PENETRATION_MIN", 0.15)` ile config'den okunuyor.
- **state_machine.py → `_check_missed_fvg()`**: Eski: `MISSED_FVG_ATR_MULT × atr` threshold. Yeni: ATR bağımlılığı kaldırıldı, `pen < FVG_PENETRATION_MIN` tek karar kriteri.
- **state_machine.py → `check_poi_retrace()`**: Eski: `POI_ATR_BUFFER × atr` zone. Yeni: `FVG size × 0.3` buffer (ATR bağımlılığı yok).
- **state_machine.py → `_handle_fvg()`**: `MISSED_FVG` ve `WAIT_POI_CONFIRM` state'lerinde FVG eventi reddediliyor (Case C patikası korunuyor).
- **state_machine.py → `_evaluate()` Case C**: Sadece `WAIT_POI_CONFIRM`, `MISSED_FVG` ve `WAIT_RETRACE` state'lerinde `READY_TO_ENTER`'a geçiş.
- **test_state_machine.py**: `test_long_ce_touched_but_body_outside_stays` → `test_long_penetration_below_zone_missed_fvg` + `test_long_penetration_above_zone_stays` olarak yeniden yazıldı. 30/30 test geçiyor.

### 2026-06-10: HTF FVG Fix + Logging Path Düzeltmesi
- **analyzer.py → `_resample_to_2h()`**: Modül seviyesine eklendi. 2 adet 1H barını birleştirerek sentetik 2H bar üretir.
- **analyzer.py → `analyze()` FVG bloğu**: Eski: 15m barlarında FVG tespiti. Yeni: H1'de önce bakılır, bulunamazsa `_resample_to_2h()` ile 2H'ye fallback. `since_index=None` (tüm H1/2H barlarını tarar). Event'e `"tf"` alanı eklendi.
- **state_logger.py → `FIELDS`**: `"fvg_tf"` eklendi (fvg_direction ile fvg_case arasına).
- **state_logger.py → `write_snapshot()`**: `getattr(state, "fvg_tf", "")` satırı eklendi.
- **main.py → logging path**: `live_trading.log` → `output/trading/live_trading.log` olarak değiştirildi. `os.makedirs("output/trading", exist_ok=True)` eklendi.

### 2026-06-10: OHLC Export Yeniden Yapılanması + State Logger
- **main.py → `export_ohlc()` silindi**: Eski fonksiyon `{symbol}_5m.csv` yazıyordu.
- **main.py → `export_ohlc_15m()` eklendi**: `{symbol}_15m.csv` yazar. Header kontrolü `f.tell() == 0` ile yapılır (dosya boşsa header yazılır).
- **main.py → `export_ohlc_1m()` eklendi**: `{symbol}_1m.csv` yazar. Aynı mantık.
- **main.py → `_on_5m_close()`**: `export_ohlc(current_bar, symbol)` satırı silindi. `_is_15m_closed` bloğunun başına `export_ohlc_15m(bars_15m[-1], symbol)` eklendi.
- **main.py → `run()`**: `make_1m_callback(s)` tanımlandı → `self.hub.register_callback(sym, "1m", make_1m_callback(sym))` eklendi. Her 1m bar kapanışında `export_ohlc_1m()` çağrılır.
- **main.py → import**: `import state_logger` eklendi.
- **main.py → `_on_5m_close()`**: `_evaluate()` ve `CACHE-RESET` bloğundan sonra `state_logger.write_snapshot()` çağrısı eklendi.
- **Yeni dosya: `sonnet/src/state_logger.py`**: Her 15m kapanışında tüm sembollerin state snapshot'ını CSV'ye yazar. Dosya: `output/summary/summary_YYYY-MM-DD.csv`. Rotasyon: 10 günlük. Thread-safe (`threading.Lock`). FIELDS: timestamp, symbol, d1_bias, h4_bias, bias_strength, h4_sl, h1_tp, killzone_utc, in_killzone, sweep*, mss*, fvg*, retrace, ltf, fvg_missed, state.

### 2026-06-09: Global Rate Limiter — Binance 429 Koruması
- **main.py → `_RateLimiter` sınıfı**: Token bucket rate limiter eklendi. asyncio-safe, dakikada max 5000 istek. Binance IP limiti (6000 req/min) için güvenli mesafe.
- **main.py → `__init__`**: `self._rate_limiter = _RateLimiter(max_per_minute=5000)` eklendi.
- **main.py → `_fetch_binance_signed()`**: `await self._rate_limiter.acquire()` semaphore'den önce eklendi.
- **main.py → `_fetch_binance_signed_post()`**: Aynı acquire eklendi.
- **main.py → `_fetch_binance_signed_delete()`**: Aynı acquire eklendi.
- **Sorun**: 22 sembolün 5m bar kapanışlarında eşzamanlı API istekleri 6000 req/min limitini aşıyordu (HTTP 429).

### 2026-06-09: Strategy Audit Trail — STRATEGY_FIELDS Yeniden Yapılanması
- **performance.py → `STRATEGY_FIELDS`**: Eski kolon seti kaldırıldı. Yeni kolonlar eklendi:
  - HTF BIAS: d1_bias, h4_bias, bias_strength, d1_bos_bar_index, d1_bos_level
  - HTF Seviyeleri: h4_sl, h1_tp
  - Killzone: killzone_utc, in_killzone
  - Sweep: sweep, sweep_side, sweep_level, sweep_bar_index
  - MSS: mss, mss_level, mss_bar_index, mss_direction, impulse_origin
  - FVG: fvg_upper, fvg_lower, fvg_ce, fvg_bar_index, fvg_direction, fvg_case
  - Flags: retrace, ltf, fvg_missed
  - State: state
  - Trade: entry, sl, tp, rr, lot, exit, exit_time, pnl
- **performance.py → `_write_strategy_csv()`**: Yeni alanlarla tamamen yeniden yazıldı.
- **main.py → `_on_5m_close()` active_trades bloğu**: `send_order` sonrası 23 yeni strateji audit trail alanı eklendi.

### 2026-06-09: ATR Parametre Geçişi (main.py → state_machine.py)
- **main.py → `_on_5m_close()`**: `compute_atr_point(bars_15m)` hesaplanıp `_check_missed_fvg(atr=atr)` ve `check_poi_retrace(atr=atr)` metodlarına `atr=` parametresi olarak geçiriliyor.
- **main.py → `_flush_state()`**: `fvg_missed`, `displacement_origin`, `poi_anchor` alanları persist ediliyor.
- **main.py → `_load_state()`**: Aynı 3 field restore ediliyor.
- **state_machine.py → `check_retrace()`**: `atr: float = 0.0` parametresi eklendi.
- **state_machine.py → `_check_missed_fvg()`**: `MISSED_ATR_MULT × atr` threshold ile `missed_fvg_at_price` kaydı.
- **state_machine.py → `check_poi_retrace()`**: `POI_ATR_BUFFER × atr` zone kontrolü.
- **state_machine.py → `_handle_ltf()`**: `WAIT_POI_CONFIRM` state'i de kabul ediliyor.
- **state_machine.py → `path_evaluate()`**: Case A + Case C ayrı if blokları.
- **state_machine.py → `_check_stale_state()`**: `MISSED_FVG` + `WAIT_POI_CONFIRM` zombi temizliğine dahil.

### 2026-06-09: Logging Altyapısı — TimedRotatingFileHandler
- **main.py import bloğu**: `import logging.handlers` eklendi.
- **main.py `logging.basicConfig()`**: `TimedRotatingFileHandler` (midnight, 10 backup).

### 2026-06-08: FVG Missed Flow (Tüm 8 Parça)
- **config.py**: `MISSED_FVG_ATR_MULT = 1.5`, `POI_ATR_BUFFER = 0.3`.
- **SetupState enum**: `MISSED_FVG`, `WAIT_POI_CONFIRM` eklendi.
- **SymbolState**: `fvg_missed`, `poi_anchor`, `displacement_origin`, `missed_fvg_at_price`.
- **analyzer.py `_detect_mss_events()`**: `impulse_origin` eklendi.

## Sonraki Adımlar
1. Canlıda H1/2H FVG tespitinin çalıştığını doğrula — log'da `[FVG] {symbol} H1'de ... FVG bulundu` mesajlarını kontrol et.
2. H1'de FVG bulunamazsa 2H fallback'in devreye girdiğini doğrula — log'da `[FVG] ... H1'de bulunamadı → 2H fallback` mesajını kontrol et.
3. `check_retrace()` CE eşiğini H1 FVG boyutuna göre dinamik yap (sonraki adım).

## Aktif Kararlar
- **FVG timeframe**: H1 birincil, 2H fallback. 15m FVG kaldırıldı (gürültülüydü).
- **FVG since_index**: `None` — tüm H1/2H barlarını tarar, MSS anchor'a bağlı değil.
- **OHLC export**: 5m export kaldırıldı — visualizer artık 15m ve 1m verilerine bağımlı.
- **State logger**: 15m kapanışında snapshot alınır, 10 gün rotate. fvg_tf alanı eklendi.
- **FVG Missed Flow**: Case C'de sistem beklemez — anında re-anchor eder.
- **Penetration Trade Zone**: `FVG_PENETRATION_MIN=0.15`, `FVG_PENETRATION_MAX=0.70`. ATR bağımlılığı kaldırıldı — penetrasyon oranı tek karar kriteri.
- **POI Buffer**: `FVG size × 0.3` (ATR bağımlılığı yok).
- **SL stratejisi**: 4H swing high/low + tier buffer.
- **TP stratejisi**: 1H BSL/SSL likidite seviyesi.
- **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir.

## Önemli Desenler ve Tercihler
- `_get_atr()`: `ATR_MAP[symbol]` → `DEFAULT_ATR` → `None` fallback zinciri.
- `export_ohlc_15m` / `export_ohlc_1m`: Header kontrolü `f.tell() == 0` ile (os.path.exists yerine).
- `state_logger.write_snapshot()`: Thread-safe CSV yazımı, `_csv_lock` ile.
- `_resample_to_2h()`: modül seviyesi fonksiyon, Bar listesi alıp 2H bar üretir.
- 3 lint aracı da geçiyor: **ruff** ✅, **mypy** ✅, **vulture** ✅.

## Öğrenimler
- 15m FVG küçük ve gürültülü — gerçek imbalance H1/2H'de oluşur. HTF FVG daha güvenilir.
- `_resample_to_2h()` sentetik bar üretimi: iki 1H barını birleştirerek high=max, low=min mantığıyla 2H barı oluşturulur.
- V-shape hareketlerde FVG hiç dokunulmadan fiyat kaçarsa, sistem `WAIT_RETRACE`'ta sonsuz beklerdi. Çözüm: displacement_origin + ATR eşiği ile MISSED tespiti.
- `displacement_origin` MSS kırılım barından önceki son pivot olarak hesaplanır.
- 5m OHLC export'u kaldırıldı — visualizer 15m ve 1m'e geçti.
- Log dosyaları kaynak kod dizinine (`sonnet/src/`) yazılmamalı — `output/trading/` gibi proje dışı dizinlere yazılmalı.
