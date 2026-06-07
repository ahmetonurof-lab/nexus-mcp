We need to apply the suggested edit to the original code. The original code is a markdown file (likely progress.md or similar). The suggested edit shows changes like adding entries in tables, updating some notes, adding new rows, etc. We need to produce the complete modified file with the suggested changes applied.

We must output ONLY the code, no explanations. We need to merge the changes:

- In "Çalışanlar" table, config.py note adds "HTF_STRICT_FILTER=False"
- analyzer.py note changes from "HTF bias → sweep → MSS → FVG → retrace → LTF zinciri" to "HTF bias → sweep → FVG → MSS → retrace → LTF zinciri (format temizlendi)"
- state_machine.py note adds "(FVG log debug→info)"
- Added three new rows for test files: test_pivot.py, test_risk_manager.py, test_state_machine.py
- In "Kalan İşler" table, remove row for "risk_manager.py unit test" (since it's now done) and maybe keep others but the suggested edit only shows remaining tasks: Canlı trading testi, analyzer.py unit test, Integration test, Grafana/Prometheus, Backtesting. No risk_manager unit test.
- In "Mevcut Durum", add "Test coverage": Pivot ✅, Risk Manager ✅, State Machine ✅ — 92 test pass
- Change "Son commit": to "cfff7c8" (from 81cc646)
- In "Bilinen Sorunlar" table, add a new row: Pylance reportMissingImports issue, resolved 2026-06-06, solution .vscode/settings.json → python.analysis.extraPaths: ["sonnet/src"]
- In "Proje Kararlarının Evrimi", add two new items:
5. HTF_STRICT_FILTER=False ...
6. Unit test altyapısı ...

We need to produce the full file with these edits.

Original code had line breaks with double-backslashes for line continuation? In the code snippet provided, it's a markdown file. We'll output the complete markdown content.

We'll write the full modified file.# Progress — NEXUS V3
## Çalışanlar ✅

| Bileşen | Durum | Not |
|----------|-------|-----|
| `models.py` | ✅ | Bar, FVG, CHoCH, SwingPoint dataclass'ları |
| `config.py` | ✅ | Tüm sabitler, sembol listesi, risk parametreleri, HTF_STRICT_FILTER=False |
| `pivot.py` | ✅ | Fraktal swing tespiti + SwingStateManager |
| `indicators.py` | ✅ | EMA, SMMA, ATR, ADX (Numba JIT) |
| `fvg.py` | ✅ | FVG tespiti, state yönetimi, retest, quality |
| `mss.py` | ✅ | CHoCH/MSS tespiti, SMC mikro-yapı veto |
| `analyzer.py` | ✅ | HTF bias → sweep → FVG → MSS → retrace → LTF zinciri (format temizlendi) |
| `scoring.py` | ✅ | FVG quality + CHoCH + rejim + konfluens skorlama |
| `event_router.py` | ✅ | Publisher → StateMachine yönlendirici |
| `state_machine.py` | ✅ | 6-state machine + pre-check layer (FVG log debug→info) |
| `exchange.py` | ✅ | Binance REST istemcisi |
| `trader.py` | ✅ | MARKET + SL/TP algo emir + pozisyon yönetimi |
| `websocket.py` | ✅ | Multi-symbol × multi-TF WS hub |
| `main.py` | ✅ | LiveTradingBot orkestrasyonu |
| `monitor.py` | ✅ | Runtime sayaçları + health endpoint |
| `performance.py` | ✅ | Trade geçmişi + leaderboard |
| `risk_manager.py` | ✅ | 4H swing SL + 1H likidite TP + lot + kademeli stop (bug fix 2026-06-06) |
| `test_pivot.py` | ✅ | 22 test — swing highs/lows, SwingStateManager |
| `test_risk_manager.py` | ✅ | 40+ test — SL/TP/lot/build_trade |
| `test_state_machine.py` | ✅ | 30 test — state geçişleri, pre-check, retrace, flag gate |

## Kalan İşler 🔧

| Görev | Öncelik | Açıklama |
|-------|---------|----------|
| Canlı trading testi | 🔴 Yüksek | READY_TO_ENTER zincirinin hatasız çalıştığını doğrula |
| `analyzer.py` unit test | 🟡 Orta | Her event detector için ayrı test |
| Integration test | 🟡 Orta | Tam zincir: WebSocket → analyzer → state → trade |
| Grafana/Prometheus bağlantısı | 🟢 Düşük | `monitor.py` health endpoint'i |
| Backtesting framework | 🟢 Düşük | Geçmiş veri ile strateji validasyonu |

## Mevcut Durum

- **State**: Geliştirme aşamasında, canlı test öncesi
- **Test coverage**: Pivot ✅, Risk Manager ✅, State Machine ✅ — 92 test pass
- **Son commit**: `cfff7c8` (nexus-mcp repo)
- **Çalışan semboller**: 22 Binance Futures perpetual
- **Aktif trade**: Yok (test aşaması)

## Bilinen Sorunlar 🐛

| Sorun | Tarih | Durum | Çözüm |
|-------|------|-------|-------|
| `AttributeError: 'RiskManager' object has no attribute 'tier_buffer'` | 2026-06-06 | ✅ Çözüldü | `_tier(symbol)` ile tier config lookup, `calculate_sl_htf` imzasına `symbol` eklendi |
| `calculate_tp_htf` çağrı imzası uyumsuzluğu | 2026-06-06 | ✅ Çözüldü | 6 parametreli hatalı çağrı 4 parametreye indirildi |
| Pylance `reportMissingImports` (models, pivot) | 2026-06-06 | ✅ Çözüldü | `.vscode/settings.json` → `python.analysis.extraPaths: ["sonnet/src"]` |

## Proje Kararlarının Evrimi

1. **SL stratejisi değişimi**: Eski FVG tabanlı SL → 4H swing high/low + tier buffer (daha güvenilir yapısal referans)
2. **TP stratejisi değişimi**: Eski default RR çarpanı → 1H BSL/SSL likidite seviyesi (piyasa yapısına uygun)
3. **SL mesafesi kısıtlaması kaldırıldı**: `build_trade` artık SL uzak diye trade reddetmez (TP 1H likiditeye sabitlendiği için)
4. **Memory Bank eklendi**: Session reset'lerinde context kaybını önlemek için 6 çekirdek dosya oluşturuldu (2026-06-06)
5. **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir — D1 bias kazanır, H4 sadece strength belirler (2026-06-06)
6. **Unit test altyapısı**: `tests/` dizini + `conftest.py` sys.path hack + 3 test dosyası — 92 test pass (2026-06-06)

