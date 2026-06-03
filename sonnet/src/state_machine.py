# state_machine.py

import logging
import time
from dataclasses import dataclass, field
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
    entry_price: float | None = None  # 5m confirmation kapanışı

    # HTF / 15m structure
    fvg_upper: float | None = None
    fvg_lower: float | None = None
    fvg_time: int | None = None

    sweep_level: float | None = None
    mss_level: float | None = None
    h4_swing_level: float | None = None  # 4H swing low (long) / high (short)
    h1_liquidity_level: float | None = None  # 1H BSL (long) / SSL (short)

    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None

    # flags
    sweep_detected: bool = False
    mss_confirmed: bool = False
    displacement_confirmed: bool = False
    retrace_seen: bool = False
    ltf_confirmed: bool = False

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


# ─────────────────────────────────────────────
# STATE MACHINE CORE
# ─────────────────────────────────────────────


class StateMachine:
    def __init__(self):
        self.symbols: dict[str, SymbolState] = {}

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

    def _handle_sweep(self, state: SymbolState, event: dict):
        logger.info("[SWEEP] %s | tf=%s | level=%s | state=%s", state.symbol, event.get("tf"), event.get("level"), state.state)
        # Sadece 15m likidite süpürmeleri sistemi tetikleyebilir
        if event.get("tf") not in ["15m"]:
            return

        state.sweep_detected = True
        state.sweep_level = event.get("level")

        if state.state == SetupState.IDLE:
            state.state = SetupState.ARMED
            logger.info(f"[{state.symbol}] HTF SWEEP detected ({event.get('tf')}) → SYSTEM ARMED")

    def _handle_mss(self, state: SymbolState, event: dict):
        logger.info("[MSS] %s | dir=%s | level=%s | state=%s", state.symbol, event.get("direction"), event.get("level"), state.state)
        state.mss_confirmed = True
        state.mss_level = event.get("level")
        state.direction = event.get("direction")

        if state.state in [SetupState.ARMED, SetupState.WAIT_RETRACE]:
            state.state = SetupState.WAIT_RETRACE

        logger.info(f"[{state.symbol}] MSS confirmed → WAIT_RETRACE")

    def _handle_fvg(self, state: SymbolState, event: dict):
        state.fvg_upper = event.get("upper")
        state.fvg_lower = event.get("lower")
        state.fvg_time = event.get("time")

        if state.mss_confirmed:
            state.state = SetupState.WAIT_RETRACE

        logger.info(f"[{state.symbol}] FVG created")

    def _handle_retrace(self, state: SymbolState, event: dict):
        logger.info("[RETRACE] %s | price=%s | fvg=[%s-%s] | state=%s", state.symbol, event.get("price"), state.fvg_lower, state.fvg_upper, state.state)
        # NoneType Çökme Koruması
        if state.fvg_lower is None or state.fvg_upper is None:
            return

        price = event.get("price")

        if state.fvg_lower <= price <= state.fvg_upper:
            state.retrace_seen = True

            if state.state == SetupState.WAIT_RETRACE:
                state.state = SetupState.WAIT_CONFIRM
                logger.info(f"[{state.symbol}] Retrace into FVG → WAIT_CONFIRM")

    def _handle_ltf(self, state: SymbolState, event: dict):
        logger.info("[LTF] %s | dir=%s | state=%s", state.symbol, event.get("direction"), state.state)
        state.ltf_confirmed = True
        state.entry_price = event.get("close")  # 5m kapanışı sakla

        if state.state == SetupState.WAIT_CONFIRM:
            # READY_TO_ENTER aşamasında bırakıyoruz ki main.py emri atabilsin
            state.state = SetupState.READY_TO_ENTER
            logger.info(f"[{state.symbol}] LTF confirm → READY_TO_ENTER")

    def _handle_htf_bias(self, state: SymbolState, event: dict):
        """HTF yön biasını state'e kaydet (MSS öncesi yön tespiti)"""
        state.direction = event.get("direction")
        state.htf_bias = event.get("direction")
        logger.info(f"[{state.symbol}] HTF bias set → {state.htf_bias}")

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

    def _evaluate(self, state: SymbolState):
        logger.info("[EVALUATE] %s | sweep=%s mss=%s retrace=%s ltf=%s | state=%s", state.symbol, state.sweep_detected, state.mss_confirmed, state.retrace_seen, state.ltf_confirmed, state.state)
        # Sert kurallar kontrol edilir (Sıfır esneklik, sıfır puanlama)
        if not (state.sweep_detected and state.mss_confirmed and state.retrace_seen and state.ltf_confirmed):
            return

        # Main.py'nin emri kaçırmaması için state'i READY_TO_ENTER'a çekip kilidini açıyoruz
        if state.state == SetupState.WAIT_CONFIRM:
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
