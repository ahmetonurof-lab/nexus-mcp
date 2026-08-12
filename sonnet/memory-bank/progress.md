# Progress — Sniper Bot

## Aşama 1 — CHoCH/FVG İzole Doğrulama (2026-08-08)
| Adım | Durum | Detay |
|------|-------|-------|
| Veri kaynağı | ✅ | Binance fapi 15m (feather 07-01'de bitiyor, sunucu CSV 07-25'te kalmış) |
| Mimari kurulum | ✅ | sonnet mss.py+pivot.py → sniper/src; CHoCH sabitleri config; compute_atr_series saf Python |
| İlk koşu (tüm gün) | ✅ | 12:45-14:30 CHoCH yok (lookback=8 saat → segment dışı, look-ahead bias) |
| Teşhis (bar yapısı) | ✅ | 13:00 C=0.3285 (0.3283 kırılışı), 14:00-14:15 sweep 0.3317 + rejection |
| **An-bazlı kırpma** | ✅ | **13:30 CHoCH YOK**; ilk geçerli bearish CHoCH 14:45 (str=0.576, pivot@12:45) |
| Canlı çapraz kontrol | ✅ | Bot 14:45 SHORT @0.3285 → SL -12.14 USDT (sweep-FVG akışı, CHoCH değil) |
| Sanity check TIA/SEI/PYTH/SOL | ✅ | 9/14 (%64) HIT; TIA 0/3 (yön yukarıydı), SEI 4/4, SOL 3/3, PYTH 2/4 |
| E varyantı analyzer_v5 (E1/E2) | ✅ REDDEDİLDİ | 28-coin A/E1/E2: A kazandı (A +4,100,540 / E1 +3,547,796 / E2 +319,403) |

**Bekleyen:** (1) 28-coin A/E1/E2 sonucu baş mühendise sunuldu → karar: E hipotezi gömüldü, A-varyant olduğu gibi kalır. (2) E2 MaxDD %25.8 bulgusu (bias'a ters CHoCH trade'leri aslında kârlı) incelenebilir.

**Aşama 2 kapanış (2026-08-09):** E implementasyonu + AE raporu commit edildi ve push edildi (backtest-sniper `eb45033`). Öncesinde pre-commit hook'ları dosya yapısı bozukluğunu yakaladı (`_LOGGER = None` edit'i main()'i ikiye bölmüş, helpers modül seviyesine düşmüştü); HEAD'e dönüp bağlamlı oldString'lerle temiz yeniden uygulandı, smoke test eski raporla birebir örtüştü (TIA: A 4257 / E1 4059 / E2 2159, contra 4104). `max_wick_ratio=None` ve `detect_mss atr_mult` (config `CHOCH_ATR_OVERSHOOT=0.2`) parity düzeltmeleri yapıldı. Ayrıca vulture blokörü olan `utils/analyzer_v3.py` kullanılmayan `ATR_PERIOD` import'u temizlendi.

## Çalışanlar ✅
| Bileşen | Durum |
|---------|-------|
| bot.py (orchestrator) | ✅ Testnet bağlantısı aktif |
| bot_pipeline.py | ✅ Sinyal pipeline çalışıyor |
| bot_positions.py | ✅ Pozisyon yönetimi aktif |
| state_machine.py (V40) | ✅ 5 state sniper flow |
| websocket.py | ✅ Multi-symbol WS hub |
| analyzer.py | ✅ Market analizi |
| config.py | ✅ V4 + sniper birleşik config |
| monitor.py | ✅ Runtime sayaçları |
| performance.py | ✅ Trade geçmişi |
| Dashboard API | ✅ http://localhost:8080 |

## Kalan İşler 🔧
| Görev | Öncelik | Açıklama |
|-------|---------|----------|
| Canlı trade validasyonu | 🟡 Orta | Bot sinyal ürettiğinde trade akışının doğrulanması |
| Error handling iyileştirme | 🟢 Düşük | WS kopma, API hataları için recovery testi |
| Performance benchmark | 🟢 Düşük | CPU/memory kullanımı profil |

## Yapılan Fixler (2026-06-29)
| Fix | Dosya | Açıklama |
|-----|-------|----------|
| FVG zero-height + adaptive_buf min garantisi | `entry_manager.py` | FVG top==bottom iken SL fallback; `adaptive_buf <= 0` → `risk_pts * 0.1` min |
| Market order debug | `entry_manager.py` | Başarısız market emrinde response body log'a yazılır |
| Demo API retry | `bot_binance.py` | POST sonrası orderId bulunamazsa 2 kere GET ile taranır |
| Duplicate minNotional kaldırıldı | `bot_binance.py` | `place_market_order` içindeki ikinci `validate_min_notional` kaldırıldı (farklı fiyatla çakışma) |
| _live flag timing | `bot.py` | `_live=True` recovery + state sync sonrasına alındı |
| ENTRY log sırası | `bot.py` | API çağrısı başarısızsa ENTRY logu basılmaz |
| Snapshot chart LWC 4.2 uyum | `chart_template.html` | `autoscaleInfoProvider` → `autoScale:false` + `setVisiblePriceRange` |

