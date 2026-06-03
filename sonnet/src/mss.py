"""
choch.py
────────
Nexus SMC Trading Bot — Change of Character (CHoCH) Modülü (Final Merge)
File 1 SMC mikro-yapı filtreleri + File 2 pipeline/state yönetimi birleştirildi.
KRİTİK KURAL: `timestamp` SADECE `CHoCH` dataclass'ında set edilir.
"""
from __future__ import annotations

import logging
from typing import Final, Literal

import config
from indicators import compute_atr_series as _compute_atr_series
from models import (
    Bar,
    CHoCH,
    SwingPoint,
    tf_params,
)
from pivot import SwingStateManager

logger = logging.getLogger("nexus.choch")

# ──────────────────────────────────────────────────────────
# SABITLER & YAPILANDIRMA
# ──────────────────────────────────────────────────────────
MIN_CHOCH_ATR_MULT: Final[float] = 0.15

# Sembol bazlı periyodik cleanup sayacı (thread-safe dict)
_SYMBOL_COUNTERS: dict[str, int] = {}

# ──────────────────────────────────────────────────────────
# 1. SMC MİKRO-YAPI YARDIMCILARI
# ──────────────────────────────────────────────────────────
def _is_convincing_break(
    break_bar: Bar,
    level: float,
    avg_body: float,
    atr_val: float,
    direction: Literal["bullish", "bearish"],
    bars_after: list[Bar],
    sfp_n: int,
) -> bool:
    """
    Kırılma kalitesi & SFP follow-through filtresi.
    avg_body/atr==0 fallback'leri içerir.
    """
    body_ok = atr_ok = False

    if avg_body > 0:
        body_ok = break_bar.body >= avg_body * config.CHoCH_MIN_BODY_RATIO
    else:
        bar_range = break_bar.high - break_bar.low
        body_ok = bar_range > 0 and break_bar.body >= bar_range * 0.3

    if atr_val > 0:
        atr_ok = abs(break_bar.close - level) >= atr_val * config.CHoCH_ATR_OVERSHOOT
    else:
        atr_ok = (direction == "bearish" and break_bar.close < level) or \
                 (direction == "bullish" and break_bar.close > level)

    if not (body_ok or atr_ok):
        return False

    # SFP Follow-through
    confirmations = 0
    for fb in bars_after[:sfp_n]:
        if not fb.is_closed:
            break
        if direction == "bearish" and fb.close < level:
            confirmations += 1
        elif direction == "bullish" and fb.close > level:
            confirmations += 1

    return confirmations >= sfp_n


