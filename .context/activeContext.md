# Active Context

## Current Work
- `trades_history.jsonl` yazma eksikti — `_exit_trade`'de deque'e append ediliyor ama diske yazılmıyordu
- FVG büyük olduğunda SL `FVG.bottom - buffer` ile entry'den çok uzakta kalıyordu
- SL buffer'ı sabitti (`FVG_BUFFER_MULT = 0.50`), FVG boyuna adaptasyon yoktu
- `FVG_BUFFER_MIN_FACTOR = 0.10` config'de tanımlı ama kullanılmıyordu (ölü parametre)

## Changes Made
- `sniper/src/bot.py`:
  - `import json` eklendi
  - `_load_history()` — bot başlangıcında `trades_history.jsonl`'den geçmişi deque'e yükler
  - `_exit_trade`'de trade kaydı `self.trades.append` sonrası `trades_history.jsonl`'e append yazılıyor
- `sniper/src/config.py`:
  - `MAX_SL_DIST_MULT = 2.0` eklendi (SL max risk_pts çarpanı)
- `sniper/src/trading/entry_manager.py`:
  - `calculate_sl_tp()`'de SL buffer'ı hybrid formüle dönüştürüldü:
    - `adaptive_buf = max(fvg_height × 0.10, min(fvg_height × 0.25, risk_pts × 0.5))`
    - `FVG_BUFFER_MIN_FACTOR` artık kullanılıyor (ölü config aktif)
    - `MAX_SL_DIST_MULT = 2.0` tavanı ikinci güvenlik katmanı

## Verification
- `bot.py`, `config.py`, `entry_manager.py` derlendi (py_compile)
