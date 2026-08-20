# Active Context

## Son İşlem — Phase 3: Control Experiment Tamamlandı
- BASELINE vs RETRACE counterfactual deney 360 trade üzerinde çalıştırıldı
- Retrace definition: FVG first touch → penetration → favorable displacement → entry
- Retrace filtresi 226 trade'i (%62.8) filtreledi — NET DESTRUCTIVE sonuçlandı

## Phase 3 Sonuçları
| | BASELINE | RETRACE |
|---|---|---|
| Trades | 360 | 134 |
| Win Rate | 48.3% | 44.0% |
| PF | 0.22 | 0.03 |
| Net PnL | -56.09 | -0.92 |

### Confusion Matrix
- Bad filtered (SL→MISS): 111
- Bad improved (SL→TP): 29
- Good lost (TP→MISS): 115
- Good hurt (TP→SL): 29
- Net: -4 trade (115 good lost - 111 bad filtered)

### Sonuç
- Retrace filtresi KÖTÜ trade'leri iyi trade'lere oranla daha fazla filtrelemiyor
- %62.8 trade azalması + win rate düşüşü = NET DESTRUCTIVE
- Öneri: Mevcut definition ile retrace filtresi uygulanmamalı
- 125 trade NO_DATA — reconstruction yetersiz, sonuçlar %65 veriye dayanıyor

## Önceki Tamamlanan
- Phase 2: Sweep/FVG/entry reconstruction (360 trade)
- Phase 1: Forensic analysis (542 trade inventory)

## İlgili Dosyalar
- `sniper/output/reports/SWEEP_RETRACE_CONTROL_EXPERIMENT.json` — full metrics
- `sniper/output/reports/SWEEP_RETRACE_CONTROL_EXPERIMENT.md` — summary report
- `sniper/output/reports/SWEEP_RETRACE_TRADE_COMPARISON.jsonl` — per-trade
- `sniper/output/_exp_run.py` — experiment runner
- `sniper/output/_exp_sim.py` — simulation functions
- `sniper/output/_exp_load.py` — data loading