def _resolve_outside_bar_priority(
    bar: Bar,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> Literal["bearish", "bullish", "both", "none"]:
    """
    Tek bar hem high hem low süpürüyorsa fitil uzunluğuna göre öncelik belirler.
    Eşitlikte SMC convention gereği bearish baskın kabul edilir.
    """
    breaks_high = any(bar.close > sp.price for sp in swing_highs)
    breaks_low  = any(bar.close < sp.price for sp in swing_lows)

    if breaks_high and breaks_low:
        uw, lw = bar.upper_wick, bar.lower_wick
        if lw > uw:
            return "bearish"
        elif uw > lw:
            return "bullish"
        return "bearish"
    if breaks_high:
        return "bullish"
    if breaks_low:
        return "bearish"
    return "none"


# ──────────────────────────────────────────────────────────
# 2. MSS TESPİTİ (Hybrid Pipeline)
# ──────────────────────────────────────────────────────────
def detect_mss(
    bars: list[Bar],
    swing_mgr: SwingStateManager,
    lookback: int | None = None,  # None → config'den dinamik hesapla
    timeframe: str = "5m",
    atr_series: list[float] | None = None,
    atr_mult: float = MIN_CHOCH_ATR_MULT,
) -> list[CHoCH]:
    """
    O(N) tarama + ATR size filter + SMC mikro-yapı veto + pivot mitigation.
    """
    # ── Dinamik lookback: timeframe'e göre saat bazında hesapla ──
    if lookback is None:
        _tf_minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
        tf_min = _tf_minutes.get(timeframe, 15)
        lookback = int(config.CHOCH_MAX_AGE_HOURS * 60 / tf_min)

    if len(bars) < lookback:
        segment = bars
    else:
        segment = bars[-lookback:]

    if atr_series is None:
        atr_series = _compute_atr_series(bars, period=config.CHoCH_ATR_PERIOD)

    break_window, body_lookback, sfp_n = tf_params(timeframe)
    active_high_map: dict[int, SwingPoint] = {p.bar_index: p for p in swing_mgr.active_highs()}
    active_low_map:  dict[int, SwingPoint] = {p.bar_index: p for p in swing_mgr.active_lows()}

    found: list[CHoCH] = []
    first_abs = bars[0].index

    for bar in segment:
        # KRİTİK 1: Kapanmamış mum kesinlikle atlanır
        if not bar.is_closed:
            continue

        bar_close = bar.close
        bar_abs   = bar.index
        bar_pos   = bar_abs - first_abs  # KRİTİK 2: Birebir indeks hizalaması
        atr_val   = atr_series[bar_pos] if 0 <= bar_pos < len(atr_series) else 0.0

        # ═══════════════════════════════════════════════════
        # ── BULLISH ADAY ──────────────────────────────────
        # ═══════════════════════════════════════════════════
        best_sp: SwingPoint | None = None
        mitigated: list[SwingPoint] = []
        for sp_abs, sp in active_high_map.items():
            if sp.bar_index >= bar_abs or sp.mitigated:
                continue
            if bar_close > sp.price:
                if best_sp is None or sp.price > best_sp.price:
                    best_sp = sp
                mitigated.append(sp)

        if best_sp is not None:
            penetration = bar_close - best_sp.price
            # 1. ATR/Kapanış büyüklük filtresi
            passes_size_filter = atr_val <= 0 or penetration >= atr_val * atr_mult

            # 2. SMC Veto Mantığı: Outside bar önceliği net değilse mikro-yapı onayı şarttır
            if passes_size_filter:
                prio = _resolve_outside_bar_priority(bar, [best_sp], [])
                if prio != "bullish":
                    body_start = max(0, bar_pos - body_lookback)
                    local_bodies = [
                        bars[x].body
                        for x in range(body_start, bar_pos)
                        if bars[x].is_closed
                    ]
                    local_avg_body = sum(local_bodies) / len(local_bodies) if local_bodies else 0.0
                    bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]

                    if not _is_convincing_break(
                        bar, best_sp.price, local_avg_body,
                        atr_val, "bullish", bars_after, sfp_n,
                    ):
                        passes_size_filter = False

            # ── Sinyal Üretimi ────────────────────────────
            if passes_size_filter:
                # Strength: penetration + SFP follow-through bileşik skoru
                pen_ratio = (
                    max(0.0, min(1.0, penetration / (atr_val * config.CHoCH_ATR_OVERSHOOT)))
                    if atr_val > 0 else 0.0
                )
                _bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]
                _confirmations = 0
                for fb in _bars_after[:sfp_n]:
                    if not fb.is_closed:
                        break
                    if fb.close > best_sp.price:
                        _confirmations += 1
                sfp_ratio = _confirmations / sfp_n if sfp_n and sfp_n > 0 else 0.0
                strength = round(max(0.0, min(1.0, pen_ratio * 0.6 + sfp_ratio * 0.4)), 3)

                found.append(CHoCH(
                    direction="bullish", level=best_sp.price, bar_index=bar_abs,
                    pivot_bar_index=best_sp.bar_index, timeframe=timeframe, timestamp=bar.timestamp,
                    strength=strength
                ))
                logger.info("[CHoCH] Bullish @ %d (level=%.5f)", bar_abs, best_sp.price)
            else:
                logger.debug("[CHoCH] Bullish veto @ %d", bar_abs)

            # KRİTİK 3: Kırılan TÜM pivot'lar mitigate edilir (yön/sonuç bağımsız)
            for sp_m in mitigated:
                object.__setattr__(sp_m, "mitigated", True)
                swing_mgr.mark_mitigated("high", sp_m.bar_index)

        # ═══════════════════════════════════════════════════
        # ── BEARISH ADAY ──────────────────────────────────
        # ═══════════════════════════════════════════════════
        best_sp = None
        mitigated = []
        for sp_abs, sp in active_low_map.items():
            if sp.bar_index >= bar_abs or sp.mitigated:
                continue
            if bar_close < sp.price:
                if best_sp is None or sp.price < best_sp.price:
                    best_sp = sp
                mitigated.append(sp)

        if best_sp is not None:
            penetration = best_sp.price - bar_close
            passes_size_filter = atr_val <= 0 or penetration >= atr_val * atr_mult

            if passes_size_filter:
                prio = _resolve_outside_bar_priority(bar, [], [best_sp])
                if prio != "bearish":
                    body_start = max(0, bar_pos - body_lookback)
                    local_bodies = [
                        bars[x].body
                        for x in range(body_start, bar_pos)
                        if bars[x].is_closed
                    ]
                    local_avg_body = sum(local_bodies) / len(local_bodies) if local_bodies else 0.0
                    bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]

                    if not _is_convincing_break(
                        bar, best_sp.price, local_avg_body,
                        atr_val, "bearish", bars_after, sfp_n,
                    ):
                        passes_size_filter = False

            if passes_size_filter:
                # Strength: penetration + SFP follow-through bileşik skoru
                pen_ratio = (
                    max(0.0, min(1.0, penetration / (atr_val * config.CHoCH_ATR_OVERSHOOT)))
                    if atr_val > 0 else 0.0
                )
                _bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]
                _confirmations = 0
                for fb in _bars_after[:sfp_n]:
                    if not fb.is_closed:
                        break
                    if fb.close < best_sp.price:
                        _confirmations += 1
                sfp_ratio = _confirmations / sfp_n if sfp_n and sfp_n > 0 else 0.0
                strength = round(max(0.0, min(1.0, pen_ratio * 0.6 + sfp_ratio * 0.4)), 3)

                found.append(CHoCH(
                    direction="bearish", level=best_sp.price, bar_index=bar_abs,
                    pivot_bar_index=best_sp.bar_index, timeframe=timeframe, timestamp=bar.timestamp,
                    strength=strength
                ))
                logger.info("[CHoCH] Bearish @ %d (level=%.5f)", bar_abs, best_sp.price)
            else:
                logger.debug("[CHoCH] Bearish veto @ %d", bar_abs)

            for sp_m in mitigated:
                object.__setattr__(sp_m, "mitigated", True)
                swing_mgr.mark_mitigated("low", sp_m.bar_index)

    return found


