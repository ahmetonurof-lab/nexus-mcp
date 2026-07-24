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

## Soruşturma Sonuçları (2026-07-03)

### 1. Coin-bazlı pencere özelliği
- `cbdr_window` parametresi **git'e hiç girmedi** — local'de yazılıp commit öncesi kaldırıldı veya hiç implemente edilmedi.
- `compare_windows.py` tek konfigürasyonla (standart 22-02 UTC) çalışıyor, coin bazlı karşılaştırma YAPMIYOR.
- Rapor başlığında "2.5 yıl veri" yazmasına rağmen aslında `data/{COIN}_1m.csv` (~90 gün) kullanılıyor.
- **Çözüm:** `SessionState.__init__`'e opsiyonel `cbdr_window: tuple | None = None` parametresi eklenip coin bazlı window tanımı yapılabilir.
- **Karar:** ⏳ AÇIK — geri getirilip getirilmeyeceği netleşmedi.

### 2. CBDR threshold veri seti
- `analyze_cbdr_thresholds.py` **yanlış** veri seti kullanıyor: `data/{COIN}_1m.csv` (130K satır, ~90 gün, 2026-01-01 → 2026-04-01).
- `data/daily/{COIN}_1m_raw.csv` (1.3M satır, ~2.5 yıl, 2024-01-01 → 2026-06-30) **kullanılmıyor**.
- Log'da **bar sayısı doğrulaması YOK** — `load_data()` kaç satır okuduğunu yazdırmıyor.
- `compare_windows.py` raporu da aynı hatalı veriyi kullanıyor (90 gün = 2.5 yıl değil).
- **Çözüm:** `collect_daily_data()` içinde `data/daily/{COIN}_1m_raw.csv`'e yönlendir, `print(f"Loaded {len(b1)} 1m bars → {len(b15)} 15m bars")` doğrulama satırı ekle.
- **Karar:** ⏳ AÇIK — veri kaynağı düzeltilmedi, log satırı eklenmedi.

### 3. "Real CBDR" window çelişkisi
- **Backtest "Real CBDR":** `analyzer_cbdr_ict.py` + `analyze_cbdr_thresholds.py` → `IctRangeState(19, 1)` = 19:00-01:00 UTC.
- **Production:** `session.py` → `CBDRState` = 22:00-02:00 UTC (sabit, `SessionPhase.CBDR`).
- Arada **3 saat fark** var — backtest'te analiz edilen window production'da kullanılmıyor.
- **İkinci çelişki:** `analyzer_cbdr.py`, production `SessionState`'den kaldırılmış `retrade_*` attribute'larına (retrade_armed, retrade_side, vs.) dynamic erişiyor. Python crash olmuyor ama production ile backtest davranışı uyumsuz.
- **Karar:** ⏳ AÇIK — window standardizasyonu veya produciton'a "Real CBDR" eklenmesi gerekiyor.

### 4. mcacp + opencode ACP entegrasyonu (2026-07-06)
- `mcacp.json` düzenlendi: `gemini-flash-lite`, `gemini-cli`, `qwen`, `opencode` ACP agent'ları eklendi
- Config Windows yoluna taşındı: `%APPDATA%\mcacp\mcacp.json`
- Test: gemini-cli üzerinden session açılıp prompt gönderildi, başarılı yanıt alındı ✅
- `opencode.json`'a `mcacp` MCP server olarak eklendi — opencode içinden Gemini çağrılabilecek

## Bekleyen
- Bot restartı ile yeni trade'lerde FVG değerlerinin `output/active_fvg.json`'da göründüğünü doğrula
- Yukarıdaki 3 soru netleşene kadar backtest raporları nihai sayılmaz

## Opencode → Roo Code Config Sync (2026-07-?)
- `opencode.json`'daki MCP server ayarları Roo Code'a kopyalandı
- Hedef: `%APPDATA%\Code\User\globalStorage\rooveterinaryinc.roo-cline\settings\mcp_settings.json`
- Kopyalanan MCP'ler: `codebase-memory-mcp` (disabled), `mcacp` (enabled)
- Komut dizileri aynı şekilde eklendi, bağımsız çalışır — opencode içermez
