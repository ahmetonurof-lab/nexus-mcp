NEXUS V3 — Mimari Dokümantasyon
1. Mimari Genel Bakış
Dosya — İşlev Tablosu
Dosya	Tek Cümleyle Ne İş Yapar
models.py	Foundation layer — Bar, FVG, CHoCH, SwingPoint dataclass'larını tanımlar, hiçbir iç modülü import etmez.
config.py	Tüm sabitler, sembol listesi, risk parametreleri, eşik değerleri.
analyzer.py	V3 Event Producer (Sensor) — HTF bias + sweep + MSS + FVG + retrace + LTF confirm event'lerini üretir, trade kararı vermez.
pivot.py	Fraktal tabanlı swing high/low tespiti + SwingStateManager ile kalıcı pivot hafızası.
mss.py (choch.py içerikli)	CHoCH/MSS tespiti + SMC mikro-yapı veto + LTFTriggerDetector (2 kriter).
fvg.py	FVG tespit motoru + state yönetimi (filled/invalidated) + retest kontrolü + quality skorlama.
indicators.py	EMA, SMMA, ATR, ADX hesaplamaları (Numba JIT hızlandırmalı).
volume_profile.py	Volume Profile (POC, VAH, VAL, HVN/LVN) + skor ayarlayıcı + TP mıknatısı.
scoring.py	Birleşik sinyal skorlama — FVG quality + CHoCH entegrasyonu + rejim tespiti + konfluens.
state_machine.py	V3 State Machine — SymbolState dataclass + state geçişleri + event handler'lar.
event_router.py	Publisher → StateMachine.update_from_event() yönlendiricisi, karar mantığı sıfır.
risk_manager.py	4H swing SL + 1H likidite TP + lot büyüklüğü + kademeli stop.
main.py	LiveTradingBot — WS hub + analyzer + state machine + executor orchestration'ı.
trader.py	ExchangeClient + LiveExecutor — MARKET emir + SL/TP algo emir + pozisyon yönetimi.
exchange.py	BinanceHTTPClient — Ham REST istemcisi, imzalı/imzasız istek, precision, kline, emir.
websocket.py	BinanceWSHub — Multi-symbol × multi-timeframe WS hub + user data stream + heartbeat.
monitor.py	Runtime observasyon — tick/signal/order/fill/reject sayaçları + health endpoint.
performance.py	Trade geçmişi kaydı + leaderboard.
Bağımlılık Zinciri (Tek Yönlü)

Apply
models.py  (bağımlılık yok — foundation)
    ↑
pivot.py ─┐
indicators.py ─┐
    ↓           ↓
fvg.py ───→ mss.py (choch) ───→ analyzer.py
    ↓                              ↓
scoring.py                  event_router.py
                                ↓
                          state_machine.py
                                ↓
                          risk_manager.py
                                ↓
                          trader.py ← exchange.py
                                ↓
                          main.py ← websocket.py
                                ↓
                          monitor.py
                          performance.py
2. State Machine Akışı
State'ler ve Geçiş Koşulları (state_machine.py)