def create_mss_event(symbol: str, timeframe: str, direction: str, level: float, timestamp: int) -> dict:
    """Converts a structural Market Structure Shift (MSS) into a normalized V3 market event."""
    return {
        "type": "MSS",
        "tf": timeframe,
        "direction": direction,  # "LONG" veya "SHORT"
        "level": float(level),
        "time": int(timestamp)
    }


# ═══════════════════════════════════════════════════════════════
# 3. LTF Trigger Detector — 1m MSS Fake/Real Dogrulayicisi
# ═══════════════════════════════════════════════════════════════
# Dort kriterin dordu de TRUE olursa 1m MSS gecerli sayilir:
#   1. Mum body >= 1.5x ATR(14)            — gercek displacement
#   2. Volume >= 1.3x SMA(20)              — kurumsal hacim
#   3. O mum arkasinda FVG birakti          — fiziksel kanit
#   4. Kapatis onceki swing disinda         — wick degil, close

from dataclasses import dataclass

# ── Timeframe bazlı varsayılan eşikler ──
_TF_DEFAULTS: Final[dict[str, tuple[float, float]]] = {
    "1m": (1.5, 1.3),  # (body_atr_mult, vol_sma_mult)
    "5m": (1.3, 1.2),
}
_DEFAULT_VOL_SMA_PERIOD: Final[int] = 20


@dataclass
class LTFTriggerResult:
    """Dedektor ciktisi."""
    is_valid: bool = False
    body_ok: bool = False
    volume_ok: bool = False
    fvg_ok: bool = False
    close_ok: bool = False
    body_val: float = 0.0
    atr_val: float = 0.0
    volume_val: float = 0.0
    volume_sma_val: float = 0.0
    direction: Literal["bullish", "bearish"] | None = None
    reason: str = ""


