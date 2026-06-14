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
    WAIT_NEW_FVG = "WAIT_NEW_FVG"
    MISSED_FVG = "MISSED_FVG"
    WAIT_POI_CONFIRM = "WAIT_POI_CONFIRM"
    READY_TO_ENTER = "READY_TO_ENTER"
    ENTERED = "ENTERED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


# ─────────────────────────────────────────────
# PENETRATION ENGINE
# ─────────────────────────────────────────────


class PenetrationEngine:
    """
    FVG içine penetration oranını 0→1 ölçeğinde hesaplar.

    SHORT: anchor = fvg_upper, price yukarıdan aşağı girer
           price = fvg_upper → pen=0 | price = fvg_lower → pen=1
    LONG:  anchor = fvg_lower, price aşağıdan yukarı girer
           price = fvg_lower → pen=0 | price = fvg_upper → pen=1

    Unified formula:
        penetration = |price - anchor| / |fvg_upper - fvg_lower|
    """

    def __init__(self, fvg_upper: float, fvg_lower: float, direction: str) -> None:
        self.fvg_upper = fvg_upper
        self.fvg_lower = fvg_lower
        self.direction = direction
        self.size = abs(fvg_upper - fvg_lower)

    def get_penetration(self, price: float) -> float:
        if self.size == 0:
            return 0.0
        if self.direction == "SHORT":
            # SHORT: price yukarıdan aşağı girer
            if price >= self.fvg_upper:
                return 0.0  # henüz FVG'ye girmedi
            if price <= self.fvg_lower:
                return 1.0  # FVG'yi tamamen geçti
            return (self.fvg_upper - price) / self.size
        else:  # LONG
            # LONG: price aşağıdan yukarı girer
            if price <= self.fvg_lower:
                return 0.0  # henüz FVG'ye girmedi
            if price >= self.fvg_upper:
                return 1.0  # FVG'yi tamamen geçti
            return (price - self.fvg_lower) / self.size


# ─────────────────────────────────────────────
# CORE DATA MODEL
# ─────────────────────────────────────────────


