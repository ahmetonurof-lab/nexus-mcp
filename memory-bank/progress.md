# nexus-mcp — Progress

## ✅ Done
- **FVG giriş filtreleri backtest ile hizalandı (2026-07-31, commit `793aaa9`):**
  - Sorun: Kullanıcı "dailybias kilitlendikten sonra boyutu ve ATR'si uygun her FVG (invalid değilse) bias yönünde işleme girmesine izin ver...aynı backtestdeki gibi" dedi; canlı iki ekstra katmanla backtest'ten sapıyordu.
  - `signal_engine.py:81` `bar_index=current.index` → `None`: sweep dedup (SWEEP SKIP) canlıda devre dışı — backtest `analyzer_v5.py:270` zaten `bar_index=None` geçiyor. Aynı sweep bar restart sonrası tekrar tetiklenebilir (dedup mekanizması `retrace_state.py:103-116` + `state_manager.py:119-149` duruyor, bar_index None iken atlanır).
  - `fvg.py:165-189` `fvg_is_alive` gevşetildi: eski "gap içi close veya far-side close → ölü" → yeni "yalnızca far-side close (bullish close<bottom, bearish close>top) → INVALIDATED". Backtest `get_fvg_status` (analyzer_v5:128-148) ile birebir: gap içi kapanış ACTIVE_ENTRY_ZONE = giriş sinyali, FVG ölmez.
  - Backtest, canlının `retrace_state.py`'sini import ediyor (analyzer_v5:28) → FVG seçimi/onayı (min_fvg_size, wick_touched, body_broke_down) zaten ortak; yalnızca giriş kapısı farklıydı.
  - Doğrulama: test_retrace_state + test_fvg 57 passed; pre-commit (ruff, ruff-format, vulture, mypy) temiz; commit push edildi.
- **-2021 hedefli guard'lar (madde 1-2, 2026-07-31):**
  - Analiz (çapraz doğrulama): DD state kirlenmesi BU KOŞUDA OLMAMIŞ (log 2058 `05:30:01,198 DD: %16.20`, trip şartı is_circuit_broken'sız mesaj → breaker temiz başladı; 4997.92×0.838≈4188.10 doğru). RENDER -2021 gerçek ama zararsız yarış. "Phantom trade" teşhisi kullanıcının Binance emir kanıtıyla çelişti (DYDX emirleri AKTİF). Global "status exiting ise atla" guard'ı `_mark_repair_required` (exit_lifecycle.py:560-594) meşru yolunu köreltir — RED.
  - `sniper/src/trading/user_data_handler.py`: normalized (≈381) + legacy (≈600) WS-REPAIR dallarına `had_immediately_trigger(sym)` guard'ı.
  - `sniper/src/trading/recovery_manager.py`: `recover_positions` else dalına (a) local status UNRESTRICTED değilse atla, (b) `had_immediately_trigger(sym)` varsa atla.
  - `_is_immediately_trigger_error` / order_manager:744-752 handler son savunma hattı olarak AYNEN korundu.
  - py_compile OK.
- **Canlı trailing konsept düzeltmesi (2026-07-31):**
  - `sniper/src/bot.py`: `_build_fvg_scan_trail_extractor` — post-entry pencerede her 15m bar'da taze FVG taraması, `TrailingManager._fvg_multihop` çağırır.
  - `sniper/src/trading/trailing_manager.py`:
    - `TrailLevel.sl_buffered` bayrağı (double-buffer önlemi).
    - `TrailScanResult` dataclass + `_fvg_multihop` static helper (backtest analyzer_v5 trailing adımlarının birebir kopyası: detect_fvgs lookback=min(50), fvg_close_confirmed, ATR×ATR_TRAIL_MULT buffer, TRAIL_MIN_MOVE_MULT min-move, çoklu-hop, TP delta-shift).
    - `evaluate_trail` → `_fvg_multihop` wrapper'ı (geriye dönük uyumlu, test'ler aynen geçer).
  - Safety katmanı korundu: `is_placeable` + fingerprint dedup + `ImmediateTriggerError` (orchestrate_trail değişmedi).
  - Min-move bazı `abs(initial_sl - entry_price)` yapıldı (backtest `rpt2` ile birebir).

## 🔧 Pending / In Progress
- **DYDX reconciliation kök analizi:** `live_state.json` DYDX `protection_health: BROKEN`/`repair_required: false` vs borsada AKTİF emirler (TP 0.115/SL 0.107, GTC) çelişkisi açık; `trade_state.json` `source: "startup_reconcile"` izi sürülecek.
- **Zaman-bazlı çıkış (MAX_HOLD_HOURS):** config + exit_lifecycle yaş kontrolü — kullanıcı onayı bekliyor (madde 3). Şu an yalnızca `fvg.py MAX_FVG_AGE_BARS` var, pozisyon çıkışı için yok.
- **Mod ayrımlı state dosyası:** `risk_state_live.json`/`risk_state_paper.json` — kullanıcı onayı bekliyor (madde 3). Şu an bot.py:218-221 tüm modlarda `risk_state.json` kullanıyor (latent testnet↔mainnet riski).
- **Log seviyeleri:** `P1-15_DEBUG` ve `trail_skipped` → DEBUG (madde 5).
- **Backtest'e 1m trailing/exit ekleme:** kullanıcı "1m trailing exit mutlaka backteste eklenmeli" dedi — henüz başlanmadı.
- **is_fvg_valid değerlendirmesi:** canlıda aktif (bot.py:451, GLOBAL_FVG_EXPIRY_BARS=45); backtest'te eksik. Kullanıcı eğilimi: canlıdan kaldırma.
- **Parite farkları (açık):**
  - E5: close-inside-FVG onayı canlıda devre dışı (retrace_state.py:210-215, backtest karşılaştırması için "geçici").
  - E8: Session filtresi canlı global (LONDON 2-13, NEWYORK 13-22, CBDR 22-2) vs backtest coin-bazlı (REAL_CBDR 19-1, ASIA_RANGE 1-5, DEFAULT 22-2).
  - E13-E15: DD devre kesici (trip 15/reset 10), dinamik equity, qty cap'leri backtest'te yok.
  - E18: Entry fiyatı canlı trigger bar CLOSE, backtest next bar OPEN (bilinçli fark).
  - T6-T8: tick normalizasyon, placeability, fingerprint canlıya özgü (kullanıcı onayı: gerekli exchange-safety katmanı).

## ✅ Doğrulananlar (2026-08-01)
- **Çapraz bağlam doğrulama turu (Bölüm F):** 0 yeni regresyon.
  - Madde 1: 03e6eaf8→639a5f0 pytest diff — 6 test fix, 0 yeni regresyon.
  - Madde 2: BINANCE_API_KEY set edilerek TÜM suite — 0 yeni regresyon (67 failed her iki koşulda aynı).
  - Madde 3: Tüm `.setdefault()` çağrıları ActiveTrade'de değil (4 yer, hepsi plain dict).
  - Madde 3b: EntryExecutionResult kontratı tutarlı.
  - Madde 3c: 6 ActiveTrade inşaat yerinde entry_order_id/entry_actual_qty doğru veya K2-A fallback tutarlı.
  - Madde 4: K1=B, risk_state.json geçerli formatında. K2-A paper-mode sınırı dokümante edildi.
  - Madde 5: test_order_manager.py ve test_integration.py düz dict kullanıyor — BUG-29 fix'ini yakalayamaz.
