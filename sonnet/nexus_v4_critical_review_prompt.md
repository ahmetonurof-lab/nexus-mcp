# NEXUS V3 — Critical Code Review Prompt

> Bu prompt, NEXUS V3 trading bot'unun tüm kaynak kodlarının acımasız, sıfır toleranslı bir şekilde analiz edilmesi için yazılmıştır. Sistem **production-ready** iddiasındadır — lütfen bu iddiayı test edin.

---

## ⚠️ ANALİZ TALİMATI

Aşağıdaki HER dosyayı **satır satır** okuyun. Hiçbir varsayım yapmayın. Gördüğünüz her sorunu raporlayın — büyüklüğü önemsiz değildir.

### Analiz Boyutları (her biri için ayrı puan verin)

| # | Boyut | Ağırlık | Açıklama |
|---|-------|---------|----------|
| 1 | **Bug / Crash Riski** | %25 | NameError, AttributeError, NoneType erişimi, race condition, sonsuz döngü, double fetch, dangling reference, asyncio misuse |
| 2 | **Mantık Hataları** | %25 | Yanlış karşılaştırma, ters yön kontrolü, eksik else, falsy/truthy bypass (0.0, ""), state machine geçersiz geçiş, eksik guard, invariant ihlali |
| 3 | **Dead Code / Kullanılmayan Kod** | %10 | Hiç çağrılmayan fonksiyon, kullanılmayan import, unreachable branch, gölgelenen değişken, etkisiz atama |
| 4 | **Tasarım / Mimari** | %20 | Döngüsel bağımlılık, God class, aşırı uzun fonksiyon (>100 satır), iç içe geçmiş blok (>4 seviye), copy-paste kod, SRP ihlali, bölünmesi gereken dosyalar |
| 5 | **Tip Güvenliği / Robustness** | %10 | Any tipi kötüye kullanımı, eksik None check, dict.get() yerine [] erişimi, exception swallowing, bare except |
| 6 | **Performans / Kaynak** | %5 | Gereksiz I/O, tekrarlayan hesaplama, memory leak potansiyeli, blocking kod |
| 7 | **Test Edilebilirlik** | %5 | Test edilemeyen side-effect, global state, singleton anti-pattern, mock zorluğu |

---

## 📂 KAYNAK DOSYALAR (okuma sırasıyla)

```
01. sonnet/src/models.py           (371 satır)  — Foundation: Bar, FVG, CHoCH dataclass'ları
02. sonnet/src/config.py           (314 satır)  — Tüm sabitler ve yapılandırma
03. sonnet/src/pivot.py            (292 satır)  — Fraktal swing tespiti + SwingStateManager
04. sonnet/src/indicators.py       (181 satır)  — EMA, SMMA, ATR, ADX (Numba JIT)
05. sonnet/src/fvg.py              (461 satır)  — FVG tespiti, state, retest, quality, sweep scoring
06. sonnet/src/mss.py              (450 satır)  — CHoCH/MSS tespiti, SMC veto
07. sonnet/src/volume_profile.py   (383 satır)  — Session VP, HVN/LVN, POC
08. sonnet/src/weekly_range_spy.py (222 satır)  — Haftalık sweep/CISD (log-only)
09. sonnet/src/scoring.py          (635 satır)  — FVG+CHoCH+rejim+konfluens skorlama
10. sonnet/src/analyzer.py         (931 satır)  — HTF bias → sweep → MSS → FVG → LTF zinciri
11. sonnet/src/event_router.py     (83 satır)   — Publisher → StateMachine yönlendirici
12. sonnet/src/state_machine.py    (814 satır)  — 10-state machine + retrace + invalidation
13. sonnet/src/risk_manager.py     (548 satır)  — SL/TP/lot + kademeli stop
14. sonnet/src/exchange.py         (921 satır)  — Binance REST istemcisi
15. sonnet/src/trader.py           (715 satır)  — MARKET/STOP_MARKET + SL/TP algo emir
16. sonnet/src/monitor.py          (436 satır)  — Runtime sayaçları + Prometheus/Grafana
17. sonnet/src/performance.py      (528 satır)  — Trade geçmişi + leaderboard
18. sonnet/src/state_logger.py     (138 satır)  — State snapshot CSV rotasyonu
19. sonnet/src/websocket.py        (651 satır)  — Multi-symbol × multi-TF WS hub
20. sonnet/src/backtest.py         (797 satır)  — BacktestEngine + VirtualExchange
21. sonnet/src/main.py             (2628 satır) — LiveTradingBot orkestrasyonu (ANA DOSYA)
```

**Toplam:** 21 dosya, ~12,500 satır kaynak kod + ~8,900 satır test

---

## 🔍 ÖZEL İNCELEME ALANLARI