Apply
                     ┌──────────────────────────────────────┐
                     │              IDLE                     │
                     │  (başlangıç / temiz state)            │
                     └──────────┬───────────────────────────┘
                                │ SWEEP event (15m)
                                ▼
                     ┌──────────────────────────────────────┐
                     │              ARMED                    │
                     │  sweep_detected=true                  │
                     │  sweep_level set                      │
                     └──────────┬───────────────────────────┘
                                │ MSS event
                                ▼
                     ┌──────────────────────────────────────┐
                     │           WAIT_RETRACE                │
                     │  mss_confirmed=true                   │
                     │  direction=MSS yönü                   │
                     │  FVG_CREATED ile de buraya geçer      │
                     └──────────┬───────────────────────────┘
                                │ RETRACE event (fiyat FVG içinde)
                                ▼
                     ┌──────────────────────────────────────┐
                     │           WAIT_CONFIRM                │
                     │  retrace_seen=true                    │
                     └──────────┬───────────────────────────┘
                                │ LTF_CONFIRM event
                                ▼
                     ┌──────────────────────────────────────┐
                     │         READY_TO_ENTER               │
                     │  ltf_confirmed=true                   │
                     │  entry_price set                      │
                     │  → main.py emri gönderir              │
                     └──────────┬───────────────────────────┘
                                │ main.py → set_state(ENTERED)
                                ▼
                     ┌──────────────────────────────────────┐
                     │            ENTERED                    │
                     │  (pozisyon açık, koruma aktif)        │
                     └──────────┬───────────────────────────┘
                                │ expire / invalidate
                                ▼
                     ┌──────────────────────────────────────┐
                     │   EXPIRED / INVALIDATED               │
                     └──────────────────────────────────────┘
Her State'te Hangi Dosya/Metod Çalışıyor
State	Çalışan Kod	Dosya
IDLE → _handle_sweep	state.sweep_detected=True; state.state="ARMED"	state_machine.py
ARMED → _handle_mss	state.mss_confirmed=True; state.state="WAIT_RETRACE"	state_machine.py
WAIT_RETRACE → _handle_retrace	Fiyat FVG içinde mi kontrolü → WAIT_CONFIRM	state_machine.py
WAIT_CONFIRM → _handle_ltf	state.ltf_confirmed=True; state.state="READY_TO_ENTER"	state_machine.py
READY_TO_ENTER	risk_mgr.build_trade() → LiveExecutor.send_order()	main.py:_on_5m_close
ENTERED	_manage_open_trades() (breakeven/trailing) + _sync_positions()	main.py
EXPIRED	state.is_expired() kontrolü (zaman aşımı)	state_machine.py
Event Handler Haritası
Event Tipi	Handler	Ne Yapar
HTF_BIAS	_handle_htf_bias	state.direction ve state.htf_bias'ı set eder
HTF_LEVELS	_handle_htf_levels	state.h4_swing_level, state.h1_liquidity_level set eder
SWEEP	_handle_sweep	IDLE → ARMED geçişini tetikler
MSS	_handle_mss	ARMED → WAIT_RETRACE geçişi
FVG_CREATED	_handle_fvg	FVG seviyelerini kaydeder
RETRACE	_handle_retrace	Fiyat FVG içinde mi kontrol eder
LTF_CONFIRM	_handle_ltf	WAIT_CONFIRM → READY_TO_ENTER
_evaluate() — Pre-Check + Sert Kural Motoru

Python

Apply
def _evaluate(self, state: SymbolState, current_time: datetime | None = None, last_closed_bar=None):
    # ── Pre-checks: Zombi temizliği ve invalidation ──
    if current_time is None:
        current_time = datetime.now()

    if self._check_stale_state(state, current_time):
        return
    if self._check_invalidation(state, last_closed_bar):
        return

    if not (state.sweep_detected and state.mss_confirmed
            and state.retrace_seen and state.ltf_confirmed):
        return
    if state.state == SetupState.WAIT_CONFIRM:
        state.state = SetupState.READY_TO_ENTER

_check_stale_state() — Zombi Temizliği

Python

Apply
def _check_stale_state(self, state: SymbolState, current_time: datetime) -> bool:
    """Zombi setup'ları çöpe atar."""
    if state.state in ["ARMED", "WAIT_RETRACE", "WAIT_CONFIRM"]:
        max_wait_hours = getattr(self.config, "MAX_SETUP_WAIT_HOURS", 24.0)
        hours_elapsed = (current_time - datetime.fromtimestamp(state.created_at)).total_seconds() / 3600
        if hours_elapsed > max_wait_hours:
            state.state = "IDLE"
            state.reset_flags()
            return True
    return False

_check_invalidation() — Yapısal Kırılım İptali

Python

