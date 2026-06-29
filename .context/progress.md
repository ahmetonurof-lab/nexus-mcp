# progress.md

## Tamamlanan
- Break-even: `config.BREAK_EVEN_TRIGGER=0.5`, SL entry_price'e çekilir (trail_count=0 iken)
- `evaluate_break_even()` — `current` bar kullanır, `TrailResult` döner
- bot.py'de break-even→FVG trailing→exit sırası
- Orphan emir temizliği: `reconcile_orphan_orders()` her restartta Binance'teki tanınmayan STOP/TP emirlerini iptal eder
- Dashboard font boyutları %25 büyütüldü, muted text renkleri açıldı
- `.gitignore`: output/ altından 6 dosya (active_fvg.json, live_state.json, nexus_dashboard.html, trade_state.json, trades_history.jsonl) serbest, paper_trade.log ignore'da
- `.vscode/settings.json`: terminal font 11

## Devam Eden
- (yok)

## Blokaj
- (yok)
