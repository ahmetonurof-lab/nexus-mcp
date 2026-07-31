# nexus-mcp — Progress

## ✅ Done
- **Canlı trailing konsept düzeltmesi (2026-07-31):**
  - `sniper/src/bot.py`: `_build_fvg_scan_trail_extractor` — post-entry pencerede her 15m bar'da taze FVG taraması, `TrailingManager._fvg_multihop` çağırır.
  - `sniper/src/trading/trailing_manager.py`:
    - `TrailLevel.sl_buffered` bayrağı (double-buffer önlemi).
    - `TrailScanResult` dataclass + `_fvg_multihop` static helper (backtest analyzer_v5 trailing adımlarının birebir kopyası: detect_fvgs lookback=min(50), fvg_close_confirmed, ATR×ATR_TRAIL_MULT buffer, TRAIL_MIN_MOVE_MULT min-move, çoklu-hop, TP delta-shift).
    - `evaluate_trail` → `_fvg_multihop` wrapper'ı (geriye dönük uyumlu, test'ler aynen geçer).
  - Safety katmanı korundu: `is_placeable` + fingerprint dedup + `ImmediateTriggerError` (orchestrate_trail değişmedi).
  - Min-move bazı `abs(initial_sl - entry_price)` yapıldı (backtest `rpt2` ile birebir).

## 🔧 Pending / In Progress
- **Backtest'e 1m trailing/exit ekleme:** kullanıcı "1m trailing exit mutlaka backteste eklenmeli" dedi — henüz başlanmadı.
- **is_fvg_valid değerlendirmesi:** canlıda aktif (bot.py:451, GLOBAL_FVG_EXPIRY_BARS=45); backtest'te eksik. Kullanıcı eğilimi: canlıdan kaldırma.
- **Parite farkları (açık):**
  - E5: close-inside-FVG onayı canlıda devre dışı (retrace_state.py:210-215, backtest karşılaştırması için "geçici").
  - E8: Session filtresi canlı global (LONDON 2-13, NEWYORK 13-22, CBDR 22-2) vs backtest coin-bazlı (REAL_CBDR 19-1, ASIA_RANGE 1-5, DEFAULT 22-2).
  - E13-E15: DD devre kesici (trip 15/reset 10), dinamik equity, qty cap'leri backtest'te yok.
  - E18: Entry fiyatı canlı trigger bar CLOSE, backtest next bar OPEN (bilinçli fark).
  - T6-T8: tick normalizasyon, placeability, fingerprint canlıya özgü (kullanıcı onayı: gerekli exchange-safety katmanı).

## ✅ Doğrulananlar (2026-07-31)
- Canlı trailing neden çalışmıyordu: `bot.py:970` entry sonrası `rsm.reset()` → `trigger_fvg=None`; trade açıkken `progress_rsm` çağrılmıyor; extractor `rsm.trigger_fvg` okuyordu → hep None → `compute_trail_candidate` hiç candidate üretmiyordu.
- `MAX_SL_DIST_MULT` canlıdan kaldırılmış (commit def7eca); config.py:558'de ölü duruyor.
- `is_high_quality_fvg` canlıdan kaldırılmış (commit aa08ef8); tek kaynak `FVG_SIZE_MAP`.
- Backtest ile yeni canlı trailing artık aynı mantıkta (level kaynağı, buffer, çoklu-hop, delta-shift TP).
