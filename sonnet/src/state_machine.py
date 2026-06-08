# state_machine.py

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from models import Bar

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# ─────────────────────────────────────────────
# STATE DEFINITIONS
# ─────────────────────────────────────────────


class SetupState(StrEnum):
    IDLE = "IDLE"
    ARMED = "ARMED"
    WAIT_RETRACE = "WAIT_RETRACE"
    WAIT_CONFIRM = "WAIT_CONFIRM"
    READY_TO_ENTER = "READY_TO_ENTER"
    ENTERED = "ENTERED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    MISSED_FVG = "MISSED_FVG"
    WAIT_POI_CONFIRM = "WAIT_POI_CONFIRM"


# ─────────────────────────────────────────────
# CORE DATA MODEL
# ─────────────────────────────────────────────


@dataclass
class SymbolState:
    symbol: str

    state: SetupState = SetupState.IDLE
    direction: str | None = None  # LONG / SHORT
    htf_bias: str | None = None  # MSS sonrası HTF yön biası
    htf_strength: str | None = None  # "STRONG", "MODERATE", "WEAK"
    entry_price: float | None = None  # 5m confirmation kapanışı

    # HTF / 15m structure
    fvg_upper: float | None = None
    fvg_lower: float | None = None
    fvg_time: int | None = None

    sweep_level: float | None = None
    sweep_bar_index: int | None = None  # YENİ: sweep bar index
    mss_level: float | None = None
    mss_bar_index: int | None = None  # YENİ: mss bar index
    h4_swing_level: float | None = None  # 4H swing low (long) / high (short)
    h1_liquidity_level: float | None = None  # 1H BSL (long) / SSL (short)

    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None

    # flags
    # FVG giriş bar index'i (5m) — WAIT_CONFIRM'e geçerken kaydedilir
    fvg_entry_bar_index: int | None = None

    # flags
    sweep_detected: bool = False
    mss_confirmed: bool = False
    displacement_confirmed: bool = False
    retrace_seen: bool = False
    ltf_confirmed: bool = False
    is_ce_tap: bool = False  # CE Tap: FVG %50 teması (scoring.py / filtreler için)

    # --- FVG MISSED FLOW ---
    fvg_missed: bool = False
    poi_anchor: float | None = None  # displacement_origin fiyatı
    poi_anchor_bar_index: int | None = None  # displacement_origin bar index'i
    displacement_origin: float | None = None  # MSS impulse başlangıç noktası
    missed_fvg_at_price: float | None = None  # MISSED anındaki fiyat (loglama)

    def reset_flags(self):
        self.sweep_detected = False
        self.mss_confirmed = False
        self.displacement_confirmed = False
        self.retrace_seen = False
        self.ltf_confirmed = False

        self.sweep_level = None
        self.sweep_bar_index = None

        self.mss_level = None
        self.mss_bar_index = None

        self.fvg_upper = None
        self.fvg_lower = None
        self.fvg_time = None

        self.direction = None
        self.entry_price = None
        self.fvg_entry_bar_index = None

        # FVG MISSED FLOW reset
        self.fvg_missed = False
        self.poi_anchor = None
        self.poi_anchor_bar_index = None
        self.displacement_origin = None
        self.missed_fvg_at_price = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


# ─────────────────────────────────────────────
# STATE MACHINE CORE
# ─────────────────────────────────────────────