Apply
def _check_invalidation(self, state: SymbolState, last_closed_bar) -> bool:
    """Fiyat setup'ın tersine YAPSAL bir kırılım (Mum Kapanışı) yaptıysa iptal et."""
    if last_closed_bar is None:
        return False
    if state.state in ["ARMED", "WAIT_RETRACE", "WAIT_CONFIRM"]:
        mss_level = getattr(state, 'mss_break_level', None)
        if not mss_level:
            return False
        # Anlık iğne değil, kapanış kontrolü!
        if state.direction == "SHORT" and last_closed_bar.close > mss_level:
            state.state = "IDLE"
            state.reset_flags()
            return True
        elif state.direction == "LONG" and last_closed_bar.close < mss_level:
            state.state = "IDLE"
            state.reset_flags()
            return True
    return False

Dört koşulun tamamı True olmadan READY_TO_ENTER'a geçiş mümkün değil. Pre-check'ler (stale + invalidation) diğer tüm event'lerden önce çalışır.

3. Timeframe Hiyerarşisi
Kullanım Amacı
Timeframe	Amaç	Kullanıldığı Yer
1D (Daily)	HTF bias tespiti — BOS yönü, swing high/low	analyzer.py:_detect_htf_bias (D1_BOS_LOOKBACK=25)
4H	HTF bias teyidi + SL referansı (swing low/high)	analyzer.py:_detect_htf_bias, _detect_h4_swing_level
1H	TP referansı — BSL/SSL likidite seviyesi	analyzer.py:_detect_h1_liquidity
15m	SWEEP + MSS + FVG tespiti (ana işlem TF'i)	analyzer.py:_detect_sweep_15m, _detect_mss_events, analyze()
5m	LTF Confirm (2 kriterli tetikleyici - V1) + entry kapanışı	analyzer.py:_detect_ltf_confirm, main.py:_on_5m_close
Fonksiyon-TF Matrisi
Python

Apply
# analyzer.py — analyze() çağrısı
events = self.analyzers[symbol].analyze(
    bars_d1=bars_d1,      # → _detect_htf_bias
    bars_h4=bars_h4,      # → _detect_htf_bias (teyit) + _detect_h4_swing_level
    bars_h1=bars_h1,      # → _detect_h1_liquidity
    bars_15m=bars_15m,    # → _detect_sweep_15m + _detect_mss_events + detect_fvgs
    bars_m5=bars_m5,      # → _detect_ltf_confirm
)
Veri Akışı:


Apply
Daily Cache (REST) → bars_d1
WebSocket 4h stream → bars_h4
WebSocket 1h stream → bars_h1
WebSocket 15m stream → bars_15m
WebSocket 5m stream → bars_m5  ← 5m kapanışı TÜM analizi TETİKLER
4. Sinyal Üretim Zinciri (IDLE → READY_TO_ENTER)
Adım 0: HTF Bias (Ana Filtre)
Python

Apply
# analyzer.py — analyze()
bias = self._detect_htf_bias(bars_d1, bars_h4)
if bias is None:
    return events  # BOŞ LİSTE — hiç event üretilmez

events.append({"type": "HTF_BIAS", "direction": bias})

h4_sl = self._detect_h4_swing_level(bars_h4, bias)
h1_tp = self._detect_h1_liquidity(bars_h1, bias)

events.append({"type": "HTF_LEVELS", ...})

# D1 bar değişti mi? → likidite havuzunu sıfırla
if bars_d1:
    last_d1_idx = bars_d1[-1].index
    if last_d1_idx != self._last_d1_index:
        self._consumed_levels.clear()
        self._last_d1_index = last_d1_idx
        logger.info("[RESET] %s günlük likidite havuzu sıfırlandı")

Kriter: 1D BOS yönü belirlenemezse → tüm sistem durur.

Adım 1: SWEEP (15m) — Likidite Havuzu Dedup
Python

Apply
# analyzer.py — _detect_sweep_15m
consumed = self._consumed_levels.setdefault(symbol, set())

if bias == "LONG":
    # SSL sweep: fiyat swing low altına indi mi?
    for sl in reversed(lows[-5:]):
        if sl.price in consumed:    # ← DEDUP: daha önce tüketildiyse atla
            continue
        if current_close < sl.price:
            consumed.add(sl.price)  # ← tüketildi olarak işaretle
            events.append({"type": "SWEEP", "side": "SSL", "level": sl.price})
            break
else:  # SHORT
    for sh in reversed(highs[-5:]):
        if sh.price in consumed:
            continue
        if current_close > sh.price:
            consumed.add(sh.price)
            events.append({"type": "SWEEP", "side": "BSL", "level": sh.price})
            break
Kriter (LONG): Fiyat son 5 swing low'dan birinin altına indi → SSL sweep.
Kriter (SHORT): Fiyat son 5 swing high'dan birinin üstüne çıktı → BSL sweep.
NOT: `_consumed_levels` D1 bar değişiminde `analyze()` içinde sıfırlanır → "[RESET] {symbol} gunluk likidite havuzu sifirlandi"

Adım 2: MSS (15m, Bias Filtreli)
Python

Apply
# analyzer.py — _detect_mss_events
# Sadece bias yönüyle eşleşen MSS'ler emit edilir
if direction != bias:
    continue  # ters yön MSS filtrelenir
Kriter: MSS yönü = bias yönü (aksi halde emit edilmez).

Adım 3: FVG (15m, Bias Filtreli)
Python

Apply
fvgs = detect_fvgs(bars_15m, lookback=60, timeframe="15m")
fvg_direction = "bullish" if bias == "LONG" else "bearish"
fvgs = [f for f in fvgs if f.direction == fvg_direction]
Kriter: FVG direction = bias yönü. FVG tanımı: 3-mum imbalance (prev.high < curr.low (bullish) veya prev.low > curr.high (bearish)).

Adım 4: RETRACE — 3-Aşamalı SMC Filtresi
Python

Apply
# analyzer.py — _detect_retrace
for f in fvgs:
    if not f.is_active: continue

    # 1. KESİŞİM (Touch): Mum fitili FVG içinde mi?
    touched = (current_bar.high >= f.bottom) and (current_bar.low <= f.top)
    if not touched: continue

    # 2. SAYGI (Respect): Kapanış FVG'yi delip geçmedi mi?
    if bias == "SHORT":
        respected = current_bar.close <= f.top
    else:
        respected = current_bar.close >= f.bottom
    if not respected:
        object.__setattr__(f, "invalidated", True)  # FVG delindi
        continue

    # 3. DERİNLİK (CE Tap): Fitil FVG %50'sine ulaştı mı?
    ce_level = (f.top + f.bottom) / 2.0
    deep_enough = (current_bar.high >= ce_level) if bias == "SHORT" \
                  else (current_bar.low <= ce_level)

    return [{"type": "RETRACE", "is_ce_tap": deep_enough, ...}]
Kriter: 3 aşamanın tamamı geçilmeli. FVG invalidated olursa bir daha kullanılmaz.
EXPECTED LOG: `"[RETRACE-DETAIL] {symbol} | fvg=[{bottom}-{top}] touched=True respected=True deep=True"`

Adım 5: LTF Confirm (5m, V1 — 2 Kriter)

Python

Apply
# mss.py — LTFTriggerDetector.validate()
İki kriterin ikisi de TRUE olmalı:

1. Güçlü gövde — bar.body ≥ body_atr_mult × ATR(14)
2. Pivot kırılımı — close > retracement_swing.price (bullish)
                       close < retracement_swing.price (bearish)

Python

Apply
# Kriter 1 — Body ATR karşılaştırması
result.body_ok = cur.body >= atr * self.body_atr_mult   # default body_atr_mult = 0.5

# Kriter 2 — Retracement swing kırılımı (analyzer.py bulur)
result.close_ok = bar.close > retracement_swing.price    # bullish
result.close_ok = bar.close < retracement_swing.price    # bearish

result.is_valid = all([result.body_ok, result.close_ok])
Biri bile FALSE → tüm sinyal iptal.

NOT: 4-kriterli sistem (body+volume+fvg+close) kaldırıldı.
Yeni V1'de sadece 2 kriter var: güçlü gövde + pivot kırılımı.

5. Risk Yönetimi
Entry Hesaplama
Python

Apply
# risk_manager.py — build_trade()
if entry_price is not None:
    entry = round(entry_price, 5)  # 5m confirmation kapanışı
else:
    # Fallback: FVG midpoint
    fvg_mid = (state.fvg_upper + state.fvg_lower) / 2.0
    entry = round(fvg_mid, 5)
Birincil: 5m LTF confirm mumunun kapanış fiyatı. Fallback: FVG midpoint (ortalama).

SL Hesaplama — 4H Swing Tabanlı
Python

Apply
# risk_manager.py — calculate_sl_htf()
if direction == "long":
    raw_sl = h4_swing_level * (1.0 - buf)  # 4H swing low altı
else:
    raw_sl = h4_swing_level * (1.0 + buf)  # 4H swing high üstü

# min_sl_pct / max_sl_pct ile makul aralık kontrolü
if dist < min_dist:  # çok yakınsa minimuma çek
    raw_sl = (entry - min_dist) if direction == "long" else (entry + min_dist)
if dist > max_dist:  # çok genişse reddet
    return None
SL formülü: 4H swing seviyesi × (1 ± tier_buffer) Tier buffer: tier1=%0.15, tier2=%0.30, tier3=%0.60 Max SL: tier1=%2.5, tier2=%3.0, tier3=%3.5 (aşarsa trade reddedilir)

TP Hesaplama — 1H Likidite Tabanlı
Python

Apply
# risk_manager.py — calculate_tp_htf()
if h1_liquidity_level is not None:
    reward_dist = abs(h1_liquidity_level - entry)
    rr = reward_dist / risk_dist
    if rr >= self.min_rr:  # min_rr = 2.0
        return round(h1_liquidity_level, 5)  # 1H BSL/SSL kullan
# Fallback: default_rr × risk_distance
tp = entry + risk_dist * min(default_rr, tier["max_rr"])
TP önceliği:

1H BSL (LONG) / SSL (SHORT) — R:R ≥ 2.0 olmalı
Fallback — default_rr × SL mesafesi
Lot Hesaplama
Python

Apply
# risk_manager.py — calculate_lot()
risk_usd = self._available_margin * self.risk_pct   # risk_pct = %0.5-3.0
sl_dist = abs(entry - sl)
raw_lot = risk_usd / sl_dist
max_lot = (available_margin * leverage * margin_usage) / entry
lot = min(raw_lot, max_lot)
Formül: risk_usd / SL_mesafesi, kaldıraç ve marjin ile sınırlı.

Kademeli Stop Seviyeleri
Kademe hesaplama (build_trade içinde):
Python

Apply
# risk_manager.py — _calc_stop_levels()
# Kademe 1 (breakeven): Fiyat 1R gittiğinde SL = entry
breakeven_trigger = entry + risk_dist * BREAKEVEN_R  # BREAKEVEN_R = 1.0

# Kademe 2 (trailing): Fiyat 2R gittiğinde SL = 1R
trailing_sl = entry + risk_dist * (TRAILING_ACTIVATE_R - 1.0)  # TRAILING_ACTIVATE_R = 2.0
Runtime yönetimi (main.py _manage_open_trades tarafından çağrılır):

should_move_to_breakeven(trade, current_price) → bool:
Python

Apply
# risk_manager.py — should_move_to_breakeven()
# Fiyat breakeven tetikleme seviyesine (1R) ulasti mi?
# LONG:  current_price >= trade["breakeven_level"]
# SHORT: current_price <= trade["breakeven_level"]
# trade'de breakeven_level yoksa entry ± risk_dist * BREAKEVEN_R ile hesaplar
breakeven_sl(trade) → float:
Python

Apply
# risk_manager.py — breakeven_sl()
# SL'yi entry fiyatina çeker (zarar yok)
return trade["entry"]
trailing_sl(trade, current_price, current_sl, step_ratio=0.25) → float:
Python

Apply
# risk_manager.py — trailing_sl()
# Kademeli trailing stop (breakeven sonrasinda, 2R+ kârdayken)
# LONG:  new_sl = current_sl + (current_price - current_sl) * step_ratio
# SHORT: new_sl = current_sl - (current_sl - current_price) * step_ratio
# step_ratio = TRAILING_STEP_RATIO = 0.25
Kademe	Tetiklenme	SL Nereye	Metod
Breakeven	Fiyat +1R gidince	SL → entry (zarar yok)	should_move_to_breakeven() + breakeven_sl()
Trailing	Breakeven sonrası	SL yukarı kayar	trailing_sl() step_ratio=0.25 ile
6. HTF Bias (1D BOS Yönü)
1D Bias Tespiti

Python

Apply
# analyzer.py — _detect_htf_bias()
lookback_d1 = min(config.D1_BOS_LOOKBACK, len(bars_d1))  # 25 bar
segment_d1 = bars_d1[-lookback_d1:]

d1_highs = find_swing_highs(segment_d1, left=2, right=2)
d1_lows = find_swing_lows(segment_d1, left=2, right=2)
last_close_d1 = bars_d1[-1].close

last_bull_bos: int = -1
last_bear_bos: int = -1

# En son kırılan swing hangisi?
for sh in d1_highs:
    if last_close_d1 > sh.price:
        if sh.bar_index > last_bull_bos:
            last_bull_bos = sh.bar_index  # LONG sinyali

for sl in d1_lows:
    if last_close_d1 < sl.price:
        if sl.bar_index > last_bear_bos:
            last_bear_bos = sl.bar_index  # SHORT sinyali

# Hiçbir BOS kırılmamışsa None döner — tüm sistem durur
if last_bull_bos == -1 and last_bear_bos == -1:
    return None

d1_bias = "LONG" if last_bull_bos >= last_bear_bos else "SHORT"
Mantık: D1'de son 25 bar içinde swing high kırıldıysa → LONG, swing low kırıldıysa → SHORT. Hangisi daha güncelse bias odur. Hiçbiri kırılmamışsa → None.

4H Teyit Mantığı

Python

Apply
# Aynı mantık H4'te tekrarlanır (H4_BOS_LOOKBACK kadar bar)
h4_bias: Literal["LONG", "SHORT"] | None = None

if bars_h4 and len(bars_h4) >= 5:
    lookback_h4 = min(config.H4_BOS_LOOKBACK, len(bars_h4))
    segment_h4 = bars_h4[-lookback_h4:]

    h4_highs = find_swing_highs(segment_h4, left=2, right=2)
    h4_lows = find_swing_lows(segment_h4, left=2, right=2)
    last_close_h4 = bars_h4[-1].close

    last_bull_h4: int = -1
    last_bear_h4: int = -1

    for sh in h4_highs:
        if last_close_h4 > sh.price and sh.bar_index > last_bull_h4:
            last_bull_h4 = sh.bar_index

    for sl in h4_lows:
        if last_close_h4 < sl.price and sl.bar_index > last_bear_h4:
            last_bear_h4 = sl.bar_index

    # H4'te BOS varsa bias hesapla, yoksa None kalır
    if last_bull_h4 != -1 or last_bear_h4 != -1:
        h4_bias = "LONG" if last_bull_h4 >= last_bear_h4 else "SHORT"

# ── Sonuç tablosu ──
if h4_bias is None:
    logger.info("D1=%s H4=belirsiz → D1 kazanır", d1_bias)
elif h4_bias == d1_bias:
    logger.info("D1=%s H4=%s → GÜÇLÜ bias", d1_bias, h4_bias)
else:
    logger.info("D1=%s H4=%s → ZAYIF bias, D1 kazanır", d1_bias, h4_bias)
Kural:

| D1 | H4 | Sonuç |
|---|---|---|
| LONG | LONG | GÜÇLÜ bias |
| SHORT | SHORT | GÜÇLÜ bias |
| LONG | SHORT | ZAYIF bias, D1 kazanır |
| LONG | H4 belirsiz | ZAYIF bias, D1 kazanır |
| None | — | Sistem durur (event üretilmez) |

Bias Yoksa?

Python

Apply
bias = self._detect_htf_bias(bars_d1, bars_h4)
if bias is None:
    logger.info("[ANALYZE] %s: HTF bias yok, event üretilmiyor.", self.symbol)
    return events  # BOŞ LİSTE
Hiçbir event üretilmez. State machine IDLE kalır. Sistem çalışmaya devam eder ama hiçbir sinyal üretilmez.

7. Koruma Mekanizmaları
7.1. State Persistence (nexus_state.json)
Python

Apply
# main.py — LiveTradingBot
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "nexus_state.json")

