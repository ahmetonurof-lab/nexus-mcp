# Product Context — NEXUS V3

## Neden Var?
NEXUS V3, SMC (Smart Money Concepts) stratejisine dayalı tam otomatik bir trading botudur. Manuel trading'deki duygusal kararları, gecikmeleri ve tutarsızlıkları ortadan kaldırmak için tasarlanmıştır.

## Hangi Sorunu Çözüyor?
1. **Likidite avlarını tespit etmek**: Piyasa yapıcıların stop-loss'ları tetiklemek için yaptığı sweep hareketlerini yakalar.
2. **Yapısal kırılımları doğrulamak**: CHoCH/MSS ile trend dönüşlerini erkenden tespit eder.
3. **Optimal entry noktası bulmak**: FVG (Fair Value Gap) retrace'i ile en düşük riskli girişi hesaplar.
4. **Tutarlı risk yönetimi**: Tier bazlı pozisyon büyüklüğü ve kademeli stop-loss yönetimi.

## Nasıl Çalışır?
1. WebSocket üzerinden 22 sembolün 5 timeframe (1D, 4H, 1H, 15m, 5m) bar verisi alınır.
2. Her 5m kapanışında `analyzer.py` sinyal zincirini çalıştırır:
   - D1/4H bias → 15m sweep → 15m MSS → 15m FVG → retrace → 5m LTF confirm
3. State machine IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER zincirini yönetir.
4. `READY_TO_ENTER` durumunda `risk_manager.py` SL/TP/lot hesaplar, `trader.py` emri gönderir.
5. Açık pozisyonlar `_manage_open_trades()` ile breakeven/trailing stop yönetimi altında izlenir.

## Kullanıcı Deneyimi Hedefleri
- **Sıfır manuel müdahale**: Bot başlatıldıktan sonra tüm kararları kendisi verir.
- **Şeffaf loglama**: Her event, state geçişi ve trade kararı loglanır.
- **Runtime monitoring**: `monitor.py` üzerinden tick/signal/order/fill/reject sayaçları ve health endpoint.
- **Güvenli risk limitleri**: Sembol başına tier sınıflandırması ile risk otomatik ölçeklenir.

## Hedef Kitle
- SMC stratejisini otomatize etmek isteyen retail trader'lar
- Çoklu sembol takibi yapamayan part-time trader'lar
- Duygusal trading kararlarını elimine etmek isteyen disiplinli yatırımcılar
