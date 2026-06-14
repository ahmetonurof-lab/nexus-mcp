# Progress — NEXUS V3

## Çalışanlar ✅

| Bileşen | Durum | Not |
|----------|-------|-----|
| `models.py` | ✅ | Bar, FVG, CHoCH, SwingPoint dataclass'ları |
| `config.py` | ✅ | Tüm sabitler, sembol listesi, risk parametreleri, HTF_STRICT_FILTER=False, MISSED_FVG_ATR_MULT, POI_ATR_BUFFER, adaptive LTF knobs, ranking params |
| `pivot.py` | ✅ | Fraktal swing tespiti + SwingStateManager |
| `indicators.py` | ✅ | EMA, SMMA, ATR, ADX (Numba JIT) |
| `fvg.py` | ✅ | FVG tespiti, state yönetimi, retest, quality |
| `mss.py` | ✅ | CHoCH/MSS tespiti, SMC mikro-yapı veto |
| `analyzer.py` | ✅ | HTF bias → sweep (H1+15m fallback) → MSS → FVG → LTF zinciri + impulse_origin + _resample_to_2h + swing_size bar_index fix + _interval_overlap_ratio + _cluster_fvgs + sweep wick+close fix + consumed_levels round(5) |
| `scoring.py` | ✅ | FVG quality + CHoCH + rejim + konfluens skorlama + _clip01 helper |
| `event_router.py` | ✅ | Publisher → StateMachine yönlendirici (zero logic, single pipeline) |
| `state_machine.py` | ✅ | 10-state machine + pre-check layer + FVG Missed Flow + 3 Patch + ATR parametre geçişi + is_active FVG filtresi + wait_confirm_since_ts + adaptive mid-band READY_TO_ENTER |
| `exchange.py` | ✅ | Binance REST istemcisi + **117 characterization test** (P1-0C partial, coverage ~%13→%55) |
| `trader.py` | ✅ | MARKET + STOP_MARKET + SL/TP algo emir + pozisyon yönetimi + protection_missing deferred |
| `websocket.py` | ✅ | Multi-symbol × multi-TF WS hub |
| `main.py` | ✅ | LiveTradingBot orkestrasyonu + export_ohlc_15m + export_ohlc_1m + 1m callback + state_logger.write_snapshot + _RateLimiter + strategy audit trail + TimedRotatingFileHandler + output/trading logger path + 15m blok ayrıştırması + time-box partial entry + STOP_MARKET entry |
| `state_logger.py` | ✅ | 15m kapanışında state snapshot CSV (10 gün rotasyon, thread-safe, fvg_tf alanı dahil) |
| `monitor.py` | ✅ | Runtime sayaçları + health endpoint |
| `performance.py` | ✅ | Trade geçmişi + leaderboard + STRATEGY_FIELDS yeniden yapılanması |
| `risk_manager.py` | ✅ | 4H swing SL + 1H likidite TP + lot + kademeli stop |
| `volume_profile.py` | ✅ | Session bazlı VP hesaplama; HVN/LVN skor adjuster + POC TP mıknatısı |
| `weekly_range_spy.py` | ✅ | Haftalık HH/LL sweep + CISD tespiti (log-only, trade açmaz) |
| `test_pivot.py` | ✅ | 22 test — swing highs/lows, SwingStateManager |
| `test_risk_manager.py` | ✅ | 40+ test — SL/TP/lot/build_trade |
| `test_state_machine.py` | ✅ | 29 test — state geçişleri, pre-check, retrace, flag gate |
| `test_analyzer.py` | ✅ | 49 test — HTF bias, sweep (H1+2H), MSS, FVG, retrace, LTF, analyze flow |
| `test_sync_positions.py` | ✅ | **50 test** — `_sync_positions` characterization (P1-0B): time guard, PM guard, full protection, infaz, missing protection, closed positions, multi-symbol, helpers. Coverage: main.py 33% |
| `test_main_coverage.py` | ✅ | **24 test** — main.py coverage phase 2: `_flush_state`, `_load_state`, `_clear_state`, `_sync_balance`, `_is_15m_closed`, safe wrappers, `_get_risk_manager`, `_on_1m_close`. Coverage: **main.py 47%** (hedef 40% aşıldı) |
| `test_fvg_missed_flow.py` | ✅ | **44 test** — Case C patikası (P1-0C): `_check_missed_fvg`, `check_poi_retrace`, tam zincir LONG+SHORT, `fvg_missed` flag set/reset, `_evaluate` Case C gate, WAIT_CONFIRM breach → WAIT_NEW_FVG, PenetrationEngine edge cases, MISSED_FVG/WAIT_POI_CONFIRM state koruma, expiry. Coverage: **state_machine.py 87%** (82%→87%) |
| `test_exchange.py` | ✅ | **117 test** — exchange.py characterization (P1-0C): `_round_to_tick`/`_round_step`, `__init__`, `_ep` PM mapping, `_sign` HMAC, `_request` retry (429/5xx/URLError/fatal codes/4xx/no-retry), precision helpers (tick/step/min_qty/apply), `get_klines` parsing, `get_open_orders`/`get_algo_orders`/`get_all_open_orders`, `create_order` (MARKET/LIMIT/STOP + PM skip + demo fallback), `create_algo_order` (STOP/TP + PM skip + demo fallback), `create_stop_order_standard`, `query_order`, `cancel_order` (normal/algo/fallback), `get_positions`/`get_account`, `set_margin_mode`/`set_leverage`, `new_listen_key`/`renew_listen_key`/`delete_listen_key`, `_load_exchange_info` (cache/force/expire) |

