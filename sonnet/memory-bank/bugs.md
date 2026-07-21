# Bug Registry

## 🔴 P0 — Finance Risk

### P0-1: STRKUSDT çift-exit/çift-PnL (event log'dan tespit)
**Kaynak:** `events_2026-07-20.jsonl` replay
```
14:59:00 exit STRKUSDT short entry=0.029 exit=0.0287 qty=17593 pnl=4.77 result=SL
18:47:15 exit STRKUSDT short entry=0.029 exit=0.0287 qty=17593 pnl=4.77 result=SL  ← AYNI trade!
```
- **Senaryo:** WS "SL FILLED" event'i ile `_exit_already_closed` fast-path'i çalışır, REST doğrulaması OLMADAN pozisyonu kapatır. Ama pozisyon borsada açık kalır.
- **60sn'lik `_check_position`** trade'i `active_trades`'te bulamayınca `_recover_unknown_position` ile geri ekler.
- 3.5 saat sonra SL gerçekten tetiklenir, PnL **tekrar** +4.77 yazılır.
- **Risk:** Balance çift PnL ile şişer → position sizing yanlış. VEYA pozisyon 3.5 saat izlemesiz kalır.

### P0-2: `_exit_already_closed` fast-path'i REST ile pozisyon doğrulamıyor
**Dosya:** `sonnet/src/trading/exit_lifecycle.py`
- `trade.get("result") in ("SL","TP","WS_FALLBACK")` → direkt çık, `_submit_and_verify_market_close` çağrılmaz.
- Sadece WS event'ine güveniyor. WS yalancı positive verirse pozisyon borsada açık kalır, bot izlemez.
- STRKUSDT çift-exit'inin kök nedeni.

### P0-3: `_check_position()` transition-guard'sız, lock'suz
**Dosya:** `sonnet/src/bot.py` — 60sn'lik `_periodic_position_check`
- `should_skip_reconcile()` kontrolü TAMAMEN YOK.
- `TRAIL_REPLACING`, `EXIT_VERIFYING`, `REPAIR_REQUIRED` state'lerinde tetiklenebilir.
- Üç yerden eşzamanlı `repair_protection()` tetiklenebilir: (a) bu 60sn döngü, (b) WS handler, (c) ExitLifecycleService — **aralarında hiçbir lock/mutex yok**.
- Çift SL/TP emri riski.

### P0-4: OPUSDT — 2. pozisyon exit event'i hiç yazılmamış (event log kanıtlı)
**Kaynak:** `events_2026-07-20.jsonl` — 2. baş mühendis analizi
```
03:45:04 entry OPUSDT short qty=7261.9
03:45:04 force_close success=true
-- 2 saat 46 dakika BOYUNCA hiçbir "exit" event'i gelmiyor --
06:31:26 ghost_missing_sltp OPUSDT has_sl=true has_tp=false
06:31:33 orphan_cleaned OPUSDT STOP_MARKET
```
- `_submit_and_verify_market_close()`'daki 5×200ms doğrulama başarısız → trade `REPAIR_REQUIRED`'da kilitli.
- REPAIR_REQUIRED'de **otomatik retry yok** (P0-2 ile aynı kök neden).
- SL emri Binance'te 2 saat 46 dakika yalnız/yetim kaldı.
- **Ghost-position temizliği sadece bot restart'ında çalışır** (`run()` içinde bir kez), periyodik eşdeğeri yok.
- **Portföy flat'ken orphan-sweep sayacı durur** — hiçbir sembolde pozisyon yoksa `_on_1m_close` tetiklenmez, sayaç ilerlemez.
- O gün en az 2 bot restartı olmuş (ghost_missing_sltp çifti ×2).

---

## 🟠 P1 — High Risk

### P1-1: `repair_protection()` fiyatı yeniden hesaplamıyor
**Dosya:** `sonnet/src/trading/protection_lifecycle.py`
- `trade["sl"]` / `trade["tp"]`'deki eski değerleri kullanır.
- Piyasa o değerleri geçmişse emir reddedilir (immediately trigger), sessizce yutulur.
- `recovery_manager.recover_positions()`'daki "mevcut fiyata göre yeniden hesapla" fallback'i burada yok.

### P1-2: `update_trail_orders()` reject sonrası retry/backoff yok
**Dosya:** `sonnet/src/order_manager.py`
- SEIUSDT event log'u ile teyit: aynı `old_id` ile 60sn arayla 2 reject, fiyat yeniden hesaplanmıyor.
- SL trailing durur, pozisyon korumasız kalır.

### P1-3: OPUSDT — entry'den ~280ms sonra sistematik force_close
**Kaynak:** `events_2026-07-20.jsonl` (1. analiz)
- 2 ayrı OPUSDT entry'si de ~270-280ms sonra force_close ile kapanıyor.
- Olası neden: entry anındaki SL/TP mesafesi borsadaki gerçek fiyatla uyuşmuyor, emir "immediately trigger" reddi.
- entry_manager.py'de precision/fiyat hesaplama hatası olabilir.

