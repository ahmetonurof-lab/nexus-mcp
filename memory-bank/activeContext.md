# nexus-mcp — Active Context

## Current State
2026-07-31: Canlı (sniper) trailing artık backtest (analyzer_v5) konseptiyle çalışıyor. Canlı trailing'in hiç çalışmadığı tespit edilmişti (rsm.trigger_fvg tabanlı extractor, entry sonrası rsm.reset() → trigger_fvg hep None). Kullanıcının onayladığı konsept ile taze FVG taraması + fvg_close_confirmed + ATR buffer + çoklu-hop'a geçildi.

Aynı gün: -2021 "immediately trigger" reject gürültüsüne karşı hedefli guard'lar uygulandı (madde 1-2). Analiz özeti: DD state kirlenmesi bu koşuda OLMAMIŞ (trip %16.20 meşru), RENDER -2021 gerçek ama zararsız yarış, global repair guard YANLIŞ olurdu — doğru çözüm yalnızca WS_FALLBACK + 60s recover loop yollarına dar kapsamlı guard.

Aynı gün: **FVG giriş filtreleri backtest ile hizalandı** (commit `793aaa9`). Kullanıcı: "dailybias kilitlendikten sonra boyutu ve ATR'si uygun her FVG (invalid değilse) bias yönünde işleme girmesine izin ver...aynı backtestdeki gibi". İki fark kapatıldı: (1) canlı `signal_engine.on_sweep` `bar_index=current.index` geçiyordu → `None` yapıldı (sweep dedup SWEEP SKIP canlıda devre dışı, backtest analyzer_v5:270 ile aynı); (2) `fvg_is_alive` gap içi kapanışı da öldürüyordu → yalnızca far-side close (bullish close<bottom, bearish close>top) INVALIDATED sayar, gap içi close (ACTIVE_ENTRY_ZONE) entry sinyalidir.

## Recently Completed
- **P0 safety fixes (2026-08-01):** 5 bare `except Exception: pass` → log.error + retry/fallback. recovery_manager.py:486 (SL/TP cancel), exit_lifecycle.py:521 (position verify), exit_lifecycle.py:549 (FILLED order check), order_manager.py:646 (SL placement), order_manager.py:966 (repair cancel). state_writer.py: BULGU-05 (protection_health flat field'lardan) + BULGU-19 (ws_event_normalization config'den).

- **FVG giriş parite (2026-07-31, commit 793aaa9):**
  - `sniper/src/trading/signal_engine.py:81` — `bar_index=None` (sweep dedup canlıda devre dışı; SWEEP SKIP artık entry engellemez).
  - `sniper/src/fvg.py:165-189` — `fvg_is_alive` backtest `get_fvg_status` semantiğine çekildi: yalnızca far-side close invalid, gap içi close öldürmez.
  - Doğrulama: test_retrace_state + test_fvg 57 pass; pre-commit (ruff, vulture, mypy) temiz; py_compile OK.
  - Bayat test hataları (25) değişiklikle İLGİSİZ: check_exit imzası, mark_trade_closed/_stage/_exit_trade_legacy eski API referansları (baseline ile aynı).
- **-2021 hedefli guard'lar (madde 1-2, 2026-07-31):**
  - `sniper/src/trading/user_data_handler.py` — hem normalized hem legacy `_on_order_update` WS-REPAIR dallarına `had_immediately_trigger(sym)` guard'ı: son 1 saatte -2021 reject kaydı varsa repair atlanır (pozisyon dolmuştur, WS FILLED gecikmeli gelecek). `_is_immediately_trigger_error` reaktif catch son savunma hattı olarak KORUNUR.
  - `sniper/src/trading/recovery_manager.py` — `recover_positions` koruma kurulum (else) dalına iki guard: (a) local trade status `UNRESTRICTED_STATUSES` dışındaysa kurma (exit lifecycle yönetiyor), (b) `had_immediately_trigger(sym)` varsa kurma.
