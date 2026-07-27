# Progress — Sniper Bot

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

## P1-15 Kök Neden Analizi (2026-07-27)
| Metrik | Değer |
|--------|-------|
| Toplam stale event (bugün) | 14 (5 cluster) |
| Etkilenen exit oranı | 5/13 (%38.5) |
| Binance fill -> WS gecikme (min) | 87s (ONDOUSDT) |
| Binance fill -> WS gecikme (medyan) | 144s (DOGEUSDT) |
| Binance fill -> WS gecikme (max) | 353s (GMXUSDT) |
| Reconnect korelasyonu | YOK |
| Tarihsel WS_FALLBACK oranı | 99/290 (%34.1) |
| Kök neden | Binance WS teslimat gecikmesi (client-side fix yok) |
| Öneri | STOP_MARKET reject (HTTP -2021) fill kanıtı olarak kullan |