def _flush_state(self):
    """active_trades + symbol_states → JSON dosyasına yaz"""
    symbol_states = {
        sym: {
            "setup_id": f"{sym}_{st.created_at}_{st.direction}",
            "state": st.state.value,
            "direction": st.direction,
            "fvg_upper": st.fvg_upper,
            "fvg_lower": st.fvg_lower,
            "sweep_level": st.sweep_level,
            "mss_break_level": st.mss_level,
            "created_at": st.created_at,
            "expires_at": st.expires_at,
        }
        for sym in config.SYMBOLS
        if st and st.state and st.state.value != "IDLE"
    }
    json.dump({"active_trades": self.active_trades, "symbol_states": symbol_states}, f)

def _load_state(self):
    """Startup'ta JSON'dan oku, state'i geri yükle"""
    for sym, s in states.items():
        st = self.state_machine.get(sym)
        st.state = SetupState(s.get("state", "IDLE"))
        st.direction = s.get("direction")
        st.fvg_upper = s.get("fvg_upper")
        # ... tüm alanlar geri yüklenir
Ne zaman yazılır: Trade açıldığında (_flush_state()). Ne zaman okunur: Startup'ta (run() → _load_state()).

7.2. WS Kopunca Ne Olur
Python

Apply
# websocket.py — BinanceWSHub.run()
# Exponential back-off ile otomatik yeniden bağlanma
delay = self.reconnect_delay  # 2sn
while not self._stop_event.is_set():
    try:
        await self._connect_and_listen()
        delay = self.reconnect_delay  # başarılı → reset
    except (ConnectionClosed, TimeoutError, OSError):
        delay = min(delay * 2, self.max_reconnect_delay)  # 60sn max
        await asyncio.sleep(delay)
