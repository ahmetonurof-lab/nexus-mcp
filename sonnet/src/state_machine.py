# state_machine.py

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

logger = logging.getLogger(__name__)

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

    def reset_flags(self):
        self.sweep_detected = False
        self.mss_confirmed = False
        self.displacement_confirmed = False
        self.retrace_seen = False
        self.ltf_confirmed = False

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

        elif event_type == "RETRACE":
            self._handle_retrace(state, event)

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
            "[MSS] %s | dir=%s | level=%s | state=%s",
            state.symbol,
            event.get("direction"),
            event.get("level"),
            state.state,
        )
        state.mss_confirmed = True
        state.mss_level = event.get("level")
        state.mss_bar_index = event.get("bar_index")  # YENİ
        state.direction = event.get("direction")

        if state.state in [SetupState.ARMED, SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM]:
            state.state = SetupState.WAIT_RETRACE

        logger.info(f"[{state.symbol}] MSS confirmed → WAIT_RETRACE")

    def _handle_fvg(self, state: SymbolState, event: dict):
        # ── Anti-resurrection guard ──
        if state.state in (SetupState.INVALIDATED, SetupState.EXPIRED, SetupState.ENTERED):
            logger.debug("[%s] FVG event reddedildi — state=%s", state.symbol, state.state)
            return
        if state.state in (SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM, SetupState.READY_TO_ENTER):
            return

        state.fvg_upper = event.get("upper")
        state.fvg_lower = event.get("lower")
        state.fvg_time = event.get("time")

        if state.mss_confirmed:
            state.state = SetupState.WAIT_RETRACE

        logger.info(f"[{state.symbol}] FVG created")

    def _handle_retrace(self, state: SymbolState, event: dict):
        logger.info(
            "[RETRACE] %s | price=%s | fvg=[%s-%s] | state=%s",
            state.symbol,
            event.get("price"),
            state.fvg_lower,
            state.fvg_upper,
            state.state,
        )
        # NoneType Çökme Koruması
        if state.fvg_lower is None or state.fvg_upper is None:
            return

        price = event.get("price")
        if price is None:
            return

        # Fiyat FVG içinde mi?
        if not (state.fvg_lower <= price <= state.fvg_upper):
            return

        # FVG zaten filled/invalidated mı? (event'ten kontrol)
        is_active = event.get("is_active", True)  # default True — geriye uyumlu
        if not is_active:
            logger.debug("[%s] FVG artık aktif değil, retrace reddedildi", state.symbol)
            return

        state.retrace_seen = True
        state.fvg_upper = event.get("fvg_upper", state.fvg_upper)
        state.fvg_lower = event.get("fvg_lower", state.fvg_lower)
        # YENİ EKLEME: CE Tap (FVG %50 teması) bilgisini kaydet
        # Bu bilgi scoring.py veya ileride ekleyeceğin filtrelerde kullanılabilir.
        state.is_ce_tap = event.get("is_ce_tap", False)

        if state.state == SetupState.WAIT_RETRACE:
            state.state = SetupState.WAIT_CONFIRM
            state.fvg_entry_bar_index = event.get("bar_index")
            logger.info(f"[{state.symbol}] Retrace into FVG → WAIT_CONFIRM (is_ce_tap={state.is_ce_tap})")

    def _handle_ltf(self, state: SymbolState, event: dict):
        if state.fvg_upper is None or state.fvg_lower is None:
            logger.warning("[%s] LTF confirm geldi ama FVG seviyeleri yok — atlandı", state.symbol)
            return

        logger.info("[LTF] %s | dir=%s | state=%s", state.symbol, event.get("direction"), state.state)
        state.ltf_confirmed = True
        state.entry_price = event.get("close")  # 5m kapanışı sakla

        if state.state == SetupState.WAIT_CONFIRM:
            # READY_TO_ENTER aşamasında bırakıyoruz ki main.py emri atabilsin
            state.state = SetupState.READY_TO_ENTER
            logger.info(f"[{state.symbol}] LTF confirm → READY_TO_ENTER")
        elif state.state == SetupState.WAIT_RETRACE:
            # RETRACE ile aynı anda geldi, _evaluate() 4 flag'i görüp çeksin
            pass

    def _handle_htf_bias(self, state: SymbolState, event: dict):
        """HTF yön biasını state'e kaydet (MSS öncesi yön tespiti)"""
        state.direction = event.get("direction")
        state.htf_bias = event.get("direction")
        state.htf_strength = event.get("strength")
        logger.info(f"[{state.symbol}] HTF bias set → {state.htf_bias} ({state.htf_strength})")

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
        # Sert kurallar kontrol edilir (Sıfır esneklik, sıfır puanlama)
        if not (state.sweep_detected and state.mss_confirmed and state.retrace_seen and state.ltf_confirmed):
            if old_state != state.state:
                logger.info("[STATE] %s: %s → %s", state.symbol, old_state, state.state)
            return

        # Main.py'nin emri kaçırmaması için state'i READY_TO_ENTER'a çekip kilidini açıyoruz
        if state.state in (SetupState.WAIT_CONFIRM, SetupState.WAIT_RETRACE):
            state.state = SetupState.READY_TO_ENTER
            logger.critical(f"[{state.symbol}] ALL CONDITIONS MET → READY_TO_ENTER ({state.direction})")

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
