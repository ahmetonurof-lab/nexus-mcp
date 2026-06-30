# progress.md

## Tamamlanan
- Break-even (1R): `evaluate_break_even()` — fiyat `risk_pts * 1.0` lehine gidince SL=entry±spread, TP'ye dokunmaz, sadece `trail_count=0` iken ateşlenir
- Trailing ATR buffer: eski sabit buffer → `atr_val * ATR_TRAIL_MULT` (0.25), her FVG'de yeniden hesaplanır
- Emniyet kilitleri: `MIN_STOP_DIST_PCT=0.006` (min SL mesafesi), `MAX_MARGIN_PCT=0.20` (max %20 marjin), `SAFETY_MARGIN` kaldırıldı
- FVG persistence: `ActiveTrade`'e `fvg_top/fvg_bottom/fvg_direction/fvg_bar_index`, `active_fvg.json`'a yazılır, recovery'de geri yüklenir
- Orphan emir temizliği: `reconcile_orphan_orders()` periyodik (her 5. 1m bar'da) + startup
- Dashboard font sizes %25 büyütüldü, muted text renkleri açıldı (`.v-wh: #e0e0e0`, `.v-mt: #888`)
- chart_template.html: trailing step'ler `addLineSeries` → canvas overlay'e taşındı (LWC 4.2 zoom sorunu çözüldü)
- `.gitignore`: `output/*` + 6 exception, `paper_trade.log` ignore'da
- AGENTS.md: jcodemunch açıklaması navigasyon aracı olarak düzeltildi
- **cleanup_on_exit güvenlik fix**: `_exit_trade()` içinde `cleanup_on_exit` öncesi `rest.get_positions()` ile Binance'te pozisyonun gerçekten kapalı olduğu doğrulanır. Açık kalırsa reduceOnly market kapatma dener, başarısızsa tüm cleanup atlanır (SL/TP korunur, state kapanmaz)

## Next Steps
1. Bot restart + orphan emirlerin `[ORPHAN]` log'unda temizlendiğini doğrula
2. Yeni trade açıldığında break-even (1R) + trailing (ATR buffer) çalışmasını gözlemle
3. Dashboard'da `.v-wh` (`#e0e0e0`) ve muted text (`#888`) renklerinin okunabilirliğini kontrol et

## Blokaj
- (yok)
