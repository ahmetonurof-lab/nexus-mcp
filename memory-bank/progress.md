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

## ✅ Doğrulananlar (2026-07-31)
- -2021 mekanizması: `order_manager.py` `_immediately_trigger_rejects` dict (78), `_is_immediately_trigger_error` `-2021` (487), `_record_immediately_trigger` (496), `had_immediately_trigger` (505, 3600s pencere, max gözlenen gecikme 353s).
- `UNRESTRICTED_STATUSES = {ACTIVE, ""}` (models.py:319); user_data_handler:365-375 status guard'ı 007983b7'den beri var (2026-07-20).
- `recovery_manager.py` `recover_positions`: SL/TP kurulumu `close_position=True` (200-211), `_try_split_qty_sl_tp` (213+), `RECOVERY_SL_FALLBACK_PCT` (0.01% KULLANMA — immediately trigger riski).
- P1-15 zinciri: `exit_lifecycle.py:220-239` `had_immediately_trigger` stale atlama, 241-252 30sn cooldown, user_data_handler:245-260 WS_FALLBACK REST cross-val, bot.py:1233-1237 60sn periodic.
- Canlı trailing neden çalışmıyordu: `bot.py:970` entry sonrası `rsm.reset()` → `trigger_fvg=None`; trade açıkken `progress_rsm` çağrılmıyor; extractor `rsm.trigger_fvg` okuyordu → hep None → `compute_trail_candidate` hiç candidate üretmiyordu.
- `MAX_SL_DIST_MULT` canlıdan kaldırılmış (commit def7eca); config.py:558'de ölü duruyor.
- `is_high_quality_fvg` canlıdan kaldırılmış (commit aa08ef8); tek kaynak `FVG_SIZE_MAP`.
- Backtest ile yeni canlı trailing artık aynı mantıkta (level kaynağı, buffer, çoklu-hop, delta-shift TP).
