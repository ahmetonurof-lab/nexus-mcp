# Progress

## Completed
- [x] `trades_history.jsonl` yazma eklendi (_exit_trade'de append)
- [x] `_load_history()` — bot restart'ta geçmişi yükler
- [x] `MAX_SL_DIST_MULT = 2.0` config'e eklendi (SL tavanı)
- [x] Hybrid SL buffer: `max(fvg_height × 0.10, min(fvg_height × 0.25, risk_pts × 0.5))`
- [x] `FVG_BUFFER_MIN_FACTOR = 0.10` aktif edildi (ölü config canlandı)

## Next Steps
- [ ] Backtest çalıştır (WR/PF değişimi bekleniyor)
