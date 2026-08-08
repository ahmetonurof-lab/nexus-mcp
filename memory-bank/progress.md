# nexus-mcp — Progress

## ✅ Done
- **D Modu canlıya birebir uygulandı (2026-08-08, commit bekliyor):** Kullanıcı direktifi: backtest D modu (Aktivasyonlu ATR-Chase: K=2.0, R=1.5) kalıcı parametre seti canlı bota taşındı.
  - `sniper/src/config.py` (Magic Numbers, ~530): `TRAIL_MODE = os.environ.get("SNIPER_TRAIL_MODE", "activation")`, `CONT_BUFFER_MULT = float(os.environ.get("SNIPER_CONT_BUFFER_MULT", "2.0"))`, `TRAIL_ACTIVATION_R_MULT = float(os.environ.get("SNIPER_TRAIL_ACTIVATION_R_MULT", "1.5"))`. Açıklama yorumu: FVG retrace her zaman aktif; K = fallback SL tamponu (K×ATR); R = aktivasyon eşiği (R × risk_pts); eşik yalnızca ATR-chase fallback'i kilitler.
  - `sniper/src/trading/trailing_manager.py` `_fvg_multihop`: `retrace_only = cfg.TRAIL_MODE in ("retrace", "activation")` → `_fvg_close_confirmed` retrace-only onayı (backtest `fvg_close_confirmed` birebir: `scan_from = real_index+2`, gap içi kapanış onaylar, pozisyon lehine far-side elimine etmez, aksi yön invalidates); `placeable = not retrace_only` (activation/retrace'ta stale kontrolü yok — backtest `placeable = TRAIL_MODE not in ("retrace","activation")` ile birebir); yeni ATR-chase fallback bloğu: `cfg.TRAIL_MODE in ("atr_chase","activation") and not updated` → `upnl_pts = price-entry` (long) / `entry-price` (short); `TRAIL_MODE == "activation"` iken `upnl_pts >= 1.5 * risk_pts` şartı (eşik altında fallback pasif); `new_sl = price ∓ 2.0*ATR`; `TRAIL_MIN_MOVE_MULT` min-move kontrolü; TP delta-shift (PTrail); `trail_steps`'e `reason="atr_chase_fallback"` step'i; `last_bar_index = chunk[-1].index`.
  - Doğrulama: `tests/test_trailing_manager.py` +6 test (D modu fallback aktif/pasif, FVG önceliği, `_fvg_close_confirmed` far-side elimine-etmeme + invalidation; `test_skips_wrong_direction_fvg_long` retrace moduna kilitlendi) → **70/70 geçiyor**. Config yükleme doğrulandı (TRAIL_MODE=activation, K=2.0, R=1.5). Bot entegrasyonu doğrulandı: bot.py:348 `_fvg_multihop(current_price=scoped_bars[-1].close)`, `trade["initial_sl"]`/`trade["entry_price"]` mevcut, `trail_steps` aynı dict referansıyla append, `compute_trail_candidate` `sl_buffered=True` → SL aynen + TP paralel öteleme.
  - Test suite durumu: baseline ile aynı — **36 failed / 835 passed** (36 başarısızlık önceden var: `mark_trade_closed`/`_exit_trade_legacy` eski API referansları, `_resolve_fvg_bar_index`, CBDR sweep yönü, state_writer sl_status vb. — trailing ile ilgisiz). Parity `SOLUSDT` baseline'da da kırık (core_diff 33462; D moduyla 33489).
  - Kapanış: commit + push yapıldı (bkz. commit log) — canlıya deploy kullanıcı onayı bekliyor.
- **STATE-SYNC fix canlı doğrulama — eski log bug desenini BİREBİR gösterdi (2026-08-06):** Eski log (`paper_trade.log.20260806_163820.bak`, 18.105 satır, eski kod bc73b5c): 16 `orphan_sweep` iptali + 4 RECOVER. Zincir kanıtı: trailing "koruma güncellendi" → 1-14 sn sonra orphan_sweep YENİ emirleri iptal ediyor (SOLUSDT 09:31:03→09:31:04, APTUSDT 10:16:01→10:16:06, LDOUSDT 10:16:17→10:16:31, NEARUSDT 06:45:01→06:45:07); SOLUSDT 02:01-02:15 RECOVER-orphan döngüsü 4 kez (RECOVER kurduğu emiri aynı saniye kendisi iptal ediyor). **Yeni log (fix 4033198 sonrası, 16:38→17:29): 0 orphan_sweep, 0 RECOVER, 0 ORPHAN** ✓. Henüz `trail_candidate updated` yok (387 trail_skipped: 387 no_better + 86 identical_invalid + 15 candidate_not_placeable [SOLUSDT long, 14x]) — ilk trailing güncellemesi bekleniyor.
- **STATE-SYNC fix (P2-4) canlıya alındı (2026-08-06, commit `4033198`):** Bot Contabo (root@169.58.41.73) üzerinde `screen -S bot` içinde çalışıyordu (`python3 bot.py`, cwd `/root/sniper/src`). Durdur → `git pull` (bc73b5c→4033198 fast-forward) → yeniden başlat. 3 katmanlı teyit: (1) `git log -1` = `4033198`, (2) `grep -cE "P1-15_DEBUG|POST_ENTRY_DEBUG"` = 0, (3) davranışsal: bot başladı, 10 pozisyon envantere alındı, WS bağlandı, loglar akıyor. Kalan: ilk canlı trailing olayında `runtime.protection.sl_current/tp_current` güncellemesinin gözlemlenmesi (tüm pozisyonlar şu an `TRAIL: 0x`).
- **Paper trade olumsuzluk raporu (2026-08-05):** `paper_trade.log` (5730+ satır) okundu; SUIUSDT -2021 reject (satır 4225) `trades_history.jsonl` satır 416 ile teyit edildi (pnl -8.82, WS FILLED kapanış). P1-15 guard'larının (`ed024c3`, `d5331fa`) koşuda doğru çalıştığı doğrulandı. Rapor: `sniper/reports/paper_trade_rapor_2026-08-05.md`.
- **Bare except remediation (2026-08-02):** `recovery_manager.py:780` ve `exit_lifecycle.py:754`'teki çıplak `except Exception: pass` blokları log.warning ile değiştirildi.
- **P0 safety fixes — bare except remediation (2026-08-01):** 5 `except Exception: pass` hatasını log.error + retry/fallback ile tamamlandı. Ayrıca state_writer.py'de BULGU-05 + BULGU-19 düzeltmesi.
  - recovery_manager.py:486 — TP iptal bare except → log.error + 1 retry + incident kaydı
  - exit_lifecycle.py:521 — position verify bare except → log.error (retry mekanizması zaten var)
  - exit_lifecycle.py:549 — FILLED order check bare except → log.error
  - order_manager.py:646 — SL parça kurulum bare (except: continue) → log.error
  - order_manager.py:966 — repair cancel bare except → log.error + _repair_failed set
  - exit_lifecycle.py:700-716 FVG state cleanup — BULGU-12: `with open()` + log.error
  - state_writer.py — BULGU-05: protection_health flat field'lardan türetildi, BULGU-19: cfg.WS_EVENT_NORMALIZATION_ENABLED

- **sweep_confirmed state sync fix (2026-08-03, commit 5c2fb1d):** When `on_sweep_confirmed()` invalidates a sweep (RSM reset to IDLE), `ss.sweep_confirmed` was staying True → display showed contradictory "SWEEP: DETECTED" + "FVG BULUNAMADI". Fix in `progress_rsm()` (signal_engine.py): after `on_sweep_confirmed()` returns, if RSM is IDLE, clear `ss.sweep_confirmed = False`. Two regression tests added: `test_sweep_invalidated_clears_sweep_confirmed` and `test_progress_rsm_keeps_sweep_confirmed_when_sweep_stays_valid`.
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

- **Continuation-confirm + is_placeable canlıya alındı (2026-08-07, commit `b9c2d53`):** trailing_manager `_fvg_close_confirmed` → `_fvg_confirm_mode` (retrace/continuation/invalidation; yön kontrolü: short `close<bottom`, long `close>top` lehine; aksi yön invalidation → None, karışmaz). Continuation SL: short `fvg.bottom + atr_buffer`, long `fvg.top - atr_buffer`. `_fvg_multihop`'a `current_price` parametresi + is_placeable (long `new_sl<price`, short `new_sl>price`) — stale candidate engeli. bot.py extractor `current_price=scoped_bars[-1].close` ile çağırıyor. Tests +169 satır (retrace/continuation/invalidation/stale) 55/55; pre-commit (ruff, vulture) temiz.
  - **Deploy:** local commit + push → sunucuda fast-forward pull `aac0e3e→b9c2d53` → restart. 3 katmanlı teyit: HEAD `b9c2d53` ✓, `_fvg_confirm_mode` grep ✓ (540/623), davranışsal ✓ (yeni run_id `paper-20260806-223127`, 28 sembol init, WS 56 stream, 8 pozisyon envanterde, ilk trailing taraması çalışıyor, LDOUSDT orphan STOP_MARKET temizlendi).
  - **Restart zorlukları (dokümante):** (a) system `python3` (3.14.4) `dotenv` içermiyor → bot `/root/sniper/venv/bin/python3` ile çalışmak zorunda; (b) `screen -dm` TTY'siz plink'te sessiz başarısız oluyor → `plink -t` + `TERM=xterm` ile çözüldü. Yeni screen `349790.bot` (PID 349791).
  - **Pozisyon:** 9→8 (downtime ~3 dk'da biri borsa SL/TP ile kapandı). ALGOUSDT-0 dokunulmadı: trailing_count=0, sl=0.09353/tp=0.08669, uPnL ~+19.3.
  - **Açık iz:** ENAUSDT 2026-08-06 18:00'de SEIUSDT fix'i (`aac0e3e`) deploy edilmiş olmasına rağmen aynı `SL/TP direction fail`'ı verdi — pre-entry SL-eps guard'ı ENA'ya uzanmıyor (tick/eps kalibrasyonu), izlenecek.
- **Trailing A/B/C replay altyapısı (2026-08-07):** `backtest-sniper/src/replay_trailing_v2.py` yazıldı: aynı entry üretimi üzerinde 3 mod (A retrace-only / B +continuation / C +ATR-chase fallback `SL=close ∓ ATR_TRAIL_MULT*ATR`), paralel ProcessPoolExecutor, `analyzer_v5.TRAIL_MODE` modül değişkeni (analyzer_v5.py'ye eklendi), per-trade eşleşme + özet tablo → `reports/trailing_replay_ab_c.md`. Doğrulama: ADA+SOL 2-coin koşusu (A=4769/B=8248/C=11973 trade; A→B eslesen +773 HOP +2519 USD; B→C +647 HOP +9209 USD). **Tam 30 coin koşusu kullanıcıda bekliyor** (modlar trade devir hızını değiştirdiği için toplam trade sayıları modlar arasında farklı — normal).

## 🔧 Pending / In Progress
- **D Modu canlıya deploy (kullanıcı onayı bekliyor):** Contabo bot (`b9c2d53` üzerine) pull + restart + 3 katmanlı teyit; ilk canlı ATR-chase fallback olayının gözlemlenmesi.
- **Implementation plan güncellenmesi (2026-08-01):** P0 fix'leri için planı güncelle — bare except remediation, state_writer fixes.
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
