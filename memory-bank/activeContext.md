# Active Context — NEXUS V3

## Mevcut Odak
FVG Missed Flow implementasyonu tamamlandı — V-shape hareketlerde fiyat FVG'yi hiç görmeden kaçtığında sistem artık sonsuz WAIT_RETRACE'de zombiye dönüşmüyor. Case C (MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER) akışı eklendi.

## Son Değişiklikler

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
