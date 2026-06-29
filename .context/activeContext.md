# activeContext.md — güncel durum

## Son Değişiklik
Break-even: `TrailingManager.evaluate_break_even()` — price risk_pts*0.5 hareket edince SL entry_price'e çekilir. FVG trailing'den önce çalışır. Orphan emir temizliği: `reconcile_orphan_orders()` eklendi.

## Değişen Dosyalar
- `sniper/src/bot.py`: `_save_fvg_state()` / `_load_fvg_state()` yardımcıları, `_try_entry()`'de FVG kaydı, recovery sonrası geri yükleme, trade çıkışında temizlik
- `sniper/src/state_writer.py`: `fvg_top`/`fvg_bottom` state_writer için `trade.get()` üzerinden okur
- `sniper/src/trading/console_reporter.py`: `display_active_position()` FVG değeri varsa gösterir, yoksa "ISLEMDE" fallback
- `sniper/src/models.py`: `ActiveTrade`'e `fvg_top`, `fvg_bottom`, `fvg_direction`, `fvg_bar_index` eklendi

## Aktif Kararlar
- FVG persistence: `active_fvg.json` ayrı dosya, trade açılırken yazılır, kapanırken silinir
- Recovery okuma: `recover_positions()` sonrası `_load_fvg_state()` ile trade'lere enjekte edilir
- Console: FVG verisi varsa `{direction} {top}-{bottom}`, yoksa "ISLEMDE"

## Bekleyen
- Bot restartı ile yeni trade'lerde FVG değerlerinin `output/active_fvg.json`'da göründüğünü doğrula
