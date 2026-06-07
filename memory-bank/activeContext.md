We need to output the modified file based on the suggested edit. The original code is the entire content of the file "Active Context — NEXUS V3". The suggested edit is a new version that updates the original. The instruction: "Apply the SUGGESTED EDIT to the ORIGINAL CODE. Output the complete modified file." So we should output the SUGGESTED EDIT as the final file. However, we need to ensure it's exactly the suggested edit, preserving any formatting. The suggested edit seems to be a Markdown file. We output it verbatim.

But note: The user says "Output ONLY code. Do NOT explain, summarize, or describe changes." So we just output the text of the suggested edit.

We must ensure there are no extra characters, just the file content.

Thus the final output is the suggested edit markdown content.# Active Context — NEXUS V3
## Mevcut Odak
Unit test altyapısı kuruldu (`tests/`). Sonraki adım: canlı trading testi ve monitoring.

## Son Değişiklikler

### 2026-06-07: MSS Log Zinciri + reset_flags Genişletme + _handle_mss Guard
- **state_machine.py → `reset_flags()`**: 5 satırdan 15 satıra çıkarıldı — artık `sweep_level`, `sweep_bar_index`, `mss_level`, `mss_bar_index`, `fvg_upper`, `fvg_lower`, `fvg_time`, `direction`, `entry_price`, `fvg_entry_bar_index` dahil tüm yapısal alanları sıfırlar.
- **state_machine.py → `_handle_mss()`**: Tamamen yeniden yazıldı — state gate kontrolü (sadece ARMED/WAIT_RETRACE/WAIT_CONFIRM'de işle), HTF bias overwrite koruması (`state.direction` None ise set et), `[MSS-HANDLE]` / `[MSS-SKIP]` log prefix'leri.
- **analyzer.py → `_detect_mss_events()`**: `events.append(...)` öncesine `logger.info("[MSS-EMIT] ...")` eklendi — log zinciri `[MSS-EMIT]` → `[MSS-HANDLE]` şeklinde takip edilebilir.

### 2026-06-06: main.py STATE-DEBUG Renklendirme
- **main.py**: STATE-DEBUG log satırındaki boolean değerler (`sweep_detected`, `mss_confirmed`, `retrace_seen`, `ltf_confirmed`) ANSI renk kodları ile renklendirildi (yeşil `True` / kırmızı `False`).
- `color_bool()` helper fonksiyonu eklendi.

### 2026-06-06: Unit Test Altyapısı + Config Güncellemesi
- **Test dosyaları eklendi**: `tests/test_pivot.py` (22 test — swing highs/lows, SwingStateManager), `tests/test_risk_manager.py` (40+ test — SL/TP/lot/build_trade), `tests/test_state_machine.py` (30 test — state geçişleri, pre-check, retrace, flag gate).
- **Test konfigürasyonu**: `tests/conftest.py` — `sonnet/src` sys.path'e eklenir, `make_bar`, `make_state`, `make_risk_manager` fabrikaları sağlanır.
- **`config.py`**: `HTF_STRICT_FILTER: True → False` — H4 D1'e ters olsa bile işleme izin verir (D1 bias'ı kazanır, H4 sadece strength belirler).
- **`analyzer.py`**: Gereksiz satır sarmaları kaldırıldı (kod format temizliği).
- **`state_machine.py`**: `_check_retrace` FVG seviyesi yok logu `debug` → `info` seviyesine çekildi.
- **Pylance fix**: `.vscode/settings.json` → `python.analysis.extraPaths: ["sonnet/src"]` (import çözümlemesi için).
- **Pre-commit fix**: Test dosyalarındaki E402 (import sırası), E741 (karışık `l` değişkeni), F841 (kullanılmayan değişken) hataları düzeltildi.

### 2026-06-06: risk_manager.py Bug Fix
- **AttributeError düzeltildi**: `calculate_sl_htf` metodunda tanımlı olmayan `self.tier_buffer`, `self.min_sl_pct`, `self.max_sl_pct`, `self.logger`, `self.symbol` referansları düzeltildi.
- **Çözüm**: `_tier(symbol)` ile tier config'ten `sl_buffer`, `min_sl_pct`, `max_sl_pct` değerleri alınıyor. Loglama modül seviyesindeki `log` ile yapılıyor.
- **Metod imzası güncellendi**: `calculate_sl_htf` artık `symbol` parametresi alıyor.
- **`calculate_tp_htf` çağrı imzası düzeltildi**: 6 parametreli hatalı çağrı, 4 parametreli doğru imzaya (`entry, risk_dist, h1_liquidity_level, state.direction`) çekildi.
- **Memory Bank oluşturuldu**: 6 çekirdek dosya yazılıyor.

