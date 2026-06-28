# Progress

## Completed
- [x] Playwright, tempfile, `_render_png` snapshot.py'den kaldırıldı
- [x] `capture_snapshot()` HTML-only çıktıya dönüştürüldü (imza değişmedi)
- [x] `_find_bar(candles, price, near_ts)` timestamp-aware arama eklendi
- [x] OHLC limit 80→200, PAD 8→30 (61+ mum bar)
- [x] `normalize_trade()` — trades_history.jsonl format desteği
- [x] Payload'a pnl, sweepLevel, cbdr, trailingCount, isRetrade, sym eklendi
- [x] chart_template.html baştan yazıldı (Lightweight Charts + header/legend/badge)
- [x] CBDR/FVG/Sweep ayrı line series olarak görselleştirildi
- [x] Entry/SL/TP/Exit marker'ları ve price line'ları eklendi
- [x] BTCUSDT long trade (SL hit) örnek HTML çıktısı üretildi
- [x] `.venv`'den playwright pip paketi kaldırıldı

## Next Steps
- [ ] SL/TP çizgileri 4-5 mum segmentine çevrilecek (createPriceLine → addSeg)
- [ ] FVG bar'ına özel marker eklenebilir
- [ ] Git commit ve push
