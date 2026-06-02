"""
analyzer.py
───────────
MSS + FVG tabanlı trading bot analizörü.
Ana analiz pipeline'ı ve MarketAnalyzer sınıfı.
Bağımlılıklar (tek yönlü, döngüsüz):
models → indicators → pivot → fvg → mss → scoring → analyzer
config, monitor, volume_profile
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import config
import monitor
from fvg import (
    MIN_FVG_SIZE,
    find_latest_unfilled_fvg,
    refresh_fvg_list,
)
from indicators import compute_adx, compute_atr, compute_ema100
from models import FVG, Bar, mss
from mss import (
    refresh_mss_list,
)
from pivot import SwingStateManager, find_swing_highs, find_swing_lows
from volume_profile import VolumeProfile, VPLevels

logger = logging.getLogger("nexus.analyzer")


@dataclass
class AnalysisResult:
    """
    Tek bir sembol için tam analiz sonucu.
    Alan hiyerarşisi (öncelik sırası):
    direction mss → fvg → fvg_quality → retest_ready / impulsive_bypass
    """

    symbol: str
    direction: Literal["long", "short"] | None = None
    mss: mss | None = None
    fvg: FVG | None = None
    retest_ready: bool = False
    adx_value: float = 0.0
    ema100: float = 0.0
    close_d1: float = 0.0
    tp_level: float | None = None
    vp_levels: VPLevels | None = None
    entry_zone: float | None = None
    entry_zone_type: Literal["proximal", "ce"] | None = None
    armed: bool = False
    stop_loss: float | None = None

    @property
    def expected_mss_direction(self) -> Literal["bullish", "bearish"] | None:
        if self.direction == "long":
            return "bullish"
        if self.direction == "short":
            return "bearish"
        return None

    def summary(self) -> str:
        mss_str = (
            f"mss={self.mss.direction}@{self.mss.level:.2f} "
            f"bar={self.mss.bar_index}"
            if self.mss else "mss=None"
        )
        fvg_str = (
            f"fvg=[{self.fvg.bottom:.2f}-{self.fvg.top:.2f}] "
            f"real={self.fvg.real_index}"
            if self.fvg else "fvg=None"
        )
        return (
            f"{self.symbol} | {self.direction} | {mss_str} | {fvg_str} | "
            f"adx={self.adx_value:.1f} | "
            f"retest={self.retest_ready}"
        )


def _is_5m_engulfing(prev: Bar, curr: Bar, direction: str) -> bool:
    bar_range = curr.high - curr.low
    if bar_range == 0:
        return False

    body_ratio = curr.body / bar_range
    if body_ratio < 0.55:
        return False

    if direction == "bullish":
        return (
            curr.close > prev.open
            and curr.open < prev.close
            and curr.close > prev.high
        )
    return (
        curr.close < prev.open
        and curr.open > prev.close
        and curr.close < prev.low
    )


def compute_structural_sl(
    fvg: FVG,
    direction: str,
    sl_buffer_pct: float = 0.001,
) -> float:
    if direction == "bullish":
        sl = fvg.bottom * (1.0 - sl_buffer_pct)
    else:
        sl = fvg.top * (1.0 + sl_buffer_pct)
    return round(sl, 6)


class MarketAnalyzer:
    """
    Sembol bazlı trading analiz motoru.
    H4 → Yapısal trend (swing kırılımı)
    H1 → ADX hesaplaması + Volume Profile
    15m → MSS + FVG tespiti ve skorlama
    5m  → LTF tetik mekanizması
    """

    def __init__(
        self,
        symbol: str,
        adx_threshold: float = 25.0,
        ema_period: int = 100,
        bot_state=None,
    ) -> None:
        self.symbol = symbol
        self.adx_threshold = adx_threshold
        self.ema_period = ema_period
        self.bot_state = bot_state
        self.vp = VolumeProfile(bins=24)
        self._mss_state = SwingStateManager()
        self.fvgs: list[FVG] = []
        self.mss: list[mss] = []

    def _trend_direction(
        self, bars_h4: list[Bar]
    ) -> Literal["long", "short"] | None:
        lookback = config.H4_SWING_LOOKBACK
        segment = bars_h4[-lookback:] if len(bars_h4) > lookback else bars_h4
        close = segment[-1].close

        highs = find_swing_highs(
            segment, left=config.H4_SWING_LEFT, right=config.H4_SWING_RIGHT
        )
        lows = find_swing_lows(
            segment, left=config.H4_SWING_LEFT, right=config.H4_SWING_RIGHT
        )

        if len(highs) < 2 or len(lows) < 2:
            logger.info(
                "[H4-STRUCT] %s yetersiz swing (highs=%d lows=%d) "
                "→ trend=None",
                self.symbol, len(highs), len(lows),
            )
            return None

        last_high, prev_high = highs[-1].price, highs[-2].price
        last_low, prev_low = lows[-1].price, lows[-2].price

        bullish_struct = last_high > prev_high and last_low > prev_low
        bearish_struct = last_low < prev_low and last_high < prev_high

        if not bullish_struct and not bearish_struct:
            if len(highs) >= 3 and len(lows) >= 3:
                h3, l3 = highs[-3].price, lows[-3].price
                bullish_struct = last_high > h3 and last_low > l3
                bearish_struct = last_low < l3 and last_high < h3

        if not bullish_struct and not bearish_struct:
            logger.info(
                "[H4-STRUCT] %s kararsız yapı (HH+HL yok, LL+LH yok) "
                "→ trend=None", self.symbol,
            )
            return None

        if bullish_struct:
            if close < last_low:
                logger.info(
                    "[H4-STRUCT] %s Bullish yapıda SWING LOW KIRILDI "
                    "(close=%.4f < low=%.4f) → SHORT",
                    self.symbol, close, last_low,
                )
                return "short"
            logger.info(
                "[H4-STRUCT] %s — LONG modu KİLİTLİ "
                "(HH=%.4f > prev_HH=%.4f, HL=%.4f > prev_HL=%.4f, "
                "close=%.4f)",
                self.symbol, last_high, prev_high, last_low, prev_low, close,
            )
            return "long"

        if close > last_high:
            logger.info(
                "[H4-STRUCT] %s Bearish yapıda SWING HIGH KIRILDI "
                "(close=%.4f > high=%.4f) → LONG",
                self.symbol, close, last_high,
            )
            return "long"
        logger.info(
            "[H4-STRUCT] %s — SHORT modu KİLİTLİ "
            "(LL=%.4f < prev_LL=%.4f, LH=%.4f < prev_LH=%.4f, "
            "close=%.4f)",
            self.symbol, last_low, prev_low, last_high, prev_high, close,
        )
        return "short"

    def analyze(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
        bars_h1: list[Bar],
        bars_15m: list[Bar],
        bars_m5: list[Bar],
        fvg_score_threshold: float | None = None,
    ) -> AnalysisResult:
        result = AnalysisResult(symbol=self.symbol)
        try:
            if not all([bars_h4, bars_h1, bars_15m, bars_m5, bars_d1]):
                return result

            trend = self._trend_direction(bars_h4)
            if trend is None:
                logger.info(
                    "[TREND] %s trend=None — H4 yapısal trend "
                    "belirlenemedi, sinyal red", self.symbol,
                )
                return result

            result.ema100 = compute_ema100(bars_d1)
            result.close_d1 = bars_d1[-1].close
            adx = compute_adx(bars_h1)
            result.adx_value = adx

            pivot_lr = 2 if adx >= config.MSS_PIVOT_ADX_THRESHOLD else 3
            self._mss_state.ingest(bars_15m, left=pivot_lr, right=pivot_lr)

            self.mss = refresh_mss_list(
                self.mss,
                bars_15m,
                swing_mgr=self._mss_state,
                lookback=None,
                timeframe="15m",
                symbol=self.symbol,
            )
            mss = self.mss[-1] if self.mss else None
            result.mss = mss

            if mss is not None:
                result.direction = (
                    "long" if mss.direction == "bullish" else "short"
                )
                fvg_dir = mss.direction
            else:
                result.direction = trend
                fvg_dir = "bullish" if trend == "long" else "bearish"

            self.fvgs = refresh_fvg_list(
                self.fvgs, bars_15m, lookback=60,
                timeframe="15m", symbol=self.symbol,
            )

            active_fvg = (
                find_latest_unfilled_fvg(
                    self.fvgs, fvg_dir, min_fvg_size=MIN_FVG_SIZE
                )
                if mss is not None else None
            )

            if mss is None:
                logger.info(
                    "[FVG-MSS] %s MSS bulunamadı — "
                    "FVG sinyali işleme alınmıyor", self.symbol,
                )
            elif active_fvg is None:
                logger.info(
                    "[FVG-RED] %s aktif FVG bulunamadı — "
                    "yon=%s (mss.direction=%s)",
                    self.symbol, fvg_dir, mss.direction,
                )

            if active_fvg and mss:
                fvg_age = mss.bar_index - active_fvg.real_index
                if fvg_age > config.FVG_MAX_AGE_BARS:
                    logger.info(
                        "[FVG-OLD] %s FVG bayat — age=%d > %d",
                        self.symbol, fvg_age, config.FVG_MAX_AGE_BARS
                    )
                    active_fvg = None

            if active_fvg is None:
                logger.info(
                    "[FVG-RED] %s aktif FVG bulunamadı — "
                    "yon=%s toplam FVG=%d adet",
                    self.symbol, fvg_dir, len(self.fvgs),
                )
                return result

            object.__setattr__(active_fvg, "timeframe", "15m")
            result.fvg = active_fvg

            atr_val = compute_atr(bars_15m)
            bars_since = max(0, bars_15m[-1].index - active_fvg.real_index)

            if bars_since > config.FVG_MAX_AGE_BARS:
                logger.info(
                    "[TIMEOUT] %s FVG bayat — bars_since=%d > %d",
                    self.symbol, bars_since, config.FVG_MAX_AGE_BARS,
                )
                monitor.update_reject(self.symbol, "timeout_reject")
                return result

            vp_levels = self.vp.build(bars_15m, symbol=self.symbol)
            result.vp_levels = vp_levels

            logger.debug(
                "FVG veto chain | symbol=%s | passed_structure=%s | passed_mss=%s | passed_adx=%s",
                self.symbol, trend is not None, mss is not None,
                adx >= config.FVG_IMPULSIVE_ADX_THRESHOLD,
                    )

            if vp_levels.poc > 0:
                vp_h1 = self.vp.build(bars_h1, symbol=f"{self.symbol}_h1")
                if vp_h1.poc > 0:
                    result.tp_level = vp_h1.poc
                    logger.debug(
                        "[FAZ2] %s VP TP mıknatısı: POC=%.6f",
                        self.symbol, vp_h1.poc,
                    )

            if active_fvg.direction == "bullish":
                proximal = active_fvg.bottom + active_fvg.size * 0.15
                ce = active_fvg.midpoint
            else:
                proximal = active_fvg.top - active_fvg.size * 0.15
                ce = active_fvg.midpoint

            current_close = bars_15m[-1].close
            dist_prox = abs(current_close - proximal)
            dist_ce = abs(current_close - ce)

            if dist_ce < dist_prox:
                entry_zone, entry_zone_type = ce, "ce"
            else:
                entry_zone, entry_zone_type = proximal, "proximal"

            result.entry_zone = round(entry_zone, 6)
            result.entry_zone_type = entry_zone_type

            logger.info(
                "[FAZ3] %s Killzone: entry=%.6f type=%s "
                "(proximal=%.6f dist=%.6f, ce=%.6f dist=%.6f, close=%.6f)",
                self.symbol, entry_zone, entry_zone_type,
                proximal, dist_prox, ce, dist_ce, current_close,
            )

            atr_15m = atr_val
            zone_tolerance = atr_15m * 0.25
            price_in_zone = abs(current_close - entry_zone) <= zone_tolerance
            price_in_fvg = active_fvg.bottom <= current_close <= active_fvg.top

            if price_in_zone or price_in_fvg:
                logger.info(
                    "[FAZ4] %s fiyat entry_zone'da: close=%.6f entry=%.6f "
                    "tolerance=%.6f in_zone=%s in_fvg=%s",
                    self.symbol, current_close, entry_zone,
                    zone_tolerance, price_in_zone, price_in_fvg,
                )

                result.armed = True
                result.stop_loss = compute_structural_sl(
                    active_fvg, active_fvg.direction
                )
                logger.info(
                    "[FAZ4] %s ARMED! entry=%.6f sl=%.6f "
                    "fvg=[%.6f-%.6f] direction=%s",
                    self.symbol, entry_zone,
                    result.stop_loss, active_fvg.bottom,
                    active_fvg.top, active_fvg.direction,
                )
                monitor.update_signal(
                    self.symbol,
                    reason="armed_entry_zone",
                )
            else:
                logger.debug(
                    "[FAZ4] %s fiyat entry_zone dışında: close=%.6f "
                    "entry=%.6f distance=%.6f tolerance=%.6f",
                    self.symbol, current_close, entry_zone,
                    abs(current_close - entry_zone), zone_tolerance,
                )

            logger.info(
                "[ANALYZE] %s tamamlandı: direction=%s mss=%s fvg=%s "
                "armed=%s entry=%.6f sl=%s",
                self.symbol, result.direction,
                result.mss.direction if result.mss else "None",
                (
                    f"{active_fvg.direction}@{active_fvg.real_index}"
                    if active_fvg else "None"
                ),
                result.armed,
                result.entry_zone,
                f"{result.stop_loss:.6f}" if result.stop_loss else "None",
            )

        except Exception as exc:
            logger.error(
                "[ANALYZE] %s analiz hatası: %s",
                self.symbol, exc, exc_info=True,
            )

        return result