## Sonraki Adımlar
1. Canlı trading testi — READY_TO_ENTER zincirinin risk_manager.py'den hatasız geçtiğini doğrula.
2. `live_trading.log` üzerinden SL/TP/lot hesaplamalarını gerçek piyasa verisiyle valide et.
3. `analyzer.py` unit test ekle — her event detector için ayrı test.
4. Opsiyonel: `monitor.py` health endpoint'ini Grafana/Prometheus'a bağla.

## Aktif Kararlar
- **SL stratejisi**: 4H swing high/low + tier buffer (eski FVG tabanlı SL'den geçildi).
- **TP stratejisi**: 1H BSL/SSL likidite seviyesi (eski default RR çarpanından geçildi).
- **Sweep sonrası daraltma**: Sweep level varsa SL sweep seviyesine göre ayarlanıyor (Turtle Soup koruması).
- **HTF strength scaling**: WEAK sinyallerde risk %40'a, MODERATE'te %70'e düşürülüyor.
- **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir — D1 bias'ı kazanır, H4 strength belirler.

## Önemli Desenler ve Tercihler
- `_tier(symbol)` → `TIER_MAP` ve `TIER_CFG` üzerinden sembol tier'ını çözümler.
- `build_trade` hiçbir şekilde SL mesafesine göre trade reddetmez (eski constraint kaldırıldı).
- FVG fallback: `h4_swing_level` yoksa eski FVG tabanlı SL kullanılır.
- Test altyapısı: `conftest.py` → `sys.path.insert(0, sonnet/src)` ile modül erişimi sağlanır. Fabrika fonksiyonları (`make_bar`, `make_state`, `make_risk_manager`) ile bağımlılık minimize edilir.
- Log seviyeleri: `log.info` (normal akış), `log.warning` (reddedilen trade), `log.debug` (fallback kullanımı).

## Öğrenimler
- `_evaluate()` pre-check layer'ı (stale + invalidation) 4-flag hard gate'ten önce çalışır.
- `_check_invalidation` anlık iğneyi değil, mum **kapanışını** kontrol eder.
- D1 bar değişiminde `_consumed_levels` likidite havuzu sıfırlanır.
- Memory Bank olmadan debug zor; her session reset'inde proje context'i kayboluyordu.
- **LTF `body_ok` sadece log'da**: `mss.py:438` — `is_valid = close_ok`. Body hesaplanır ama karar mantığına girmez. `[LTF] body_ok=False` logu debug amaçlıdır.
- **Pylance import hataları**: `conftest.py`'nin `sys.path.insert`'i runtime'da çalışır, Pylance statik analizinde görünmez. Çözüm: `.vscode/settings.json` → `python.analysis.extraPaths`.
- **Pre-commit hooks**: `ruff` lint + format otomatik çalışır. Yeni dosyalarda E402 (sys.path sonrası import), E741 (tek harfli değişken), F841 (kullanılmayan değişken) sık karşılaşılan hatalar.

## Debug Workflow (AI Protocol)
1. Log satırını oku.
2. Log prefix'ine göre fonksiyonla eşleştir (örn. `[BIAS]`, `[SWEEP]`, `[MSS]`).
3. Log değerlerini beklenen eşiklerle karşılaştır (aşağıdaki Common Patterns tablosu).
4. Uyuşmazlık varsa → o fonksiyonun ERROR bölümünü kontrol et.
5. Zincir kırıldıysa (event'ler yarıda kesildiyse) → state machine'i geriye doğru yürüt.

## Common Patterns & Root Causes

| Semptom | En Olası Neden |
|---|---|
| Tüm semboller IDLE, hiç event yok | D1 verisi yüklenmiyor, `analyze()` `[]` döner |
| Bias=None tüm sembollerde | `find_swing_highs/lows` pivot.py'de bozuk |
| SWEEP hiç ateşlenmez | 15m swing listeleri boş — pivot.py 15m'de çalışmıyor |
| MSS hiç ateşlenmez | bias filter tüm CHoCH'ları öldürüyor veya since_bar_index çok dar |
| FVG hiç ateşlenmez | MSS yok (mss_since=None) veya lookback çok küçük |
| RETRACE hiç ateşlenmez | FVG'ler price ulaşmadan expire oluyor veya `is_active` mantığı bozuk |
| LTF_CONFIRM hep false | body_atr_mult=0.5 çok sert veya 1m barlarda retracement_swing yok |
| State WAIT_RETRACE'te takılı | RETRACE event üretildi ama `_handle_retrace()` NoneType guard'ına takıldı |
| State WAIT_CONFIRM'de takılı | `_evaluate()` çağrılmıyor veya ltf_confirmed flag'i hâlâ False |
| READY_TO_ENTER ama trade yok | `build_trade()` None döner (SL çok geniş) veya send_order blocked |
| WS koptu, pozisyonlar gitti | Binance tarafında kontrol et — server-side order'lar kalır. WS sadece yeni sinyalleri etkiler |
| State EXPIRED ama log yok | `update_from_event()` erken döner `is_expired()` → state=EXPIRED, event işlenmez |