## Kapsamlı Sistem Analizi | 🟢 Tamamlandı | jCodemunch ile complexity/hotspot/dead code/dependency analizi → 7.2/10 notu |

## Kalan İşler 🔧

| Görev | Öncelik | Açıklama |
|-------|---------|----------|
| ~~main.py coverage 40%+~~ | ~~🔴 Yüksek~~ | ~~✅ **47%** — `_flush_state`/`_load_state`/`_clear_state`/`_sync_balance`/`_is_15m_closed`/`_on_1m_close` kapsandı~~ |
| ~~FVG Missed Flow canlı/backtest doğrulaması~~ | ~~🔴 Yüksek~~ | ~~✅ **44 test** — Case C patikası (MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER) characterization. state_machine.py 82%→87%~~ |
| ~~exchange.py/scoring.py coverage~~ | ~~🔴 Yüksek~~ | ~~✅ **exchange.py 117 test** — `_request` retry, precision, orders, cancel, listen key. Sıradaki: **scoring.py** (%0) ve **volume_profile.py** (%0)~~ |
| ~~scoring.py coverage~~ | ~~🔴 Yüksek~~ | ~~✅ **53 test, %91 coverage** — build_scoring_context, detect_market_regime, FVG component scores, CHoCH score, confluence, entry/exit zones, RR ratio, evaluate_trade_signal, classify_strength, evaluate_all_signals, generate_market_summary. fvg.py'ye 7 yeni fonksiyon eklendi~~ |
| STOP_MARKET entry doğrulaması | 🔴 Yüksek | STOP_MARKET emirlerinin doğru tetikleme ve SL/TP yerleşimi |
| `check_retrace()` CE eşiğini H1 FVG boyutuna göre dinamik yap | 🟡 Orta | H1 FVG更大 olduğu için eşik farklı olmalı |
| `DEFAULT_ATR` / `ATR_MAP` config'e ekle | 🟡 Orta | `_get_atr()` şu anda fallback olarak None döner; canlıda exchange.atr() ile beslenebilir |
| Integration test | 🟡 Orta | Tam zincir: WebSocket → analyzer → state → trade (Case A + Case C) |
| Grafana/Prometheus bağlantısı | 🟢 Düşük | `monitor.py` health endpoint'i |
| Backtesting framework | 🟢 Düşük | Geçmiş veri ile strateji validasyonu |

## Mevcut Durum

