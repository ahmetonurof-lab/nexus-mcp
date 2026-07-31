# nexus-mcp — Active Context

## Current State
2026-07-31: Canlı (sniper) trailing artık backtest (analyzer_v5) konseptiyle çalışıyor. Canlı trailing'in hiç çalışmadığı tespit edilmişti (rsm.trigger_fvg tabanlı extractor, entry sonrası rsm.reset() → trigger_fvg hep None). Kullanıcının onayladığı konsept ile taze FVG taraması + fvg_close_confirmed + ATR buffer + çoklu-hop'a geçildi.

## Recently Completed
- **Trailing konsept düzeltmesi (2026-07-31):** `sniper/src/bot.py` — `_build_fvg_scoped_trail_extractor` (rsm.trigger_fvg tabanlı, hiç tetiklenmiyordu) → `_build_fvg_scan_trail_extractor` (backtest ile aynı: post-entry pencerede her 15m bar'da detect_fvgs + fvg_close_confirmed + ATR buffer + TRAIL_MIN_MOVE_MULT çoklu-hop). SL seviyesi `sl_buffered=True` ile donuyor.
- **compute_trail_candidate double-buffer fix:** `sniper/src/trading/trailing_manager.py` — `TrailLevel.sl_buffered` bayrağı eklendi; `sl_buffered=True` iken tick×2 buffer uygulanmıyor (buffer = ATR×ATR_TRAIL_MULT=0.25).
- **`evaluate_trail` refactor:** `_fvg_multihop` static helper'ına çekildi (backtest adımlarının birebir kopyası). `evaluate_trail` ince wrapper, geriye dönük uyumlu. `last_bar_index` fingerprint için döndürülüyor.
- **Kullanıcı konsept kararları:** Seviye kaynağı = taze FVG taraması (rsm.trigger_fvg değil); Buffer = ATR×0.25 (tick×2 değil); TP = delta-shift (RR yeniden hesap yok); Adım = çoklu-hop; is_placeable + fingerprint dedup + ImmediateTriggerError katmanı AYNEN kalır (exchange-safety).

## Next Actions
1. Backtest'e 1m trailing/exit akışı eklenmesi (kullanıcı şart koşuyor) — henüz başlanmadı.
2. is_fvg_valid canlıdan kaldırılması değerlendirmesi (kullanıcı: "FVG invalid olmadıysa/dokunulmadıysa hâlâ geçerli kalmalı") — onay bekliyor.
3. Kalan parite farkları: session saatleri (global vs coin-bazlı), DD circuit breaker / dinamik equity / qty cap'leri backtest'te yok, E18 entry fiyatı (bilinçli fark).

## Notlar
- Canlı trailing artık çalışıyor: compute_trail_candidate her 1m close'ta aynı 15m pencereyi tarar; fingerprint dedup tekrar uygulamayı engeller; yeni 15m bar kapanınca yeni FVG hop'u tetiklenir.
- `reports/backtest_canli_farklari_31_07_2026.md` — entry (E1-E19) / trailing (T1-T10) parite tablosu.
- Test durumu: test_trailing_manager 25 geçiyor, 17 önceden mevcut check_exit imza hatası (değişiklikle ilgisiz). Tam suite baseline ile birebir aynı (74 failed / 700 passed).
