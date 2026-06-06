# Active Context — NEXUS V3

## Mevcut Odak
Risk yönetimi modülünde (`risk_manager.py`) bug fix tamamlandı. Sonraki adım: canlı trading testi ve monitoring.

## Son Değişiklikler

### 2026-06-06: risk_manager.py Bug Fix
- **AttributeError düzeltildi**: `calculate_sl_htf` metodunda tanımlı olmayan `self.tier_buffer`, `self.min_sl_pct`, `self.max_sl_pct`, `self.logger`, `self.symbol` referansları düzeltildi.
- **Çözüm**: `_tier(symbol)` ile tier config'ten `sl_buffer`, `min_sl_pct`, `max_sl_pct` değerleri alınıyor. Loglama modül seviyesindeki `log` ile yapılıyor.
- **Metod imzası güncellendi**: `calculate_sl_htf` artık `symbol` parametresi alıyor.
- **`calculate_tp_htf` çağrı imzası düzeltildi**: 6 parametreli hatalı çağrı, 4 parametreli doğru imzaya (`entry, risk_dist, h1_liquidity_level, state.direction`) çekildi.
- **Memory Bank oluşturuldu**: 6 çekirdek dosya yazılıyor.

## Sonraki Adımlar
1. Canlı trading testi — READY_TO_ENTER zincirinin risk_manager.py'den hatasız geçtiğini doğrula.
2. `live_trading.log` üzerinden SL/TP/lot hesaplamalarını gerçek piyasa verisiyle valide et.
3. `risk_manager.py` unit test ekle — `calculate_sl_htf`, `calculate_tp_htf`, `build_trade` için.
4. Opsiyonel: `monitor.py` health endpoint'ini Grafana/Prometheus'a bağla.

## Aktif Kararlar
- **SL stratejisi**: 4H swing high/low + tier buffer (eski FVG tabanlı SL'den geçildi).
- **TP stratejisi**: 1H BSL/SSL likidite seviyesi (eski default RR çarpanından geçildi).
- **Sweep sonrası daraltma**: Sweep level varsa SL sweep seviyesine göre ayarlanıyor (Turtle Soup koruması).
- **HTF strength scaling**: WEAK sinyallerde risk %40'a, MODERATE'te %70'e düşürülüyor.

## Önemli Desenler ve Tercihler
- `_tier(symbol)` → `TIER_MAP` ve `TIER_CFG` üzerinden sembol tier'ını çözümler.
- `build_trade` hiçbir şekilde SL mesafesine göre trade reddetmez (eski constraint kaldırıldı).
- FVG fallback: `h4_swing_level` yoksa eski FVG tabanlı SL kullanılır.
- Log seviyeleri: `log.info` (normal akış), `log.warning` (reddedilen trade), `log.debug` (fallback kullanımı).

## Öğrenimler
- `_evaluate()` pre-check layer'ı (stale + invalidation) 4-flag hard gate'ten önce çalışır.
- `_check_invalidation` anlık iğneyi değil, mum **kapanışını** kontrol eder.
- D1 bar değişiminde `_consumed_levels` likidite havuzu sıfırlanır.
- Memory Bank olmadan debug zor; her session reset'inde proje context'i kayboluyordu.
- **LTF `body_ok` sadece log'da**: `mss.py:438` — `is_valid = close_ok`. Body hesaplanır ama karar mantığına girmez. `[LTF] body_ok=False` logu debug amaçlıdır.