- **State**: HTF FVG (H1+15m fallback) + state_logger fvg_tf + output/trading log path
- **Test coverage**: Pivot ✅ (22), Risk Manager ✅ (40+), State Machine ✅ (29), Analyzer ✅ (49), **_sync_positions ✅ (50)**, **main_coverage ✅ (24)**, **fvg_missed_flow ✅ (44)**, **exchange ✅ (117)** — toplam **407 test** pass (state_machine.py coverage **87%**, main.py **47%**, exchange.py **%55**, overall ~%52)
- **Son değişiklik (2026-06-14)**: exchange.py characterization (P1-0C) — 117 test: `_request` retry logic (429/5xx/URLError/fatal codes/4xx), precision helpers, kline parsing, order creation/algo/standard + PM skip + demo fallback, cancel order normal/algo/fallback, listen key CRUD, exchange info cache. Toplam test: 290 → **407** (+117).
- **Son değişiklik (2026-06-13)**: Fix-1 (sweep wick+close), Fix-2 (analyze sırası: sweep→MSS→FVG), Fix-3 (fvg_since sweep sonrası MSS filtresi), Fix-4 (consumed_levels float precision), 2H→15m fallback, reset_symbol_cache(), FVG timestamp
- **Önceki değişiklik (2026-06-13)**: `_check_invalidation` — sadece ARMED/WAIT_RETRACE'de MSS invalidasyonu (+buffer); `_handle_mss` — sweep_tf bazlı MAX_SETUP_WAIT seçimi (15m→8h, diğer→16h)
- **Önceki değişiklik (2026-06-12)**: jcodemunch index güncellendi (config.py, analyzer.py, main.py, scoring.py, state_machine.py, trader.py — 250 sembol). Memory bank dosyaları güncellendi.
- **Önceki değişiklik (2026-06-12)**: `.bak` yedek dosyaları temizlendi (`sonnet/src/scoring.py.bak`, `sonnet/src/analyzer.py.bak`).
- **Önceki değişiklik (2026-06-11 23:54)**: Adaptive LTF gating, time-box partial entry, STOP-MARKET entry option — bkz. activeContext.md
- **Çalışan semboller**: 22 Binance Futures perpetual
- **Aktif trade**: Yok (test aşaması)

## Deepseek v4 Pro Counter-Analysis (2026-06-14)

**Kaynak:** Kullanıcı tarafından sağlanan sistem analizi raporu üzerinden Deepseek v4 Pro tarafından manuel semantic code review.

### 5 Semantic Bug (Static Analysis'in Kaçırdığı)

| # | Bulgu | Dosya | Risk |
|---|-------|-------|------|
| 1 | `bars_m1` Double Fetch — veri tutarsızlığı | `main.py::_on_1m_close` | 🔴 Fonksiyon içinde 2. kez `bars_m1 = self.hub.get_bars(...)` override — ilk yarı eski, ikinci yarı yeni bar |
| 2 | `_update_sl_order` Dangling Reference — NameError | `main.py::_update_sl_order` | 🔴 `old_sl` try içinde tanımlı, except'te referans → network timeout → NameError → handler crash |
| 3 | `_startup_cleanup` — Invariant Violation | `main.py::_startup_cleanup` | 🔴 `_load_existing_positions` boş dönerse → `active_trades={}` → cleanup tüm open order'ları siler |
| 4 | `trade_locks` — Asyncio-Only Safety | `main.py::get_lock` | 🟡 `asyncio.Lock` dict access thread-safe değil. `run_in_executor` ile threading riski |
| 5 | `_fetch_binance_signed_post` — No Retry | `main.py` | 🟡 SL güncelleme POST endpoint'inde retry yok. %1 fail = günde 1 kayıp SL |

### Ek Tespitler

| # | Bulgu | Detay |
|---|-------|-------|
| 6 | `_repair_protection` — Implicit State Mutation | Yeni order_id'leri `active_trades` dict'ine yazılmaz |
| 7 | `_manage_open_trades` — Missing Await | `self._update_sl_order(...)` await edilmemiş olabilir |
| 8 | `active_trades` — No Type Safety | TypedDict/dataclass yok. 4 farklı yerde dict oluşturuluyor |
| 9 | `_sync_positions` → `_clear_state` desync | Trade kapanınca analyzer cache temizlenir → aynı sembolde yeni setup varsa double emission riski |

### Revize Sistem Notu: **6.5/10** (7.2'den düşürüldü)

**Düşürme sebepleri:** Veri tutarsızlığı, exception safety problemleri, critical path retry eksikliği, state mutation desync.
**Hâlâ 6.5:** Mimari temiz, problemler lokalize (3-4 fonksiyon), fix'ler straightforward.

