# Project Brief — NEXUS V3

## Proje Tanımı
NEXUS V3, Binance Futures üzerinde çalışan tam otomatik bir SMC (Smart Money Concepts) trading botudur. 4H swing SL + 1H likidite TP tabanlı risk yönetimi ile 15m timeframe'te işlem açar.

## Temel Gereksinimler
1. **Tam otomatik trade**: IDLE → READY_TO_ENTER → ENTERED state zincirini takip eder, manuel müdahale gerektirmez.
2. **SMC tabanlı sinyal üretimi**: Sweep (likidite avı) → MSS (yapısal kırılım) → FVG → Retrace → LTF Confirm zinciri.
3. **Çoklu timeframe analizi**: 1D bias, 4H swing SL, 1H likidite TP, 15m ana işlem, 5m onay.
4. **Risk yönetimi**: Tier bazlı (Tier1/2/3) SL buffer, lot büyüklüğü, kademeli stop (breakeven + trailing).
5. **Canlı WebSocket bağlantısı**: Multi-symbol × multi-timeframe Binance WS hub.

## Proje Kapsamı
- 22 Binance Futures perpetual sembolü (BTC, ETH, SOL, XRP, ADA, vb.)
- Tier1/2/3 risk sınıflandırması
- Canlı emir gönderimi (MARKET + SL/TP algo order)
- Runtime monitoring (tick/signal/order/fill/reject sayaçları)
- Trade geçmişi ve performans takibi

## Kapsam Dışı
- Backtesting
- Spot trading
- Grid/DCA stratejileri
- UI dashboard (şimdilik sadece log + monitoring endpoint)