### A. State Machine (state_machine.py) — KRİTİK
- `_handle_mss`: WAIT_CONFIRM gate'te direction override doğru mu? Eski displacement_origin korunuyor mu?
- `_handle_fvg`: Hangi state'lerde FVG overwrite'a izin veriliyor? Mid-setup overwrite tamamen engellenmiş mi?
- `_evaluate`: `last_closed_bar=None` geldiğinde ne oluyor? Adaptive mid-band'de `state.direction` None olabilir mi?
- `check_retrace`: `fvg_size_ratio` hesaplamasında division by zero riski var mı?
- `_check_invalidation`: MSS seviyesi güncellenmemişse (eski setup'tan kalma) yanlış invalidasyon yapabilir mi?
- `PenetrationEngine`: SHORT direction'da `price >= fvg_upper` kontrolü yeterli mi? Kenar durumlar?
- State geçiş tablosu invariantları: Hangi state hangi flag'leri zorunlu kılıyor? İhlal eden path var mı?
- `_check_stale_state`: expires_at kontrolü `current_time.timestamp()` ile yapılıyor — `created_at` UTC mi? Timezone mismatch riski?
- `_last_bar` referansı: Event'ten önce bar gelmezse None kalır — sorun mu?

### B. Risk Manager (risk_manager.py) — KRİTİK
- `calculate_sl_htf`: sweep_level=0.0 artık işleniyor — ama sweep_level negatif olabilir mi?
- `calculate_tp_htf`: Yön kontrolü `bias` parametresiyle yapılıyor — state_machine'dan gelen direction ile uyuşmazlık?
- `build_trade`: HTF strength scaling try/finally doğru çalışıyor mu? Exception'da risk_pct restore ediliyor mu?
- `_calc_stop_levels`: Sadece breakeven dönüyor artık — çağıran taraf trailing bekliyor muydu?
- `trailing_sl`: step_ratio=0.25 ile SL güncellemesi — fiyat ters yöne giderse SL geri çekilir mi?
- `calculate_lot`: `_available_margin` negatif kontrolü var — sıfır bölme riski?
- Tier konfigürasyonları: Tier eşleşmeyen sembol tier3'e düşüyor — bu bilinçli mi?

### C. Trader / Executor (trader.py) — KRİTİK
- `send_order`: SL yazılamazsa emergency close — ama close_position'da reduceOnly: True string mi bool mu?
- `_wait_for_fill`: 0.1sn × 20 = 2sn timeout — Binance gecikmesinde yetersiz kalır mı?
- `create_stop_order`: Algo emir zorunlu parametreleri (`closePosition: True`) — tüm senaryolarda doğru mu?
- `_safe_create_order`: -2021 retry mantığı sadece son denemede raise — aradaki -2021'ler nasıl işleniyor?
- `close_position`: Pozisyon yoksa False dönüyor ama caller exception handle ediyor mu?
- `fetch_position`: Exception'da None dönüyor — caller None kontrolü yapıyor mu?
- Trade locks: `trade_locks.setdefault()` thread-safe mi? Asyncio lock sözlüğü race condition?

### D. Main Orchestrator (main.py) — KRİTİK
- `_on_1m_close`: 2,628 satırlık dosyanın en karmaşık fonksiyonu — kaç satır? Kaç iç içe seviye?
- `_sync_positions`: Coverage %33 — geri kalan %67 ne? API bağımlılığı mı yoksa test edilemeyen logic mi?
- `_manage_open_trades`: Breakeven/trailing mantığı doğru yönde mi? SHORT'ta trailing SL aşağı çekiliyor mu?
- `_startup_cleanup`: 4 guard var — 5. bir edge case olabilir mi? (örn: API'da pozisyon var ama local'de order_id yok)
- `_repair_protection`: Yeni order_id'leri `active_trades` dict'ine yazıyor mu? State desync riski?
- WebSocket callback'leri: Exception'da session crash olur mu? Fire-and-forget wrapper her yerde var mı?
- `_fetch_binance_signed_post`: Retry backoff süresi yeterli mi? Rate limit aşımında ne oluyor?

### E. Analyzer / Signal Pipeline (analyzer.py + fvg.py + mss.py)
- `analyze()`: Tek fonksiyonda 931 satır — hangi sorumlulukları taşıyor? Bölünebilir mi?
- `_detect_sweep_h1`: H1 → 2H → 15m fallback zinciri — her fallback'te bar kalitesi kontrol ediliyor mu?
- `_detect_mss_events`: `since_bar_index` filtresi doğru çalışıyor mu? Eski sweep'leri filtreliyor mu?
- `score_sweep`: Graded scoring [0.0, 1.0] — edge case'ler (tek bar, 0 bar) doğru işleniyor mu?
- `compute_fvg_quality`: 6 parametre alıp sadece ilk 4'ünü mü kullanıyor? Kalan 2 neden var?
- `is_retesting_fvg`: Buffer clamp `max(..., 0.0)` — fiyat 0'a çok yakın sembollerde sorun olur mu?

### F. Exchange Layer (exchange.py)
- `_request`: Retry mantığı 429/5xx/URLError kapsıyor — connection timeout ayrı işleniyor mu?
- `create_algo_order`: Demo/paper trading fallback'i doğru mu?
- Precision helpers: `_apply_amount_precision` ve `_apply_price_precision` — 0 değer için erken return?
- `get_klines`: Time parsing UTC mi? Yaz saati riski?
- `_load_exchange_info`: Cache expiry süresi? Force refresh mekanizması?

### G. Diğer Modüller
- `websocket.py`: 110 stream tek connection'da — connection drop'ta reconnection stratejisi?
- `monitor.py`: Prometheus metrik isimlendirmesi standartlara uygun mu? Label cardinality?
- `backtest.py`: VirtualExchange — commission, spread, slippage simülasyonu gerçekçi mi?
- `state_logger.py`: CSV rotasyonu 10 gün — disk doluluğu kontrolü var mı?

---

## 📊 PUANLAMA ŞABLONU

Her analiz boyutu için **0–10 puan** verin. Toplam ağırlıklı puan üzerinden final notunu hesaplayın.

```
┌──────────────────────────────────────────────────────────┬────────┬────────┐
│ Boyut                                                     │  Puan   │ Ağırlık │
├──────────────────────────────────────────────────────────┼────────┼────────┤
│ 1. Bug / Crash Riski                                      │  ?/10   │  ×0.25 │
│ 2. Mantık Hataları                                        │  ?/10   │  ×0.25 │
│ 3. Dead Code / Kullanılmayan Kod                          │  ?/10   │  ×0.10 │
│ 4. Tasarım / Mimari                                       │  ?/10   │  ×0.20 │
│ 5. Tip Güvenliği / Robustness                             │  ?/10   │  ×0.10 │
│ 6. Performans / Kaynak                                    │  ?/10   │  ×0.05 │
│ 7. Test Edilebilirlik                                     │  ?/10   │  ×0.05 │
├──────────────────────────────────────────────────────────┼────────┼────────┤
│ AĞIRLIKLI TOPLAM                                          │  ?/10   │         │
└──────────────────────────────────────────────────────────┴────────┴────────┘
```

### Puanlama Kılavuzu
| Puan | Anlamı |
|------|--------|
| 9–10 | Production-grade, kusursuza yakın |
| 7–8 | İyi, minör iyileştirmeler yeterli |
| 5–6 | Orta, belirgin sorunlar var, düzeltilmeli |
| 3–4 | Zayıf, kritik eksikler mevcut |
| 0–2 | Ciddi sorunlu, production'a hazır değil |

---

## 📝 RAPOR FORMATI

Aşağıdaki yapıda bir rapor üretin:

### 1. YÖNETİCİ ÖZETİ (Executive Summary)
- Tek cümlede sistem durumu
- Genel not (ağırlıklı)
- En kritik 3 bulgu
- "Production'a hazır mı?" sorusuna net EVET/HAYIR

### 2. BULGU TABLOSU (Tüm bulgular öncelik sıralı)

| # | Öncelik | Dosya | Satır | Kategori | Bulgu | Etki | Önerilen Fix |
|---|---------|-------|-------|----------|-------|------|-------------|
| 1 | 🔴 P0 | ... | ... | Bug | ... | ... | ... |
| 2 | 🔴 P0 | ... | ... | Mantık | ... | ... | ... |
| ... | ... | ... | ... | ... | ... | ... | ... |

### 3. DETAYLI BULGU ANALİZİ (Her P0/P1 bulgu için)
- Mevcut kod (ilgili satırlar)
- Sorunun açıklaması
- Nasıl tetiklenir?
- Önerilen düzeltme (kod örneği ile)

### 4. MİMARİ DEĞERLENDİRME
- Bağımlılık grafiği sağlıklı mı?
- Döngüsel import var mı?
- Bölünmesi gereken dosyalar (hangileri, neden, nasıl?)
- God class / God function tespiti
- Sadeleştirme önerileri

### 5. TEST KAPSAMA DEĞERLENDİRMESİ
- Hangi modüller yeterli test kapsamına sahip?
- Hangi modüller kritik boşluklu?
- Eksik test senaryoları

### 6. PERFORMANS / KAYNAK ANALİZİ
- Gereksiz I/O noktaları
- Tekrarlayan hesaplamalar
- Memory riskleri

### 7. SONUÇ VE ÖNERİLER
- İlk 30 günde yapılması gerekenler (P0)
- İlk 90 günde yapılması gerekenler (P1)
- Uzun vadeli iyileştirmeler (P2)