### P0 Bug Fix Sıralaması (En Kolay → En Yüksek Etki)

| Sıra | Görev | Süre |
|------|-------|------|
| P0-1 | `_update_sl_order` dangling ref fix — `old_sl = None` try öncesi | 5 dk |
| P0-2 | `_on_1m_close` bars_m1 rename — `bars_m1_latest = self.hub.get_bars(...)` | 5 dk |
| P0-3 | `_startup_cleanup` guard — `if not self.active_trades and real_positions:` → RuntimeError | 15 dk |
| P0-4 | Fire-and-forget exception handler — `_safe_sync_positions` wrapper | 30 dk |
| P0-5 | `_sync_positions` desync fix — `_clear_state` çağrısını düzelt | 10 dk |

---

## Bilinen Sorunlar 🐛

| Sorun | Tarih | Durum | Çözüm |
|-------|------|-------|-------|
| V-shape hareketlerde sonsuz WAIT_RETRACE zombisi | 2026-06-08 | ✅ Çözüldü | FVG Missed Flow: _check_missed_fvg + check_poi_retrace + _evaluate Case C path |
| Semboller WAIT_RETRACE'te takılı: sweep=False, mss_confirmed=True, fvg_upper=None | 2026-06-07 | ✅ Çözüldü | Fix 1: MSS upstream guard; Fix 2: reset_symbol_cache(); Fix 3+3b: lifecycle coupling |
| `_emitted_fvg_ids` / `_seen_mss` state reset'te temizlenmiyordu | 2026-06-07 | ✅ Çözüldü | reset_symbol_cache() eklendi, _clear_state ve state-diff hook'a bağlandı |
| `_mss_state` (SwingStateManager) reset'te temizlenmiyordu | 2026-06-07 | ✅ Çözüldü | reset_symbol_cache() içinde self._mss_state = SwingStateManager() |
| AttributeError: RiskManager tier_buffer | 2026-06-06 | ✅ Çözüldü | _tier(symbol) ile tier config lookup |
| calculate_tp_htf çağrı imzası uyumsuzluğu | 2026-06-06 | ✅ Çözüldü | 6 parametreli hatalı çağrı 4 parametreye indirildi |
| Pylance reportMissingImports (models, pivot) | 2026-06-06 | ✅ Çözüldü | .vscode/settings.json → python.analysis.extraPaths |
| `_sweep_on_bars` pivot kalite filtresinde `sl.index` / `sh.index` AttributeError | 2026-06-11 | ✅ Çözüldü | `sl.index` → `sl.bar_index`, `sh.index` → `sh.bar_index` (SwingPoint'te `bar_index` var, `index` yok) |
| `_handle_sweep` tf filtresi dar (sadece 15m), 1H/2H sweep kaçırılıyor | 2026-06-11 | ✅ Çözüldü | `["15m"]` → `("1H", "2H", "15m")`, expires_at silindi, log zenginleştirildi |
| `_handle_sweep`'te expires_at 24h hardcode, MSS'de expires_at hiç atanmıyor | 2026-06-11 | ✅ Çözüldü | Sweep'ten expires_at kaldırıldı, MSS'e taşındı (MAX_SETUP_WAIT_HOURS=8.0 ile) |
| H1 FVG'ler rastgele sırada emit ediliyor, önce büyük gap değerlendirilmiyor | 2026-06-11 | ✅ Çözüldü | `sorted(fvgs, key=lambda f: abs(f.top - f.bottom), reverse=True)` eklendi |
| Türkçe karakter encoding sorunu (config.py, analyzer.py, main.py, scoring.py) | 2026-06-12 | ✅ Çözüldü | 4 dosya UTF-8 encoding ile yeniden yazıldı, commit/push yapıldı |

## Proje Kararlarının Evrimi

1. **SL stratejisi değişimi**: Eski FVG tabanlı SL → 4H swing high/low + tier buffer
2. **TP stratejisi değişimi**: Eski default RR çarpanı → 1H BSL/SSL likidite seviyesi
3. **SL mesafesi kısıtlaması kaldırıldı**: build_trade artık SL uzak diye trade reddetmez
4. **Memory Bank eklendi**: 6 çekirdek dosya (2026-06-06)
5. **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir (2026-06-06)
6. **Unit test altyapısı**: tests/ + conftest.py + 3 test dosyası — 92 test pass (2026-06-06)
7. **MSS = anchored event**: since_bar_index=None → MSS taraması yapılmaz (2026-06-07)
8. **State machine = truth, analyzer cache = derived ephemeral state**: reset_symbol_cache() IDLE glue'su (2026-06-07)
9. **FVG Missed Flow (Case C)**: Fiyat FVG'yi hiç görmeden kaçarsa MISSED_FVG state'i (2026-06-08)
10. **MISSED_FVG_ATR_MULT isim uyumu**: config.py + state_machine.py aynı sabit ismini kullanıyor (2026-06-08)
11. **STATE-DEBUG fvg=**: Tek dinamik alan — FVG durumunu tek satırda gösterir (2026-06-08)
12. **set_state() log düzeltmesi**: "manually forced" → "State geçişi: X → Y" formatı (2026-06-09)
13. **ATR parametre geçişi**: ATR artık main.py'den compute_atr_point() ile hesaplanıp atr= parametresi olarak geçiriliyor (2026-06-09)
14. **OHLC export yeniden yapılanması**: export_ohlc() (5m) kaldırıldı → export_ohlc_15m() + export_ohlc_1m() eklendi. 1m callback run()'da register edildi (2026-06-10)
15. **state_logger.py**: 15m kapanışında state snapshot CSV'si — output/summary/summary_YYYY-MM-DD.csv, 10 gün rotasyon, thread-safe (2026-06-10)
16. **HTF FVG Fix**: 15m FVG kaldırıldı → H1 + 2H fallback. `_resample_to_2h()` sentetik 2H bar üretimi. `fvg_tf` state_logger'a eklendi (2026-06-10)
17. **Logging path**: `live_trading.log` → `output/trading/live_trading.log`. `os.makedirs` ile klasör oluşturulur (2026-06-10)
18. **is_active FVG filtresi**: WAIT_NEW_FVG state'inde sadece `is_active=True` olan FVG'ler kabul edilir. `is_active=False` FVG'ler reddedilir — daha önce delinmiş/pasif FVG'nin tekrar tetiklemesi engellenir (2026-06-10)
19. **Sweep tf genişletme + expires_at taşıma**: `_handle_sweep`'te tf filtresi 1H/2H/15m kabul eder oldu (2026-06-11). expires_at sweep'ten kaldırılıp `_handle_mss`'e taşındı. `MAX_SETUP_WAIT_HOURS=8.0` config'e eklendi.
20. **FVG boyut sıralaması**: `analyzer.py`'da FVG listesi büyükten küçüğe sıralanır — state machine önce büyük gap'i değerlendirir (2026-06-11)
21. **Adaptive LTF gating + time-box + STOP-MARKET**: `_evaluate()`'de adaptive mid-band READY_TO_ENTER (pen ∈ [0.30, 0.70]), WAIT_CONFIRM time-box partial entry (3 dk), STOP_MARKET entry order tipi (2026-06-11)
22. **15m blok ayrıştırması**: 15m kapanışında sadece export + snapshot; her 1m'de state check + emir kapısı (2026-06-11)
23. **jcodemunch index güncellendi**: config.py, analyzer.py, main.py, scoring.py, state_machine.py, trader.py — 250 sembol (2026-06-12)
24. **Memory bank güncellendi**: systemPatterns.md, techContext.md, progress.md, activeContext.md — güncel kod yapısıyla eşleştirildi (2026-06-12)
25. **jCodeMunch VS Code Extension oluşturuldu**: `vscode-extension/` — auto-reindex on save + risk gutter. GitHub'da `jgravelle/jcodemunch-mcp` reposunda yayınlanacak, `nexus-mcp`'de sadece yerel (gitignore). Cline/Continue kuralları güncellendi (2026-06-12)
26. **Cline rules birleştirildi**: 3 ayrı dosya (`globalrules.md`, `conditional.md`, `Jcodemunch.md`) → tek `.clinerules/Jcodemunch.md` — strict context management + path scoping + jcodemunch MCP + VS Code extension (2026-06-12)
27. **STATE-DEBUG fix**: `if events:` içinden dışarı taşındı — her 1m callback'te basılır. Gereksiz `fmt_bool` satırları temizlendi. Commit `18d8d18` (2026-06-12)
28. **Binance 429 rate limit fix (klines)**: `exchange.py` → `get_klines()`'a `max_retries=2` parametresi. `main.py` → global `rate_limiter` instance, `DailyDataCache._fetch()` ve `_prefill_one()` artık `rate_limiter.acquire()` + `max_retries=2` kullanıyor. Signed + unsigned istekler aynı token bucket'tan besleniyor. (2026-06-13)
29. **`_check_invalidation` narrowing + sweep_tf-based expiry**: MSS invalidation sadece ARMED/WAIT_RETRACE'de çalışır, WAIT_CONFIRM+ pas geçer. `mss_level * 0.001` buffer eklendi. `_handle_mss`'de sweep_tf'e göre MAX_SETUP_WAIT seçimi (15m→8h, diğer→16h). (2026-06-13)
29. **`.clinerules/Jcodemunch.md` → `.clinerules/readmefirst.md`**: Dosya adı değişikliği + "Minimal yanıt" kuralı eklendi. (2026-06-13)

## ✅ P0 Bug Fixes — V2 (2026-06-14) — Refined Fixes

**Status:** 5/5 semantic bugs fixed — 222 tests passing (208 existing + 14 new P0 tests)

**Previous fix (V1):** Commits `75df245`, `559287e`, `3ec8da3`, `54d4411`, `59af55a`
**Current fix (V2):** Uncommitted refinements

| # | Bug | V1 Fix | V2 Refinement | Test File |
|---|-----|--------|---------------|-----------|
| **P0-1** | `_update_sl_order` old_id NameError | `old_sl = None` before try | Added `old_id = None` init in except handler before `if old_sl:` block — previous fix didn't fix the actual NameError (`old_id` was still undefined when `old_sl is None`) | `test_p0_bugs.py::TestP0_1_UpdateSlOrderDanglingRef` |
| **P0-2** | `_on_1m_close` double fetch | Renamed second fetch to `bars_m1_latest` | Changed to `bars_m1_latest = bars_m1` (use parameter, no re-fetch) — V1 only renamed, didn't eliminate the duplicate source | `test_p0_bugs.py::TestP0_2_On1mCloseDoubleFetch` |
| **P0-3** | `_startup_cleanup` invariant | 3 guards for edge cases | Added **4th guard**: `if not symbols_with_position and not self.active_trades:` → skip cleanup when both empty | `test_p0_bugs.py::TestP0_3_StartupCleanupGuard` |
| **P0-4** | Missing exception handler | `_safe_sync_positions` wrapper only | Added `_safe_manage_open_trades` wrapper — `_manage_open_trades` crash artık `_on_1m_close`'un geri kalanını bloke etmez | `test_p0_bugs.py::TestP0_4_SafeManageOpenTrades` |
| **P0-5** | `_clear_state` → cache desync | `if removed is not None` guard in `_clear_state` | Added `_state_before != SetupState.IDLE` guard to `_on_1m_close`'s cache reset — `_clear_state` sonrası fresh IDLE durumunda redundant reset/double emission engellenir | `test_p0_bugs.py::TestP0_5_ClearStateDesync` |

**System score:** 6.5 → **7.0** ✅

---

## ✅ Test Fixes — COMPLETED (2026-06-14)

**Status:** 149 passed / 0 failed ✅

**Commit:** `ba806df` → `e71a212` (after rebase + push)

| # | Test Issue | Root Cause | Fix |
|---|------------|------------|-----|
| 1-9 | `TestDetectSweepH1` TypeError | `_detect_sweep_h1` signature added `bars_15m` param | Added `bars_15m=[]` to all 9 test calls |
| 10 | `test_retrace_ce_only_no_body_stays` AssertionError | `PenetrationEngine.get_penetration` returned non-zero for price outside FVG | Added clamping: LONG `price <= fvg_lower` → 0, SHORT `price >= fvg_upper` → 0 |

**Bonus fix:** `_sweep_on_bars` empty bars guard (IndexError on `bars[-1]`)

**System score:** 7.0 (unchanged — test fixes, not code bugs)

---

## 📊 Coverage Analysis — CRITICAL FINDINGS (2026-06-14)

**Overall coverage:** 28% (4869 statements, 3514 missing)

### ✅ Well-Tested Modules
| Module | Coverage | Statements | Status |
|--------|----------|------------|--------|
| `pivot.py` | 97% | 101 | 🟢 Excellent |
| `risk_manager.py` | 93% | 201 | 🟢 Excellent |
| `state_machine.py` | 82% | 403 | 🟢 Good |
| `analyzer.py` | 81% | 358 | 🟢 Good |
| `models.py` | 74% | 158 | 🟡 Good |

### ⚠️ Medium Coverage
| Module | Coverage | Statements | Issue |
|--------|----------|------------|-------|
| `mss.py` | 63% | 201 | Bullish/bearish paths partially tested |
| `fvg.py` | 47% | 131 | Edge case detection untested |
| `indicators.py` | 44% | 114 | Advanced logic untested |

### 🚨 ZERO COVERAGE — CRITICAL PRODUCTION FILES

| File | Statements | Complexity | Risk | Impact |
|------|-----------|-----------|------|--------|
| **`main.py`** | 1224 | cc=96 | **10/10** | Entry point, runs every second, 0% tested |
| **`trader.py`** | 365 | cc=69 | **9/10** | Order execution, all validation untested |
| **`exchange.py`** | 393 | cc=51 | **6/10** | Binance API, retry logic ~%55 tested ✅ |
| **`scoring.py`** | 303 | cc=55 | **7/10** | Signal evaluation untested |
| `websocket.py` | 302 | — | 6/10 | Real-time stream untested |
| `performance.py` | 157 | — | 3/10 | Metrics untested |
| `monitor.py` | 79 | — | 2/10 | Health checks untested |

**System score:** 7.0 → **6.8** ⚠️ (downgraded due to critical path coverage gaps)

---

## 🎯 REVISED P1 Plan — Test Coverage Priority (2026-06-14)

### NEW: P1-0 Test Coverage (Critical Path Protection)

**Goal:** Protect production-critical paths with test coverage

#### P1-0A: `trader.py::send_order` Test Suite (1 day)
- **Target:** trader.py: 0% → 60%
- **Tests:** Validation guards, order type logic, network errors, mock Binance API

#### P1-0B: `main.py::_sync_positions` Integration Test (1 day)
- **Target:** main.py: 0% → 40%
- **Tests:** Duplicate position, missing protection, closed position cleanup

#### P1-0C: `exchange.py` Unit Test ✅ COMPLETED (2026-06-14)
- **Target:** exchange.py: ~%13 → ~%55 ✅ (hedef %30 aşıldı)
- **Tests:** 117 characterization — retry logic, precision, orders, cancel, listen key

### Updated P1 Timeline

| Day | Task | Coverage Target |
|-----|------|----------------|
| 1-2 | P1-0A (send_order tests) | trader.py: 0% → 60% |
| 3-4 | P1-0B (_sync_positions integration) | main.py: 0% → 40% |
| 5 | ~~P1-0C (exchange unit tests)~~ | ~~exchange.py: 0% → 30%~~ → **%55 ✅ DONE** |
| 6 | P1-2 (TypedDict) | Type safety |
| 7 | P1-3 (Custom Exception) + P1-4 (POST retry) | Error handling |

**1 week target:**
- Coverage: 28% → **45%**
- System score: 6.8 → **7.5**

### 🟡 P1 — Type Safety & Error Handling (Days 6-7)

| Task | Description |
|------|-------------|
| P1-2: TypedDict | `active_trades` type safety, prevent typo bugs |
| P1-3: Custom Exceptions | RuntimeError → TradingError/ProtectionError taxonomy |
| P1-4: POST retry | `_fetch_binance_signed_post` retry + backoff |
| P1-5: State sync | `_repair_protection` → write new order_id to `active_trades` |

### 🟢 P2 — Refactor (Week 2)

| Task | Target |
|------|--------|
| `_sync_positions` decomposition (3 functions) | cc=96 → <30 |
| `detect_mss` DRY fix (bullish/bearish unify) | cc=63 → <35 |
| `_on_1m_close` → partial entry separate function | cc=70 → <25 |
| `analyze` → FVG emit helper | cc=46 → <25 |