WS kopma senaryosu:

Exponential back-off ile yeniden bağlanma (2sn → 4sn → 8sn → ... → 60sn)
heartbeat_monitor — her 30 sn'de bir son tick zamanını kontrol eder
Timeout: 5m için 450sn, 15m için 1350sn tolerans
WS kapalıyken yeni sinyal ÜRETİLMEZ (bar gelmez)
Açık pozisyonlar Binance'te korunmaya devam eder (SL/TP API'de durur)
User data stream ayrı WS bağlantısı üzerinden ayrıca yönetilir
7.3. Duplikasyon/Duplicate Emir Koruması
Startup Cleanup (Sorgusuz İnfaz Protokolü):

Python

Apply
# main.py — _startup_cleanup()
# 1. API'den tüm açık emirleri çek (normal + algo)
all_orders = await self._fetch_binance_signed("/fapi/v1/openOrders")
algo_orders = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders")

# 2. Sembole göre grupla
orders_by_symbol = group_by_symbol(all_orders + algo_orders)

for symbol, orders in orders_by_symbol.items():
    if symbol not in symbols_with_position:
        # ORPHAN: emir var, pozisyon yok → HEPSi iptal
        if symbol in self.active_trades:
            continue  # ORPHAN-GUARD: local state varsa ATLA
        cancel_all(orders)
    else:
        sl_orders = [o for o in orders if is_stop_loss(o)]
        tp_orders = [o for o in orders if is_take_profit(o)]

        if len(sl_orders) > 1 or len(tp_orders) > 1:
            # DUPLICATE: >1 SL veya >1 TP → TÜM koruma SİLİNİR
            # Safe Mode: sıfırdan kurulacak
            cancel_all(sl_orders + tp_orders)
