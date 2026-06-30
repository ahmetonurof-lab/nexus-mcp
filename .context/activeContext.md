# activeContext.md — güncel durum

## Son Değişiklik
**cleanup_on_exit güvenlik fix**: `_exit_trade()` artık `cleanup_on_exit` çağırmadan önce `rest.get_positions()` ile Binance'te pozisyonun gerçekten kapalı olduğunu doğrular. Açık kalmış pozisyon tespit edilirse:
1. reduceOnly market emriyle kapatmayı dener
2. Başarısız olursa tüm cleanup atlanır (SL/TP korunur, `active_trades`'ten silinmez, `mark_trade_closed` çağrılmaz)
3. `log.critical` + `_pl(force=True)` ile acil uyarı basılır

## Değişen Dosyalar
- `sniper/src/bot.py`: `_exit_trade()` — FIX #6 pozisyon doğrulama bloğu eklendi
- `sniper/tests/test_trailing_manager.py`: tüm `@patch`'li testlere `mock_cfg.ATR_TRAIL_MULT=0.25` eklendi, beklenti değerleri güncellendi

## Aktif Kararlar
- FVG persistence: `active_fvg.json` ayrı dosya, trade açılırken yazılır, kapanırken silinir
- Recovery okuma: `recover_positions()` sonrası `_load_fvg_state()` ile trade'lere enjekte edilir
- Console: FVG verisi varsa `{direction} {top}-{bottom}`, yoksa "ISLEMDE"
- availableBalance ile walletBalance arasındaki fark: **orphan emirlerden değil**, gerçek açık pozisyonların marjininden kaynaklanır. reduceOnly=true asılı emirler marjin bloklamaz.

## Bekleyen
- Bot restartı ile yeni trade'lerde FVG değerlerinin `output/active_fvg.json`'da göründüğünü doğrula
