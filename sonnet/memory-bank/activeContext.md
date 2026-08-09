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

## D-2: Trailing/Entry Formülleri Senkronizasyon Sorunu (2026-07-24)

- `bugs.md` oluşturuldu — D-2 maddesi eklendi
- **3 kopya kod tespit edildi**: `trailing_manager.py` (live), `simulate.py`, `analyzer_v5.py`
- **Kritik farklar:**
  - `exit_now` guard: LIVE'da var (FVG kırıldı exit), backtest'lerde YOK → backtest'ler optimist
  - `is_closed` guard: LIVE'da var, `fvg_close_confirmed`'te backtest'lerde YOK
  - `analyzer_v5` open-bar'da trigger olabilir, live/simulate olamaz
  - `simulate.py` trail_count'u eksik sayar (per-bar +1, per-FVG değil)
- **Öneri:** Trailing formülleri ortak modüle çıkarılmalı, backtest'ler inline kod yerine import kullanmalı

## Opencode → Roo Code Config Sync (2026-07-?)
- opencode.json'daki MCP server ayarları Roo Code'a kopyalandi
- Hedef: `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json`
- Kopyalanan MCP'ler: codebase-memory-mcp (disabled), mcacp (enabled)
- Komut dizileri ayni sekilde eklendi, bagimsiz calisir — opencode icermez

## Aşama 1: detect_mss/detect_fvgs İzole Doğrulama (2026-08-08)
- **Görev:** Baş mühendis direktifi — TIAUSDT 08-08 08:00-15:00 TSİ, sonnet mss.py+pivot.py'nin canlı/backtest ile ortak config üzerinden izole doğrulaması. Onay sonrası E varyantı.
- **Mimari:** sonnet'ten sadece `mss.py`+`pivot.py` sniper/src'ye kopyalandı. CHoCH sabitleri sniper config'de (CHoCH_MIN_BODY_RATIO=1.0, CHoCH_ATR_OVERSHOOT=0.2, CHoCH_ATR_PERIOD=14, CHOCH_MAX_AGE_HOURS=8). `compute_atr_series` (saf Python, numba'sız) indicators.py'ye eklendi.
- **Kritik metodoloji:** Tek segmentte tüm günü vermek look-ahead bias üretir (detect_mss lookback=son 32 bar → 8 saat). Çözüm: **an-bazlı kırpma** — her kontrol anında veri o ana kadar kesilip detect_mss çalıştırılır. Baş mühendis bunu onayladı ("tam olarak istediğim şey").
- **13:30 sorusunun cevabı:** CHoCH YOK. 13:00'deki 0.3283 pivot kırılışı convincing break olamadan geri alındı (13:15-13:30'da 0.3290'a dönüş). 14:00'teki 0.3317 sweep gerçek yukarı kırılımdı (boğa tuzağı değil). 13:30'daki hareket düzeltmeymiş — baş mühendisin görsel okuması yanlış çıktı, metodoloji doğru çalıştı.
- **Canlı bot çapraz doğrulama:** TIAUSDT 14:45:08 SHORT @0.3285 (sweep 0.3301 + 14:30 bearish FVG [0.3299-0.3297], CBDR akışı — CHoCH değil). SL/TP = 0.33006/0.32570 (A-varyant 1.5·ATR / 1.8·RR ile birebir). Sonuç: SL @0.3295 17:20:17, **-12.14 USDT**. Fiyat 19:00'da 0.3310'a gitti.
- **Sanity check (TIA/SEI/PYTH/SOL):** 14 CHoCH, 9/14 (%64) yapısal devam, 5 yanlış yön. SEI 4/4 HIT, SOL 3/3 HIT, PYTH 2/4, TIA 0/3 (günün yönü yukarıydı, tüm bearish sinyaller yenildi). GEÇ giriş sinyali 3/14. Ön görü: tek başına CHoCH yönü yetmez, E varyantında FVG çakışması + günlük trend/bias filtresi belirleyici.