Runtime Duplicate Koruması:

Python

Apply
# main.py — _sync_positions()
# Her döngüde API'den sorgula
sl_orders = [o for o in open_orders if is_sl(o)]
tp_orders = [o for o in open_orders if is_tp(o)]

if len(sl_orders) > 1 or len(tp_orders) > 1:
    # SORGUSUZ İNFAZ — tüm korumayı sil, sıfırdan kur
    cancel_all(sl_orders + tp_orders)
    await self._create_protection(symbol, trade)
Pending Symbol Koruması (Race Condition):

Python

Apply
# trader.py — LiveExecutor.send_order()
if symbol in self._pending_symbols:
    log.warning("Zaten bekleyen emir var → atlanıyor")
    return None

async with lock:  # asyncio.Lock ile thread-safe
    self._pending_symbols.add(symbol)
    # ... emir gönder ...
    self._pending_symbols.discard(symbol)
Cooldown:

Python

Apply
# trader.py — LiveExecutor
def _check_cooldown(self, symbol: str) -> bool:
    last = self._last_order_time.get(symbol, 0)
    if time.time() - last < self.cooldown_seconds:  # 2sn
        return True  # cooldown aktif, emir atlanır
Safe Mode:

Python

Apply
# main.py — active_trades[symbol]["protection_missing"] = True
# → yeni sinyal ENGELLENİR
# → sadece izleme modu
# → repair_protection() düzeltene kadar devam eder
if existing.get("protection_missing"):
    log.warning("🟡 SAFE MODE | %s | yeni sinyal ENGELLENDİ", symbol)
    return