## Tespit Edilen Mimari Riskler (2026-07-24)
| ID | Dosya | Açıklama |
|----|-------|----------|
| D-2 | `trailing_manager.py`, `simulate.py`, `analyzer_v5.py` | Trailing/entry formülleri 3 yerde kopya kod, senkronizasyon garantisi yok. `exit_now` guard live'da var backtest'lerde yok (HIGH). `is_closed` guard live'da var backtest'lerde yok (MEDIUM). `simulate.py` trail_count eksik sayar (LOW). `analyzer_v5` open-bar trigger yapabilir (MEDIUM). `bugs.md`'de detaylı kayıt mevcut. |

## backtest-sniper PF Regresyonu (2026-07-29)
| ID | Detay |
|----|-------|
| Bisect sonucu | `8322010` (cd3b053 revert, PF=4.61) -> `9a2c0bc` (PF=0.71) |
| Kok neden | `9a2c0bc` trailing'e MIN_SL_DISTANCE_PCT=0.15% engeli + execution_sim altyapisi eklemis |
| PTrail% | 51.9% -> 11.4% (trailing calisamaz hale gelmis) |
| Etkilenen | SOLUSDT ve tum coin'ler - PF hicbir sonraki commit'te 1.0'i gormemis |
| Ikincil katman | `44e891d` would_reject_immediately (-2021 simulasyonu) trailing blokajini perciniememis |

## DOGEUSDT Çift Emir Kazası Fix (2026-08-09)
| Adım | Durum | Detay |
|------|-------|-------|
| Olay teşhisi | ✅ | Trail 17:37 eski SL/TP'yi iptal etmeden yeni çift koydu (restart sonrası protection_orders boştu) → 4 emir |
| Kök neden | ✅ | `_replace_one` sadece `protection_orders.get(kind)` okuyordu; recovery flat ID yazıyordu → restore sonrası iptal adımı atlanıyor |
| Fix A | ✅ | `_replace_one` flat `sl_order_id`/`tp_order_id` fallback'i (`_known_protection_ids` deseni) |
| Fix B | ✅ | recovery `protection_orders`'ı gerçek borsa tipiyle dolduruyor (existing + yeni trade) |
| Fix C | ✅ | `_dedupe_protection_orders` — fazla SL/TP emirleri iptal, en yeni kalır; state yazımından ÖNCE çalışır |
| Testler | ✅ | 3 yeni regresyon + mevcut schema testine Fix B assert; 136 passed |
| Pre-existing fail | ⚠️ | 4 fail (initial_protection_failures 2, state_writer 2) base'de de var, dokunulmadı |
| Deploy | ✅ | Fix commit/push yapıldı; sunucu pull + restart tamamlandı |

## Fixler (2026-08-10)
| Fix | Dosya | Açıklama |
|-----|-------|----------|
| FVG band render lokalize | `chart_template.html` | `rangedBand()` eklendi, FVG tüm grafiğe değil sadece 12-bar span'da çiziliyor; CE de aynı aralıkta |
| Snapshot reverse sort key DÜZELTMESİ | `snapshot.py` | `f15f253`'te string reversal (`digits[::-1]`) değişken uzunluklu karşılaştırmada kronolojik sıralamayı bozuyordu → `9681564` ile digit-wise `9-rakam` inversion'a geri dönüldü; format `{sort_key}_{sym}_{ts}.html` (sort key BAŞTA, direktife uygun) |
| Sunucu charts temizliği | server `sniper/output/charts/` | 09/10-08-2026 haric tüm 494 eski HTML silindi; kalan 8 dosya yeni sıralama anahtarıyla yeniden adlandırıldı |
| Bot restart (format aktivasyonu) | server | Eski bot 2eecba8'i bellekte tutuyordu (`{sym}_{sort_key}` formatı) → SCREEN restart ile 9681564 yüklendi; WS 56 stream + user data bağlı, state yeniden üretiliyor |
| Sort doğrulaması | test | `tools/test_sort_order.py` lokalde ve sunucuda PASS (alfabetik == ters kronolojik); sentetik 3-sembol snapshot testi sunucuda PASS, test dosyaları silindi |

## Sonnet Direktifi: 7 Reset Noktası 3 Grup (2026-08-12)
| Adım | Durum | Detay |
|------|-------|-------|
| Grup 1 (680/808/831) | ✅ | Full reset KORUNDU (aktif trade, zehirli bölge, qty≤0 — hesap/oturum seviyesi) |
| Grup 2 (756/784) | ✅ `bf89a2e` | Risk doğrulama + eps guard → `lock_bias()` (FVG'ye özgü, düşük risk) |
| Grup 3 (885/907) | ✅ `a723ab1` | `on_operational_fail()` + `_fail_count` (RSM), 3. ardışık hata → full reset; başarıda `clear_fail_streak()` |
| Testler | ✅ | Her 7 nokta ayrı senaryo; `TestOperationalFail` 5 test (3. hata IDLE şartı) |
| Doğrulama | ✅ | test_bot 13 bayat fail (dokunulmadı) + 39 pass; retrace_state 46/46; integration 9 fail pre-existing (stash kanıtı) |
| HEAD | ✅ | sniper `a723ab1`, backtest `b16d751`; push bekliyor |
| Backtest perf | 🟢 Düşük | `fvg_close_confirmed` O(N) tam liste taraması + `_latest_choch`/`_pick_overlap_fvg` şüphelisi; profil doğrulaması bekliyor |