## Aşama 2: A/E1/E2 CHoCH Giriş Filtresi Backtest'i (2026-08-09)
- **Görev:** Baş mühendis direktifi — CHoCH yönünün sweep/CBDR bias'ıyla çelişmesi durumunda (TIA örneği) yumuşak (E1) ve sert (E2) filtreyi ayrı varyant olarak 28-coin'de test et, tahmin etme.
- **Mimari:** `config.ENTRY_VARIANT` (A/E1/E2) + `CHOCH_FVG_OVERLAP_ATR_MULT=1.0`. analyzer_v5.py'ye `_latest_choch` (SwingStateManager.ingest + detect_mss, an-bazlı kırpma) + `_pick_overlap_fvg` (CHoCH.level'a en yakın aynı yönlü FVG, tolerans = max(band, ATR·mult)). Entry bloğunda: CHoCH yoksa A ile birebir; destekleyici CHoCH → overlap FVG tercihi; ters CHoCH → E1'de yok say (A'ya düş), E2'de reddet (`CHOCH_CONTRA`). Trailing/SL/TP formülüne dokunulmadı. `run_compare_ae` (A/E1/E2 üçlü) + `--compare-ae` flag; rapor `reports/analyzer_v5_ae_compare.md`.
- **Sonuç (28 coin):** **A kazandı** — A: 111,246 trade / PE %60.9 / MaxDD %1.0 / **+4,100,540**; E1: 105,640 / %58.0 / %1.3 / +3,547,796; E2: 56,833 / %44.6 / **%25.8** / +319,403 (contra reddi 117,774).
- **Kritik bulgu:** Baş mühendisin öngörüsü doğrulandı — "bias'a ters CHoCH" girişleri A'nın kârlılığının bel kemiği; E2'nin elediği 117,774 trade'in çoğu kazanan, kalan portföy MaxDD %1.0→%25.8'a fırladı, PE %60.9→%44.6'ya düştü. 28 coin'in HİÇBİRİNDE E1/E2 A'yı geçemedi. TIA özelinde: A +221,036 → E2 +26,808 (14:45 zararı istisnaymış).
- **A deterministikliği doğrulandı:** AE raporundaki A değerleri, önceki D-karşılaştırma raporuyla (08-08) birebir aynı (111,246 trade, +4,100,540).
- **Karar:** E1/E2 hipotezleri reddedildi, A-varyant olduğu gibi kalır. Canlı bot etkilenmedi (ENTRY_VARIANT config'te "A").

## Bisect: backtest-sniper PF Regression (2026-07-29)
- **Görev:** cd3b053 (SOLUSDT PF=4.61, +42,347) ile HEAD (PF=0.56-0.58) arasındaki commit'lerde SOLUSDT PF düşüşünü bul
- **Yöntem:** 5 commit (8322010..dbab1ab) tek tek checkout edilip SOLUSDT-only backtest koşuldu
- **Sonuç:**
  | Commit | PF | PTrail% | NetPnL | Sebep |
  |--------|----|---------|--------|-------|
  | `8322010` (baseline) | 4.61 | 51.9% | +42,347 | cd3b053 revert (GOOD) |
  | `9a2c0bc` | 0.71 | 11.4% | -5,724 | **İLK KIRICI** 🚩 |
  | `44e891d` | 0.73 | 9.5% | -5,449 | +would_reject |
  | `1fcde6e` | 0.56 | 14.9% | -9,211 | guard kalktı, would_reject kaldı |
  | `c36a59c` | 0.56 | 14.9% | -9,211 | structural SL (kapalı) |
  | `dbab1ab` (HEAD) | 0.58 | 25.3% | -4,189 | structural SL (açık) |
- **Kök neden:** İki bağımsız suçlu:
  1. `9a2c0bc` — `MIN_SL_DISTANCE_PCT` engeli (0.15%)
  2. `44e891d` — `would_reject_immediately` (-2021 simülasyonu)
- **İzolasyon testi:** 8322010 baseline + SADECE `would_reject_immediately` → PF=0.56, PTrail%=14.9%. Guard yokken dahi `would_reject_immediately` tek başına trailing'i kırıyor. Muhtemel sebep: `_estimate_tick_size()` kaba tahmini gerçek Binance tick_size'ından saparak çok sık red üretiyor.
- **Tüm commit'ler kırık:** PF hiçbirinde 1.0'ın üstüne çıkmadı

## DOGEUSDT Çift Emir Kazası — Fix A/B/C (2026-08-09)
- **Olay:** DOGEUSDT long @0.07037 (16:30 entry). Restart 16:35 → trail 17:37 `replace_protection` eski 16:30 SL/TP emirlerini iptal etmeden yeni çift koydu → Binance'te 4 koruma emri (2 SL + 2 TP).
- **Kök neden zinciri (doğrulandı):**
  1. `models.py:539` — `protection_orders: dict = field(default_factory=dict)`; recovery doldurmazsa gerçekten boş kalır.
  2. `recovery_manager.py` recover_positions — hem existing hem yeni `ActiveTrade(...)` dalı sadece flat `sl_order_id`/`tp_order_id` yazıyordu, `protection_orders` hiç geçilmiyordu.
  3. `order_manager.py:_replace_one` — eski emri yalnızca `protection_orders.get(kind)`'tan buluyordu; flat ID'lere bakmıyordu → boşsa cancel adımı sessizce atlanıyor, yeni emir üstüne koyuluyordu.
- **Fix A (order_manager.py `_replace_one`):** `protection_orders[kind]` boşsa flat `sl_order_id`/`tp_order_id` fallback'i — `_known_protection_ids()` deseniyle aynı (flat + protection_orders birlikte okunur). Cancel sonrası `protection_orders[kind]` satır 1198'de zaten yazılıyordu, ek değişiklik gerekmedi.
- **Fix B (recovery_manager.py):** recover_positions restore'da `protection_orders` dict'i gerçek borsa tipiyle doldurur (`get_order_type(emir)` — sabit "STOP_MARKET"/"TAKE_PROFIT_MARKET" varsayımı yok). Hem existing dalına hem yeni ActiveTrade'ye.
- **Fix C (recovery_manager.py `_dedupe_protection_orders`):** borsada aynı pozisyon için birikmiş 1'den fazla SL/TP emri varsa en yenisini (en büyük sayısal orderId) tutup fazlaları iptal eder. **Sıra önemli:** `protection_orders` doldurulmadan ÖNCE çalışır.
- **Kullanıcı aksiyonu:** Binance'teki fazla çifti manuel iptal etti.
- **Testler:** 3 yeni regresyon testi (`test_replace_one_cancels_flat_order_id_fallback`, `test_recover_dedupes_duplicate_sl_tp_and_fills_protection_orders`, `test_recover_existing_trade_gets_protection_orders`) + mevcut schema testine Fix B assert'leri. 136 passed (order+recovery+trailing+protection+exit+state).
- **Pre-existing 4 fail (dokunulmadı):** `test_initial_protection_failures` (direction validation 2), `test_state_writer` (sl_status 2) — stash ile base'de de aynı olduğu doğrulandı.
- **Deploy durumu:** Fix commit + push sonrası sunucuya pull + bot restart gerekir (kullanıcı onayı bekliyor).
