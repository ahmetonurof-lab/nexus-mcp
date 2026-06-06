# Progress — NEXUS V3

## Çalışanlar ✅

| Bileşen | Durum | Not |
|----------|-------|-----|
| `models.py` | ✅ | Bar, FVG, CHoCH, SwingPoint dataclass'ları |
| `config.py` | ✅ | Tüm sabitler, sembol listesi, risk parametreleri |
| `pivot.py` | ✅ | Fraktal swing tespiti + SwingStateManager |
| `indicators.py` | ✅ | EMA, SMMA, ATR, ADX (Numba JIT) |
| `fvg.py` | ✅ | FVG tespiti, state yönetimi, retest, quality |
| `mss.py` | ✅ | CHoCH/MSS tespiti, SMC mikro-yapı veto |
| `analyzer.py` | ✅ | HTF bias → sweep → MSS → FVG → retrace → LTF zinciri |
| `scoring.py` | ✅ | FVG quality + CHoCH + rejim + konfluens skorlama |
| `event_router.py` | ✅ | Publisher → StateMachine yönlendirici |
| `state_machine.py` | ✅ | 6-state machine + pre-check layer |
| `exchange.py` | ✅ | Binance REST istemcisi |
| `trader.py` | ✅ | MARKET + SL/TP algo emir + pozisyon yönetimi |
| `websocket.py` | ✅ | Multi-symbol × multi-TF WS hub |
| `main.py` | ✅ | LiveTradingBot orkestrasyonu |
| `monitor.py` | ✅ | Runtime sayaçları + health endpoint |
| `performance.py` | ✅ | Trade geçmişi + leaderboard |
| `risk_manager.py` | ✅ | 4H swing SL + 1H likidite TP + lot + kademeli stop (bug fix 2026-06-06) |

## Kalan İşler 🔧

| Görev | Öncelik | Açıklama |
|-------|---------|----------|
| Canlı trading testi | 🔴 Yüksek | READY_TO_ENTER zincirinin hatasız çalıştığını doğrula |
| `risk_manager.py` unit test | 🟡 Orta | `calculate_sl_htf`, `calculate_tp_htf`, `build_trade` için |
| `analyzer.py` unit test | 🟡 Orta | Her event detector için ayrı test |
| Integration test | 🟡 Orta | Tam zincir: WebSocket → analyzer → state → trade |
| Grafana/Prometheus bağlantısı | 🟢 Düşük | `monitor.py` health endpoint'i |
| Backtesting framework | 🟢 Düşük | Geçmiş veri ile strateji validasyonu |

## Mevcut Durum

- **State**: Geliştirme aşamasında, canlı test öncesi
- **Son commit**: `81cc646` (nexus-mcp repo)
- **Çalışan semboller**: 22 Binance Futures perpetual
- **Aktif trade**: Yok (test aşaması)

## Bilinen Sorunlar 🐛

| Sorun | Tarih | Durum | Çözüm |
|-------|------|-------|-------|
| `AttributeError: 'RiskManager' object has no attribute 'tier_buffer'` | 2026-06-06 | ✅ Çözüldü | `_tier(symbol)` ile tier config lookup, `calculate_sl_htf` imzasına `symbol` eklendi |
| `calculate_tp_htf` çağrı imzası uyumsuzluğu | 2026-06-06 | ✅ Çözüldü | 6 parametreli hatalı çağrı 4 parametreye indirildi |

## Proje Kararlarının Evrimi

1. **SL stratejisi değişimi**: Eski FVG tabanlı SL → 4H swing high/low + tier buffer (daha güvenilir yapısal referans)
2. **TP stratejisi değişimi**: Eski default RR çarpanı → 1H BSL/SSL likidite seviyesi (piyasa yapısına uygun)
3. **SL mesafesi kısıtlaması kaldırıldı**: `build_trade` artık SL uzak diye trade reddetmez (TP 1H likiditeye sabitlendiği için)
4. **Memory Bank eklendi**: Session reset'lerinde context kaybını önlemek için 6 çekirdek dosya oluşturuldu (2026-06-06)