class LTFTriggerDetector:
    """
    MSS fake/real validasyonu — 1m ve 5m destekli.

    timeframe="1m" → body ≥ 1.5× ATR, vol ≥ 1.3× SMA(20)
    timeframe="5m" → body ≥ 1.3× ATR, vol ≥ 1.2× SMA(20)
    Hepsi TRUE → is_valid=True. Biri bile FALSE → iptal.
    """

    def __init__(
        self,
        timeframe: str = "1m",
        body_atr_mult: float | None = None,
        vol_sma_period: int = _DEFAULT_VOL_SMA_PERIOD,
        vol_sma_mult: float | None = None,
        atr_period: int = 14,
    ) -> None:
        tf_body, tf_vol = _TF_DEFAULTS.get(timeframe, _TF_DEFAULTS["1m"])
        self.body_atr_mult = body_atr_mult if body_atr_mult is not None else tf_body
        self.vol_sma_period = vol_sma_period
        self.vol_sma_mult = vol_sma_mult if vol_sma_mult is not None else tf_vol
        self.atr_period = atr_period
        self.timeframe = timeframe

    # ── Yardimci hesaplamalar ──

    @staticmethod
    def _atr(bars: list[Bar], period: int = 14) -> float:
        if len(bars) < period + 1:
            return 0.0
        tr_sum = 0.0
        for i in range(len(bars) - period, len(bars)):
            h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
            tr_sum += max(h - l, abs(h - pc), abs(l - pc))
        return tr_sum / period

    @staticmethod
    def _vol_sma(bars: list[Bar], period: int = 20) -> float:
        if len(bars) < period:
            return 0.0
        return sum(b.volume for b in bars[-period:]) / period

    # ── Dort kriter ──

    @staticmethod
    def _chk_body(bar: Bar, atr: float, mult: float) -> tuple[bool, float]:
        body = bar.body
        return body >= atr * mult, body

    @staticmethod
    def _chk_volume(bar: Bar, sma: float, mult: float) -> tuple[bool, float]:
        if sma <= 0:
            return False, bar.volume
        return bar.volume >= sma * mult, bar.volume

    @staticmethod
    def _chk_fvg(
        prev: Bar, cur: Bar, direction: Literal["bullish", "bearish"]
    ) -> bool:
        if direction == "bullish":
            return prev.high < cur.low
        return prev.low > cur.high

    @staticmethod
    def _chk_close(
        bar: Bar,
        direction: Literal["bullish", "bearish"],
        nearest_swing: SwingPoint | None,
    ) -> bool:
        if nearest_swing is None:
            return False
        if direction == "bullish":
            return bar.close > nearest_swing.price
        return bar.close < nearest_swing.price

    # ── Ana giris ──

    def validate(
        self,
        bars: list[Bar],
        direction: Literal["bullish", "bearish"],
        nearest_swing: SwingPoint | None = None,
    ) -> LTFTriggerResult:
        result = LTFTriggerResult(direction=direction)

        if len(bars) < max(self.vol_sma_period + 1, self.atr_period + 2):
            result.reason = f"Yetersiz bar: {len(bars)}"
            return result

        cur, prev = bars[-1], bars[-2]
        atr = self._atr(bars, self.atr_period)
        vsma = self._vol_sma(bars, self.vol_sma_period)
        result.atr_val = atr
        result.volume_sma_val = vsma

        result.body_ok, result.body_val = self._chk_body(cur, atr, self.body_atr_mult)
        if not result.body_ok:
            result.reason = f"Body FAIL: {result.body_val:.4f} < {atr:.4f}x{self.body_atr_mult}"
            return result

        result.volume_ok, result.volume_val = self._chk_volume(cur, vsma, self.vol_sma_mult)
        if not result.volume_ok:
            result.reason = f"Volume FAIL: {result.volume_val:.2f} < {vsma:.2f}x{self.vol_sma_mult}"
            return result

        result.fvg_ok = self._chk_fvg(prev, cur, direction)
        if not result.fvg_ok:
            result.reason = "FVG FAIL"
            return result

        result.close_ok = self._chk_close(cur, direction, nearest_swing)
        if not result.close_ok:
            result.reason = f"Close FAIL: {cur.close:.4f} not beyond swing"
            return result

        result.is_valid = True
        result.reason = (
            f"OK VALID | body={result.body_val:.4f} vol={result.volume_val:.2f} "
            f"fvg=OK close=OK dir={direction}"
        )
        logger.info(result.reason)
        return result