- **Trailing konsept düzeltmesi (2026-07-31):** `sniper/src/bot.py` — `_build_fvg_scoped_trail_extractor` (rsm.trigger_fvg tabanlı, hiç tetiklenmiyordu) → `_build_fvg_scan_trail_extractor` (backtest ile aynı: post-entry pencerede her 15m bar'da detect_fvgs + fvg_close_confirmed + ATR buffer + TRAIL_MIN_MOVE_MULT çoklu-hop). SL seviyesi `sl_buffered=True` ile donuyor.
- **compute_trail_candidate double-buffer fix:** `sniper/src/trading/trailing_manager.py` — `TrailLevel.sl_buffered` bayrağı eklendi; `sl_buffered=True` iken tick×2 buffer uygulanmıyor (buffer = ATR×ATR_TRAIL_MULT=0.25).
- **`evaluate_trail` refactor:** `_fvg_multihop` static helper'ına çekildi (backtest adımlarının birebir kopyası). `evaluate_trail` ince wrapper, geriye dönük uyumlu. `last_bar_index` fingerprint için döndürülüyor.
- **Kullanıcı konsept kararları:** Seviye kaynağı = taze FVG taraması (rsm.trigger_fvg değil); Buffer = ATR×0.25 (tick×2 değil); TP = delta-shift (RR yeniden hesap yok); Adım = çoklu-hop; is_placeable + fingerprint dedup + ImmediateTriggerError katmanı AYNEN kalır (exchange-safety).

## Next Actions
1. DYDX reconciliation tutarsızlığının kökü hâlâ açık: `live_state.json` DYDX `protection_health: BROKEN`/`repair_required: false` ama borsada emirler AKTİF (TP 0.115/SL 0.107, GTC, 07-30 21:00:04). `trade_state.json` `source: "startup_reconcile"` izi sürülecek.
2. Zaman-bazlı çıkış YOK (kök eksik): `MAX_HOLD_HOURS` config + exit_lifecycle yaş kontrolü kullanıcı onayı bekliyor; mod ayrımlı state dosyası (`risk_state_live.json`/`risk_state_paper.json`) onay bekliyor.
3. Backtest'e 1m trailing/exit akışı eklenmesi (kullanıcı şart koşuyor) — henüz başlanmadı.
4. is_fvg_valid canlıdan kaldırılması değerlendirmesi (kullanıcı: "FVG invalid olmadıysa/dokunulmadıysa hâlâ geçerli kalmalı") — onay bekliyor. NOT: `fvg_is_alive` zaten bu semantiğe çekildi (793aaa9).
5. Kalan parite farkları: session saatleri (global vs coin-bazlı), DD circuit breaker / dinamik equity / qty cap'leri backtest'te yok, E18 entry fiyatı (bilinçli fark).

## Notlar
- **-2021 kanıt zinciri:** RENDER 05:42:02 WS `SL FILLED` → 05:42:02.321 POST_ENTRY_DEBUG SL listede yok → 05:42:03.284 -2021 → 05:42:03.285 repair atlandı → 05:43:01 trade_closed pnl −7.09. Yarış yapısal (WS-push vs REST-poll), tamamen kapanmaz — "önemli ölçüde azalır, sıfırlanmaz".
- **DD state:** `risk_state.json` = `{peak_equity: 4997.92, is_circuit_broken: true}`; DD %14.51 > reset %10 → açık kalması histerezis gereği DOĞRU. Trip kanıtı log 2058 `05:30:01,198 DD: %16.20`.
- `UNRESTRICTED_STATUSES = {ACTIVE, ""}` (models.py:319) → user_data_handler:365-375 guard'ı exiting durumları zaten eliyor; yeni eklemeler bunun üstüne -2021 gürültüsünü keser.
- Canlı trailing artık çalışıyor: compute_trail_candidate her 1m close'ta aynı 15m pencereyi tarar; fingerprint dedup tekrar uygulamayı engeller; yeni 15m bar kapanınca yeni FVG hop'u tetiklenir.
- `reports/backtest_canli_farklari_31_07_2026.md` — entry (E1-E19) / trailing (T1-T10) parite tablosu.
- Test durumu: test_trailing_manager 25 geçiyor, 17 önceden mevcut check_exit imza hatası (değişiklikle ilgisiz). Tam suite baseline ile birebir aynı (74 failed / 700 passed).

## Verification Results (2026-08-01)
- **Çapraz bağlam doğrulama turu (Bölüm F) tamamlandı.** 0 yeni regresyon tespit edildi.
  - Madde 1 (ampirik baz): 03e6eaf8→639a5f0 pytest diff'i — 6 test fix oldu, 0 yeni regresyon.
  - Madde 2 (.env live-path): BINANCE_API_KEY set edilerek TÜM suite koşuldu — 0 yeni regresyon (67 failed her iki koşulda da aynı).
  - Madde 3 (setdefault deseni): src/ içindeki tüm `.setdefault()` çağrıları kontrol edildi — hiçbiri ActiveTrade nesnesinde değil (4 yer, hepsi plain dict class attribute'ları).
  - Madde 3b (success/error kontrat): `EntryExecutionResult` kontratı tutarlı — `bot.py:796`'deki `if not exec_result.success:` doğru şekilde kullanılıyor.
  - Madde 3c (ActiveTrade inşaat): 6 yer tespit edildi (bot.py:943, models.py:584, recovery_manager.py:145/516/539). Hepsinde `entry_order_id`/`entry_actual_qty` alanları doğru doldurulmuş veya K2-A fallback'iyle tutarlı.
  - Madde 4 (K1/K2): K1=B seçildi, risk_state.json geçerli formatında. K2-A paper-mode sınırı dokümante edildi.
  - Madde 5 (test kapsam boşluğu): test_order_manager.py ve test_integration.py düz dict kullanıyor — BUG-29 setdefault fix'ini yakalayamaz. test_integration_lifecycle.py ve test_protection_lifecycle.py ActiveTrade kullanıyor.