### P1-4: Ghost/temizlik sadece restart'ta çalışır, periyodik değil
**Kaynak:** 2. baş mühendis analizi — OPUSDT event log ile kanıtlı
- `reconcile_ghost_positions()` sadece `run()` içinde bot başlangıcında **BİR KEZ** çağrılır.
- Periyodik `reconcile_orphan_orders()` portföy flat'ken **çalışmaz** (sayacı artıracak bar kapanışı yok).
- Arızalı exit'in yetim SL/TP'si sadece sonraki restart'ta temizlenir — teorik olarak sınırsız süre asılı kalabilir.

### P1-5: qty=0.1 dust exit — muhasebe kirliliği
**Kaynak:** `events_2026-07-20.jsonl` — OPUSDT force_close sonrası
```
exit OPUSDT WS_FALLBACK exit=0.0949 qty=0.1 pnl=-0.0
```
- stepSize/precision nedeniyle ana pozisyon tam kapanmaz, 0.1 birim artık kalır.
- Ayrı bir reduceOnly WS fill olarak gelir, ikinci bir "exit" kaydı oluşturur.
- `mark_sweep_consumed()`'ı o anki (farklı) RSM durumuyla tetikler — sweep seviyesi yanlış işaretlenebilir.

---

## 🟡 P2 — Medium Risk

### P2-1: `ProtectionLifecycleService.maybe_repair()` ölü kod
**Dosya:** `sonnet/src/trading/protection_lifecycle.py`
- `tests/test_protection_lifecycle.py` dışında HİÇBİR YERDEN çağrılmıyor.
- `is_sweep_consumed()` ile aynı kader.
- Asıl repair kararları inline veriliyor.

### P2-2: `CleanupPlan` eksik — prev/history/pending ID'leri iptal etmiyor
**Dosya:** `sonnet/src/trading/protection_lifecycle.py`
- `cleanup_after_confirmed_exit()` sadece `sl_order_id`/`tp_order_id` iptal ediyor.
- `sl_order_id_prev`, `tp_order_id_prev`, `pending_*`, `*_history` atlanıyor.
- **Telafi:** `order_manager.cleanup_on_exit()` sonunda `cancel_all_open_orders()` broad-sweep var — canlı modda risk düşük ama CleanupPlan başlı başına yanıltıcı.

### P2-3: `promote_sl/tp()` dokümantasyon/niyet uyuşmazlığı
**Dosya:** `sonnet/src/trading/protection_lifecycle.py`
- Doküman: "pending bekler, eski ID hemen silinmez."
- Gerçek: `begin_replace_*` + `promote_*` aynı senkron blokta çağrılır, pending state anlık.
- Şu an zararsız ama ileride yanıltıcı.

### P2-4: `PositionManager.sync()` — direction default dead kod
**Dosya:** `sonnet/src/bot_positions.py`
- `direction` önce `"long"` default (line ~750), sonra `trade.setdefault("direction", "unknown")` (line ~785). "unknown" hiç kullanılmaz.
- TP/SL reason hesabı `trade.get("direction", "long")` ile — direction yoksa short trade yanlış reason alır.

---

## 🔵 P3 — Low Risk

### P3-1: `startup_cleanup()` exception handling dağınık
**Dosya:** `sonnet/src/bot_positions.py`
- API yanıt tipleri bazı yerlerde `isinstance(x, list)` var bazı yerlerde yok.
- `algo_raw` tip doğrulaması tutarsız.

### P3-2: `MarketAnalyzer.analyze()` cyclomatic 59
**Dosya:** `sonnet/src/analyzer.py`
- İç içe conditional fazlalığı.
- `except Exception` ile hata yutma (line 888, 970).

### P3-3: Genel — `except Exception` çok yaygın
**Dosya:** `sonnet/src/` geneli
- Spesifik exception tipleri kullanılmalı.
- Type hinting var ama runtime kontrol zayıf.

---

## ✅ Verified Correct (analizlerde doğrulanan)

### V1: SEIUSDT sl_reject×2 — eski SL korunuyor ✓
- `events_2026-07-20`: aynı `old_id` ile 60sn arayla 2 reject.
- `order_manager.update_trail_orders()` yeni SL reddedilince eski SL'yi değiştirmiyor.
- Sonuç: trailing_count=3 ile orijinal SL tetiklendi, pozisyon korumasız kalmadı.

### V2: GMXUSDT force_close + WS_FALLBACK — beklenen davranış ✓
- Unmatched reduceOnly fill → `INCIDENT_WS_UNMATCHED_REDUCE_ONLY` → `WSFallbackError`.
- `user_data_handler.py`'deki tasarlanmış yol, doğru çalışıyor.

### V3: `execute()` çift tetiklenme koruması — atomic pop ✓
- `_commit_confirmed_exit()` içinde `pop()`, öncesinde `await` yok → GIL/single-thread event loop'da atomic.

### V4: `recovery_manager.reconcile_orphan_orders()` transition-aware ✓
- `should_skip_reconcile()` kontrolü doğru çalışıyor.
- `_known_protection_ids()` current+prev+history+pending'in tamamını topluyor.
- 60sn `_check_position()`'ın aksine, burada guard var.
