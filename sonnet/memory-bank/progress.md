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
| FVG zero-height | `entry_manager.py` | FVG top==bottom iken SL fallback'e düşer, risk_dist=0 hatası önlenir |
| Market order debug | `entry_manager.py` | Başarısız market emrinde response body log'a yazılır |
| Demo API retry | `bot_binance.py` | POST sonrası orderId bulunamazsa 2 kere GET ile taranır |
| _live flag timing | `bot.py` | `_live=True` recovery + state sync sonrasına alındı |
| ENTRY log sırası | `bot.py` | API çağrısı başarısızsa ENTRY logu basılmaz |
