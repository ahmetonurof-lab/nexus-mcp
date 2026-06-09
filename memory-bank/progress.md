# Progress — NEXUS V3

## Çalışanlar ✅

| Bileşen | Durum | Not |
|----------|-------|-----|
| `models.py` | ✅ | Bar, FVG, CHoCH, SwingPoint dataclass'ları |
| `config.py` | ✅ | Tüm sabitler, sembol listesi, risk parametreleri, HTF_STRICT_FILTER=False, MISSED_FVG_ATR_MULT, POI_ATR_BUFFER |
| `pivot.py` | ✅ | Fraktal swing tespiti + SwingStateManager |
| `indicators.py` | ✅ | EMA, SMMA, ATR, ADX (Numba JIT) |
| `fvg.py` | ✅ | FVG tespiti, state yönetimi, retest, quality |
| `mss.py` | ✅ | CHoCH/MSS tespiti, SMC mikro-yapı veto |
| `analyzer.py` | ✅ | HTF bias → sweep → MSS → FVG → LTF zinciri + impulse_origin hesaplama |
| `scoring.py` | ✅ | FVG quality + CHoCH + rejim + konfluens skorlama |
| `event_router.py` | ✅ | Publisher → StateMachine yönlendirici (zero logic, single pipeline) |
| `state_machine.py` | ✅ | 10-state machine + pre-check layer + FVG Missed Flow (MISSED_FVG, WAIT_POI_CONFIRM, check_poi_retrace) + 3 Patch + MISSED_FVG_ATR_MULT isim uyumu + set_state() log düzeltmesi + ATR parametre geçişi |
| `exchange.py` | ✅ | Binance REST istemcisi |
| `trader.py` | ✅ | MARKET + SL/TP algo emir + pozisyon yönetimi |
| `websocket.py` | ✅ | Multi-symbol × multi-TF WS hub |
| `main.py` | ✅ | LiveTradingBot orkestrasyonu + check_poi_retrace çağrısı + STATE-DEBUG fvg= dinamik alan + ATR hesaplama & persist (fvg_missed, displacement_origin, poi_anchor) + TimedRotatingFileHandler (midnight, 10 backup) + strategy audit trail (23 alan active_trades'e eklendi) |
| `monitor.py` | ✅ | Runtime sayaçları + health endpoint |
| `performance.py` | ✅ | Trade geçmişi + leaderboard + STRATEGY_FIELDS yeniden yapılanması (HTF bias, sweep, MSS, FVG, killzone, state) + _write_strategy_csv() yeniden yazıldı |
| `risk_manager.py` | ✅ | 4H swing SL + 1H likidite TP + lot + kademeli stop (bug fix 2026-06-06) |
| `volume_profile.py` | ✅ | Session bazlı VP hesaplama; HVN/LVN skor adjuster + POC TP mıknatısı |
| `weekly_range_spy.py` | ✅ | Haftalık HH/LL sweep + CISD tespiti (log-only, trade açmaz) |
| `test_pivot.py` | ✅ | 22 test — swing highs/lows, SwingStateManager |
| `test_risk_manager.py` | ✅ | 40+ test — SL/TP/lot/build_trade |
| `test_state_machine.py` | ✅ | 30 test — state geçişleri, pre-check, retrace, flag gate |

## Kalan İşler 🔧

| Görev | Öncelik | Açıklama |
|-------|---------|----------|
| FVG Missed Flow canlı/backtest doğrulaması | 🔴 Yüksek | Case C patikasının (MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER) log'da görünüp görünmediğini kontrol et |
| `DEFAULT_ATR` / `ATR_MAP` config'e ekle | 🟡 Orta | `_get_atr()` şu anda fallback olarak None döner; canlıda exchange.atr() ile beslenebilir |
| Canlı trading testi | 🟡 Orta | READY_TO_ENTER zincirinin Case C path'te de hatasız çalıştığını doğrula |
| `analyzer.py` unit test | 🟡 Orta | `impulse_origin` hesaplaması dahil MSS event testi |
| Integration test | 🟡 Orta | Tam zincir: WebSocket → analyzer → state → trade (Case A + Case C) |
| Grafana/Prometheus bağlantısı | 🟢 Düşük | `monitor.py` health endpoint'i |
| Backtesting framework | 🟢 Düşük | Geçmiş veri ile strateji validasyonu |

## Mevcut Durum

- **State**: FVG Missed Flow + 3 Patch + isim uyumu + STATE-DEBUG fvg= tamam, 4 lint aracı geçiyor (ruff ✅ ruff-format ✅ mypy ✅ vulture ✅)
- **Test coverage**: Pivot ✅, Risk Manager ✅, State Machine ✅ — 29 test pass
- **Son değişiklik**: Logging altyapısı — `import logging.handlers` + `TimedRotatingFileHandler` (midnight rotation, 10 backup) eklendi (2026-06-09)
- **Çalışan semboller**: 22 Binance Futures perpetual
- **Aktif trade**: Yok (test aşaması)

## Bilinen Sorunlar 🐛

| Sorun | Tarih | Durum | Çözüm |
|-------|------|-------|-------|
| V-shape hareketlerde sonsuz WAIT_RETRACE zombisi | 2026-06-08 | ✅ Çözüldü | FVG Missed Flow: _check_missed_fvg + check_poi_retrace + _evaluate Case C path |
| Semboller WAIT_RETRACE'te takılı: sweep=False, mss_confirmed=True, fvg_upper=None | 2026-06-07 | ✅ Çözüldü | Fix 1: MSS upstream guard; Fix 2: reset_symbol_cache(); Fix 3+3b: lifecycle coupling |
| `_emitted_fvg_ids` / `_seen_mss` state reset'te temizlenmiyordu | 2026-06-07 | ✅ Çözüldü | reset_symbol_cache() eklendi, _clear_state ve state-diff hook'a bağlandı |
| `_mss_state` (SwingStateManager) reset'te temizlenmiyordu | 2026-06-07 | ✅ Çözüldü | reset_symbol_cache() içinde self._mss_state = SwingStateManager() |
| AttributeError: RiskManager tier_buffer | 2026-06-06 | ✅ Çözüldü | _tier(symbol) ile tier config lookup |
| calculate_tp_htf çağrı imzası uyumsuzluğu | 2026-06-06 | ✅ Çözüldü | 6 parametreli hatalı çağrı 4 parametreye indirildi |
| Pylance reportMissingImports (models, pivot) | 2026-06-06 | ✅ Çözüldü | .vscode/settings.json → python.analysis.extraPaths |

## Proje Kararlarının Evrimi

1. **SL stratejisi değişimi**: Eski FVG tabanlı SL → 4H swing high/low + tier buffer
2. **TP stratejisi değişimi**: Eski default RR çarpanı → 1H BSL/SSL likidite seviyesi
3. **SL mesafesi kısıtlaması kaldırıldı**: build_trade artık SL uzak diye trade reddetmez
4. **Memory Bank eklendi**: 6 çekirdek dosya (2026-06-06)
5. **HTF_STRICT_FILTER=False**: H4 D1'e tersse işlem alınabilir (2026-06-06)
6. **Unit test altyapısı**: tests/ + conftest.py + 3 test dosyası — 92 test pass (2026-06-06)
7. **MSS = anchored event**: since_bar_index=None → MSS taraması yapılmaz (2026-06-07)
8. **State machine = truth, analyzer cache = derived ephemeral state**: reset_symbol_cache() IDLE glue'su (2026-06-07)
9. **FVG Missed Flow (Case C)**: Fiyat FVG'yi hiç görmeden kaçarsa MISSED_FVG state'i, poi_anchor, WAIT_POI_CONFIRM → READY_TO_ENTER (2026-06-08)
10. **MISSED_FVG_ATR_MULT isim uyumu**: config.py + state_machine.py aynı sabit ismini kullanıyor (2026-06-08)
11. **STATE-DEBUG fvg=**: Tek dinamik alan — FVG durumunu tek satırda gösterir (2026-06-08)
12. **set_state() log düzeltmesi**: "manually forced" → "State geçişi: X → Y" formatı — sembol bazlı tutarlı log (2026-06-09)
13. **ATR parametre geçişi**: `_get_atr()` fallback kaldırıldı — ATR artık `main.py`'den `compute_atr_point(bars_15m)` ile hesaplanıp `atr=` parametresi olarak `check_retrace()`, `_check_missed_fvg()`, `check_poi_retrace()`'a geçiriliyor. `fvg_missed`, `displacement_origin`, `poi_anchor` persist/restore ediliyor (2026-06-09)
