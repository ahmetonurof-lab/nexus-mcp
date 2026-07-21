# Active Context — Sniper Bot (Paper Trade → Live)

## Mevcut Durum
- **Bot calisiyor**: Testnet WS + REST API bagli
- **Testnet bakiyesi**: 4995.96 USDT
- **Strateji**: CBDR → Sweep → FVG Wick Rejection → Trailing → Exit (analyzer_v3)
- **Sembol sayisi**: 7 (BTC/ETH/BNB/SOL/AVAX/LINK/XRP)
- **Emir gonderme**: Aktif — STOP_MARKET + TAKE_PROFIT_MARKET testnete gidiyor
- **Session gate**: ASIA (22:00-02:00 UTC) red, LONDON+NY kabul
- **Kazanc**: +37.42 USDT (LINK SHORT)

## Son Degisiklikler (2026-06-20)
- `bot.py`: CBDR warmup (gecmis barlardan body hesapla) → sweep hemen yakalanir
- `bot.py`: Position recovery (restartta API'den pozisyonlari yukle, cift trade engelle)
- `bot.py`: Testnet emir gonderme (SL=STOP_MARKET, TP=TAKE_PROFIT_MARKET)
- `bot.py`: Trailing guncellemesinde SL/TP emirlerini yenile
- `bot.py`: Logging duzeltildi — paper_trade.log hem sniper.paper hem ws_hub yazar
- `bot.py`: Session/CBDR/Sweep status her bar'da gosterilir
- `bot_binance.py`: get_positions(), place_stop_order(), place_tp_order() eklendi
- `websocket.py`: prefill_bars() eklendi, open_timeout asyncio.wait_for ile
- `config.py`: FVG_SIZE_MAP, TESTNET_API_KEY destegi
- `backtest-sniper/config.py`: FVG_SIZE_MAP eklendi

## Son Degisiklikler (devam)
- `bot.py`: 5 fix — risk_pts trailing buffer, warmup CBDR 22:00-02:00 filtresi, synthetic SL/TP recover, exit_timestamp dogru bar, _live=True prefill oncesi

## Acik Basliklar
- Pre-commit hooks (ruff, mypy, vulture) su an calismiyor — .pre-commit-config.yaml guncellenmeli
- ETH/BTC/XRP icin backtest sonuclari kontrol edilecek
- `pre-commit install` sonucta runner dogru calismali
- `bot.py` analyzer_v3.py ile davranissal birebir uyumlu, canliya gecis icin onay bekliyor

## Son Fixler (2026-06-29)
- `entry_manager.py`: FVG zero-height guard — `fvg_height <= 0` iken fallback SL (risk_pts * 2) kullanilir, SL/TP entry'ye esit kalmaz
- `entry_manager.py`: `adaptive_buf <= 0` → `max(risk_pts * 0.1, ...)` minimum garantisi
- `entry_manager.py`: `risk_dist <= 0` son kontrol — her iki tarafta fallback
- `entry_manager.py`: Market order hatasinda detayli log (response icerigi)
- `bot_binance.py`: `place_market_order` demo API icin 2x retry + `origType` fallback
- `bot_binance.py`: `place_market_order` icindeki ikinci `validate_min_notional` kaldirildi — `entry_manager._bump_to_min_notional` zaten yapiyordu, farkli anlik fiyatla cakisma cozuldu
- `bot.py`: `_live = True` recovery sonrasina alindi, ENTRY logu API dogrulamasindan sonra basiliyor
- `entry_manager.py`: `_bump_to_min_notional()` metodu eklendi — qty < minNotional ise minimum geçerli qty'ye ceil ile yükseltir, buying power tavanını aşarsa iptal eder
- `entry_manager.py`: `execute_live_entry()` imzasına `balance` + `leverage` parametreleri eklendi
- `bot.py`: `execute_live_entry()` çağrısına `balance=self._available_balance, leverage=cfg.LEVERAGE` eklendi

## Snapshot Chart Fix (2026-06-29)
- `chart_template.html`: LWC 4.2 uyumluluk — `autoscaleInfoProvider` kaldirildi
- `chart_template.html`: `rightPriceScale: { autoScale: false }` + data sonrasi `setVisiblePriceRange(priceRange)`
- `chart_template.html`: `fitContent()` sonrasi scale resetlenmesini engellemek icin 2. kez `setVisiblePriceRange`
- `chart_template.html`: TP mesafesi mum range'inin 3x katindan fazlaysa scale'e dahil edilmez (ATOMUSDT gibi dusuk fiyatli ciftler)
- `chart_template.html`: `fmt()` maximumFractionDigits 2 → 4 (kucuk fiyatli coinlerde dogru gosterim)

## Son Fixler (2026-07-21)

### `repair_protection()` — stale SL fix
- `bot_positions.py`: Eskiden `trade["entry"]` bazlı SL hesaplıyordu (stale).
- Fix: `mark_price` (güncel) bazlı hesapla + fiyat çoktan geçtiyse market close.
- P1-1 çözüldü.

### `periodic_protection_check()` — 60sn watchdog
- `bot_positions.py`: Yeni metod. Her 60sn `_health_loop`'tan çağrılır.
- `protection_repairing` flag'i ile guard.
- Exchange'de pozisyon yoksa → `clear_state()`.
- SL/TP eksikse → `repair_protection()`.
- P0-3 (guard), P1-4 (periyodik) kısmen çözüldü.

### Restart state cleanup
- `bot.py` `run()`: `startup_cleanup` sonrası, `protection_missing` veya `recovered_unprotected` trade'leri state'ten temizle.
- Ölü trade'lerin restart'ta geri gelmesi engellendi.
- P0-1 (çift-exit senaryosu) zincirleme engellendi.

## Onemli Notlar
- `sonnet/src/` icindeki hicbir dosya degistirilmez veya silinmez
- Veriler mainnet WS'den gelir (testnet WS = mainnet data)
- Emirler testnet'e gider — canliya geciste sadece API url degisecek
- Bot koparsa testnet'te pozisyon kalir, restartta `_recover_positions()` alir

## Opencode → Roo Code Config Sync (2026-07-?)
- opencode.json'daki MCP server ayarları Roo Code'a kopyalandi
- Hedef: `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json`
- Kopyalanan MCP'ler: jcodemunch (disabled), mcacp (enabled)
- Komut dizileri ayni sekilde eklendi, bagimsiz calisir — opencode icermez