@dataclass
class SymbolState:
    symbol: str

    state: SetupState = SetupState.IDLE
    direction: str | None = None  # LONG / SHORT
    htf_bias: str | None = None
    htf_strength: str | None = None
    entry_price: float | None = None

    # HTF / 15m structure
    fvg_upper: float | None = None
    fvg_lower: float | None = None
    fvg_time: int | None = None

    sweep_level: float | None = None
    sweep_bar_index: int | None = None
    sweep_tf: str | None = None  # 1H / 2H — telemetry only
    mss_level: float | None = None
    mss_bar_index: int | None = None
    h4_swing_level: float | None = None
    h1_liquidity_level: float | None = None

    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None

    wait_confirm_since_ts: int | None = None
    fvg_entry_bar_index: int | None = None

    sweep_detected: bool = False
    mss_confirmed: bool = False
    displacement_confirmed: bool = False
    retrace_seen: bool = False
    ltf_confirmed: bool = False
    is_ce_tap: bool = False

    # FVG Missed Flow (Case C)
    fvg_missed: bool = False
    displacement_origin: float | None = None
    poi_anchor: float | None = None
    poi_anchor_bar_index: int | None = None
    missed_fvg_at_price: float | None = None
    missed_fvg_bar_index: int | None = None
    displacement_high: float | None = None
    displacement_low: float | None = None

    def reset_flags(self):
        self.sweep_detected = False
        self.mss_confirmed = False
        self.displacement_confirmed = False
        self.retrace_seen = False
        self.ltf_confirmed = False

        self.sweep_level = None
        self.sweep_bar_index = None
        self.sweep_tf = None

        self.mss_level = None
        self.mss_bar_index = None

        self.fvg_upper = None
        self.fvg_lower = None
        self.fvg_time = None

        self.direction = None
        self.entry_price = None
        self.fvg_entry_bar_index = None

        # FVG Missed Flow
        self.fvg_missed = False
        self.displacement_origin = None
        self.poi_anchor = None
        self.poi_anchor_bar_index = None
        self.missed_fvg_at_price = None
        self.missed_fvg_bar_index = None
        self.displacement_high = None
        self.displacement_low = None

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
        self._last_bar: Bar | None = None  # zombie setup invalidation için son kapanan bar

    # ─────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────

    def get(self, symbol: str) -> SymbolState:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolState(symbol=symbol)
        return self.symbols[symbol]

    def update_from_event(self, symbol: str, event: dict):
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

        self._evaluate(state, last_closed_bar=self._last_bar)

    # ─────────────────────────────────────────
    # EVENT HANDLERS
    # ─────────────────────────────────────────

    def _handle_sweep(self, state: SymbolState, event: dict):
        if event.get("tf") not in ("1H", "2H", "15m"):
            return
        if state.state != SetupState.IDLE:
            logger.debug("[%s] Sweep atlandı — state=%s", state.symbol, state.state)
            return
        state.sweep_detected = True
        state.sweep_level = event.get("level")
        state.sweep_bar_index = event.get("bar_index")
        state.sweep_tf = event.get("tf")  # telemetry: 1H / 2H
        state.state = SetupState.ARMED
        logger.info("[%s] SWEEP → ARMED | tf=%s level=%s", state.symbol, event.get("tf"), event.get("level"))

    def _handle_mss(self, state: SymbolState, event: dict):
        logger.info(
            "[MSS-HANDLE] symbol=%s state=%s level=%s dir=%s",
            state.symbol,
            state.state,
            event.get("level"),
            event.get("direction"),
        )

        if state.state not in (SetupState.ARMED, SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM):
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

        # WAIT_CONFIRM gate: direction zaten varsa eski setup'ı temizle,
        # yeni MSS yönüyle taze WAIT_RETRACE başlat
        if state.state == SetupState.WAIT_CONFIRM and state.direction is not None:
            logger.warning(
                "[%s] MSS WAIT_CONFIRM gate: direction zaten var (%s) → eski setup sıfırlanıp WAIT_RETRACE'e geç",
                state.symbol,
                state.direction,
            )
            state.retrace_seen = False
            state.is_ce_tap = False
            state.ltf_confirmed = False
            state.fvg_entry_bar_index = None
            state.wait_confirm_since_ts = None
            state.fvg_upper = None
            state.fvg_lower = None
            state.displacement_origin = event.get("impulse_origin") or event.get("level")
            state.direction = event.get("direction")
            state.expires_at = int(time.time()) + int(16.0 * 3600)
            state.state = SetupState.WAIT_RETRACE
            logger.info(
                "[%s] MSS (WAIT_CONFIRM gate) → WAIT_RETRACE | yeni_dir=%s",
                state.symbol,
                state.direction,
            )
            return

        if state.displacement_origin is None:
            state.displacement_origin = event.get("impulse_origin") or event.get("level")

        if state.direction is None:
            state.direction = event.get("direction")

        if state.state in (SetupState.ARMED, SetupState.WAIT_RETRACE, SetupState.WAIT_CONFIRM):
            sweep_tf = getattr(state, "sweep_tf", "1H")
            if sweep_tf == "15m":
                max_wait = getattr(self.config, "MAX_SETUP_WAIT_HOURS_15M", 8.0) if self.config else 8.0
            else:
                max_wait = getattr(self.config, "MAX_SETUP_WAIT_HOURS", 16.0) if self.config else 16.0
            state.expires_at = int(time.time()) + int(max_wait * 3600)
            state.state = SetupState.WAIT_RETRACE
            logger.info("[%s] MSS confirmed → WAIT_RETRACE | expires_in=%.0fh", state.symbol, max_wait)
        else:
            logger.info("[%s] MSS confirmed → WAIT_RETRACE", state.symbol)

    def _handle_fvg(self, state: SymbolState, event: dict):
        # Terminal + Case C state'lerde FVG kabul edilmez
        if state.state in (
            SetupState.INVALIDATED,
            SetupState.EXPIRED,
            SetupState.ENTERED,
            SetupState.MISSED_FVG,  # Case C patikası bozulmasın
            SetupState.WAIT_POI_CONFIRM,  # Case C patikası bozulmasın
        ):
            state.fvg_upper = None
            state.fvg_lower = None
            logger.debug("[%s] FVG event reddedildi — state=%s", state.symbol, state.state)
            return

        # Critical: WAIT_CONFIRM ve READY_TO_ENTER'da FVG değişikliğini reddet.
        # Mid-setup silent overwrite — FVG setup sırasında değişirse
        # entry/SL/TP seviyeleri bozulur, kontrolsüz trade üretilir.
        if state.state in (SetupState.WAIT_CONFIRM, SetupState.READY_TO_ENTER):
            logger.warning(
                "[%s] FVG mid-setup overwrite reddedildi — state=%s | mevcut=[%.5f-%.5f] yeni=[%.5f-%.5f]",
                state.symbol,
                state.state,
                state.fvg_upper,
                state.fvg_lower,
                event.get("upper"),
                event.get("lower"),
            )
            return

        state.fvg_upper = event.get("upper")
        state.fvg_lower = event.get("lower")
        state.fvg_time = event.get("time")

        if state.state == SetupState.WAIT_RETRACE:
            logger.info("[%s] FVG güncellendi — state=%s", state.symbol, state.state)
            return

        # WAIT_NEW_FVG: eski FVG delinmişti, yeni FVG geldi → WAIT_RETRACE
        if state.state == SetupState.WAIT_NEW_FVG:
            # Sadece geçerli (active) FVG kabul edilir
            if not event.get("is_active", True):
                logger.debug("[%s] WAIT_NEW_FVG: FVG is_active=False — reddedildi", state.symbol)
                return
            state.retrace_seen = False
            state.is_ce_tap = False
            state.fvg_entry_bar_index = None
            state.state = SetupState.WAIT_RETRACE
            logger.info(
                "[%s] WAIT_NEW_FVG → yeni FVG alındı → WAIT_RETRACE | upper=%.5f lower=%.5f",
                state.symbol,
                state.fvg_upper,
                state.fvg_lower,
            )
            return

        if state.mss_confirmed:
            state.state = SetupState.WAIT_RETRACE

        logger.info("[%s] FVG kaydedildi | upper=%.5f lower=%.5f", state.symbol, state.fvg_upper, state.fvg_lower)

    def check_retrace(self, symbol: str, current_bar: Bar, atr: float = 0.0) -> None:
        """
        Her yeni kapanan barda ana event loop tarafından çağrılır.

        CASE A — PENETRATION TRADE ZONE (0.15 – 0.70):
          PenetrationEngine ile FVG içine girişi ölçer.
          SHORT: anchor = fvg_upper, pen = |price - fvg_upper| / size
          LONG:  anchor = fvg_lower, pen = |price - fvg_lower| / size
          0.15 <= pen <= 0.70 → WAIT_CONFIRM

        CASE C — MISSED FVG (pen < 0.15 + fiyat uzaklaştı):
          FVG'ye hiç girmeden fiyat kaçtı → MISSED_FVG
        """
        state = self.get(symbol)

        # Son kapanan bar referansını güncelle — event-triggered invalidation için
        self._last_bar = current_bar

        if state.state != SetupState.WAIT_RETRACE:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            logger.info("[%s] check_retrace: FVG seviyeleri yok, atlandı", symbol)
            return
        if state.direction is None:
            return

        engine = PenetrationEngine(state.fvg_upper, state.fvg_lower, state.direction)
        price = current_bar.close
        pen = engine.get_penetration(price)

        logger.debug(
            "[%s] check_retrace | dir=%s | pen=%.2f | close=%.5f | fvg=[%.5f-%.5f]",
            symbol,
            state.direction,
            pen,
            price,
            state.fvg_lower,
            state.fvg_upper,
        )

        # ── Dinamik CE Eşiği (FVG boyutuna göre) ─────────────────────────
        fvg_size = abs(state.fvg_upper - state.fvg_lower)
        ref_ratio = getattr(self.config, "FVG_REF_SIZE_RATIO", 0.002)
        scale_min = getattr(self.config, "FVG_CE_SCALE_MIN", 0.5)
        scale_max = getattr(self.config, "FVG_CE_SCALE_MAX", 2.0)
        base_pen_min = getattr(self.config, "FVG_CE_PEN_MIN_BASE", 0.15)
        base_pen_max = getattr(self.config, "FVG_CE_PEN_MAX_BASE", 0.70)
        pen_min_floor = getattr(self.config, "FVG_CE_PEN_MIN_FLOOR", 0.05)
        pen_max_ceil = getattr(self.config, "FVG_CE_PEN_MAX_CEIL", 0.85)

        # FVG size ratio = FVG genişliği / fiyat seviyesi
        price_ref = (state.fvg_upper + state.fvg_lower) / 2.0
        if price_ref > 0 and fvg_size > 0:
            fvg_size_ratio = fvg_size / price_ref
            scale = fvg_size_ratio / ref_ratio
            scale = max(scale_min, min(scale_max, scale))
        else:
            scale = 1.0

        pen_min = max(pen_min_floor, base_pen_min / scale)
        pen_max = min(pen_max_ceil, base_pen_max * scale)

        logger.debug(
            "[%s] CE dynamic | fvg_size=%.5f ratio=%.6f scale=%.2f pen_min=%.2f pen_max=%.2f",
            symbol,
            fvg_size,
            fvg_size_ratio if price_ref > 0 else 0,
            scale,
            pen_min,
            pen_max,
        )

        if pen_min <= pen <= pen_max:
            state.retrace_seen = True
            state.is_ce_tap = True
            state.fvg_entry_bar_index = current_bar.index
            state.wait_confirm_since_ts = getattr(current_bar, "timestamp", None)
            state.state = SetupState.WAIT_CONFIRM
            logger.info(
                "[%s] CASE A — RETRACE ✓ penetration=%.2f (%.0f%%–%.0f%%) → WAIT_CONFIRM | dir=%s | close=%.5f",
                symbol,
                pen,
                pen_min * 100,
                pen_max * 100,
                state.direction,
                price,
            )
            return

        # ── CASE C: Missed FVG ───────────────────────────────────────────
        if pen < pen_min:
            self._check_missed_fvg(state, current_bar)

    def _check_missed_fvg(self, state: SymbolState, current_bar: Bar) -> None:
        """
        CASE C: FVG'ye hiç girmeden fiyat uzaklaştı.

        Koşul:
          1. retrace_seen == False
          2. pen < FVG_PENETRATION_MIN (0.15)
          3. Fiyat FVG'nin yanlış tarafında değil (henüz gelmemiş değil)

        ATR bağımlılığı YOK — penetration % tek karar kriteri.
        """
        if state.retrace_seen:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            return

        # Fiyat FVG'ye henüz ulaşmadıysa tetikleme (yaklaşım yönüne göre)
        if state.direction == "SHORT" and current_bar.close > state.fvg_upper:
            return  # Fiyat FVG'nin üstünde, henüz gelmedi
        if state.direction == "LONG" and current_bar.close < state.fvg_lower:
            return  # Fiyat FVG'nin altında, henüz gelmedi

        # Minimum bar kontrolü — erken false positive önle
        if state.fvg_entry_bar_index is not None:
            bars_since = current_bar.index - state.fvg_entry_bar_index
            if bars_since < 3:
                return

        state.fvg_missed = True
        state.missed_fvg_at_price = current_bar.close
        state.missed_fvg_bar_index = current_bar.index
        state.poi_anchor = state.displacement_origin
        state.poi_anchor_bar_index = current_bar.index
        state.state = SetupState.MISSED_FVG

        logger.warning(
            "[%s] CASE C — MISSED_FVG | dir=%s | close=%.5f → poi_anchor=%.5f",
            state.symbol,
            state.direction,
            current_bar.close,
            state.poi_anchor or 0.0,
        )

    def check_poi_retrace(self, symbol: str, current_bar: Bar, atr: float = 0.0) -> None:
        """
        MISSED_FVG state'inde: fiyat poi_anchor bölgesine gelirse WAIT_POI_CONFIRM'e geç.

        Buffer = FVG size * 0.3 (ATR bağımlılığı yok)
        """
        state = self.get(symbol)

        if state.state != SetupState.MISSED_FVG:
            return
        if state.poi_anchor is None:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            return

        fvg_size = abs(state.fvg_upper - state.fvg_lower)
        buffer = fvg_size * 0.3 if fvg_size > 0 else 0.001
        anchor = state.poi_anchor

        in_zone = (anchor - buffer) <= current_bar.close <= (anchor + buffer)

        if not in_zone:
            return

        state.state = SetupState.WAIT_POI_CONFIRM
        logger.info(
            "[%s] MISSED_FVG → WAIT_POI_CONFIRM | dir=%s | close=%.5f anchor=%.5f buffer=%.5f",
            symbol,
            state.direction,
            current_bar.close,
            anchor,
            buffer,
        )

    def check_ltf_fvg_validity(self, symbol: str, current_bar: Bar) -> None:
        """
        WAIT_CONFIRM state'inde her 1m kapanışında çağrılır.
        Fiyat hâlâ FVG içinde mi kontrol eder.
        İçinden çıktıysa WAIT_NEW_FVG'ye düşer.
        """
        state = self.get(symbol)
        if state.state != SetupState.WAIT_CONFIRM:
            return
        if state.fvg_upper is None or state.fvg_lower is None:
            return
        if state.direction is None:
            return

        engine = PenetrationEngine(state.fvg_upper, state.fvg_lower, state.direction)
        pen = engine.get_penetration(current_bar.close)
        pen_min = getattr(self.config, "FVG_PENETRATION_MIN", 0.15)
        pen_max = getattr(self.config, "FVG_PENETRATION_MAX", 0.70)

        if pen > pen_max:
            state.retrace_seen = False
            state.is_ce_tap = False
            state.ltf_confirmed = False
            state.fvg_entry_bar_index = None
            state.wait_confirm_since_ts = None
            state.fvg_upper = None
            state.fvg_lower = None
            state.state = SetupState.WAIT_NEW_FVG
            logger.warning(
                "[%s] WAIT_CONFIRM: pen=%.2f > %.2f — FVG delinmiş → WAIT_NEW_FVG",
                symbol,
                pen,
                pen_max,
            )
            return

        if pen < pen_min:
            logger.debug(
                "[%s] WAIT_CONFIRM: pen=%.2f < %.2f — FVG dışına çıktı, MSS bekleniyor",
                symbol,
                pen,
                pen_min,
            )

    def _get_atr(self, state: SymbolState, bars=None) -> float | None:
        """ATR fallback zinciri — sadece SL buffer için kullanılır."""
        import config as cfg

        atr_map = getattr(cfg, "ATR_MAP", {})
        if state.symbol in atr_map:
            return float(atr_map[state.symbol])
        default = getattr(cfg, "DEFAULT_ATR", None)
        if default is not None:
            return float(default)
        return None

    def _handle_ltf(self, state: SymbolState, event: dict):
        if state.state not in (
            SetupState.WAIT_CONFIRM,
            SetupState.WAIT_RETRACE,
            SetupState.WAIT_POI_CONFIRM,
        ):
            logger.debug(
                "[LTF-SKIP] %s state=%s — kabul edilen state dışında LTF reddedildi",
                state.symbol,
                state.state,
            )
            return

        if state.fvg_upper is None or state.fvg_lower is None:
            if state.state == SetupState.WAIT_POI_CONFIRM and state.poi_anchor is not None:
                pass
            else:
                logger.warning("[%s] LTF confirm geldi ama FVG seviyeleri yok — atlandı", state.symbol)
                return

        logger.info("[LTF] %s | dir=%s | state=%s", state.symbol, event.get("direction"), state.state)
        state.ltf_confirmed = True
        state.entry_price = event.get("close")

        if state.state == SetupState.WAIT_CONFIRM:
            # Giriş anında pen tekrar kontrol et
            engine = PenetrationEngine(state.fvg_upper, state.fvg_lower, state.direction)
            pen = engine.get_penetration(event.get("close", state.entry_price or 0.0))
            pen_max = getattr(self.config, "FVG_PENETRATION_MAX", 0.70)

            if pen > pen_max:
                # Oda kapısı: geri dön — FVG delinmiş, yeni FVG bekle
                state.retrace_seen = False
                state.is_ce_tap = False
                state.ltf_confirmed = False
                state.fvg_entry_bar_index = None
                state.wait_confirm_since_ts = None
                state.fvg_upper = None
                state.fvg_lower = None
                state.state = SetupState.WAIT_NEW_FVG
                logger.warning(
                    "[%s] LTF geldi ama pen=%.2f > %.2f — FVG delinmiş → WAIT_NEW_FVG",
                    state.symbol,
                    pen,
                    pen_max,
                )
                return

            state.state = SetupState.READY_TO_ENTER
            logger.info("[%s] LTF confirm → READY_TO_ENTER (Case A) pen=%.2f", state.symbol, pen)
        elif state.state == SetupState.WAIT_POI_CONFIRM:
            state.state = SetupState.READY_TO_ENTER
            logger.info("[%s] LTF confirm → READY_TO_ENTER (Case C / poi_anchor)", state.symbol)
        elif state.state == SetupState.WAIT_RETRACE:
            pass  # _evaluate() 4 flag'i görüp çeksin

    def _handle_htf_bias(self, state: SymbolState, event: dict):
        new_direction = event.get("direction")
        state.htf_bias = new_direction
        state.htf_strength = event.get("strength")

        # IDLE'da ilk bias set — direction da aynı anda set edilir
        if state.state == SetupState.IDLE:
            state.direction = new_direction
        # IDLE dışında bias değişirse direction'ı da override et (desync önleme)
        elif new_direction is not None and state.direction != new_direction:
            logger.warning(
                "[%s] HTF bias değişti: %s → %s (state=%s) — direction override ediliyor",
                state.symbol,
                state.direction,
                new_direction,
                state.state,
            )
            state.direction = new_direction

        logger.debug("[%s] HTF bias set → %s (%s)", state.symbol, state.htf_bias, state.htf_strength)

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
        stale_states = ["ARMED", "WAIT_RETRACE", "WAIT_CONFIRM", "WAIT_NEW_FVG", "MISSED_FVG", "WAIT_POI_CONFIRM"]
        if state.state in stale_states:
            if state.expires_at is not None and current_time.timestamp() > state.expires_at:
                logger.warning(
                    "[%s] ZOMBİ SETUP TEMİZLENDİ | State=%s | expires_at aşıldı → IDLE",
                    state.symbol,
                    state.state,
                )
                state.state = SetupState.IDLE
                state.reset_flags()
                return True
        return False

    def _check_invalidation(self, state: SymbolState, last_closed_bar) -> bool:
        if last_closed_bar is None:
            return False

        # Zombi setup önleme — ARMED/WAIT_RETRACE'te olduğu gibi
        # WAIT_CONFIRM, WAIT_NEW_FVG, MISSED_FVG, WAIT_POI_CONFIRM
        # state'lerinde de fiyat MSS seviyesini ihlal ederse setup'ı IDLE'a düşür.
        if state.state not in (
            SetupState.ARMED,
            SetupState.WAIT_RETRACE,
            SetupState.WAIT_CONFIRM,
            SetupState.WAIT_NEW_FVG,
            SetupState.MISSED_FVG,
            SetupState.WAIT_POI_CONFIRM,
        ):
            return False

        mss_level = getattr(state, "mss_level", None)
        if mss_level is None:
            return False

        # Buffer: küçük geri çekilmeleri tolere et
        buffer = mss_level * 0.001

        if state.direction == "SHORT" and last_closed_bar.close > mss_level + buffer:
            logger.warning(
                "[%s] INVALIDATION | close=%.5f > SHORT MSS=%.5f + buffer → IDLE",
                state.symbol,
                last_closed_bar.close,
                mss_level,
            )
            state.state = SetupState.IDLE
            state.reset_flags()
            return True

        elif state.direction == "LONG" and last_closed_bar.close < mss_level - buffer:
            logger.warning(
                "[%s] INVALIDATION | close=%.5f < LONG MSS=%.5f - buffer → IDLE",
                state.symbol,
                last_closed_bar.close,
                mss_level,
            )
            state.state = SetupState.IDLE
            state.reset_flags()
            return True

        return False

    def _evaluate(self, state: SymbolState, current_time: datetime | None = None, last_closed_bar=None):
        if current_time is None:
            current_time = datetime.now()

        if self._check_stale_state(state, current_time):
            return
        if self._check_invalidation(state, last_closed_bar):
            return

        old_state = state.state

        logger.debug(
            "[EVALUATE] %s | sweep=%s mss=%s retrace=%s ltf=%s fvg_missed=%s | state=%s",
            state.symbol,
            state.sweep_detected,
            state.mss_confirmed,
            state.retrace_seen,
            state.ltf_confirmed,
            state.fvg_missed,
            state.state,
        )

        # ── CASE A: Klasik penetration yolu ─────────────────────────────
        if state.sweep_detected and state.mss_confirmed and state.retrace_seen and state.ltf_confirmed:
            if state.state in (SetupState.WAIT_CONFIRM, SetupState.WAIT_RETRACE):
                state.state = SetupState.READY_TO_ENTER
                logger.critical(
                    "[%s] CASE A — ALL CONDITIONS MET → READY_TO_ENTER (%s)",
                    state.symbol,
                    state.direction,
                )
            return

        # ── CASE C: Missed FVG recovery yolu ────────────────────────────
        if state.sweep_detected and state.mss_confirmed and state.fvg_missed and state.ltf_confirmed:
            if state.state in (
                SetupState.WAIT_POI_CONFIRM,
                SetupState.MISSED_FVG,
                SetupState.WAIT_RETRACE,
            ):
                state.state = SetupState.READY_TO_ENTER
                logger.critical(
                    "[%s] CASE C — POI CONFIRM → READY_TO_ENTER (%s) poi_anchor=%.5f",
                    state.symbol,
                    state.direction,
                    state.poi_anchor or 0.0,
                )
            return

        # ── ADAPTIVE mid-band READY_TO_ENTER (optional) ────────────────
        try:
            if getattr(self.config, "ADAPTIVE_LTF_ENABLE", False):
                if (
                    state.state == SetupState.WAIT_CONFIRM
                    and state.sweep_detected
                    and state.mss_confirmed
                    and state.retrace_seen
                    and not state.ltf_confirmed
                    and state.direction is not None
                    and state.fvg_upper is not None
                    and state.fvg_lower is not None
                    and last_closed_bar is not None
                ):
                    engine = PenetrationEngine(state.fvg_upper, state.fvg_lower, state.direction)
                    pen = engine.get_penetration(last_closed_bar.close)
                    pen_mid = getattr(self.config, "FVG_PENETRATION_MID", 0.30)
                    pen_max = getattr(self.config, "FVG_PENETRATION_MAX", 0.70)
                    if pen_mid <= pen <= pen_max:
                        state.state = SetupState.READY_TO_ENTER
                        logger.info(
                            "[%s] ADAPTIVE READY → READY_TO_ENTER (mid-band pen=%.2f)",
                            state.symbol,
                            pen,
                        )
                        return
        except Exception:
            pass

        if old_state != state.state:
            logger.info("[STATE] %s: %s → %s", state.symbol, old_state, state.state)

    # ─────────────────────────────────────────
    # CLEANUP & MANUAL MANIPULATION
    # ─────────────────────────────────────────

    def set_state(self, symbol: str, new_state: SetupState):
        state = self.get(symbol)
        old_state = state.state
        state.state = new_state
        logger.info("[%s] State geçişi: %s → %s", symbol, old_state, new_state)

    def invalidate(self, symbol: str):
        state = self.get(symbol)
        state.state = SetupState.INVALIDATED

    def clear(self, symbol: str):
        if symbol in self.symbols:
            del self.symbols[symbol]