7.4. Minimum Yaş Süresi (Breakeven/Trailing Koruması)
Python

Apply
# main.py — _manage_open_trades()
open_time = trade.get("open_time", 0)
if open_time and (current_time_ms - open_time) < 300_000:  # 5 dakika
    log.info("[MANAGE] %s işlemi henüz çok taze — Breakeven/Trailing atlandı.")
    continue
İşlem açıldıktan sonra ilk 5 dakika boyunca hiçbir stop güncellemesi yapılmaz.

7.5. API Rate Limit Koruması
Python

Apply
# main.py — LiveTradingBot
self._api_semaphore = asyncio.Semaphore(5)  # maks 5 eşzamanlı istek

# Her istek semafor üzerinden geçer
async with self._api_semaphore:
    # ... imzalı HTTP isteği ...
Tüm _fetch_binance_signed* çağrıları _api_semaphore ile sınırlandırılmıştır.

Özet: NEXUS V3, event-driven mimariyle çalışan, SMC (Smart Money Concepts) prensiplerine dayalı bir kripto trading botudur. HTF bias ana filtre olarak çalışır, 15m'de yapısal kırılımları tespit eder, 5m'de son onayı alır ve 4H swing + 1H likidite bazlı risk yönetimiyle emir gönderir. Çok katmanlı koruma mekanizmaları (persistence, WS auto-reconnect, duplicate infaz, safe mode, cooldown, semaphore) ile production-ready seviyededir.