class StateMachine:
    def __init__(self, config=None):
        self.symbols: dict[str, SymbolState] = {}
        self.config = config

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def get(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(symbol=symbol)
        return self.symbols[symbol]

    def update_from_event(self, symbol: str, event: dict):
        """
        Entry point from analyzer.py
        event = normalized market event (NO decision logic inside analyzer)
        """
        state = self.get(symbol)

        if state.is_expired():
            state.state = SetupState.EXPIRED
            return

        event_type = event.get("type")

        if event_type == "SWEEP":
            self._handle_sweep(state, event)

        elif event_type == "MSS":
            self._handle_mss(state, event)

        elif event_type == "FVG_CREATED":
            self._handle_fvg(state, event)

        elif event_type == "LTF_CONFIRM":
            self._handle_ltf(state, event)

        elif event_type == "HTF_BIAS":
            self._handle_htf_bias(state, event)

        elif event_type == "HTF_LEVELS":
            self._handle_htf_levels(state, event)

        self._evaluate(state)

    # ─────────────────────────────────────────
    # EVENT HANDLERS
    # ─────────────────────────────────────────

    def _handle_sweep(self, state, event):
        if event.get("tf") not in ["15m"]:
            return
        if state.state != SetupState.IDLE:
            logger.debug("[%s] Sweep atlandı — state=%s", state.symbol, state.state)
            return
        state.sweep_detected = True
        state.sweep_level = event.get("level")
        state.sweep_bar_index = event.get("bar_index")  # YENİ
        state.expires_at = int(time.time()) + (getattr(self.config, "MAX_SETUP_WAIT_HOURS", 24.0) * 3600)
        state.state = SetupState.ARMED
        logger.info("[%s] SWEEP → ARMED | level=%s", state.symbol, event.get("level"))

    def _handle_mss(self, state: SymbolState, event: dict):
        logger.info(
            "[MSS-HANDLE] symbol=%s state=%s level=%s dir=%s",
            state.symbol,
            state.state,
            event.get("level"),
            event.get("direction"),
        )

        if state.state not in (
            SetupState.ARMED,
            SetupState.WAIT_RETRACE,
            SetupState.WAIT_CONFIRM,
        ):
            logger.warning(
                "[MSS-SKIP] %s state=%s MSS reddedildi level=%s dir=%s",
                state.symbol,
                state.state,
                event.get("level"),
                event.get("direction"),
            )
            return

        state.mss_confirmed = True
        state.mss_level = event.get("level")
        state.mss_bar_index = event.get("bar_index")

        # YENİ: impulse başlangıcını kaydet
        # analyzer.py'dan "impulse_origin" alanını event içine koy
        state.displacement_origin = event.get("impulse_origin", event.get("level"))

        # HTF bias zaten direction set ettiyse overwrite etme
        if state.direction is None:
            state.direction = event.get("direction")

        if state.state in (SetupState.ARMED, SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM):
            state.state = SetupState.WAIT_RETRACE

        logger.info("[%s] MSS confirmed → WAIT_RETRACE", state.symbol)

    def _handle_fvg(self, state: SymbolState, event: dict):
        # Terminal state'lerde FVG kabul edilmez
        if state.state in (SetupState.INVALIDATED, SetupState.EXPIRED, SetupState.ENTERED):
            logger.debug("[%s] FVG event reddedildi — state=%s", state.symbol, state.state)
            return

        # FVG değerlerini her zaman güncelle (WAIT_RETRACE dahil)
        state.fvg_upper = event.get("upper")
        state.fvg_lower = event.get("lower")
        state.fvg_time = event.get("time")

        # WAIT_RETRACE/WAIT_CONFIRM/READY_TO_ENTER → değerleri güncelle, state'i değiştirme
        # (Daha iyi FVG gelirse referans güncellenir, zincir bozulmaz)
        if state.state in (SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM, SetupState.READY_TO_ENTER):
            logger.info("[%s] FVG güncellendi — state=%s", state.symbol, state.state)
            return

        # IDLE / ARMED → MSS varsa WAIT_RETRACE'e geç
        if state.mss_confirmed:
            state.state = SetupState.WAIT_RETRACE

        logger.info("[%s] FVG kaydedildi | upper=%.5f lower=%.5f", state.symbol, state.fvg_upper, state.fvg_lower)

    def check_retrace(self, symbol: str, current_bar: Bar) -> None:
        """
        Her yeni kapanan barda ana event loop tarafından çağrılır.
        Analyzer'dan bağımsız olarak state machine kendi FVG referansıyla
        retrace kontrolü yapar.

        WAIT_RETRACE → WAIT_CONFIRM geçişi için iki şart aynı anda sağlanmalı:

          1. CE Şartı (%50):
             LONG  → current_bar.low  <= fvg_mid  (fitil mid'e değdi veya geçti)
             SHORT → current_bar.high >= fvg_mid  (fitil mid'e değdi veya geçti)

          2. Gövde Kapanışı (FVG içinde):
             LONG  → fvg_lower <= current_bar.close <= fvg_upper
             SHORT → fvg_lower <= current_bar.close <= fvg_upper
             (Sadece fitil yetmez — gövde FVG içinde kapanmalı)
        """
        state = self.get(symbol)

        if state.state != SetupState.WAIT_RETRACE:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            logger.info("[%s] _check_retrace: FVG seviyeleri yok, atlandı", symbol)
            return
        if state.direction is None:
            return

        fvg_mid = (state.fvg_upper + state.fvg_lower) / 2.0

        # ── Case B: Invalidation ─────────────────────────────────────────────
        # (mevcut _check_invalidation() zaten bunu yapıyor, burada tekrar kontrol yok)

        # ── Case A: Classic CE tap ────────────────────────────────────────────
        if state.direction == "LONG":
            ce_touched = current_bar.low <= fvg_mid
        else:  # SHORT
            ce_touched = current_bar.high >= fvg_mid

        body_inside = state.fvg_lower <= current_bar.close <= state.fvg_upper

        logger.debug(
            "[%s] check_retrace | dir=%s | ce_touched=%s body_inside=%s "
            "| low=%.5f high=%.5f close=%.5f | fvg=[%.5f-%.5f] mid=%.5f",
            symbol,
            state.direction,
            ce_touched,
            body_inside,
            current_bar.low,
            current_bar.high,
            current_bar.close,
            state.fvg_lower,
            state.fvg_upper,
            fvg_mid,
        )

        if ce_touched and body_inside:
            state.retrace_seen = True
            state.is_ce_tap = True
            state.fvg_entry_bar_index = current_bar.index
            state.state = SetupState.WAIT_CONFIRM
            logger.info(
                "[%s] CASE A — CE + body → WAIT_CONFIRM | close=%.5f | fvg=[%.5f-%.5f] mid=%.5f",
                symbol,
                current_bar.close,
                state.fvg_lower,
                state.fvg_upper,
                fvg_mid,
            )
            return

        # ── Case C: Missed FVG ───────────────────────────────────────────────
        self._check_missed_fvg(state, current_bar)

    # ── Missed FVG Detection ──────────────────────────────────────────────────

    def _check_missed_fvg(self, state: SymbolState, current_bar: Bar) -> None:
        """
        Case C: FVG hiç dokunulmadı, fiyat güçlü displacement ile uzaklaştı.
        Koşul (ikisi birden sağlanmalı):
          1. CE hiç dokunulmadı (retrace_seen == False)
          2. Fiyat FVG'den MISSED_ATR_MULT * ATR uzaklaştı (yön uyumlu)
        Aksiyon:
          - fvg_missed = True
          - poi_anchor = displacement_origin
          - state → MISSED_FVG
        """
        if state.retrace_seen:
            return
        if state.displacement_origin is None:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            return

        atr = self._get_atr(state.symbol)
        if atr is None or atr <= 0:
            return

        missed_atr_mult = getattr(self.config, "MISSED_ATR_MULT", 1.5)
        threshold = missed_atr_mult * atr
        fvg_mid = (state.fvg_upper + state.fvg_lower) / 2.0

        if state.direction == "LONG":
            # Fiyat FVG ortasının threshold kadar ÜSTÜNE çıktıysa
            moved_away = current_bar.close > (fvg_mid + threshold)
        else:
            # Fiyat FVG ortasının threshold kadar ALTINA indi
            moved_away = current_bar.close < (fvg_mid - threshold)

        if not moved_away:
            return

        # ── Transition ───────────────────────────────────────────
        state.fvg_missed = True
        state.missed_fvg_at_price = current_bar.close
        state.poi_anchor = state.displacement_origin
        state.poi_anchor_bar_index = current_bar.index
        state.state = SetupState.MISSED_FVG

        logger.warning(
            "[%s] CASE C — MISSED_FVG | close=%.5f fvg_mid=%.5f " "threshold=%.5f → poi_anchor=%.5f",
            state.symbol,
            current_bar.close,
            fvg_mid,
            threshold,
            state.poi_anchor,
        )

    # ── POI Retrace (MISSED_FVG → WAIT_POI_CONFIRM) ─────────────────────────

    def check_poi_retrace(self, symbol: str, current_bar: Bar) -> None:
        """
        MISSED_FVG state'inde: fiyat poi_anchor'a ±POI_ATR_BUFFER*ATR
        mesafesine gelirse WAIT_POI_CONFIRM'e geç.
        Her 5m kapanışında _on_5m_close() içinden çağrılır.
        """
        state = self.get(symbol)
        if state.state != SetupState.MISSED_FVG:
            return
        if state.poi_anchor is None:
            return

        atr = self._get_atr(state.symbol)
        if atr is None or atr <= 0:
            return

        poi_atr_buffer = getattr(self.config, "POI_ATR_BUFFER", 0.3)
        buffer = poi_atr_buffer * atr
        anchor = state.poi_anchor

        if state.direction == "LONG":
            in_zone = (anchor - buffer) <= current_bar.low <= (anchor + buffer)
        else:
            in_zone = (anchor - buffer) <= current_bar.high <= (anchor + buffer)

        if not in_zone:
            return

        state.state = SetupState.WAIT_POI_CONFIRM
        logger.info(
            "[%s] MISSED_FVG → WAIT_POI_CONFIRM | " "price=%.5f anchor=%.5f buffer=%.5f",
            state.symbol,
            current_bar.close,
            anchor,
            buffer,
        )

    # ── ATR Cache ─────────────────────────────────────────────────────────────

    def _get_atr(self, symbol: str) -> float | None:
        """
        Rolling ATR değerini config veya exchange üzerinden alır.
        Config'de ATR_MAP varsa oradan, yoksa DEFAULT_ATR fallback.
        Canlı sistemde exchange.atr(symbol) ile beslenir.
        """
        atr_map = getattr(self.config, "ATR_MAP", None)
        if atr_map and symbol in atr_map:
            return float(atr_map[symbol])
        return getattr(self.config, "DEFAULT_ATR", None)

    def _handle_ltf(self, state: SymbolState, event: dict):
        # [FIX-4] State guard: LTF sadece WAIT_CONFIRM veya WAIT_RETRACE'de kabul edilir.
        # Guard olmazsa: her 5m kapanışında analyzer LTF event üretiyor, IDLE/ARMED
        # state'lerinde ltf_confirmed=True set ediliyor ve flag reset_flags() çağrılmadan
        # sonsuza kadar takılı kalıyor (log: "[LTF] SOLUSDT | state=IDLE").
        if state.state not in (SetupState.WAIT_CONFIRM, SetupState.WAIT_RETRACE):
            logger.debug(
                "[LTF-SKIP] %s state=%s — WAIT_CONFIRM/WAIT_RETRACE dışında LTF reddedildi",
                state.symbol,
                state.state,
            )
            return

        if state.fvg_upper is None or state.fvg_lower is None:
            logger.warning("[%s] LTF confirm geldi ama FVG seviyeleri yok — atlandı", state.symbol)
            return

        logger.info("[LTF] %s | dir=%s | state=%s", state.symbol, event.get("direction"), state.state)
        state.ltf_confirmed = True
        state.entry_price = event.get("close")  # 5m kapanışı sakla

        if state.state == SetupState.WAIT_CONFIRM:
            state.state = SetupState.READY_TO_ENTER
            logger.info("[%s] LTF confirm → READY_TO_ENTER", state.symbol)
        elif state.state == SetupState.WAIT_RETRACE:
            # RETRACE ile aynı anda geldi, _evaluate() 4 flag'i görüp çeksin
            pass

    def _handle_htf_bias(self, state: SymbolState, event: dict):
        """HTF yön biasını state'e kaydet (MSS öncesi yön tespiti)"""
        state.htf_bias = event.get("direction")
        state.htf_strength = event.get("strength")
        # [FIX-5] Setup aktifken (ARMED ve sonrası) direction'ı override etme.
        # MSS/sweep ile set edilmiş direction, HTF bias değişimiyle ezilirse
        # aktif setup yanlış yönde devam eder.
        if state.state == SetupState.IDLE:
            state.direction = event.get("direction")
        logger.info("[%s] HTF bias set → %s (%s)", state.symbol, state.htf_bias, state.htf_strength)

    def _handle_htf_levels(self, state: SymbolState, event: dict):
        state.h4_swing_level = event.get("h4_swing_level")
        state.h1_liquidity_level = event.get("h1_liquidity_level")
        logger.debug(
            "[%s] HTF levels — h4_sl=%s h1_tp=%s",
            state.symbol,
            state.h4_swing_level,
            state.h1_liquidity_level,
        )

    # ─────────────────────────────────────────
    # DECISION LAYER
    # ─────────────────────────────────────────

    def _check_stale_state(self, state: SymbolState, current_time: datetime) -> bool:
        """Zombi setup'ları çöpe atar — expires_at bazlı."""
        if state.state in ["ARMED", "WAIT_RETRACE", "WAIT_CONFIRM"]:
            if state.expires_at is not None and current_time.timestamp() > state.expires_at:
                logger.warning(
                    f"[{state.symbol}] ZOMBİ SETUP TEMİZLENDİ | " f"State={state.state} | expires_at aşıldı → IDLE"
                )
                state.state = SetupState.IDLE
                state.reset_flags()
                return True
        return False

    def _check_invalidation(self, state: SymbolState, last_closed_bar) -> bool:
        """
        Fiyat setup'ın tersine YAPSAL bir kırılım (Mum Kapanışı) yaptıysa iptal et.
        last_closed_bar: En son kapanan mum objesi (close değerini içerir)
        """
        if last_closed_bar is None:
            return False
        if state.state in [SetupState.ARMED, SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM]:
            # State içinde mss_break_level yoksa koruma amaçlı çık (Fail-safe)
            mss_level = getattr(state, "mss_level", None)
            if not mss_level:
                return False

            # Anlık fiyat (current_price) yerine kapanış (close) kontrolü!
            # Böylece anlık iğneler (stop hunt'lar) setup'ı piç etmez.
            if state.direction == "SHORT" and last_closed_bar.close > mss_level:
                logger.warning(
                    f"[{state.symbol}] INVALIDATION | Mum Kapanışı ({last_closed_bar.close}) "
                    f"SHORT MSS seviyesini ({mss_level}) aştı. Yapı bozuldu → IDLE"
                )
                state.state = SetupState.IDLE
                state.reset_flags()
                return True
            elif state.direction == "LONG" and last_closed_bar.close < mss_level:
                logger.warning(
                    f"[{state.symbol}] INVALIDATION | Mum Kapanışı ({last_closed_bar.close}) "
                    f"LONG MSS seviyesinin altına indi. Yapı bozuldu → IDLE"
                )
                state.state = SetupState.IDLE
                state.reset_flags()
                return True
        return False

    def _evaluate(self, state: SymbolState, current_time: datetime | None = None, last_closed_bar=None):
        # ── Pre-checks: Zombi temizliği ve invalidation ──
        if current_time is None:
            current_time = datetime.now()

        if self._check_stale_state(state, current_time):
            return
        if self._check_invalidation(state, last_closed_bar):
            return

        old_state = state.state

        logger.debug(
            "[EVALUATE] %s | sweep=%s mss=%s retrace=%s ltf=%s | state=%s",
            state.symbol,
            state.sweep_detected,
            state.mss_confirmed,
            state.retrace_seen,
            state.ltf_confirmed,
            state.state,
        )
        # ── Case A path: 4-flag kontrolü (classic CE tap) ──
        if state.sweep_detected and state.mss_confirmed and state.retrace_seen and state.ltf_confirmed:
            if state.state in (SetupState.WAIT_CONFIRM, SetupState.WAIT_RETRACE):
                state.state = SetupState.READY_TO_ENTER
                logger.critical("[%s] CASE A → READY_TO_ENTER", state.symbol)
            return

        # ── Case C path: missed FVG recovery (poi_anchor) ──
        if state.sweep_detected and state.mss_confirmed and state.fvg_missed and state.ltf_confirmed:
            if state.state == SetupState.WAIT_POI_CONFIRM:
                state.state = SetupState.READY_TO_ENTER
                logger.critical("[%s] CASE C → READY_TO_ENTER (poi_anchor)", state.symbol)
            return

        if old_state != state.state:
            logger.info("[STATE] %s: %s → %s", state.symbol, old_state, state.state)

    # ─────────────────────────────────────────
    # CLEANUP & MANUAL MANIPULATION
    # ─────────────────────────────────────────

    def set_state(self, symbol: str, new_state: SetupState):
        """Allows main.py to set state to ENTERED after successful order placement"""
        state = self.get(symbol)
        state.state = new_state
        logger.info(f"[{symbol}] State manually forced to {new_state}")

    def invalidate(self, symbol: str):
        state = self.get(symbol)
        state.state = SetupState.INVALIDATED

    def clear(self, symbol: str):
        if symbol in self.symbols:
            del self.symbols[symbol]
