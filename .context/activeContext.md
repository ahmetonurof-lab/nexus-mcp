# Active Context

## Current Work
- Playwright tamamen kaldırıldı, snapshot artık doğrudan HTML çıktısı üretiyor
- chart_template.html baştan tasarlandı: header + legend + trade badge UI
- `_find_bar` timestamp-aware hale getirildi (trade timestamp'ına en yakın mumu bulur)
- OHLC limit 200'e çıkarıldı, PAD 30 ile 60+ mum bar görünür

## Changes Made
- `sniper/src/snapshot/snapshot.py`:
  - Playwright, tempfile, `_render_png` kaldırıldı
  - `capture_snapshot()` imzası değişmedi (bot.py uyumlu)
  - `_find_bar(candles, price, near_ts)` — timestamp parametresi eklendi
  - OHLC limit default 200, PAD=30
  - `normalize_trade()` eklendi (trades_history.jsonl format desteği)
  - Payload'a pnl, sweepLevel, cbdr, trailingCount, isRetrade, sym eklendi
  - `_TEMPLATE_PATH` için `HTML_TEMPLATE_PATH` env override'ı
- `sniper/src/snapshot/chart_template.html`:
  - Lightweight Charts 4.2.0 tabanlı yeni UI
  - Header: sembol, side, exit reason, timestamp, PnL, trailing, sweep yönü
  - Legend panel: tüm seviyeler (Entry, Exit, SL, TP, CBDR, FVG, Sweep)
  - Trade badge: PnL durumu (win/loss)
  - CBDR/FVG/Sweep ayrı line series olarak çiziliyor
  - Entry/SL/TP `createPriceLine` ile gösteriliyor
  - Entry/exit marker'ları arrowUp/arrowDown+diamond
  - Crosshair aktif, grid koyu tema

## Verification
- BTCUSDT long trade (SL hit) başarıyla HTML çıktısı üretildi
- 61 mum bar görünür, tüm seviyeler legend'da listeleniyor

## Open Questions
- SL/TP çizgileri tüm chart boyunca çiziliyor (createPriceLine), istenirse 4-5 mum segmentine çevrilebilir
